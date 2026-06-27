# User guide

## Prerequisites

- Python 3.10 or later
- A free [Google AI Studio API key](https://aistudio.google.com/apikey)
- A [Tavily API key](https://tavily.com) (free tier available)
- A [LangSmith API key](https://smith.langchain.com) (free tier available)

## Installation

```bash
git clone https://github.com/chaeyoonyunakim/noteguard-agent.git
cd noteguard-agent

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
```

## Configuration

```bash
cp .env.example .env
```

Open `.env` and fill in your credentials:

```env
GOOGLE_API_KEY=AIza...
TAVILY_API_KEY=tvly-...
LANGSMITH_API_KEY=ls__...
LANGSMITH_TRACING=true
# NOTEGUARD_MODEL=google_genai:gemini-2.5-flash   # optional override
```

## Running the clinician web UI (recommended for demos)

```bash
uvicorn app.api:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000).

1. Click **Load synthetic note** to prefill a realistic ward note, or paste your own.
2. Click **Generate** (~20–30 s on first run; the model loads and de-identifies).
3. Use the segmented toggle to switch views without re-calling the API:
   - **Clinician view** — the original note with every redacted identifier highlighted in red.
   - **What the AI sees** — the de-identified note; real identifiers are replaced by
     `[TYPE_N]` surrogate chips (e.g. `[PERSON_1]`, `[NHS_1]`).
4. The discharge summary appears on the right, re-identified for the clinician, with a
   "powered by Gemini" label.
5. The trust panel below the two cards shows:
   - **Re-id risk · model input** — `0.0 %` when the privacy guarantee holds; `100.0 %` if PHI
     survived (should never happen on a healthy install).
   - **Identifiers removed** — count of distinct tokens de-identified in this call.
   - **Faithfulness** — LLM-as-judge score (`0–100 %`), hidden when no retrieval context was available.
   - **Grounded sources** — number of distinct Tavily / NICE / NHS URLs cited by Gemini.
6. Click **← Edit note** to reset and process a different note.

## Running the trust panel (Streamlit, alternative demo UI)

```bash
make run
# or: streamlit run app/trust_panel.py
```

Open [http://localhost:8501](http://localhost:8501).

1. Paste a ward note into the sidebar (a synthetic example is pre-loaded).
2. Click **Analyse with NoteGuard** (first run ~20–30 s; the model loads).
3. Toggle between **Raw note**, **What the AI sees**, and **Clinician answer**.
4. The trust panel shows identifiers removed, residual leakage %, faithfulness
   score, and source URLs.

## Running the LangGraph dev server

```bash
langgraph dev
```

Connect the [Agent Chat UI](https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024)
and interact with the `noteguard` graph directly.

## Running the LangSmith evaluations

```bash
make eval
# or: python -m eval.run_eval
```

Needs `LANGSMITH_API_KEY` and `LANGSMITH_TRACING=true`. Runs two evaluators:

| Evaluator | Target | What it measures |
|---|---|---|
| `zero_phi_to_model` | 1.0 | No known identifier appeared in any message seen by the model. |
| `faithfulness` | 0.8+ | Every clinical claim in the answer is supported by the source note. |

## Running the de-identification demo (no API keys needed)

```bash
python noteguard/deid.py
```

Demonstrates the de-id core on a synthetic note — no network calls, no keys.

## Development

```bash
make install-dev   # install dev deps + pre-commit hooks
make format        # auto-format with ruff + black
make lint          # ruff + black --check
make test          # run the pytest suite
make coverage      # tests with a coverage report
make help          # list all targets
```

## Loading a real patient vault

The de-id core can be seeded from the
[`NHSEDataScience/synthetic_clinical_notes`](https://huggingface.co/datasets/NHSEDataScience/synthetic_clinical_notes)
dataset (MIT licence, fully synthetic):

```python
from noteguard.deid import NoteGuard, load_known_from_csv

known = load_known_from_csv("patients.csv")
ng = NoteGuard(known=known)
result = ng.deidentify(raw_note)
ng.assert_clean(result.clean_text)
```

This builds the identifier vault from structured tables so residual leakage is
measured against ground truth rather than estimated.
