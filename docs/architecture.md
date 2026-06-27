# Architecture

## Overview

NoteGuard is the trust layer for clinical AI — a LangGraph ReAct agent (Gemini +
Tavily + Superlinked) where the language model structurally **cannot** see patient
identifiers because `assert_clean()` raises before any PHI reaches it.

The system has four layers:

1. **De-identification core** (`noteguard/deid.py`) — dependency-free, runnable
   standalone. NHS-aware recognisers, vault-from-CSV, consistent surrogates,
   DOB date-shift, `assert_clean()` hard guarantee.
2. **Retrieval** (`noteguard/retrieve.py`) — Superlinked in-memory vector index.
   `assert_clean()` called on every document indexed and every chunk retrieved.
3. **Agent** (`agent/graph.py`) — LangGraph `StateGraph`. Gemini drafts the
   answer; Tavily grounds it in NICE/NHS public guidance. Neither sees PHI.
4. **UI** (`app/trust_panel.py`) — Streamlit trust panel styled to the NHS
   England identity.

## Package layout

```
noteguard/
├── __init__.py        # exports NoteGuard, DeidResult, load_known_from_csv, NoteIndex
├── deid.py            # de-id core (standard library only)
└── retrieve.py        # Superlinked NoteIndex — PHI-safe vector retrieval

agent/
└── graph.py           # LangGraph StateGraph exposed as `noteguard` for langgraph dev

app/
└── trust_panel.py     # Streamlit demo UI with trust panel

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

## External services

| Concern | Service | Notes |
|---|---|---|
| Reasoning | Google Gemini | `google_genai:gemini-2.5-flash` (configurable via `NOTEGUARD_MODEL`). |
| Retrieval | Superlinked | In-memory vector index; `all-MiniLM-L6-v2` embeddings. |
| Grounding | Tavily | Public NICE/NHS guidance only — patient text never sent. |
| Observability | LangSmith | Auto-traces when `LANGSMITH_TRACING=true`. |

All credentials are read from environment variables; nothing is hard-coded.
