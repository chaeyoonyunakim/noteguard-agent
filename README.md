---
title: NoteGuard
emoji: 🏥
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

[![status: experimental](https://github.com/GIScience/badges/raw/master/status/experimental.svg)](https://github.com/GIScience/badges#experimental)
[![CI](https://github.com/chaeyoonyunakim/noteguard-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/chaeyoonyunakim/noteguard-agent/actions/workflows/ci.yml)
[![RAP level: Gold](https://img.shields.io/badge/RAP-Gold-ffd700)](https://nhsdigital.github.io/rap-community-of-practice/introduction_to_RAP/levels_of_RAP/)
[![code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000)](https://github.com/astral-sh/ruff)

# NoteGuard — Trust Layer for Clinical AI

> **{Tech: Europe} London AI Hackathon**
> NHS clinical notes go in → a safe AI-drafted summary comes out → the model **provably never sees a single identifier**, with a live re-identification-risk number to prove it.

Partner technologies: **Gemini · Tavily · Superlinked** (≥3 rule met)
Observability: LangSmith traces + evals (not a listed partner, counts for depth)

---

## What it does

```
messy NHS note  ──►  NoteGuard de-id  ──►  de-identified text
(synthetic)           (NHS-aware rules       + identifiers removed count
                       + vault from CSV)     + residual leakage %
                                │
                         Superlinked  ──  PHI-safe semantic retrieval
                         (patient journey context, no PHI ever indexed)
                                │
                  Tavily (NICE/NHS guidance) ──►│
                                                ▼
                                         Gemini drafts
                                         compact eDischarge card
                                         (sees ONLY de-identified text)
                                                │
                         NoteGuard re-id  ◄─────┘
                         (surrogates → real names, clinician only)
                                │
                         Trust panel:
                         leakage % · identifiers removed
                         leaked tokens · faithfulness · sources
```

The **key technical guarantee**: `assert_clean()` raises before Gemini or Tavily receive anything — the model structurally cannot leak what it never saw.

---

## Quickstart

```bash
# 1. Clone and create environment
git clone https://github.com/chaeyoonyunakim/noteguard-agent.git
cd noteguard-agent
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

# 2. Install
pip install -e ".[dev]"

# 3. Configure
cp .env.example .env
# fill: GOOGLE_API_KEY  TAVILY_API_KEY  LANGSMITH_API_KEY

# 4. Smoke test — no API keys needed
python src/deid.py

# 5. Interactive de-id demo — no API keys needed
streamlit run streamlit_app.py

# 6. Clinician web UI (full agent)
uvicorn app.api:app --reload --port 8000
# then open: http://localhost:8000

# 7. LangGraph dev server + Agent Chat UI
langgraph dev   # requires pip install -e ".[dev]"
# then open: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024

# 8. LangSmith evals
python -m eval.run_eval
```

---

## Key files

| File | Purpose |
|---|---|
| `src/deid.py` | Dependency-free de-id core. `python src/deid.py` runs standalone. |
| `src/retrieve.py` | Superlinked NoteIndex — `add_notes` + `retrieve`, both guarded by `assert_clean`. |
| `src/fetch_dataset.py` | Downloads the synthetic dataset into `data/` (run once). |
| `agent/graph.py` | LangGraph graph exposed as `noteguard` for `langgraph dev`. |
| `app/api.py` | FastAPI backend — `/`, `/health`, `/process`, `/summarise`, `/samples`, `/sample/{id}`. |
| `app/static/index.html` | Single-file clinician web UI (vanilla JS, no build step). |
| `streamlit_app.py` | Interactive de-id demo — no API keys needed. |
| `eval/run_eval.py` | LangSmith evals: `zero_phi_to_model` (must be 1.0) + faithfulness. |
| `langgraph.json` | Graph manifest for `langgraph dev`. |
| `.env.example` | Required environment variables. |
| `docs/tool_card.md` | Five Safes, bias & fairness, use cases out of scope, DPIA prerequisites. |
| `docs/report.md` | gov.uk ATRS record (Tier 1 + Tier 2). |

---

## The guarantee (non-negotiable)

```
deidentify_in → assert_clean() → [ONLY DE-IDENTIFIED TEXT] → Gemini / Tavily
                                                               ↓
                                                          reidentify_out → clinician
```

`assert_clean()` raises `ValueError` if any known identifier or regex pattern (NHS number, email, phone, GMC, NMC, postcode) survives de-identification. The LangSmith `zero_phi_to_model` evaluator verifies this on every run and must score **1.0**.

---

## REST API

### POST /process

```json
{
  "note": "Pt Margaret Okafor (NHS 485 777 3456) admitted post-fall.",
  "question": "Draft a discharge summary.",
  "person_id": "pt-001"
}
```

Response fields:

| Field | Description |
|---|---|
| `clinician_note` | Verbatim input note |
| `ai_note` | De-identified note the model saw (surrogate tokens) |
| `identifiers` | Original identifier strings that were redacted |
| `discharge_summary` | Gemini-drafted compact eDischarge card, re-identified for the clinician |
| `metrics.identifiers_removed` | Count of identifiers replaced |
| `metrics.residual_risk` | `0.0` when privacy guarantee held; fractional or `1.0` when leaks detected |
| `metrics.leaked_tokens` | List of unmapped/unresolved surrogate tokens detected post-model |
| `metrics.grounded_sources` | Distinct Tavily sources cited |
| `metrics.faithfulness` | LLM-judge score `0–1`, or `null` if no retrieval context |

A `422` response means `assert_clean()` detected surviving PHI — the request is rejected before the model sees anything.

### GET /samples

Paginated list of synthetic notes with optional search and `note_type` filter.

```
GET /samples?q=COPD&note_type=Discharge&limit=50
```

### GET /sample/{clinical_note_id}

Returns the full note text for a given note ID (used by the note-picker UI).

---

## Reused vs built at the hackathon

| Component | Reused (NoteGuard v1 boilerplate) | Built at the hackathon |
|---|---|---|
| `src/deid.py` | NHS-aware NER rules, vault-from-CSV, consistent surrogates, DOB date-shift, mojibake fix | GMC/NMC connector words, Presidio detector interface, admissions.csv vault, word-boundary residual check |
| `src/retrieve.py` | — | **Superlinked** in-memory vector index; `assert_clean` on every doc in/out |
| `agent/graph.py` | — | Full LangGraph pipeline: de-id → retrieve → Gemini → re-id → trust metrics; `{{PATIENT}}` placeholder |
| `app/api.py` | — | FastAPI backend: `/`, `/health`, `/process`, `/summarise`, `/samples`, `/sample/{id}`; `person_id` resolution |
| `app/static/index.html` | — | Single-file clinician UI: note picker modal, PHI-highlight toggle, compact eDischarge card, trust panel with leak detail |
| `streamlit_app.py` | — | Interactive de-id demo; no API keys needed |
| `eval/run_eval.py` | Residual-leakage metric concept | `zero_phi_to_model` + faithfulness LangSmith evals |

---

## n8n integration

NoteGuard exposes a REST API so any automation platform can act as a headless front door.

```bash
npx n8n          # start n8n at http://localhost:5678
```

1. Open n8n → **Workflows** → **Import from file**
2. Select `workflows/noteguard.n8n.json`
3. Activate — exposes `POST http://localhost:5678/webhook/noteguard`

---

## Hugging Face Spaces deployment

The app ships as a Docker Space — FastAPI + vanilla JS UI, served by uvicorn on port 7860.
Superlinked/torch are excluded from the image (retrieval falls back to Gemini-only mode).

**Required secrets** (Space → Settings → Variables and secrets):

- `GOOGLE_API_KEY`
- `TAVILY_API_KEY`
- `LANGSMITH_API_KEY` (optional — enables tracing)

---

## Sponsor map

| Stage | Partner | Role |
|---|---|---|
| Reasoning | **Google Gemini** | Drafts discharge summary; sees only de-identified text |
| Retrieval | **Superlinked** | Vector index over de-identified notes; PHI-safe cohort search |
| Grounding | **Tavily** | Pulls NICE / NHS public guidance; never receives patient text |
| Observability | LangSmith | Traces + privacy & faithfulness evals (not a listed partner) |

---

## Data

`NHSEDataScience/synthetic_clinical_notes` (Hugging Face, MIT licence, fully synthetic).

```bash
python src/fetch_dataset.py   # downloads patients.csv, admissions.csv, synthetic_clinical_notes.csv into data/
```

`load_known_from_csv("data/patients.csv", "data/admissions.csv")` builds the identifier vault from both structured tables — patient names and clinician names — so residual leakage is measured against ground truth.

---

## Ethics

- Pseudonymised ≠ anonymous — still personal data under UK GDPR; don't over-claim.
- Synthetic ≠ real — frame as methodology, not a finished product.
- Clinician stays in the loop and signs off every summary.
- See [`docs/tool_card.md`](docs/tool_card.md) for the full Five Safes mapping and bias & fairness statement.
