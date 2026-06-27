# NoteGuard — the trust layer for clinical AI

## What this is
Hackathon build ({Tech: Europe} London AI Hackathon). NoteGuard de-identifies NHS
clinical free-text so LLM agents can use it safely, and proves the privacy with a
measured number. This repo is the **agent slice**: a LangGraph ReAct agent
(Gemini + Tavily) wrapped so the model and tools only ever see de-identified text;
real identifiers are restored only in the final clinician-facing answer.

Status: de-id core + LangGraph graph + LangSmith eval are written; the de-id core
is verified running. Next: add PHI-safe retrieval (Superlinked).

Full plan and rationale: `docs/plan.md` (read it if you need the why).

## Architecture
`deidentify_in → agent (Gemini + Tavily) → reidentify_out`
- The guarantee (non-negotiable): nothing downstream of `deidentify_in` may
  receive PHI. `assert_clean()` raises if any identifier remains. Never weaken or
  bypass this — it is the whole point of the project.
- Tavily is public-guidance grounding only (NICE/NHS). Never send patient text to it.

## Key files
- `noteguard/deid.py` — de-id core (std-lib only): NHS-aware rules + vault-from-CSV,
  consistent surrogates, DOB date-shift, `reidentify`, `assert_clean`. Keep it
  dependency-free; Presidio/spaCy are optional behind the same interface.
- `agent/graph.py` — the graph; exposed as `noteguard` for `langgraph dev`.
- `eval/run_eval.py` — LangSmith evals: `zero_phi_to_model` (must be 1.0) + `faithfulness`.
- `langgraph.json`, `.env.example`, `requirements.txt`.

## Commands
- De-id demo (no keys): `python noteguard/deid.py`
- Install: `pip install -r requirements.txt`
- Serve agent: `langgraph dev` (then connect Agent Chat UI)
- Evals: `python -m eval.run_eval`
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

## Next steps (in order)
1. Add a **Superlinked** retrieval node feeding the agent de-identified context
   (banks the 3rd sponsor; enables cohort search). Plan before implementing.
2. Wire **Agent Chat UI** to `langgraph dev` for the demo.
3. Build the trust panel (residual leakage %, identifiers removed, faithfulness, sources).
4. Aikido scan + screenshot. Record 2-min Loom. README: boilerplate-vs-new table.

## Hackathon constraints
Newly built today (boilerplate allowed — state reused-vs-new in README). Submit by
19:00. ≥3 partner techs. Public repo + README + 2-min video.

## Ethics
Pseudonymised ≠ anonymous (still personal data under UK GDPR). Synthetic ≠ real —
frame as methodology. Clinician stays in the loop and signs off.
