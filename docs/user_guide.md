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

pip install -e ".[dev]"
```

To also install the Streamlit de-id demo:

```bash
pip install -e ".[demo]"       # Streamlit interactive demo
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

## Running the de-identification demo (no API keys needed)

```bash
python src/deid.py
```

Demonstrates the de-id core on a synthetic note — no network calls, no keys.

## Running the interactive Streamlit demo (no API keys needed)

```bash
streamlit run streamlit_app.py
```

Lets you paste any text, click **De-identify**, and see the surrogate-token
output alongside the vault contents and `assert_clean` result.

## Downloading the dataset

```bash
python src/fetch_dataset.py
```

Downloads `patients.csv`, `admissions.csv`, and `synthetic_clinical_notes.csv`
from the `NHSEDataScience/synthetic_clinical_notes` Hugging Face dataset into `data/`.
Run once before starting the server to enable the note-picker and vault-based leakage metrics.

## Running the clinician web UI (recommended for demos)

```bash
uvicorn app.api:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000).

1. Click **Load note** (top-right) to open the note picker, or paste your own note.
2. Click **Generate** (~20–30 s on first run; the model loads and de-identifies).
3. Use the segmented toggle to switch views without re-calling the API:
   - **Clinician view** — the original note with every redacted identifier highlighted in red.
   - **What the AI sees** — the de-identified note; real identifiers are replaced by
     `[TYPE_N]` surrogate chips (e.g. `[PERSON_1]`, `[NHS_1]`).
4. The compact eDischarge card appears on the right, re-identified for the clinician.
5. The trust panel below shows whether de-identification was done correctly — and
   nothing about answer quality:
   - **De-identification** — `PASS` only when nothing un-redacted reached the model
     *and* every surrogate is reversible; `FAIL` otherwise.
   - **Identifiers replaced** — count of PII spans pseudonymised in this call.
   - **Residual PII · model input** — suspected un-redacted identifiers the model still
     saw (`0` = clean). When > 0, the offending snippets are listed (e.g.
     `name: Ethel Joanne Duffy`). This catches free-text names the vault/NER passes
     missed — the case the old re-id-risk number was blind to.
   - **Reversible** — `✓` when every surrogate restores to a real value; `✗` lists the
     orphaned/unresolved tokens.
6. Click **← Edit note** to reset and process a different note.

## Running the LangGraph dev server

```bash
langgraph dev
```

Connect the [Agent Chat UI](https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024)
and interact with the `noteguard` graph directly.

## Running the LangSmith evaluations

```bash
python -m eval.run_eval
```

Needs `LANGSMITH_API_KEY` and `LANGSMITH_TRACING=true`. Runs two evaluators:

| Evaluator | Target | What it measures |
|---|---|---|
| `zero_phi_to_model` | 1.0 | No known identifier appeared in any message seen by the model. |
| `faithfulness` | 0.8+ | Every clinical claim in the answer is supported by the source note. |

## Development

```bash
ruff check src agent app eval tests   # lint
ruff format src agent app eval tests  # format
pytest                                 # run the test suite
pytest --cov=src --cov-report=term    # with coverage
```

## Loading a real patient vault

The de-id core can be seeded from the
[`NHSEDataScience/synthetic_clinical_notes`](https://huggingface.co/datasets/NHSEDataScience/synthetic_clinical_notes)
dataset (MIT licence, fully synthetic):

```python
from src.deid import NoteGuard, load_known_from_csv

known = load_known_from_csv("data/patients.csv", "data/admissions.csv")
ng = NoteGuard(known=known)
result = ng.deidentify(raw_note)
ng.assert_clean(result.clean_text)
```

This builds the identifier vault from both structured tables — patient names and
clinician names — so residual leakage is measured against ground truth.
