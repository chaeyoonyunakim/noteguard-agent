[![status: experimental](https://github.com/GIScience/badges/raw/master/status/experimental.svg)](https://github.com/GIScience/badges#experimental)
[![CI](https://github.com/chaeyoonyunakim/noteguard-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/chaeyoonyunakim/noteguard-agent/actions/workflows/ci.yml)
[![RAP level: Gold](https://img.shields.io/badge/RAP-Gold-ffd700)](https://nhsdigital.github.io/rap-community-of-practice/introduction_to_RAP/levels_of_RAP/)
[![code style: black](https://img.shields.io/badge/code%20style-black-000000)](https://github.com/psf/black)

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
                                         discharge summary
                                         (sees ONLY de-identified text)
                                                │
                         NoteGuard re-id  ◄─────┘
                         (surrogates → real names, clinician only)
                                │
                         Trust panel:
                         leakage % · identifiers removed
                         faithfulness · sources
```

The **key technical guarantee**: `assert_clean()` raises before Gemini or Tavily receive anything — the model structurally cannot leak what it never saw.

---

## Quickstart

```bash
# 1. Create environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

# 2. Install
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# fill: GOOGLE_API_KEY  TAVILY_API_KEY  LANGSMITH_API_KEY

# 4. Smoke test (no keys needed)
python noteguard/deid.py

# 5. Streamlit trust panel (the demo UI)
streamlit run app/trust_panel.py

# 6. LangGraph dev server + Agent Chat UI
langgraph dev
# then open: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024

# 7. LangSmith evals
python -m eval.run_eval

# 8. REST API + Clinician Web UI
uvicorn app.api:app --reload --port 8000
# then open: http://localhost:8000
```

---

## Reused vs built at the hackathon

| Component | Reused (NoteGuard v1 boilerplate) | Built at the hackathon |
|---|---|---|
| `noteguard/deid.py` | NHS-aware NER rules, vault-from-CSV, consistent surrogates, DOB date-shift, mojibake fix | — |
| `noteguard/retrieve.py` | — | **Superlinked** in-memory vector index; `assert_clean` on every doc in/out |
| `agent/graph.py` | — | Full LangGraph pipeline: de-id → retrieve → Gemini → re-id → trust metrics |
| `app/trust_panel.py` | — | Streamlit UI: 3-way toggle, trust panel, identifier vault |
| `app/api.py` | — | FastAPI backend: `GET /`, `/health`, `POST /process`, `/summarise`; lazy graph import |
| `app/static/index.html` | — | Single-file clinician web UI: PHI-highlight toggle, trust panel, vanilla JS |
| `eval/run_eval.py` | Residual-leakage metric concept | `zero_phi_to_model` + faithfulness LangSmith evals |

---

## Key files

| File | Purpose |
|---|---|
| `noteguard/deid.py` | Dependency-free de-id core. `python noteguard/deid.py` runs standalone. |
| `noteguard/retrieve.py` | Superlinked NoteIndex — `add_notes` + `retrieve`, both guarded by `assert_clean`. |
| `agent/graph.py` | LangGraph graph exposed as `noteguard` for `langgraph dev`. |
| `app/api.py` | FastAPI backend — `/`, `/health`, `/process`, `/summarise`. |
| `app/static/index.html` | Single-file clinician web UI (vanilla JS, no build step). |
| `app/trust_panel.py` | Streamlit demo UI with trust panel. |
| `eval/run_eval.py` | LangSmith evals: `zero_phi_to_model` (must be 1.0) + faithfulness. |
| `langgraph.json` | Graph manifest for `langgraph dev`. |
| `.env.example` | Required environment variables. |

---

## The guarantee (non-negotiable)

```
deidentify_in → assert_clean() → [ONLY DE-IDENTIFIED TEXT] → Gemini / Tavily
                                                               ↓
                                                          reidentify_out → clinician
```

`assert_clean()` raises `ValueError` if any known identifier or regex pattern (NHS number, email, phone, GMC, postcode) survives de-identification. The LangSmith `zero_phi_to_model` evaluator verifies this on every run and must score **1.0**.

---

## n8n integration

NoteGuard exposes a REST API so any automation platform — n8n, Make, Zapier — can
act as a headless front door without touching the de-identification logic.

**n8n sends a ward note → NoteGuard de-identifies → Gemini drafts → n8n gets the clinician-safe answer back.** The model never sees PHI.

### Run the API + web UI

```bash
uvicorn app.api:app --reload --port 8000
# GET  http://localhost:8000            -> clinician web UI (NoteGuard demo)
# GET  http://localhost:8000/health     -> {"status": "ok"}
# POST http://localhost:8000/process    -> full UI payload (see below)
# POST http://localhost:8000/summarise  -> legacy compact payload
```

The web UI at `http://localhost:8000` lets you paste a ward note, click **Generate**, and see:
- **Clinician view** — the original note with each redacted identifier highlighted in red
- **What the AI sees** — the de-identified note with `[TYPE_N]` surrogate chips
- Discharge summary drafted by Gemini (re-identified for the clinician)
- Trust panel: re-id risk, identifiers removed, grounded sources

Example `POST /process` body:

```json
{
  "note": "Pt Margaret Okafor (NHS 485 777 3456) admitted post-fall.",
  "question": "Draft a discharge summary."
}
```

Response fields:

| Field | Description |
|---|---|
| `clinician_note` | Verbatim input note |
| `ai_note` | De-identified note the model saw (surrogate tokens) |
| `identifiers` | Original identifier strings that were redacted (for UI highlighting) |
| `discharge_summary` | Gemini-drafted summary, re-identified for the clinician |
| `metrics.identifiers_removed` | Count of identifiers replaced |
| `metrics.residual_risk` | `0.0` if privacy guarantee held, `1.0` otherwise |
| `metrics.grounded_sources` | Distinct Tavily sources cited |
| `metrics.faithfulness` | LLM-judge score `0–1`, or `null` if no retrieval context |

A `422` response means `assert_clean()` detected surviving PHI — the request is rejected before the model sees anything.

### Import the n8n workflow

```bash
npx n8n          # start n8n at http://localhost:5678
```

1. Open n8n → **Workflows** → **Import from file**
2. Select `workflows/noteguard.n8n.json`
3. Activate the workflow — it exposes `POST http://localhost:5678/webhook/noteguard`
4. Send a ward note to the n8n webhook; n8n forwards it to the NoteGuard API
   and returns the clinician-safe JSON response.

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
Use `load_known_from_csv("patients.csv")` to build the identifier vault from structured tables and measure residual leakage against ground truth.

---

## Ethics

- Pseudonymised ≠ anonymous — still personal data under UK GDPR; don't over-claim.  
- Synthetic ≠ real — frame as methodology, not a finished product.  
- Clinician stays in the loop and signs off every summary.
