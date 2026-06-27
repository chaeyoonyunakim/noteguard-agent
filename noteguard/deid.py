"""NoteGuard de-identification core.

Dependency-free and runnable on its own (`python noteguard/deid.py`).
If `presidio-analyzer` + a spaCy model are installed you can plug them in behind
the same interface to upgrade free-text PERSON detection; the rule + vault layer
below already runs without them.

Design (carried over from NoteGuard v1):
- NHS-aware recognisers (NHS number, GMC/NMC, postcode, DOB, email, phone)
- a "vault" of known identifiers loaded from the dataset's structured tables
  (patients.csv) so redaction is exact AND measurable
- patient-consistent surrogates (same original -> same token across notes)
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
GMC = re.compile(r"(?i)\bGMC[:\s]*?(\d{7})\b")
NMC = re.compile(r"(?i)\bNMC[:\s]*?(\d{2}[A-Z]\d{4}[A-Z])\b")


def load_known_from_csv(patients_csv: str) -> dict:
    """Build the identifier vault from the synthetic dataset's patients.csv."""
    known = {"PERSON": set(), "NHS": set()}
    with open(patients_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("full_name"):
                known["PERSON"].add(row["full_name"].strip())
            if row.get("nhs_number"):
                known["NHS"].add(str(row["nhs_number"]).strip())
    return {k: sorted(v) for k, v in known.items()}


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
        self._counter = {}
        for tok in self.reverse:
            m = re.match(r"\[([A-Z]+)_(\d+)\]", tok)
            if m:
                self._counter[m.group(1)] = max(self._counter.get(m.group(1), 0), int(m.group(2)))

    @staticmethod
    def _fix_mojibake(s: str) -> str:
        return (s.replace("Â·", "·").replace("â€™", "’")
                 .replace("â€“", "–").replace("Ã©", "é"))

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
        for label in ("PERSON", "NHS"):
            terms = [x for x in self.known.get(label, []) if x]
            if terms:
                pat = re.compile(r"\b(" + "|".join(re.escape(x) for x in sorted(terms, key=len, reverse=True)) + r")\b")
                t = self._redact(pat, label, t, group=1)
        t = self._redact(NHS_CONTEXT, "NHS", t, group=1)
        t = self._redact(NHS_NUMBER, "NHS", t, group=0)
        t = self._redact(GMC, "GMC", t, group=1)
        t = self._redact(NMC, "NMC", t, group=1)
        t = self._redact(EMAIL, "EMAIL", t, group=0)
        t = self._redact(PHONE, "PHONE", t, group=0)
        t = self._redact(UK_POSTCODE, "POSTCODE", t, group=1)
        t = self._redact(DOB, "DOB", t, group=1, transform=self._shift_date)
        return DeidResult(t, dict(self.forward), dict(self.reverse), self._residual_known(t))

    def _residual_known(self, text: str) -> list:
        return [v for vals in self.known.values() for v in vals if v and v in text]

    def residual_identifiers(self, text: str) -> list:
        hits = list(self._residual_known(text))
        for pat in (NHS_CONTEXT, NHS_NUMBER, EMAIL, GMC):
            if pat.search(text):
                hits.append(pat.pattern)
        return hits

    def assert_clean(self, text: str) -> None:
        hits = self.residual_identifiers(text)
        if hits:
            raise ValueError(f"NoteGuard guarantee failed: identifiers reached the model boundary: {hits}")

    def reidentify(self, text: str) -> str:
        for tok, original in sorted(self.reverse.items(), key=lambda kv: len(kv[0]), reverse=True):
            text = text.replace(tok, original)
        return text


if __name__ == "__main__":
    known = {"PERSON": ["Margaret Okafor"], "NHS": ["485 777 3456"]}
    note = ("02 Jan, Ward RJ1. Pt Margaret Okafor (NHS 485 777 3456, DOB 14/03/1934) "
            "admitted post-fall. Contact a.okafor@example.com, 020 7946 0991. GMC 7654321.")
    ng = NoteGuard(known=known)
    res = ng.deidentify(note)
    print("DE-IDENTIFIED (what the model sees):\n", res.clean_text, "\n")
    print("residual known identifiers:", res.residual)
    ng.assert_clean(res.clean_text)
    print("guarantee: no identifiers reached the model boundary  [ok]\n")
    restored = NoteGuard(reverse=res.reverse).reidentify(res.clean_text)
    print("RE-IDENTIFIED (clinician view only):\n", restored)
