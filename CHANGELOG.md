# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-06-27

### Added

- **Clinician web UI** (`app/static/index.html`) — single-file, vanilla JS, no build
  step. NHS dark-blue header, segmented toggle (Clinician view / What the AI sees),
  PHI highlighted in red in the clinician view, `[TYPE_N]` monospace chips in the AI
  view, discharge summary pane, trust-panel metric cards.
- **`POST /process` endpoint** (`app/api.py`) — returns `clinician_note`, `ai_note`,
  `identifiers` (original strings for highlighting), `discharge_summary`, and
  `metrics` (`identifiers_removed`, `residual_risk`, `grounded_sources`,
  `faithfulness`).
- **`GET /`** — FastAPI serves `app/static/index.html` directly; no separate static
  server needed.
- **`StaticFiles` mount** at `/static` — allows future CSS/JS assets alongside the
  single-page UI.
- **n8n workflow** (`workflows/noteguard.n8n.json`) — importable three-node workflow
  (Webhook → HTTP Request → Respond to Webhook) that routes ward notes through the
  NoteGuard API without the model ever seeing PHI.

- **Vercel deployment** (`api/index.py`, `api/requirements.txt`, `vercel.json`) —
  the FastAPI app is deployable as a serverless Vercel function. Light dep set
  omits superlinked/torch to stay under the 250 MB bundle limit; retrieval falls
  back gracefully to Gemini-only mode.

### Changed

- `app/api.py` now also serves the clinician web UI in addition to the REST API.
- `agent/graph.py`: `NoteIndex` import made lazy (inside try block) so the module
  loads cleanly in environments where superlinked is unavailable (CI, Vercel).
- `noteguard/__init__.py`: removed `NoteIndex` re-export; only `NoteGuard`,
  `DeidResult`, and `load_known_from_csv` are exported from the package.
- `Makefile` `run` target now starts uvicorn (`uvicorn app.api:app --reload --port 8000`)
  instead of Streamlit.
- `pyproject.toml` version bumped to 0.2.0; `per-file-ignores` added for E402
  (intentional `load_dotenv()` before API-key-consuming imports).

### Removed

- **`app/trust_panel.py`** — Streamlit demo UI retired; superseded by the
  single-file clinician web UI (`app/static/index.html`) served by FastAPI.
- **`streamlit`** removed from `requirements.txt`.

---

## [0.1.0] - 2026-06-27

### Added

- **De-identification core** (`noteguard/deid.py`) — dependency-free NHS-aware
  pipeline: NHS number, GMC/NMC, postcode, DOB, email and phone recognisers;
  vault-from-CSV for ground-truth measurement; consistent surrogates;
  `assert_clean()` hard guarantee; `reidentify()` for clinician-only restoration.
- **Superlinked retrieval node** (`noteguard/retrieve.py`) — in-memory vector
  index (`sentence-transformers/all-MiniLM-L6-v2`) with `assert_clean()` called
  on every document in and every retrieved chunk out.
- **LangGraph agent** (`agent/graph.py`) — full pipeline:
  `deidentify_in → retrieve_context → agent (Gemini + Tavily) → reidentify_out → compute_trust`.
  Trust metrics surfaced in graph state: identifiers removed, residual leakage,
  faithfulness score, source URLs.
- **Streamlit trust panel** (`app/trust_panel.py`) — three-way toggle
  (raw / de-identified / clinician answer) and live trust panel; styled to the
  NHS England identity.
- **LangSmith evaluations** (`eval/run_eval.py`) — `zero_phi_to_model` (must
  score 1.0) and `faithfulness` (LLM-as-judge over de-identified text only).
- Gold RAP packaging: `pyproject.toml`, `Makefile`, `CHANGELOG.md`,
  `CONTRIBUTING.md`, `.pre-commit-config.yaml`, `.editorconfig`, CI workflow,
  and `docs/` (architecture, user guide, RAP compliance).
