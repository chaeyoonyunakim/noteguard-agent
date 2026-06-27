"""Unit tests for noteguard.deid.

All tests use the standard-library-only de-id core — no external services,
no API keys, no network calls required. Safe to run in CI.
"""

from __future__ import annotations

import pytest

from noteguard.deid import NoteGuard, load_known_from_csv


KNOWN = {"PERSON": ["Margaret Okafor"], "NHS": ["485 777 3456"]}


def _ng() -> NoteGuard:
    return NoteGuard(known=KNOWN)


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
