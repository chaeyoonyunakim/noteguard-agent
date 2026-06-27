# RAP compliance

This repository is organised to meet **Gold RAP** under the
[NHS RAP Community of Practice maturity framework](https://nhsdigital.github.io/rap-community-of-practice/introduction_to_RAP/levels_of_RAP/).
The levels are cumulative — Gold includes everything in Baseline and Silver.
The structure also draws on the
[NHS England repository template](https://github.com/nhs-england-tools/repository-template)
and the [NHS England "package your code" workshop](https://github.com/nhsengland/package-your-code-workshop).

## Baseline RAP

| Criterion | Status | Evidence |
|---|---|---|
| Data produced by code in an open-source language | ✅ | Python pipeline (`src/`, `agent/`, `eval/`). |
| Code is version controlled | ✅ | Git, hosted on GitHub. |
| README details steps to reproduce | ✅ | [`README.md`](../README.md), [`docs/user_guide.md`](user_guide.md). |
| Code has been peer reviewed | ✅ | Pull request workflow with template + required human review. |
| Code is published in the open | ✅ | Public GitHub repository, MIT licensed. |

## Silver RAP

| Criterion | Status | Evidence |
|---|---|---|
| Outputs produced with minimal manual intervention | ✅ | `uvicorn app.api:app` / `python -m eval.run_eval`; one-command startup. |
| Code is well-documented (guidance, structure, docstrings) | ✅ | Module + function docstrings throughout; `docs/` directory. |
| Well-organised, standard directory format | ✅ | `src/` core, `agent/`, `app/`, `eval/`, `tests/`, `docs/`, `data/`, `outputs/`. |
| Reusable functions and/or classes | ✅ | `NoteGuard`, `NoteIndex`, `build_graph()` — composable and parameterisable. |
| Adheres to agreed coding standards | ✅ | PEP 8, type hints, **ruff** lint + format (see `pyproject.toml`). |
| Pipeline includes a testing framework | ✅ | `pytest` suite in `tests/` (24 tests; de-id core covered; no external deps needed). |
| Dependency information included | ✅ | `pyproject.toml` — single source of truth; optional extras for retrieval, demo, and dev tooling. |
| Logs automatically recorded by the pipeline | ✅ | LangSmith auto-traces every graph run (`LANGSMITH_TRACING=true`). |
| Configuration aids reusability | ✅ | All settings from environment variables; `.env.example` provided. |

## Gold RAP

| Criterion | Status | Evidence |
|---|---|---|
| Code is fully packaged | ✅ | `pyproject.toml` (setuptools, `pip install -e ".[dev]"`, optional extras). |
| Tests run automatically via CI/CD | ✅ | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) — ruff + pytest on 3.10–3.12. |
| Process runs on event-based triggers or a schedule | ✅ | CI on push / pull request; agent runs on live query events. |
| Changes clearly signposted (changelog, releases) | ✅ | [`docs/CHANGELOG.md`](CHANGELOG.md), `VERSION`, semantic versioning. |

## Additional good practice

- **Pre-commit hooks** (`.pre-commit-config.yaml`) for local quality gates.
- **Editor configuration** (`.editorconfig`) for consistent formatting.
- **Pull request template** and `CONTRIBUTING.md` documenting the review process.
- **Secret hygiene**: no credentials in code; `.env` git-ignored; a
  `detect-private-key` pre-commit hook.
- **Hard privacy guarantee**: `assert_clean()` enforced at every PHI boundary —
  de-id node, retrieval index, retrieved chunks, and the LangSmith eval.
- **Reproducible outputs via the web UI**: `GET /` + `POST /process` provide a
  documented, versioned HTTP interface that produces the same clinician output for
  the same input — satisfying the reproducibility intent of RAP Gold.
- **Documented API contract**: `docs/architecture.md` specifies every endpoint,
  request/response shape, and the `assert_clean()` guarantee; consumers can
  reproduce the analysis without reading source code.
- **Governance documentation**: `docs/tool_card.md` (Five Safes mapping, bias &
  fairness statement, DPIA prerequisites) and `docs/report.md` (gov.uk ATRS record,
  Tier 1 + Tier 2).
