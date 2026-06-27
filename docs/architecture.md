# Architecture

## Overview

NoteGuard is the trust layer for clinical AI — a LangGraph ReAct agent (Gemini +
Tavily + Superlinked) where the language model structurally **cannot** see patient
identifiers because `assert_clean()` raises before any PHI reaches it.

The system has five layers:

1. **De-identification core** (`src/deid.py`) — dependency-free, runnable
   standalone. NHS-aware recognisers, vault-from-CSV, consistent surrogates,
   DOB date-shift, `assert_clean()` hard guarantee.
2. **Retrieval** (`src/retrieve.py`) — Superlinked in-memory vector index.
   `assert_clean()` called on every document indexed and every chunk retrieved.
3. **Agent** (`agent/graph.py`) — LangGraph `StateGraph`. Gemini drafts the
   answer; Tavily grounds it in NICE/NHS public guidance. Neither sees PHI.
4. **REST API** (`app/api.py`) — FastAPI backend exposing `GET /` (web UI),
   `GET /health`, `POST /process`, `POST /summarise`, `GET /samples`, and
   `GET /sample/{id}`. Also serves the static clinician UI.
5. **UI** — `app/static/index.html` (clinician web UI, vanilla JS, no build step, served by the FastAPI `GET /` handler).

## Package layout

```
src/
├── __init__.py           # exports NoteGuard, DeidResult, load_known_from_csv
├── deid.py               # de-id core (standard library only)
├── retrieve.py           # Superlinked NoteIndex — PHI-safe vector retrieval
└── fetch_dataset.py      # downloads synthetic_clinical_notes to data/

agent/
└── graph.py              # LangGraph StateGraph exposed as `noteguard` for langgraph dev

app/
├── api.py                # FastAPI — GET /, GET /health, GET /samples, GET /sample/{id},
│                         #           POST /process, POST /summarise
└── static/
    └── index.html        # Clinician web UI (single-file, vanilla JS, no build step)

streamlit_app.py          # Interactive de-id demo — no API keys needed

eval/
└── run_eval.py           # LangSmith evals: zero_phi_to_model + faithfulness

tests/                    # pytest suite (24 tests, no external deps)
data/                     # synthetic CSV files (git-ignored; produced by src/fetch_dataset.py)
outputs/                  # pipeline outputs (git-ignored)
docs/                     # architecture, user guide, RAP compliance, tool card, ATRS report
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
| `person_name` | `str` | Real patient name for `{{PATIENT}}` placeholder resolution. |
| `forward` | `dict` | Original-identifier → surrogate mapping. |
| `identifiers_removed` | `int` | Count of identifiers replaced in this turn. |
| `residual_count` | `int` | Known identifiers that survived (target: 0). |
| `leaked_tokens` | `list[str]` | Unmapped/unresolved surrogate tokens detected post-model. |
| `retrieved_context` | `list[str]` | Superlinked chunks fed to the agent. |
| `clinician_answer` | `str` | Re-identified, clinician-facing answer. |
| `faithfulness_score` | `float` | LLM-as-judge 0–1 score. |
| `sources` | `list[str]` | Tavily / NICE / NHS URLs cited. |

## REST API

`app/api.py` exposes six endpoints:

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Serves `app/static/index.html` — the clinician web UI. |
| `/health` | GET | Liveness probe; no API keys required. Returns `notes_loaded` count. |
| `/samples` | GET | Paginated list of synthetic notes; supports `q`, `note_type`, `limit`, `offset`. |
| `/sample/random` | GET | One random synthetic note. |
| `/sample/{clinical_note_id}` | GET | Full note by ID (used by the note-picker modal). |
| `/process` | POST | Full UI payload: `clinician_note`, `ai_note`, `identifiers`, `discharge_summary`, `metrics`. |
| `/summarise` | POST | Compact payload: `clinician_answer`, `identifiers_removed`, `residual_risk`, `deidentified_excerpt`, `ok`. |

`POST /process` request shape:

```json
{
  "note": "Pt Margaret Okafor (NHS 485 777 3456) admitted post-fall.",
  "question": "Draft a discharge summary.",
  "person_id": "pt-001"
}
```

`POST /process` response shape:

```json
{
  "clinician_note": "verbatim input",
  "ai_note": "de-identified text the model saw ([PERSON_1], [NHS_1], …)",
  "identifiers": ["Margaret Okafor", "485 777 3456", "…"],
  "discharge_summary": "re-identified Gemini compact eDischarge card for the clinician",
  "metrics": {
    "identifiers_removed": 5,
    "residual_risk": 0.0,
    "grounded_sources": 2,
    "faithfulness": 0.9,
    "leaked_tokens": []
  }
}
```

`422` is returned when `assert_clean()` detects surviving PHI — the model sees nothing.

`metrics.residual_risk` is `0.0` when the guarantee holds; fractional (or `1.0`) when
residual identifiers or leaked surrogate tokens are detected.

## Clinician web UI

`app/static/index.html` is a self-contained single-page application (vanilla JS, no build step):

- **Note picker modal** — browse and filter synthetic notes by keyword and note type;
  clicking a row loads the note into the textarea and sets `person_id` for `{{PATIENT}}` resolution.
- **Segmented toggle** — switches between two views without re-calling the API:
  - *Clinician view*: original note with each redacted identifier wrapped in a red `<mark>`.
  - *What the AI sees*: de-identified note with `[TYPE_N]` surrogate tokens displayed as blue monospace chips.
- **Generate** — POSTs to `/process`, populates the discharge summary pane and trust panel.
- **Trust panel** — metric cards: Re-id risk, Identifiers removed, Faithfulness (hidden if `null`), Grounded sources, leaked tokens (shown when non-empty).

## External services

| Concern | Service | Notes |
|---|---|---|
| Reasoning | Google Gemini | `google_genai:gemini-2.5-flash` (configurable via `NOTEGUARD_MODEL`). |
| Retrieval | Superlinked | In-memory vector index; `all-MiniLM-L6-v2` embeddings. Lazy import; gracefully omitted in Docker. |
| Grounding | Tavily | Public NICE/NHS guidance only — patient text never sent. |
| Observability | LangSmith | Auto-traces when `LANGSMITH_TRACING=true`. |

All credentials are read from environment variables; nothing is hard-coded.

## Deployment

### Local (development)

```bash
pip install -e ".[dev]"
uvicorn app.api:app --reload --port 8000
```

### Hugging Face Spaces (production)

`Dockerfile` builds a Docker image that excludes Superlinked/torch to keep the image
lean (<1 GB). The retrieval node is disabled via the existing fallback path in
`agent/graph.py`; all other features work identically.

Required secrets: `GOOGLE_API_KEY`, `TAVILY_API_KEY`, `LANGSMITH_API_KEY`.
