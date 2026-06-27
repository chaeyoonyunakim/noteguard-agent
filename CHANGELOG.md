# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
