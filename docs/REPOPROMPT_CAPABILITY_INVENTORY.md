# RepoPrompt Consumer-Surface Capability Inventory

First-pass capability inventory for RepoPrompt/plugin/project-consumer-facing surfaces produced by `aiwf`.

This document focuses on **what consumers can read or act on** from this repository today:

- compiled RP artifacts (`rp-bundle.md`, `rp-projection.json`, `install-surface.json`, `manifest.json`)
- manual handoff / auto response artifacts in `.ai/runs/<run_id>/`
- operator-facing JSON/reporting surfaces such as `doctor`, `inspect`, and `conformance`

It does **not** claim that a real RepoPrompt plugin or external project already consumes these surfaces unless repo evidence exists.

For shared terminology, status labels, and confidence semantics, see `docs/RP_CAPABILITY_INVENTORY.md`.

## Scope split used in this inventory

| Surface type | Meaning |
| --- | --- |
| **Repo-owned consumer surface** | JSON, markdown, or run artifacts emitted by `aiwf` and protected in this repo. |
| **Consumer assumption** | How a RepoPrompt plugin, operator, or external project would use that surface. |
| **Validation boundary** | Whether usage is validated by tests in this repo, or only described in docs. |

## Evidence baseline

Primary anchors used here:

- Output generation: `src/aiwf/compilers/rp.py`, `src/aiwf/compilers/base.py`
- RP contracts and artifacts: `src/aiwf/adapters/rp_agent.py`, `src/aiwf/adapters/base.py`, `src/aiwf/adapters/__init__.py`
- Compatibility/consumer policy: `docs/INSTALL_GUIDE.md`, `docs/compatibility-policy.md`, `docs/QUICKSTART.md`
- Validation: `tests/test_compile.py`, `tests/fixtures/rp_projection_compat.json`, `tests/test_cli.py`, `tests/test_adapter_rp.py`, `tests/test_adapter_contracts.py`, `tests/test_doctor.py`, `tests/test_conformance_rp.py`
- CI posture: `.github/workflows/ci.yml`, `.github/workflows/release-check.yml`, `.github/workflows/testpypi-release.yml`

## Capability inventory: RepoPrompt/plugin or project-consumer surfaces

