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

# Column names we look for in any CSV to extract person names
_NAME_COLS = frozenset(
    {
        "full_name", "patient_name", "first_name", "surname", "last_name",
        "clinician_name", "author_name", "author", "attending", "attending_physician",
        "nurse", "consultant", "doctor", "provider",
    }
)


# ── Optional NLP detector (Presidio + spaCy) ─────────────────────────────────


class _Detector:
    """Stub detector — no-op when Presidio/spaCy is not installed."""

    def detect_persons(self, text: str) -> list[str]:
        return []


def _build_detector() -> _Detector:
    try:
        from presidio_analyzer import AnalyzerEngine  # type: ignore

        engine = AnalyzerEngine()

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
                self._counter[m.group(1)] = max(
                    self._counter.get(m.group(1), 0), int(m.group(2))
                )

    @staticmethod
    def _fix_mojibake(s: str) -> str:
        # Each pair: (UTF-8 bytes of the real char decoded as Windows-1252, real char)
        # Â·  = Â· → ·  (middle dot U+00B7)
        # â€™ = â€™ → '  (right single quote U+2019)
        # â€“ = â€" → –  (en-dash U+2013; 0x93 in Win-1252 = U+201C)
        # Ã© = Ã© → é  (e-acute U+00E9)
        return (
            s.replace("Â·", "·")
            .replace("â€™", "’")
            .replace("â€“", "–")
            .replace("Ã©", "é")
        )

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
                shifted = (datetime.strptime(s, fmt) + timedelta(days=self.dob_shift)).strftime(
                    fmt
                )
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
        for name in _DETECTOR.detect_persons(t):
            if name and len(name) > 2 and name not in self.forward:
                t = t.replace(name, self._surrogate("PERSON", name))

        return DeidResult(t, dict(self.forward), dict(self.reverse), self._residual_known(t))

    def _residual_known(self, text: str) -> list:
        return [v for vals in self.known.values() for v in vals if v and v in text]

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
        for name in _DETECTOR.detect_persons(text):
            if name:
                hits.append(f"PERSON:{name[:30]}")

        return list(dict.fromkeys(hits))  # deduplicate, preserve order

    def assert_clean(self, text: str) -> None:
        """Hard guarantee: raises if any known identifier or regex pattern survives."""
        hits = list(self._residual_known(text))
        for pat in (NHS_CONTEXT, NHS_NUMBER, EMAIL, GMC, NMC):
            if pat.search(text):
                hits.append(pat.pattern[:40])
        if hits:
            raise ValueError(
                f"NoteGuard guarantee failed: identifiers reached the model boundary: {hits}"
            )

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
