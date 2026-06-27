# NoteGuard — the trust layer for clinical AI

## What this is
Hackathon build ({Tech: Europe} London AI Hackathon). NoteGuard de-identifies NHS
clinical free-text so LLM agents can use it safely, and proves the privacy with a
measured number. This repo is the **agent slice**: a LangGraph ReAct agent
(Gemini + Tavily + Superlinked) wrapped so the model and tools only ever see
de-identified text; real identifiers are restored only in the final clinician-facing
answer.

Full plan and rationale: `docs/plan.md` (read it if you need the why).

## Architecture
`deidentify_in → retrieve_context → agent (Gemini + Tavily) → reidentify_out → compute_trust`
- The guarantee (non-negotiable): nothing downstream of `deidentify_in` may
  receive PHI. `assert_clean()` raises if any identifier remains. Never weaken or
  bypass this — it is the whole point of the project.
- Tavily is public-guidance grounding only (NICE/NHS). Never send patient text to it.

## Key files
- `noteguard/deid.py` — de-id core (std-lib only): NHS-aware rules + vault-from-CSV,
  consistent surrogates, DOB date-shift, `reidentify`, `assert_clean`. Keep it
  dependency-free; Presidio/spaCy are optional behind the same interface.
- `noteguard/retrieve.py` — Superlinked in-memory NoteIndex; `assert_clean` on every
  doc in and every chunk out. Lazy-imported — unavailable in CI and on Vercel.
- `agent/graph.py` — the graph; exposed as `noteguard` for `langgraph dev`. NoteIndex
  import is lazy (inside a try block) so the module loads without superlinked.
- `app/api.py` — FastAPI backend: `GET /` (serves index.html), `GET /health`,
  `POST /process` (full UI payload), `POST /summarise` (compact legacy).
- `app/static/index.html` — single-file clinician web UI (vanilla JS, no build step).
- `api/index.py` — Vercel ASGI entry point (`from app.api import app`).
- `api/requirements.txt` — light production deps for Vercel (no superlinked/torch).
- `vercel.json` — Vercel config: routes all traffic → api/index.py, bundles
  app/agent/noteguard dirs, maxDuration 60 s.
- `eval/run_eval.py` — LangSmith evals: `zero_phi_to_model` (must be 1.0) + `faithfulness`.
- `langgraph.json`, `.env.example`, `requirements.txt`.

## Commands
- De-id demo (no keys): `python noteguard/deid.py`
- Install: `pip install -r requirements.txt`
- Clinician web UI: `uvicorn app.api:app --reload --port 8000` (or `make run`)
  then open http://localhost:8000
- Serve agent (Agent Chat UI): `langgraph dev`
  then open: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
- Evals: `python -m eval.run_eval`
- Deploy: `vercel --prod` (requires Vercel CLI: `npm i -g vercel`)
- Env: copy `.env.example` → `.env`; fill `GOOGLE_API_KEY`, `TAVILY_API_KEY`,
  `LANGSMITH_API_KEY`; set `LANGSMITH_TRACING=true`.

## Sponsors / counting
Partner techs for the ≥3 rule: **Gemini + Tavily + Superlinked**. LangGraph and
LangSmith are NOT listed partners (they're for depth + observability and don't
count). Stretch sponsors: n8n (ingest), Mubit (model routing), Aikido (repo scan),
SLNG (voice).

## Dataset
`NHSEDataScience/synthetic_clinical_notes` (Hugging Face, MIT, fully synthetic).
Build the vault from `patients.csv` via `load_known_from_csv()` so leakage is
measured against ground truth. Dataset has mojibake — `_fix_mojibake` handles it.

## Conventions
- Python 3.10+. Keep `noteguard/deid.py` std-lib only.
- Verify/round any number shown in the demo.
- Model id lives in `NOTEGUARD_MODEL` (default `google_genai:gemini-2.5-flash`).
- Versions drift: if a `langgraph`/`langsmith`/`create_react_agent` import fails,
  adjust to the installed version rather than pinning blindly.
- `noteguard/__init__.py` must NOT re-export `NoteIndex` — superlinked is not
  available in CI or on Vercel and the import would break both.

## Vercel notes
- Superlinked/torch exceed the 250 MB bundle limit → excluded from `api/requirements.txt`.
- `agent/graph.py` falls back gracefully when NoteIndex is unavailable.
- `maxDuration: 60` (Hobby plan limit). Gemini inference typically 15–40 s.
- Set `GOOGLE_API_KEY`, `TAVILY_API_KEY`, `LANGSMITH_API_KEY` in Vercel dashboard.

## Hackathon constraints
Newly built today (boilerplate allowed — state reused-vs-new in README). Submit by
19:00. ≥3 partner techs. Public repo + README + 2-min video.

## Ethics
Pseudonymised ≠ anonymous (still personal data under UK GDPR). Synthetic ≠ real —
frame as methodology. Clinician stays in the loop and signs off.
