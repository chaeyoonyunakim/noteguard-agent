# Changelog

All notable changes to NoteGuard are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.2.0] — 2026-06-27

### Added
- **Four-fix person-name leak** — GMC/NMC connector-word patterns (`NMC number: ...`, `PIN ...`, `GMC No. ...`); Presidio + spaCy `_Detector` interface (graceful no-op fallback); `load_known_from_csv` extended to pull clinician names from `admissions.csv`; `residual_identifiers()` catches orphaned `[LABEL_n]` tokens; `assert_clean()` now covers NMC patterns.
- **`{{PATIENT}}` placeholder** — patient name resolved from `patients.csv` via `person_id`; model never writes or sees a real name in the title.
- **Leaked-token trust panel** — `leaked_tokens` propagated through `compute_trust` → API → UI; `residual_risk > 0` when any leak is detected; detail panel in the clinician UI.
- **Note picker modal** — `/samples` API with search, `note_type` filter, shuffle, and row-click load; built-in fallback when dataset absent.
- **Compact eDischarge card** — four-element format (patient · narrative · follow-up · grounded); `renderSummary()` styles each element; `Grounded:` line omitted when Tavily returns nothing.
- **Word-boundary fix in `_residual_known`** — prevents false 422s from short vault names matching inside clinical words (e.g. `Dia` in `Diastolic`).
- **Gold RAP structure** — `noteguard/` renamed to `src/`; `pyproject.toml` is the single dependency source; `requirements.txt` removed; `outputs/` directory added.
- **Streamlit demo** — `streamlit_app.py` at repo root for interactive de-id demonstration without API keys.
- **Governance docs** — `docs/tool_card.md` (Five Safes, bias & fairness, use cases out of scope); `docs/report.md` (ATRS Tier 1 + Tier 2); `CODE_OF_CONDUCT.md`.
- **CI** — switched from `black` to `ruff format`; install via `pip install -e ".[dev]"` instead of `requirements-dev.txt`.

### Fixed
- `_fix_mojibake` SyntaxError — replaced literal curly-quote/en-dash characters with `\uXXXX` Unicode escape sequences.
- `faithfulness_score` always 0 — flattened Gemini list-content (`AIMessage.content` can be `list[{type, text}]`) in `compute_trust`.
- `import re` missing from `agent/graph.py`.

---

## [0.1.0] — 2026-06-27 (initial hackathon build)

### Added
- Core de-identification pipeline: NHS number, DOB, postcode, email, phone, GMC/NMC, vault-based PERSON redaction, consistent surrogates, date-shift, `assert_clean()`.
- LangGraph ReAct agent: Gemini 2.5 Flash + Tavily public-guidance search.
- Superlinked in-memory NoteIndex for semantic retrieval.
- FastAPI backend (`app/api.py`) with `/health`, `/process`, `/summarise`, `/samples`, `/sample/{id}`.
- Single-file clinician web UI (`app/static/index.html`).
- LangSmith evals: `zero_phi_to_model` (must be 1.0) + `faithfulness`.
- Dockerfile for Hugging Face Spaces deploy (port 7860).
- `NHSEDataScience/synthetic_clinical_notes` dataset integration; baked into Docker image at build time.
