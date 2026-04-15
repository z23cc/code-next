# Contributing

Thank you for contributing to `aiwf`.

## Development setup

```bash
uv sync --extra dev
```

## Validation before opening a PR

Run the same checks used by CI:

```bash
uv run ruff check src/ tests/
uv run mypy src/aiwf/
uv run pytest tests/ -x -q
```

## Pull request expectations

- Keep changes scoped and minimal.
- If behavior changes, update relevant docs under `README.md` / `docs/`.
- Include test updates when applicable.

## Versioning and release guidance (minimal)

- Use semantic versioning (`MAJOR.MINOR.PATCH`).
- For a release, update version in both:
  - `pyproject.toml` (`[project].version`)
  - `src/aiwf/__init__.py` (`__version__`)
- Tag releases as `vX.Y.Z` after checks pass.
- This repository does not define automated publishing yet.
