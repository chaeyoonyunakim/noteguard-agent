# Architecture

## Overview

NoteGuard is the trust layer for clinical AI — a LangGraph ReAct agent (Gemini +
Tavily + Superlinked) where the language model structurally **cannot** see patient
identifiers because `assert_clean()` raises before any PHI reaches it.

The system has five layers:

1. **De-identification core** (`noteguard/deid.py`) — dependency-free, runnable
   standalone. NHS-aware recognisers, vault-from-CSV, consistent surrogates,
   DOB date-shift, `assert_clean()` hard guarantee.
2. **Retrieval** (`noteguard/retrieve.py`) — Superlinked in-memory vector index.
   `assert_clean()` called on every document indexed and every chunk retrieved.
3. **Agent** (`agent/graph.py`) — LangGraph `StateGraph`. Gemini drafts the
   answer; Tavily grounds it in NICE/NHS public guidance. Neither sees PHI.
4. **REST API** (`app/api.py`) — FastAPI backend exposing `GET /` (web UI),
   `GET /health`, `POST /process`, and `POST /summarise`. Also serves the
   static clinician UI.
5. **UI** — `app/static/index.html` (clinician web UI, vanilla JS, no build step, served by the FastAPI `GET /` handler).

## Package layout

```
noteguard/
├── __init__.py        # exports NoteGuard, DeidResult, load_known_from_csv
├── deid.py            # de-id core (standard library only)
└── retrieve.py        # Superlinked NoteIndex — PHI-safe vector retrieval

agent/
└── graph.py           # LangGraph StateGraph exposed as `noteguard` for langgraph dev

app/
├── api.py             # FastAPI — GET /, GET /health, POST /process, POST /summarise
└── static/
    └── index.html     # Clinician web UI (single-file, vanilla JS, no build step)

api/
├── index.py           # Vercel ASGI entry point (re-exports app.api:app)
└── requirements.txt   # Production-only deps for Vercel function (no superlinked/torch)

eval/
└── run_eval.py        # LangSmith evals: zero_phi_to_model + faithfulness
```

## Graph pipeline

For every query the graph runs:

```
deidentify_in → retrieve_context → agent → reidentify_out → compute_trust
```

| Node | Function | Description |
|---|---|---|
| `deidentify_in` | `NoteGuard.deidentify()` + `assert_clean()` | Strips PHI; raises if any identifier survives. |
| `retrieve_context` | `NoteIndex.retrieve()` | Fetches de-identified context chunks from Superlinked. |
| `agent` | `create_react_agent` (Gemini + Tavily) | Drafts answer; sees only de-identified text. |
| `reidentify_out` | `NoteGuard.reidentify()` | Restores surrogates → real names for the clinician only. |
| `compute_trust` | LLM-as-judge + source extraction | Faithfulness score + source URLs for the trust panel. |

## State fields

In addition to `messages`, the graph state carries:

| Field | Type | Description |
|---|---|---|
| `deid_text` | `str` | De-identified version of the input note. |
| `identifiers_removed` | `int` | Count of identifiers replaced in this turn. |
| `residual_count` | `int` | Known identifiers that survived (target: 0). |
| `retrieved_context` | `list[str]` | Superlinked chunks fed to the agent. |
| `clinician_answer` | `str` | Re-identified, clinician-facing answer. |
| `faithfulness_score` | `float` | LLM-as-judge 0–1 score. |
| `sources` | `list[str]` | Tavily / NICE / NHS URLs cited. |

## REST API

`app/api.py` exposes four endpoints:

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Serves `app/static/index.html` — the clinician web UI. |
| `/health` | GET | Liveness probe; no API keys required. |
| `/process` | POST | Full UI payload: `clinician_note`, `ai_note`, `identifiers`, `discharge_summary`, `metrics`. |
| `/summarise` | POST | Compact payload: `clinician_answer`, `identifiers_removed`, `residual_risk`, `deidentified_excerpt`, `ok`. |

`POST /process` response shape:

```json
{
  "clinician_note": "verbatim input",
  "ai_note": "de-identified text the model saw ([PERSON_1], [NHS_1], …)",
  "identifiers": ["Margaret Okafor", "485 777 3456", "…"],
  "discharge_summary": "re-identified Gemini summary for the clinician",
  "metrics": {
    "identifiers_removed": 5,
    "residual_risk": 0.0,
    "grounded_sources": 2,
    "faithfulness": 0.9
  }
}
```

`422` is returned when `assert_clean()` detects surviving PHI — the model sees nothing.

## Clinician web UI

`app/static/index.html` is a self-contained single-page application (vanilla JS, no build step):

- **Segmented toggle** — switches between two views without re-calling the API:
  - *Clinician view*: original note with each redacted identifier wrapped in a red `<mark>`.
  - *What the AI sees*: de-identified note with `[TYPE_N]` surrogate tokens displayed as blue monospace chips.
- **Generate** — POSTs to `/process`, populates the discharge summary pane and trust panel.
- **Trust panel** — four metric cards: Re-id risk, Identifiers removed, Faithfulness (hidden if `null`), Grounded sources.

## External services

| Concern | Service | Notes |
|---|---|---|
| Reasoning | Google Gemini | `google_genai:gemini-2.5-flash` (configurable via `NOTEGUARD_MODEL`). |
| Retrieval | Superlinked | In-memory vector index; `all-MiniLM-L6-v2` embeddings. |
| Grounding | Tavily | Public NICE/NHS guidance only — patient text never sent. |
| Observability | LangSmith | Auto-traces when `LANGSMITH_TRACING=true`. |

All credentials are read from environment variables; nothing is hard-coded.

## Deployment

### Local (development)

```bash
uvicorn app.api:app --reload --port 8000
```

### Vercel (production)

`api/index.py` re-exports `app.api:app` as the Vercel ASGI handler.
`vercel.json` routes all traffic to that function and bundles `app/`, `agent/`,
and `noteguard/` directories. The `api/requirements.txt` intentionally omits
superlinked and torch to stay under Vercel's 250 MB bundle limit — the
retrieval node is skipped via the existing fallback path in `agent/graph.py`.

Function timeout: 60 s (`maxDuration` in `vercel.json`).

Required env vars: `GOOGLE_API_KEY`, `TAVILY_API_KEY`, `LANGSMITH_API_KEY`.
