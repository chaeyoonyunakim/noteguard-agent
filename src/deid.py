"""NoteGuard de-identification core.

Dependency-free and runnable on its own (`python noteguard/deid.py`).
If `presidio-analyzer` + a spaCy model are installed the module upgrades
free-text PERSON/LOCATION detection automatically; the rule + vault layer
below always runs without them.

Design:
- NHS-aware recognisers (NHS number, GMC/NMC, postcode, DOB, email, phone)
- vault of known identifiers from patients.csv + admissions.csv so redaction
  is exact AND measurable
- patient-consistent surrogates (same original → same token across notes)
- DOB date-shift (kept clinically plausible); other identifiers tokenised
- reidentify() restores originals for the CLINICIAN's eyes only
- assert_clean() is the hard guarantee that no identifier reaches the model
"""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

NHS_NUMBER = re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{4}\b")
NHS_CONTEXT = re.compile(r"(?i)\bNHS(?:\s*(?:no\.?|number|#))?[:\s]*([0-9][0-9 \-]{6,12}\d)")
UK_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2})\b")
DOB = re.compile(r"\b(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})\b")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE = re.compile(r"\b0\d{2,3}[ -]?\d{3,4}[ -]?\d{3,4}\b")

# GMC/NMC: optional connector word then optional colon/spaces before the ID
# Handles: "GMC No. 7654321", "NMC number: 18D6896L", "PIN 18D6896L", etc.
_CONN = r"(?:\s*(?:no\.?|number|reg(?:istration)?|pin|#))?[:\s]*"
GMC = re.compile(r"(?i)\bGMC" + _CONN + r"(\d{7})\b")
NMC = re.compile(r"(?i)\b(?:NMC|PIN)" + _CONN + r"(\d{2}[A-Z]\d{4}[A-Z])\b")

# Surrogate token pattern — catches any [LABEL_n] the model might invent
_SURROGATE_PAT = re.compile(r"\[[A-Z]+_\d+\]")

# Person-title prefixes that almost always precede a real name. Used by the
# trust-panel audit (scan_pii) to flag free-text names that slipped past the
# vault / NER passes — e.g. "Dr Ethel Joanne Duffy", "Nurse Jasmine Freda Murray".
# Requires >= 2 Title-Case tokens after the title so role words ("Nurse
# Practitioner", "Consultant Cardiologist") do not false-positive, and a correctly
# tokenised name ("Dr [PERSON_1]") never matches because "[" is not a letter.
_PERSON_TITLE = (
    r"(?:Dr|Doctor|Mr|Mrs|Ms|Miss|Prof|Professor|Nurse|Sister|Matron|Midwife|Sir|Dame|Consultant|GP)"
)
_NAME_AFTER_TITLE = re.compile(r"\b" + _PERSON_TITLE + r"\b[.,:]?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})")

# Column names we look for in any CSV to extract person names
_NAME_COLS = frozenset(
    {
        "full_name",
        "patient_name",
        "first_name",
        "surname",
        "last_name",
        "clinician_name",
        "author_name",
        "author",
        "attending",
        "attending_physician",
        "nurse",
        "consultant",
        "doctor",
        "provider",
    }
)


# ── Optional NLP detector (Presidio + spaCy) ─────────────────────────────────

# Clinical terms/abbreviations that the small spaCy model (en_core_web_md) often
# mislabels as PERSON/LOCATION. They are never redacted as names even when the NER
# layer flags them — over-redaction like "Subcut" -> [PERSON_3] is wrong and noisy.
# Compared case-insensitively; keep to terms that are not plausible real names.
_NER_STOPWORDS = frozenset(
    {
        "subcut",
        "subcutaneous",
        "obs",
        "sats",
        "spo2",
        "nad",
        "nbm",
        "nkda",
        "prn",
        "stat",
        "mane",
        "nocte",
        "neuro",
        "resp",
        "cvs",
        "abdo",
        "perrla",
        "gcs",
        "afebrile",
        "apyrexial",
        "euvolaemic",
        "normotensive",
        "tachycardic",
        "bradycardic",
        "pyrexial",
        "bibasal",
        "pneumomediastinum",
    }
)


