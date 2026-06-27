# Contributing

Thank you for considering a contribution to NoteGuard. This project follows the
[NHS RAP Community of Practice](https://nhsdigital.github.io/rap-community-of-practice/)
guidance and the [Government Digital Service (GDS) coding standards](https://gds-way.digital.cabinet-office.gov.uk/standards/programming-languages.html).

## Getting started

```bash
git clone https://github.com/chaeyoonyunakim/noteguard-agent.git
cd noteguard-agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
make install-dev          # installs dev deps and pre-commit hooks
cp .env.example .env      # fill in GOOGLE_API_KEY, TAVILY_API_KEY, LANGSMITH_API_KEY
```

## Development workflow

1. Create a feature branch from `main`.
2. Make your change, keeping functions small and well-documented.
3. Run the checks locally:
   ```bash
   make format   # auto-fix style
   make lint     # ruff + black
   make test     # pytest
   ```
4. Commit. Pre-commit hooks run ruff, black and basic hygiene checks.
5. Open a **pull request**. CI (GitHub Actions) runs lint and tests on every PR.

## Coding standards

- **Python**: PEP 8, 4-space indentation, type hints, formatted with **black**
  and linted with **ruff** (line length 110).
- Write **tests for all new functions** (`tests/`, run with pytest).
- Keep `noteguard/deid.py` **dependency-free** (standard library only).
- Never weaken or bypass `assert_clean()` — it is the project's core guarantee.
- Use **British English** in comments and documentation.
- Never commit secrets, credentials or API keys — use environment variables
  (see `.env.example`).

## The privacy guarantee

The non-negotiable invariant: nothing downstream of `deidentify_in` may receive
PHI. `assert_clean()` must be called before any identifier-bearing text reaches
a language model or external tool. Do not relax this check under any
circumstances — it is the entire point of the project.

## Review

All changes must be **reviewed by a human** before merge. The pull request
template includes a checklist to confirm standards are met.
