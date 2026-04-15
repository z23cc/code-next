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
- Keep `CHANGELOG.md` updated with a short human-readable summary for the release, and make sure the latest release heading matches the package version.
- Confirm local validation before tagging:

  ```bash
  uv run ruff check src/ tests/
  uv run mypy src/aiwf/
  uv run pytest tests/ -x -q
  uv build
  uv run python -m aiwf.release verify --dist dist
  uv run aiwf --version
  ```

- Tag releases as `vX.Y.Z` after checks pass and the tag matches the package version.
- `uv run python -m aiwf.release verify --dist dist --expect-tag vX.Y.Z` is the strict local preflight for tag/version/changelog/package alignment.
- Pushing a release tag runs the lightweight `Release Check` workflow, which reuses the CI validation contract, verifies tag/version/changelog/package alignment, writes `dist/release-metadata.json`, and uploads the built release bundle.
- This repository does not define automated publishing yet; release tags are a verification boundary, not a publish step.
