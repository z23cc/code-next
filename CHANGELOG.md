# Changelog

All notable changes to `aiwf` should be recorded here in a lightweight, contributor-friendly format.

## Unreleased

### Added
- RP bridge foundation baseline consolidation across contracts, models, engine persistence/restore, CLI bridge flags, doctor/conformance messaging, RP projection surfaces, fixtures, docs, and regression coverage for the manual-assist groundwork.
- Release/versioning closure with version consistency tests, a tag-based release-check workflow, and clearer compiler projection/release guidance.
- Release metadata hardening with strict changelog/version/package artifact verification, a reusable `python -m aiwf.release verify` preflight, and uploaded `dist/release-metadata.json` in release-check runs.
- A manual TestPyPI trial workflow that reuses `python -m aiwf.release verify --dist dist --install-smoke` as preflight, publishes built artifacts to TestPyPI, and performs a post-publish install smoke from the published index.

## 0.0.1

### Added
- Initial Phase 1 workflow kernel with run/state/artifact orchestration, Claude/stub adapters, deterministic gates, and Claude compilation support.
