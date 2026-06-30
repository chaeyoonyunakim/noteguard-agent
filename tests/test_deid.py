"""Unit tests for noteguard.deid.

All tests use the standard-library-only de-id core — no external services,
no API keys, no network calls required. Safe to run in CI.
"""

from __future__ import annotations

import pytest
from src.deid import NoteGuard, load_known_from_csv

KNOWN = {"PERSON": ["Margaret Okafor"], "NHS": ["485 777 3456"]}


def _ng() -> NoteGuard:
    return NoteGuard(known=KNOWN)


@pytest.fixture(autouse=True)
def _no_ner(monkeypatch):
    """Pin the rule/vault layer for unit tests.

    Presidio NER is an optional recall boost (the ``[nlp]`` extra). Tests must be
    deterministic whether or not it is installed, so default every test to the
    no-op detector; the NER-path test injects its own fake on top.
    """
    import src.deid as deid

    monkeypatch.setattr(deid, "_DETECTOR", deid._Detector())


# ── deidentify ────────────────────────────────────────────────────────────────


def test_nhs_number_replaced():
    ng = _ng()
    result = ng.deidentify("Patient NHS 485 777 3456 admitted.")
    assert "485 777 3456" not in result.clean_text
    assert "[NHS_" in result.clean_text


def test_person_name_replaced():
    ng = _ng()
    result = ng.deidentify("Pt Margaret Okafor discharged home.")
    assert "Margaret Okafor" not in result.clean_text
    assert "[PERSON_" in result.clean_text


def test_email_replaced():
    ng = _ng()
    result = ng.deidentify("Contact a.okafor@nhs.net for follow-up.")
    assert "@" not in result.clean_text


def test_dob_replaced():
    ng = _ng()
    result = ng.deidentify("DOB 14/03/1934, admitted post-fall.")
    assert "14/03/1934" not in result.clean_text


def test_gmc_replaced():
    ng = _ng()
    result = ng.deidentify("Referring clinician GMC 1234567.")
    assert "1234567" not in result.clean_text


def test_clean_text_passes_through_unchanged():
    ng = _ng()
    note = "Patient admitted post-fall. Hx AF, on warfarin. BP 128/74."
    result = ng.deidentify(note)
    assert result.clean_text == note


# ── GMC / NMC connector-word variants ────────────────────────────────────────


def test_gmc_with_connector_no():
    ng = _ng()
    res = ng.deidentify("Referring clinician GMC No. 7654321.")
    assert "7654321" not in res.clean_text
    assert "[GMC_" in res.clean_text


def test_gmc_with_connector_number():
    ng = _ng()
    res = ng.deidentify("GMC number 7654321 on record.")
    assert "7654321" not in res.clean_text


def test_nmc_with_connector_number_colon():
    ng = _ng()
    res = ng.deidentify("Nurse Chukwuebuka Okafor, NMC number: 18D6896L")
    assert "18D6896L" not in res.clean_text
    assert "[NMC_" in res.clean_text


def test_nmc_with_pin():
    ng = _ng()
    res = ng.deidentify("Registered nurse PIN 18D6896L.")
    assert "18D6896L" not in res.clean_text


def test_nmc_bare():
    ng = _ng()
    res = ng.deidentify("NMC 18D6896L confirmed.")
    assert "18D6896L" not in res.clean_text


# ── Clinician name detection (via expanded vault) ─────────────────────────────


def test_clinician_name_via_vault():
    """Clinician names added to the vault are redacted deterministically."""
    known = {"PERSON": ["Chukwuebuka Okafor", "Margaret Okafor"], "NHS": []}
    ng = NoteGuard(known=known)
    res = ng.deidentify("Nurse Chukwuebuka Okafor assessed the patient.")
    assert "Chukwuebuka Okafor" not in res.clean_text
    assert "[PERSON_" in res.clean_text


def test_full_clinician_nmc_note():
    """Combined: nurse name in vault + NMC number with connector word."""
    known = {"PERSON": ["Chukwuebuka Okafor"], "NHS": []}
    ng = NoteGuard(known=known)
    note = "Patient assessed at triage by Nurse Chukwuebuka Okafor, NMC number: 18D6896L"
    res = ng.deidentify(note)
    assert "Chukwuebuka Okafor" not in res.clean_text
    assert "18D6896L" not in res.clean_text
    ng.assert_clean(res.clean_text)


# ── assert_clean ──────────────────────────────────────────────────────────────


