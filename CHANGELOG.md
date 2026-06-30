# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.1] - 2026-06-30

### Fixed

- **NER over-redaction of clinical terms** — the small spaCy model (`en_core_web_md`)
  shipped in 1.2.0 mislabels abbreviations like "Subcut" as a `PERSON`, and Presidio
  scores every spaCy entity a flat `0.85`, so a confidence threshold cannot separate
  them from real names. Added a clinical-term allow-list (`_NER_STOPWORDS`) applied at
  the detector boundary (`NoteGuard._detect_names`), so those terms are never redacted
  as names while real names alongside them still are. Used in both `deidentify()` and
  `residual_identifiers()` so the eval leak-check is consistent too.

## [1.2.0] - 2026-06-29

Follow-up to 1.1.0: actually **raise de-identification recall** so the residual-PII
audit has less to catch. The 1.1.0 panel honestly reported leaked free-text names
(e.g. "Dr Ethel Joanne Duffy") but nothing redacted them in the deployed image,
because Presidio/spaCy NER was wired behind the `_Detector` interface yet never
shipped. This turns it on.

### Added

- **Presidio + spaCy NER in the deployed image** — `Dockerfile` installs the `[nlp]`
  extra (`presidio-analyzer`, `spacy`) and `en_core_web_md`, so free-text PERSON/
  LOCATION names with no vault entry are now tokenised before the model sees them.
- **`[nlp]` optional dependency** in `pyproject.toml` (`pip install -e ".[nlp]"`).
- **`NOTEGUARD_SPACY_MODEL`** env var (default `en_core_web_md`) — switch to
  `en_core_web_lg` for higher recall at ~14× the model size, or `en_core_web_sm`
  for a smaller image.

### Changed

- `src/deid.py` `_build_detector()` now configures the spaCy model explicitly via
  `NlpEngineProvider` (so it no longer hard-defaults to the unshipped `en_core_web_lg`)
  and still degrades gracefully to a no-op stub when Presidio is absent (CI, local).
- Tests pin the no-op detector by default (autouse fixture) so the suite is
  deterministic whether or not the `[nlp]` extra is installed; a new test covers the
  NER redaction path.

### Notes

- NER is a recall **boost**, not a guarantee: `en_core_web_md` misses some names
  (recall is also lower for non-English names — see `docs/tool_card.md`). `scan_pii`
  remains the high-precision backstop that surfaces anything still leaking, and
  `assert_clean()` is unchanged (vault + structured patterns).

## [1.1.0] - 2026-06-29

The trust panel now reports **only** whether reversible pseudonymisation was done
correctly. The previous panel could read `RE-ID RISK 0.0%` while un-redacted free-text
names (e.g. "Dr Ethel Joanne Duffy") reached the model, because the risk number was
computed from the *vault* — and arbitrary pasted names are never in the vault.

### Added

- **`NoteGuard.scan_pii(text)`** (`src/deid.py`) — a vault-independent residual-PII
  audit of de-identified text. Flags structured identifiers that survived (NHS, GMC,
  NMC, email, phone, postcode) and free-text person names via a high-precision
  person-title heuristic (`Dr/Nurse/Consultant/…` + ≥2 Title-Case tokens). Surrogate
  tokens and bare role words are never flagged. Works on notes with no ground-truth
  vault, which is exactly where the old metric was blind.
- **Trust-panel metrics focused on de-id correctness** — `/process` now returns
  `deid_ok` (PASS/FAIL verdict), `residual_pii` (`[{type, text}]` the model still saw),
  `residual_pii_count`, and `reversible`. The UI cards become **De-identification**,
  **Identifiers replaced**, **Residual PII · model input** (with the offending snippets
  listed), and **Reversible**.

### Removed

- **Faithfulness and Grounded-sources metrics** from the trust panel — answer-quality
  signals, not de-identification correctness. Dropped the in-graph faithfulness judge
  (`model.invoke`) and Tavily-source extraction from `compute_trust`, and the
  `faithfulness_score` / `sources` state fields. (Tavily still grounds the answer; the
  `eval/run_eval.py` faithfulness evaluator is unchanged — it is a separate experiment.)
- **`metrics.residual_risk`** from `/process` — replaced by the honest `deid_ok` +
  `residual_pii_count`. `/summarise` keeps `residual_risk`/`ok`, now derived from the
  audit (`residual_pii` + `leaked_tokens`).

## [1.0.1] - 2026-06-28

### Changed

- **Default model downgraded to `gemini-2.0-flash`** — `NOTEGUARD_MODEL` default in
  `agent/graph.py` and `eval/run_eval.py` changed from `gemini-2.5-flash` to
  `gemini-2.0-flash`; `.env.example` updated to match.

### Added

- **HF Space auto-deploy** (`.github/workflows/deploy-hf.yml`) — every push to `main`
  mirrors the repo onto the HF Space `chaeyoona/noteguard-agent` as an orphan commit,
  triggering a Docker rebuild on port 7860. Needs the `HF_TOKEN` repo secret. Orphan
  strategy avoids the historical `docs/init.png` blob that HF's binary-in-history
  check rejects.

### Removed

- `docs/CHANGELOG.md` — duplicate of the root `CHANGELOG.md`.
- `docs/plan.md` — historical planning doc; no longer relevant post-1.0.
- `outputs/.gitkeep` — unused placeholder directory.

### Changed (CI)

- GitHub Actions Python matrix trimmed to **3.10 + 3.12** (intermediate versions
  removed).

---

## [1.0.0] - 2026-06-27

First post-hackathon release. The codebase is pruned to exactly the components
that ship in the deployed Hugging Face Space; sponsor-only integrations that never
ran in the deployed image are removed.