| Capability / surface | Repo-owned consumer surface | Consumer assumption | Primary evidence | Validation method | Status | Confidence | Drift risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| RP projection contract | `compile rp` emits `rp-projection.json` with host variants, commands, artifacts, install surface, and workflow contract fields. | A consumer can reliably parse this as the machine-readable RP integration entrypoint. | `src/aiwf/compilers/rp.py`, `src/aiwf/compilers/base.py`, `tests/test_compile.py`, `tests/fixtures/rp_projection_compat.json`, `docs/compatibility-policy.md` | Compile tests + compat fixture + policy | **Implemented + validated** | High | Low |
| RP install-surface contract | `compile rp` emits `install-surface.json` with `install_strategy = use_compiled_output_directory`, generated assets, and no RP external assets. | A consumer should preserve the compiled output directory as a stable bundle rather than cherry-picking files. | `src/aiwf/compilers/base.py`, `src/aiwf/compilers/rp.py`, `tests/test_compile.py`, `docs/INSTALL_GUIDE.md`, `docs/compatibility-policy.md` | Compile tests + docs | **Implemented + validated** | High | Low |
| RP bundle markdown | `compile rp` emits `rp-bundle.md` describing host contract, suggested commands, review evidence, and traceability. | A human operator can read/paste/use the bundle during RepoPrompt workflows. | `src/aiwf/compilers/rp.py`, `tests/test_compile.py`, `docs/INSTALL_GUIDE.md` | Bundle content assertions + docs | **Implemented + validated** | High | Low |
| Manifest and drift surface | `compile rp` emits `manifest.json` with source index, hashes, and drift status. | A consumer or cache layer can detect when recompilation is needed. | `src/aiwf/compilers/base.py`, `tests/test_compile.py`, `README.md`, `docs/INSTALL_GUIDE.md` | Compile tests | **Implemented + validated** | High | Low |
| Manual implement handoff artifact | RP manual implement writes `rp-agent-implement-prompt.md` and stores manual `host_contract` metadata. | An operator can take the prompt into RepoPrompt, then continue with `aiwf resume`. | `src/aiwf/adapters/rp_agent.py`, `tests/test_adapter_rp.py`, `tests/test_cli.py`, `docs/INSTALL_GUIDE.md`, `docs/QUICKSTART.md` | Adapter tests + CLI manual flow | **Implemented + validated** | High | Low |
| Manual review handoff artifact | RP manual review writes `rp-agent-review-prompt.md` and links review evidence expectations through the stored contract. | An operator can perform manual review handoff and then resume/finalize the run. | `src/aiwf/adapters/rp_agent.py`, `tests/test_adapter_rp.py`, `tests/test_cli.py`, `docs/INSTALL_GUIDE.md` | Adapter tests + CLI manual flow | **Implemented + validated** | High | Low |
| Auto response artifacts | RP auto mode writes `rp-agent-implement-response.md` and `rp-agent-review-response.md` instead of prompt files. | Automation can read these files after native RP execution. | `src/aiwf/adapters/rp_agent.py`, `tests/test_adapter_rp.py`, `src/aiwf/compilers/rp.py`, `tests/test_compile.py` | Adapter tests + projection assertions | **Implemented + assumed** | Medium | Medium |
| Review evidence/report contract surface | RP review contracts explicitly distinguish manual `prompt_file` vs auto `response_file`, required artifacts, and expected report mode. | Consumers can validate whether a run is review-ready and whether stored review evidence is complete. | `src/aiwf/adapters/base.py`, `src/aiwf/adapters/rp_agent.py`, `src/aiwf/contracts.py`, `tests/test_adapter_contracts.py`, `tests/fixtures/rp_projection_compat.json`, `docs/compatibility-policy.md` | Contract tests + compat fixture | **Implemented + validated** | High | Low |
| Resume restores RP host contract | Run metadata persists `host_contract`, and resume/inspect paths rely on restoring it instead of inferring behavior from transient flags. | Consumers and future tooling can treat `host_contract` as the durable source of RP run semantics. | `src/aiwf/adapters/__init__.py`, `tests/test_adapter_contracts.py`, `tests/test_cli.py`, `tests/fixtures/run_metadata_rp_manual_no_native_runtime.json`, `docs/compatibility-policy.md` | Metadata restore tests + CLI flow + fixture | **Implemented + validated** | High | Low |
| Doctor JSON as consumer signal | `doctor --json` exposes RP `protocol_supported` and `protocol_version`, and CI asserts those fields. | Operators/automation can use doctor output to decide whether RP auto/native should be attempted. | `src/aiwf/doctor.py`, `tests/test_doctor.py`, `.github/workflows/ci.yml` | Mocked tests + stub-based CI gate | **Implemented + assumed** | Medium | Medium |
| Conformance JSON/report as consumer signal | `conformance rp` emits structured pass/fail checks for a target executable. | Operators/CI can use it as a runtime-certification signal before enabling RP auto/native. | `src/aiwf/conformance.py`, `tests/test_conformance_rp.py`, workflows | Fake runtime + stub-only CI/release smoke | **Implemented + assumed** | Medium | Medium |
| RP projection consumer inside RepoPrompt/plugin | None in this repo; there is no in-repo RepoPrompt plugin or MCP consumer that reads `rp-projection.json` and drives workflow. | A future RepoPrompt-side integration would consume projection/install surfaces directly. | File search across repo; no consumer implementation surfaced; docs only imply consumption | No implementation evidence | **Gap** | None | High |
| External project example consuming RP compiled output | Docs describe how another project should use `.rp/compiled/`, but no example repo or integration test exists here. | External projects can consume the compiled directory without additional glue. | `docs/INSTALL_GUIDE.md`, `README.md`, `docs/QUICKSTART.md` | Docs only | **Documented-only** | Low | Medium |
| RepoPrompt-specific plugin API or MCP contract beyond compiled artifacts | No RepoPrompt-side API contract is defined here beyond projection/install/manual-handoff surfaces. | A plugin author would know exactly how to map these outputs into RepoPrompt-native automation. | Negative repo evidence; only high-level references to RepoPrompt app / MCP CLI runtime | No implementation/spec in repo | **Gap** | None | High |

## Current posture summary

- **Well-defined and protected here:** RP compile outputs, run-artifact contracts, resume metadata restore, and review evidence semantics.
- **Usable by humans today:** manual handoff prompts plus `resume` are strongly evidenced.
- **Not yet proven with a real consumer:** auto response consumption, doctor/conformance as production signals, and any RepoPrompt-side plugin/MCP reader of `rp-projection.json`.

## Practical reading rule

When evaluating RepoPrompt-facing integration claims in this repo:

- Treat `rp-projection.json`, `install-surface.json`, and stored `host_contract` as **stable aiwf-owned surfaces** because they are protected by fixtures/tests and called out in `docs/compatibility-policy.md`.
- Treat claims about **actual RepoPrompt/plugin consumption** as tentative unless backed by a real consumer implementation or integration test.
