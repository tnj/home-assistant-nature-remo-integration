# Contributing

Thanks for your interest in improving the Nature Remo integration!

## Development setup

Requirements: [uv](https://docs.astral.sh/uv/). Python 3.13 is pinned via
`.python-version`.

    uv sync

## Quality gate

All four commands must pass before every commit / PR:

    uv run ruff check .
    uv run ruff format --check .
    uv run mypy
    uv run pytest -q

CI runs the same gate plus Home Assistant's hassfest validation.

## Conventions

- Conventional-commit style messages (`feat:`, `fix:`, `chore:`, …).
- Code, comments, and `strings.json` are English; Japanese belongs only in
  `translations/ja.json` and `README.ja.md`.
- `strings.json` and `translations/en.json` must stay identical.
- Test fixtures in `tests/fixtures/*.json` mirror real Nature API payload
  shapes — change them only to match observed reality.
- Entity/platform design decisions (why buttons instead of a `remote` entity,
  state only where the API provides it, …) are documented in
  `docs/DESIGN.md` — please read it before proposing new entities.
  Repository operations (Dependabot, auto-merge, branch protection) are
  described in `docs/MAINTENANCE.md`.

## Pull requests

- Target `main`. CI (lint / typecheck / test / hassfest) must be green.
- PRs are squash-merged and the PR title becomes the commit message, so write
  the title in conventional-commit style.