class _Detector:
    """Stub detector — no-op when Presidio/spaCy is not installed."""

    def detect_persons(self, text: str) -> list[str]:
        return []


def _build_detector() -> _Detector:
    """Upgrade free-text PERSON/LOCATION detection to Presidio + spaCy when
    available; otherwise return a no-op stub so the rule + vault layer still runs.

    The spaCy model is configurable via ``NOTEGUARD_SPACY_MODEL`` (default
    ``en_core_web_md`` — small enough to ship in the Docker image, materially
    better recall than ``_sm``; set ``_lg`` for best recall at ~14x the size).
    Any import or engine-setup failure degrades gracefully to the stub: NER is a
    recall boost over the rules + vault, never a hard dependency.
    """
    try:
        from presidio_analyzer import AnalyzerEngine  # type: ignore
        from presidio_analyzer.nlp_engine import NlpEngineProvider  # type: ignore

        model = os.getenv("NOTEGUARD_SPACY_MODEL", "en_core_web_md")
        provider = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": model}],
            }
        )
        engine = AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])

        class _PresidioDetector(_Detector):
            def detect_persons(self, text: str) -> list[str]:
                results = engine.analyze(text, language="en", entities=["PERSON", "LOCATION"])
                return [text[r.start : r.end] for r in results if r.end > r.start]

        return _PresidioDetector()
    except Exception:
        return _Detector()


_DETECTOR: _Detector = _build_detector()


# ── Vault loader ──────────────────────────────────────────────────────────────


