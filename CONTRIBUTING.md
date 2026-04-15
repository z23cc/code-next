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
- Keep `CHANGELOG.md` updated with a short human-readable summary for the release.
- Confirm local validation before tagging:

  ```bash
  uv run ruff check src/ tests/
  uv run mypy src/aiwf/
  uv run pytest tests/ -x -q
  uv run aiwf --version
  ```

- Tag releases as `vX.Y.Z` after checks pass and the tag matches the package version.
- Pushing a release tag runs the lightweight `Release Check` workflow, which reuses the CI validation contract, verifies tag/version alignment, and builds distributable artifacts.
- This repository does not define automated publishing yet; release tags are a verification boundary, not a publish step.
