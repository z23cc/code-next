# Changelog

All notable changes to `aiwf` should be recorded here in a lightweight, contributor-friendly format.

## Unreleased

### Added
- Release/versioning closure with version consistency tests, a tag-based release-check workflow, and clearer compiler projection/release guidance.
- Release metadata hardening with strict changelog/version/package artifact verification, a reusable `python -m aiwf.release verify` preflight, and uploaded `dist/release-metadata.json` in release-check runs.

## 0.0.1

### Added
- Initial Phase 1 workflow kernel with run/state/artifact orchestration, Claude/stub adapters, deterministic gates, and Claude compilation support.
