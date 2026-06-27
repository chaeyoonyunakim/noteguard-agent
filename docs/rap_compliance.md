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
| Data produced by code in an open-source language | ✅ | Python pipeline (`noteguard/`, `agent/`, `eval/`). |
| Code is version controlled | ✅ | Git, hosted on GitHub. |
| README details steps to reproduce | ✅ | [`README.md`](../README.md), [`docs/user_guide.md`](user_guide.md). |
| Code has been peer reviewed | ✅ | Pull request workflow with template + required human review. |
| Code is published in the open | ✅ | Public GitHub repository, MIT licensed. |

## Silver RAP

| Criterion | Status | Evidence |
|---|---|---|
| Outputs produced with minimal manual intervention | ✅ | `make run` / `make eval`; one-command startup. |
| Code is well-documented (guidance, structure, docstrings) | ✅ | Module + function docstrings throughout; `docs/` directory. |
| Well-organised, standard directory format | ✅ | `noteguard/` core, `agent/`, `app/`, `eval/`, `tests/`, `docs/`. |
| Reusable functions and/or classes | ✅ | `NoteGuard`, `NoteIndex`, `build_graph()` — composable and parameterisable. |
| Adheres to agreed coding standards | ✅ | PEP 8, type hints, **black** + **ruff** (see `pyproject.toml`). |
| Pipeline includes a testing framework | ✅ | `pytest` suite in `tests/` (de-id core covered; no external deps needed). |
| Dependency information included | ✅ | `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`. |
| Logs automatically recorded by the pipeline | ✅ | LangSmith auto-traces every graph run (`LANGSMITH_TRACING=true`). |
| Configuration aids reusability | ✅ | All settings from environment variables; `.env.example` provided. |

## Gold RAP

| Criterion | Status | Evidence |
|---|---|---|
| Code is fully packaged | ✅ | `pyproject.toml` (setuptools, entry points, `[project]` metadata). |
| Tests run automatically via CI/CD | ✅ | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) — ruff + black + pytest on 3.10–3.12. |
| Process runs on event-based triggers or a schedule | ✅ | CI on push / pull request; agent runs on live query events. |
| Changes clearly signposted (changelog, releases) | ✅ | [`CHANGELOG.md`](../CHANGELOG.md), `VERSION`, semantic versioning. |

## Additional good practice

- **Pre-commit hooks** (`.pre-commit-config.yaml`) for local quality gates.
- **Editor configuration** (`.editorconfig`) for consistent formatting.
- **Pull request template** and `CONTRIBUTING.md` documenting the review process.
- **Secret hygiene**: no credentials in code; `.env` git-ignored; a
  `detect-private-key` pre-commit hook.
- **Hard privacy guarantee**: `assert_clean()` enforced at every PHI boundary —
  de-id node, retrieval index, retrieved chunks, and the LangSmith eval.