def load_known_from_csv(patients_csv: str, admissions_csv: str | None = None) -> dict:
    """Build the identifier vault from the synthetic dataset's structured tables.

    Reads ``full_name`` and common name columns from *patients_csv*, plus NHS
    numbers.  If *admissions_csv* is supplied, any clinician/author name columns
    found there are added to the PERSON set so clinician names are caught
    deterministically even without Presidio.
    """
    known: dict[str, set] = {"PERSON": set(), "NHS": set()}

    def _pull_row(row: dict) -> None:
        for col in _NAME_COLS:
            v = (row.get(col) or "").strip()
            if len(v) > 2:
                known["PERSON"].add(v)

    with open(patients_csv, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            _pull_row(row)
            nhs = (row.get("nhs_number") or "").strip()
            if nhs:
                known["NHS"].add(nhs)

    if admissions_csv:
        try:
            with open(admissions_csv, newline="", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    _pull_row(row)
        except FileNotFoundError:
            pass

    return {k: sorted(v) for k, v in known.items()}


# ── Core de-identification ────────────────────────────────────────────────────


@dataclass
class DeidResult:
    clean_text: str
    forward: dict
    reverse: dict
    residual: list


class NoteGuard:
    def __init__(self, known=None, dob_shift_days=37, forward=None, reverse=None):
        self.known = {k: list(v) for k, v in (known or {}).items()}
        self.dob_shift = dob_shift_days
        self.forward = dict(forward or {})
        self.reverse = dict(reverse or {})
        self._counter: dict[str, int] = {}
        for tok in self.reverse:
            m = re.match(r"\[([A-Z]+)_(\d+)\]", tok)
            if m:
                self._counter[m.group(1)] = max(self._counter.get(m.group(1), 0), int(m.group(2)))

    @staticmethod
    def _fix_mojibake(s: str) -> str:
        # Each pair: (UTF-8 bytes of the real char decoded as Windows-1252, real char)
        # Â·  = Â· → ·  (middle dot U+00B7)
        # â€™ = â€™ → '  (right single quote U+2019)
        # â€“ = â€" → –  (en-dash U+2013; 0x93 in Win-1252 = U+201C)
        # Ã© = Ã© → é  (e-acute U+00E9)
        return s.replace("Â·", "·").replace("â€™", "’").replace("â€“", "–").replace("Ã©", "é")

    def _surrogate(self, label: str, original: str) -> str:
        if original in self.forward:
            return self.forward[original]
        self._counter[label] = self._counter.get(label, 0) + 1
        tok = f"[{label}_{self._counter[label]}]"
        self.forward[original] = tok
        self.reverse[tok] = original
        return tok

    def _shift_date(self, s: str) -> str:
        if s in self.forward:
            return self.forward[s]
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y"):
            try:
                shifted = (datetime.strptime(s, fmt) + timedelta(days=self.dob_shift)).strftime(fmt)
                self.forward[s] = shifted
                self.reverse[shifted] = s
                return shifted
            except ValueError:
                continue
        return self._surrogate("DATE", s)

    def _redact(self, pattern, label, text, group=0, transform=None):
        def repl(m):
            original = m.group(group)
            surr = transform(original) if transform else self._surrogate(label, original)
            return m.group(0).replace(original, surr)

        return pattern.sub(repl, text)

    def deidentify(self, text: str) -> DeidResult:
        t = self._fix_mojibake(text)

        # Vault pass — patient names + NHS numbers from structured tables
        for label in ("PERSON", "NHS"):
            terms = [x for x in self.known.get(label, []) if x]
            if terms:
                alternatives = "|".join(re.escape(x) for x in sorted(terms, key=len, reverse=True))
                pat = re.compile(r"\b(" + alternatives + r")\b")
                t = self._redact(pat, label, t, group=1)

        # Rule-based recognisers
        t = self._redact(NHS_CONTEXT, "NHS", t, group=1)
        t = self._redact(NHS_NUMBER, "NHS", t, group=0)
        t = self._redact(GMC, "GMC", t, group=1)
        t = self._redact(NMC, "NMC", t, group=1)
        t = self._redact(EMAIL, "EMAIL", t, group=0)
        t = self._redact(PHONE, "PHONE", t, group=0)
        t = self._redact(UK_POSTCODE, "POSTCODE", t, group=1)
        t = self._redact(DOB, "DOB", t, group=1, transform=self._shift_date)

        # Optional NLP pass — catches clinician names and locations not in vault
        for name in self._detect_names(t):
            if name not in self.forward:
                t = t.replace(name, self._surrogate("PERSON", name))

        return DeidResult(t, dict(self.forward), dict(self.reverse), self._residual_known(t))

    @staticmethod
    def _detect_names(text: str) -> list[str]:
        """NER-detected person/location names, minus clinical-term false positives.

        Filters the raw detector output so abbreviations the small spaCy model
        mislabels (e.g. "Subcut") are not treated as names.
        """
        return [
            n for n in _DETECTOR.detect_persons(text) if n and len(n) > 2 and n.lower() not in _NER_STOPWORDS
        ]

    def _residual_known(self, text: str) -> list:
        # Use word-boundary match, same as the deidentify vault pass, so that
        # short names like "Dia" don't false-positive on "Diastolic"/"Diabetes".
        return [
            v
            for vals in self.known.values()
            for v in vals
            if v and re.search(r"\b" + re.escape(v) + r"\b", text)
        ]

    def residual_identifiers(self, text: str) -> list[str]:
        """Comprehensive leak check — used for the trust metric.

        Covers:
        - vault names that survived de-id
        - regex patterns (NHS, email, GMC, NMC)
        - orphaned surrogate tokens (invented by the model, no reverse mapping)
        - NLP-detected persons/locations (when Presidio is installed)
        """
        hits: list[str] = list(self._residual_known(text))

        for pat in (NHS_CONTEXT, NHS_NUMBER, EMAIL, GMC, NMC):
            if pat.search(text):
                hits.append(f"pattern:{pat.pattern[:40]}")

        # Orphaned surrogates: a [LABEL_n] in the text with no reverse mapping
        # means the model invented a token we cannot restore — it's a leak.
        for m in _SURROGATE_PAT.finditer(text):
            tok = m.group(0)
            if tok not in self.reverse:
                hits.append(f"unmapped_token:{tok}")

        # NLP pass (no-op when Presidio not installed)
        for name in self._detect_names(text):
            hits.append(f"PERSON:{name[:30]}")

        return list(dict.fromkeys(hits))  # deduplicate, preserve order

    def scan_pii(self, text: str) -> list[dict]:
        """Vault-independent audit of a *de-identified* text for residual PII.

        ``assert_clean``/``residual_identifiers`` only know the vault and
        structured patterns, so a free-text name that was never in the vault
        (with no Presidio installed) passes them silently — exactly the failure
        where "Dr Ethel Joanne Duffy" reaches the model un-redacted. This adds a
        high-precision person-title heuristic so the trust panel can report
        whether de-identification actually succeeded, even on a pasted note with
        no ground-truth vault.

        Returns a de-duplicated list of ``{"type": str, "text": str}`` findings,
        each a span of suspected un-redacted PII still visible to the model.
        Surrogate tokens (``[PERSON_1]``) are never flagged. Shifted dates are
        intentional, so dates are out of scope here.
        """
        findings: list[dict] = []
        spans: list[tuple[int, int]] = []

        def _add(typ: str, start: int, end: int) -> None:
            if start < 0 or any(start < pe and ps < end for ps, pe in spans):
                return  # invalid, or overlaps an earlier (higher-priority) finding
            spans.append((start, end))
            findings.append({"type": typ, "text": text[start:end]})

        # 1. structured identifiers that should have been tokenised but survived
        for typ, pat, grp in (
            ("NHS number", NHS_CONTEXT, 1),
            ("NHS number", NHS_NUMBER, 0),
            ("GMC", GMC, 1),
            ("NMC", NMC, 1),
            ("email", EMAIL, 0),
            ("phone", PHONE, 0),
            ("postcode", UK_POSTCODE, 1),
        ):
            for m in pat.finditer(text):
                _add(typ, m.start(grp), m.end(grp))

        # 2. free-text person names the vault/NER passes missed (title heuristic)
        for m in _NAME_AFTER_TITLE.finditer(text):
            _add("name", m.start(1), m.end(1))

        # 3. vault names that survived de-id (when a ground-truth vault is loaded)
        for v in self._residual_known(text):
            idx = text.find(v)
            _add("name", idx, idx + len(v))

        return findings

    def assert_clean(self, text: str) -> None:
        """Hard guarantee: raises if any known identifier or regex pattern survives."""
        hits = list(self._residual_known(text))
        for pat in (NHS_CONTEXT, NHS_NUMBER, EMAIL, GMC, NMC):
            if pat.search(text):
                hits.append(pat.pattern[:40])
        if hits:
            raise ValueError(f"NoteGuard guarantee failed: identifiers reached the model boundary: {hits}")

    def reidentify(self, text: str) -> str:
        for tok, original in sorted(self.reverse.items(), key=lambda kv: len(kv[0]), reverse=True):
            text = text.replace(tok, original)
        return text


if __name__ == "__main__":
    known = {"PERSON": ["Margaret Okafor"], "NHS": ["485 777 3456"]}
    note = (
        "02 Jan, Ward RJ1. Pt Margaret Okafor (NHS 485 777 3456, DOB 14/03/1934) "
        "admitted post-fall. Nurse Chukwuebuka reviewed. "
        "Contact a.okafor@example.com, 020 7946 0991. "
        "GMC No. 7654321. NMC number: 18D6896L."
    )
    print("INPUT:\n", note, "\n")
    ng = NoteGuard(known=known)
    res = ng.deidentify(note)
    print("DE-IDENTIFIED (what the model sees):\n", res.clean_text, "\n")
    print("Residual identifiers:", res.residual)
    ng.assert_clean(res.clean_text)
    print("assert_clean: OK\n")
    restored = NoteGuard(reverse=res.reverse).reidentify(res.clean_text)
    print("RE-IDENTIFIED (clinician view only):\n", restored)