def test_assert_clean_passes_on_safe_text():
    ng = _ng()
    ng.assert_clean("Admitted post-fall. Hx AF. INR 2.4.")  # must not raise


def test_assert_clean_raises_on_nhs_number():
    ng = _ng()
    with pytest.raises(ValueError, match="485 777 3456"):
        ng.assert_clean("NHS 485 777 3456 still present.")


def test_assert_clean_raises_on_known_name():
    ng = _ng()
    with pytest.raises(ValueError, match="Margaret Okafor"):
        ng.assert_clean("Patient Margaret Okafor discharged.")


def test_assert_clean_raises_on_nmc():
    ng = _ng()
    with pytest.raises(ValueError):
        ng.assert_clean("NMC number: 18D6896L not redacted.")


# ── residual_identifiers (trust metric) ───────────────────────────────────────


def test_residual_identifiers_catches_orphaned_token():
    """A [LABEL_n] token with no reverse mapping is an unmapped-token leak."""
    ng = NoteGuard(known={}, reverse={"[PERSON_1]": "Real Name"})
    text = "Summary for [PERSON_1] and [PERSON_2]."  # PERSON_2 has no mapping
    hits = ng.residual_identifiers(text)
    assert any("unmapped_token" in h for h in hits)
    # PERSON_1 is mapped — should NOT appear as orphaned
    assert not any("PERSON_1" in h for h in hits)


def test_residual_identifiers_catches_nmc():
    ng = _ng()
    hits = ng.residual_identifiers("Nurse PIN 18D6896L still present.")
    assert any(h for h in hits)  # something was found


# ── reidentify ────────────────────────────────────────────────────────────────


def test_reidentify_restores_surrogate():
    ng = _ng()
    result = ng.deidentify("Pt Margaret Okafor (NHS 485 777 3456) admitted.")
    restored = ng.reidentify(result.clean_text)
    assert "Margaret Okafor" in restored
    assert "485 777 3456" in restored


def test_reidentify_consistent_surrogates():
    """Same original -> same surrogate across multiple notes."""
    ng = _ng()
    r1 = ng.deidentify("Note 1: Margaret Okafor, INR normal.")
    r2 = ng.deidentify("Note 2: Margaret Okafor, discharged.")
    tokens_1 = {tok for tok in r1.clean_text.split() if tok.startswith("[PERSON-")}
    tokens_2 = {tok for tok in r2.clean_text.split() if tok.startswith("[PERSON-")}
    assert tokens_1 == tokens_2


# ── load_known_from_csv ───────────────────────────────────────────────────────


def test_load_known_from_csv(tmp_path):
    csv_file = tmp_path / "patients.csv"
    csv_file.write_text("full_name,nhs_number\nJane Smith,123 456 7890\n")
    known = load_known_from_csv(str(csv_file))
    assert "Jane Smith" in known["PERSON"]
    assert "123 456 7890" in known["NHS"]


def test_load_known_from_csv_admissions(tmp_path):
    """Names in admissions.csv clinician columns are added to the vault."""
    patients = tmp_path / "patients.csv"
    patients.write_text("full_name,nhs_number\nJane Smith,123 456 7890\n")
    admissions = tmp_path / "admissions.csv"
    admissions.write_text("clinician_name,attending\nDr Wei Wang,Nurse Chukwuebuka Okafor\n")
    known = load_known_from_csv(str(patients), str(admissions))
    assert "Dr Wei Wang" in known["PERSON"]
    assert "Nurse Chukwuebuka Okafor" in known["PERSON"]


def test_load_known_from_csv_missing_admissions(tmp_path):
    """Missing admissions.csv is silently ignored."""
    patients = tmp_path / "patients.csv"
    patients.write_text("full_name,nhs_number\nJane Smith,123 456 7890\n")
    known = load_known_from_csv(str(patients), str(tmp_path / "missing.csv"))
    assert "Jane Smith" in known["PERSON"]


# ── scan_pii: vault-independent residual-PII audit for the trust panel ─────────


