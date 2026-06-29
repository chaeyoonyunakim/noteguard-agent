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

> NHS clinical notes go in → a safe AI-drafted summary comes out → the model **provably never sees a single identifier**, with a live re-identification-risk number to prove it.

NoteGuard is a LangGraph agent (Gemini + Tavily) wrapped so that the language
model and every tool only ever receive **de-identified** text. Real identifiers
are restored only in the final, clinician-facing answer. The guarantee is
enforced by `assert_clean()`, which raises before any PHI can reach the model.

> **Project history:** NoteGuard began at the {Tech: Europe} London AI Hackathon.
> This is the post-hackathon `1.0` line — the codebase has been pruned to exactly
> the components that ship in the deployed app. See [`CHANGELOG.md`](CHANGELOG.md).

---

## What it does

```
messy NHS note  ──►  NoteGuard de-id  ──►  de-identified text
(synthetic)           (NHS-aware rules       + identifiers removed count
                       + vault from CSV)     + residual leakage %
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
                         Trust panel (de-id correctness only):
                         de-id PASS/FAIL · identifiers replaced
                         residual PII (model input) · reversible
```

The **key technical guarantee**: `assert_clean()` raises before Gemini or Tavily
receive anything — the model structurally cannot leak what it never saw.

---

## Quickstart

```bash
# 1. Clone and create environment
git clone https://github.com/chaeyoonyunakim/noteguard-agent.git
cd noteguard-agent
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/Scripts/activate # bash
# source .venv/bin/activate     # macOS/Linux

# 2. Install
pip install -e ".[dev]"

# 3. Configure
cp .env.example .env
# fill: GOOGLE_API_KEY  TAVILY_API_KEY  LANGSMITH_API_KEY

# 4. Smoke test — no API keys needed
python src/deid.py

# 5. Interactive de-id demo — no API keys needed
pip install -e ".[demo]"
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

`assert_clean()` raises `ValueError` if any known identifier or regex pattern (NHS
number, email, phone, GMC, NMC, postcode) survives de-identification. The LangSmith
`zero_phi_to_model` evaluator verifies this on every run and must score **1.0**.

---

## Graph pipeline

```
deidentify_in → agent (Gemini + Tavily) → reidentify_out → compute_trust
```

| Node | Function |
|---|---|
| `deidentify_in` | `NoteGuard.deidentify()` + `assert_clean()` — strips PHI; raises if any identifier survives. |
| `agent` | `create_react_agent` (Gemini + Tavily) — drafts the eDischarge card; sees only de-identified text. |
| `reidentify_out` | `NoteGuard.reidentify()` — restores surrogates → real names for the clinician only. |
| `compute_trust` | Audits de-id correctness — `scan_pii(deid_text)` for residual PII the model saw, plus orphaned surrogate tokens for reversibility. |

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
| `metrics.deid_ok` | Overall verdict — `true` only when nothing leaked **and** every surrogate is reversible |
| `metrics.identifiers_removed` | Count of PII spans pseudonymised this turn |
| `metrics.residual_pii` | List of `{type, text}` — suspected un-redacted PII the model still saw |
| `metrics.residual_pii_count` | Number of residual-PII findings (`0` = de-identified) |
| `metrics.reversible` | `true` when every surrogate restores to a real value |
| `metrics.leaked_tokens` | Orphaned/unresolved surrogate tokens (the reversibility detail) |

A `422` response means `assert_clean()` detected surviving PHI — the request is
rejected before the model sees anything.

### GET /samples

Paginated list of synthetic notes with optional search and `note_type` filter.

```
GET /samples?q=COPD&note_type=Discharge&limit=50
```

### GET /sample/{clinical_note_id}

Returns the full note text for a given note ID (used by the note-picker UI).

---

## Components

| Stage | Service | Role |
|---|---|---|
| De-identification | `src/deid.py` | Dependency-free NHS-aware recognisers; the trust boundary. |
| Reasoning | **Google Gemini** | Drafts the discharge summary; sees only de-identified text. |
| Grounding | **Tavily** | Pulls NICE / NHS public guidance; never receives patient text. |
| Orchestration | **LangGraph** | Wires the de-id → agent → re-id → trust pipeline. |
| Observability | **LangSmith** | Traces + privacy & faithfulness evals. |

---

## Hugging Face Spaces deployment

The app ships as a Docker Space — FastAPI + vanilla JS UI, served by uvicorn on port 7860.

**Required secrets** (Space → Settings → Variables and secrets):

- `GOOGLE_API_KEY`
- `TAVILY_API_KEY`
- `LANGSMITH_API_KEY` (optional — enables tracing)

**Auto-deploy:** [`.github/workflows/deploy-hf.yml`](.github/workflows/deploy-hf.yml)
pushes a fresh snapshot of `main` onto the Space (`chaeyoona/noteguard-agent`) on
every push, which triggers a Docker rebuild. (A snapshot — a single orphan commit —
is used so historical binary blobs that HF's git backend rejects are never sent.)
It needs an `HF_TOKEN` repository secret — a write-scoped
[Hugging Face access token](https://huggingface.co/settings/tokens) added under
**Settings → Secrets and variables → Actions**. Trigger the first deploy manually via
the workflow's **Run workflow** button once the secret is set.

---

## Data

`NHSEDataScience/synthetic_clinical_notes` (Hugging Face, MIT licence, fully synthetic).

```bash
python src/fetch_dataset.py   # downloads patients.csv, admissions.csv, synthetic_clinical_notes.csv into data/
```

`load_known_from_csv("data/patients.csv", "data/admissions.csv")` builds the
identifier vault from both structured tables — patient names and clinician names —
so residual leakage is measured against ground truth.

---

## Ethics

- Pseudonymised ≠ anonymous — still personal data under UK GDPR; don't over-claim.
- Synthetic ≠ real — frame as methodology, not a finished product.
- Clinician stays in the loop and signs off every summary.
- See [`docs/tool_card.md`](docs/tool_card.md) for the full Five Safes mapping and bias & fairness statement.
