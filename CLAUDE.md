# NoteGuard — the trust layer for clinical AI

## What this is
NoteGuard de-identifies NHS clinical free-text so LLM agents can use it safely, and
proves the privacy with a measured number. This repo is the **agent slice**: a
LangGraph ReAct agent (Gemini + Tavily) wrapped so the model and tools only ever see
de-identified text; real identifiers are restored only in the final clinician-facing
answer.

It started at the {Tech: Europe} London AI Hackathon. The `1.0` line is pruned to the
components that actually ship in the deployed Space (see `CHANGELOG.md`).

## Architecture
`deidentify_in → agent (Gemini + Tavily) → reidentify_out → compute_trust`
- The guarantee (non-negotiable): nothing downstream of `deidentify_in` may
  receive PHI. `assert_clean()` raises if any identifier remains. Never weaken or
  bypass this — it is the whole point of the project.
- Tavily is public-guidance grounding only (NICE/NHS). Never send patient text to it.
- `compute_trust` audits de-identification: `NoteGuard.scan_pii(deid_text)` flags PII
  the vault/NER passes missed (vault-independent, so it works on pasted notes), plus
  orphaned surrogate tokens for reversibility. The trust panel reports only this — no
  answer-quality metrics (faithfulness/sources were removed).

## Key files
- `src/deid.py` — de-id core (std-lib only): NHS-aware rules + vault-from-CSV,
  consistent surrogates, DOB date-shift, `reidentify`, `assert_clean`. Keep it
  dependency-free; Presidio/spaCy are optional behind the same interface.
- `agent/graph.py` — the graph; exposed as `noteguard` for `langgraph dev`.
- `app/api.py` — FastAPI backend: `GET /` (serves index.html), `GET /health`,
  `POST /process` (full UI payload), `POST /summarise` (compact legacy).
- `app/static/index.html` — single-file clinician web UI (vanilla JS, no build step).
- `streamlit_app.py` — Streamlit demo (no API keys required; rule layer only).
- `Dockerfile` — HF Spaces Docker config; uvicorn on port 7860.
- `eval/run_eval.py` — LangSmith evals: `zero_phi_to_model` (must be 1.0) + `faithfulness`.
- `langgraph.json`, `.env.example`.
- `docs/tool_card.md` — Five Safes, bias & fairness, use cases out of scope.
- `docs/report.md` — ATRS Tier 1 + Tier 2 record.

## Commands
- De-id demo (no keys): `python src/deid.py`
- Install: `pip install -e ".[dev]"`
- Clinician web UI: `uvicorn app.api:app --reload --port 8000` (or `make run`)
  then open http://localhost:8000
- Serve agent (Agent Chat UI): `langgraph dev`
  then open: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
- Evals: `python -m eval.run_eval`
- Deploy: push to `main` → `.github/workflows/deploy-hf.yml` mirrors it onto the HF
  Space `chaeyoona/noteguard-agent` (needs `HF_TOKEN` repo secret); HF rebuilds from
  `Dockerfile` (Docker SDK, `app_port: 7860`).
- Env: copy `.env.example` → `.env`; fill `GOOGLE_API_KEY`, `TAVILY_API_KEY`,
  `LANGSMITH_API_KEY`; set `LANGSMITH_TRACING=true`.

## Components
Gemini (reasoning) + Tavily (public-guidance grounding) are the external services.
LangGraph orchestrates the pipeline; LangSmith provides traces + evals. Superlinked
(retrieval) and n8n (a proxy workflow) were hackathon-era integrations that never ran
in the deployed Space and were removed in `1.0`.

## Dataset
`NHSEDataScience/synthetic_clinical_notes` (Hugging Face, MIT, fully synthetic).
Build the vault from `patients.csv` via `load_known_from_csv()` so leakage is
measured against ground truth. Dataset has mojibake — `_fix_mojibake` handles it.

## Conventions
- Python 3.10+. Keep `src/deid.py` std-lib only.
- Verify/round any number shown in the demo.
- Model id lives in `NOTEGUARD_MODEL` (default `google_genai:gemini-2.5-flash`).
- Versions drift: if a `langgraph`/`langsmith`/`create_react_agent` import fails,
  adjust to the installed version rather than pinning blindly.
- `src/__init__.py` exports only `NoteGuard`, `DeidResult`, `load_known_from_csv`.
- `pyproject.toml` is the single dependency source; `requirements.txt` is removed.
- Linting: `ruff check` + `ruff format` (not black).

## HF Spaces notes
- The Docker image installs only the runtime deps in `pyproject.toml`; `streamlit`
  and `dev` extras are not part of the deployed image.
- Set `GOOGLE_API_KEY`, `TAVILY_API_KEY`, `LANGSMITH_API_KEY` in Space Secrets.

## Ethics
Pseudonymised ≠ anonymous (still personal data under UK GDPR). Synthetic ≠ real —
frame as methodology. Clinician stays in the loop and signs off.