def test_scan_pii_flags_titled_names_missed_by_vault():
    """The reported failure: free-text clinician names with no vault entry slip
    past de-id, and scan_pii must catch them while ignoring tokenised IDs."""
    ng = NoteGuard(known={"PERSON": [], "NHS": []})  # arbitrary pasted note, no vault
    note = (
        "Contacted patient's GP, Dr. Ethel Joanne Duffy, to provide an update.\n"
        "Nurse Jasmine Freda Murray\nNMC number: 20F4626L"
    )
    res = ng.deidentify(note)
    findings = ng.scan_pii(res.clean_text)
    texts = " | ".join(f["text"] for f in findings)
    assert all(f["type"] == "name" for f in findings)
    assert "Ethel Joanne Duffy" in texts
    assert "Jasmine Freda Murray" in texts
    assert "NMC" not in texts and "[NMC_1]" not in texts  # tokenised id is not PII


def test_scan_pii_clean_when_names_tokenised():
    """When names are in the vault they become surrogates → no residual PII."""
    ng = NoteGuard(known={"PERSON": ["Ethel Joanne Duffy", "Jasmine Freda Murray"], "NHS": []})
    res = ng.deidentify("GP Dr. Ethel Joanne Duffy. Nurse Jasmine Freda Murray.")
    assert ng.scan_pii(res.clean_text) == []


def test_scan_pii_ignores_surrogate_tokens_and_role_words():
    """Surrogate tokens and bare role words must not be flagged as names."""
    ng = NoteGuard()
    text = "Consultant: [PERSON_1], seen by Dr [PERSON_2]. Nurse Practitioner reviewed."
    assert ng.scan_pii(text) == []


def test_scan_pii_flags_residual_structured_identifier():
    """A structured identifier that slipped through is reported with its type."""
    ng = NoteGuard()
    findings = ng.scan_pii("Contact the team at a.b.smith@nhs.net for queries.")
    assert any(f["type"] == "email" and "a.b.smith@nhs.net" in f["text"] for f in findings)


# ── NER path: Presidio/spaCy redacts free-text names with no vault entry ───────


def test_deidentify_redacts_ner_detected_names(monkeypatch):
    """When an NLP detector is present, a free-text name with no vault entry is
    still tokenised — the recall boost the [nlp] extra adds in the deployed image."""
    import src.deid as deid

    class _Fake(deid._Detector):
        def detect_persons(self, text: str) -> list[str]:
            return ["Ethel Joanne Duffy"] if "Ethel Joanne Duffy" in text else []

    monkeypatch.setattr(deid, "_DETECTOR", _Fake())
    ng = deid.NoteGuard(known={"PERSON": [], "NHS": []})
    res = ng.deidentify("Reviewed by Ethel Joanne Duffy on the ward round.")
    assert "Ethel Joanne Duffy" not in res.clean_text
    assert "[PERSON_" in res.clean_text
    assert ng.scan_pii(res.clean_text) == []  # nothing left for the audit to flag


def test_redact_unresolved_strips_stray_date_placeholder():
    """A stray template placeholder like [DATE_X] (label + non-digit) is redacted
    and flagged, so it never reaches the clinician verbatim."""
    ng = NoteGuard()
    out, leaked = ng.redact_unresolved("Admitted [DATE_X] after chest pain.")
    assert "[DATE_X]" not in out
    assert out == "Admitted [redacted] after chest pain."
    assert leaked == ["[DATE_X]"]


def test_redact_unresolved_strips_unrestored_surrogate():
    """An unrestored [LABEL_n] surrogate is also caught."""
    ng = NoteGuard()
    out, leaked = ng.redact_unresolved("Seen by [PERSON_9].")
    assert out == "Seen by [redacted]." and leaked == ["[PERSON_9]"]


def test_redact_unresolved_leaves_clean_text_untouched():
    """Text with no surrogate-shaped tokens is returned unchanged."""
    ng = NoteGuard()
    out, leaked = ng.redact_unresolved("Admitted after chest pain. Stable.")
    assert out == "Admitted after chest pain. Stable." and leaked == []


def test_ner_clinical_stopwords_not_redacted(monkeypatch):
    """Clinical abbreviations the NER layer mislabels (e.g. 'Subcut') are kept,
    while a real name flagged in the same pass is still redacted."""
    import src.deid as deid

    class _Fake(deid._Detector):
        def detect_persons(self, text: str) -> list[str]:
            return ["Subcut", "Afua Asare"]

    monkeypatch.setattr(deid, "_DETECTOR", _Fake())
    ng = deid.NoteGuard(known={"PERSON": [], "NHS": []})
    res = ng.deidentify("Subcut emph noted on palpation. Reviewed by Afua Asare.")
    assert "Subcut" in res.clean_text  # clinical term — not a name
    assert "Afua Asare" not in res.clean_text and "[PERSON_" in res.clean_text