### Removed

- **Superlinked retrieval** (`src/retrieve.py`, `[retrieval]` optional dependency,
  and the `retrieve_context` graph node) — the in-memory vector index was excluded
  from the Docker image and lazy-imported behind a graceful fallback, so it never
  executed in the deployed app. Removing it deletes the `retrieved_context` state
  field and the per-request demo index seeding.
- **n8n workflow** (`workflows/noteguard.n8n.json`) — a three-node proxy
  (Webhook → HTTP Request → Respond) to NoteGuard's own REST API. It added no logic
  and sat off the runtime path; any automation platform can still call the REST API.

### Changed

- **Faithfulness judge now scores against the de-identified source note** (`deid_text`)
  instead of Superlinked-retrieved context. The score was previously gated on retrieval,
  so it never populated in the deployed app (which had no retrieval); it now produces a
  live number for every request and matches the definition used by `eval/run_eval.py`.
- `agent/graph.py`: pipeline simplified to
  `deidentify_in → agent → reidentify_out → compute_trust`; `build_graph()` no longer
  takes a `note_index` argument.
- `app/api.py`: `/process` reports `faithfulness` whenever a de-identified note exists;
  FastAPI app version bumped to `1.0.0`.
- `Dockerfile`: dependency comment updated — the image no longer "omits" Superlinked,
  it is simply not a dependency.
- `Makefile`: modernised to the real toolchain — installs via `pip install -e .`
  (no `requirements.txt`), lints/formats with `ruff` (not `black`), uses the `src`
  package and `src/fetch_dataset.py`.
- `pyproject.toml`: version bumped to `1.0.0`; `superlinked` removed from keywords;
  `[retrieval]` optional-dependency group dropped.

---

## [0.2.0] - 2026-06-27

### Added

- **Clinician web UI** (`app/static/index.html`) — single-file, vanilla JS, no build
  step. NHS dark-blue header, segmented toggle (Clinician view / What the AI sees),
  PHI highlighted in red in the clinician view, `[TYPE_N]` monospace chips in the AI
  view, discharge summary pane, trust-panel metric cards.
- **`POST /process` endpoint** (`app/api.py`) — returns `clinician_note`, `ai_note`,
  `identifiers` (original strings for highlighting), `discharge_summary`, and
  `metrics` (`identifiers_removed`, `residual_risk`, `grounded_sources`,
  `faithfulness`).
- **`GET /`** — FastAPI serves `app/static/index.html` directly; no separate static
  server needed.
- **`StaticFiles` mount** at `/static` — allows future CSS/JS assets alongside the
  single-page UI.
- **n8n workflow** (`workflows/noteguard.n8n.json`) — importable three-node workflow
  (Webhook → HTTP Request → Respond to Webhook) that routes ward notes through the
  NoteGuard API without the model ever seeing PHI.

- **Vercel deployment** (`api/index.py`, `api/requirements.txt`, `vercel.json`) —
  the FastAPI app is deployable as a serverless Vercel function. Light dep set
  omits superlinked/torch to stay under the 250 MB bundle limit; retrieval falls
  back gracefully to Gemini-only mode.

### Changed

- `app/api.py` now also serves the clinician web UI in addition to the REST API.
- `agent/graph.py`: `NoteIndex` import made lazy (inside try block) so the module
  loads cleanly in environments where superlinked is unavailable (CI, Vercel).
- `noteguard/__init__.py`: removed `NoteIndex` re-export; only `NoteGuard`,
  `DeidResult`, and `load_known_from_csv` are exported from the package.
- `Makefile` `run` target now starts uvicorn (`uvicorn app.api:app --reload --port 8000`)
  instead of Streamlit.
- `pyproject.toml` version bumped to 0.2.0; `per-file-ignores` added for E402
  (intentional `load_dotenv()` before API-key-consuming imports).

### Removed

- **`app/trust_panel.py`** — Streamlit demo UI retired; superseded by the
  single-file clinician web UI (`app/static/index.html`) served by FastAPI.
- **`streamlit`** removed from `requirements.txt`.

---

## [0.1.0] - 2026-06-27

### Added

- **De-identification core** (`noteguard/deid.py`) — dependency-free NHS-aware
  pipeline: NHS number, GMC/NMC, postcode, DOB, email and phone recognisers;
  vault-from-CSV for ground-truth measurement; consistent surrogates;
  `assert_clean()` hard guarantee; `reidentify()` for clinician-only restoration.
- **Superlinked retrieval node** (`noteguard/retrieve.py`) — in-memory vector
  index (`sentence-transformers/all-MiniLM-L6-v2`) with `assert_clean()` called
  on every document in and every retrieved chunk out.
- **LangGraph agent** (`agent/graph.py`) — full pipeline:
  `deidentify_in → retrieve_context → agent (Gemini + Tavily) → reidentify_out → compute_trust`.
  Trust metrics surfaced in graph state: identifiers removed, residual leakage,
  faithfulness score, source URLs.
- **Streamlit trust panel** (`app/trust_panel.py`) — three-way toggle
  (raw / de-identified / clinician answer) and live trust panel; styled to the
  NHS England identity.
- **LangSmith evaluations** (`eval/run_eval.py`) — `zero_phi_to_model` (must
  score 1.0) and `faithfulness` (LLM-as-judge over de-identified text only).
- Gold RAP packaging: `pyproject.toml`, `Makefile`, `CHANGELOG.md`,
  `CONTRIBUTING.md`, `.pre-commit-config.yaml`, `.editorconfig`, CI workflow,
  and `docs/` (architecture, user guide, RAP compliance).
