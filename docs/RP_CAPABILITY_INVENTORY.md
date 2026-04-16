# RP Capability Inventory

First-pass capability inventory for the `aiwf` ↔ RP runtime/provider boundary.

This document is intentionally evidence-first and repo-scoped:

- **aiwf-known facts** = behaviors implemented or explicitly emitted by code, tests, fixtures, or CI in this repository.
- **RP runtime assumptions** = behaviors that a real external RepoPrompt runtime (`rp` / `rp-cli`) would need to honor for end-to-end native execution.
- **Not included yet** = the three-layer integration matrix and priority recommendations.

## Status legend

| Status | Meaning |
| --- | --- |
| **Implemented + validated** | Implemented in this repo and directly protected by tests/fixtures/CI in this repo. |
| **Implemented + assumed** | Implemented in this repo, but end-to-end correctness still depends on an external RP runtime that this repo does not validate. |
| **Documented-only** | Defined in docs/specs or reference stub behavior, but not validated against a real RP runtime. |
| **Gap** | No sufficient implementation or validation evidence in this repo for the claimed capability. |

## Confidence legend

| Confidence | Meaning |
| --- | --- |
| **High** | Protected by code + tests/fixtures, with no dependency on external RP runtime behavior. |
| **Medium** | Protected in repo, but only via fake runtime or `rp-cli-stub` reference behavior. |
| **Low** | Primarily documentation/reference-harness evidence. |
| **None** | No meaningful evidence in repo. |

## Inventory framework

Use these fields for each capability row:

| Field | Description |
| --- | --- |
| **Capability** | Named behavior or contract surface. |
| **Layer owner** | `aiwf core` or `external RP runtime`. |
| **aiwf-known fact** | What this repo actually implements or emits. |
| **RP runtime assumption** | What a real RepoPrompt runtime must do for end-to-end native use. |
| **Primary evidence** | Source files, tests, fixtures, or workflows that anchor the claim. |
| **Validation method** | Tests, compat fixture, CI smoke, or docs only. |
| **Status** | Current posture using the legend above. |
| **Confidence** | Strength of the evidence in this repo. |
| **Drift risk** | Low / medium / high risk that docs, code, and external reality diverge. |

## Evidence baseline

Primary anchors used for this inventory:

- Protocol/spec: `docs/RP_NATIVE_PROTOCOL.md`
- Product positioning: `docs/INSTALL_GUIDE.md`, `docs/QUICKSTART.md`, `README.md`, `docs/PYTHON_IMPLEMENTATION_SPEC.md`
- Runtime adapter: `src/aiwf/adapters/rp_agent.py`
- Contract models/restore: `src/aiwf/adapters/base.py`, `src/aiwf/adapters/__init__.py`
- Diagnostics/conformance: `src/aiwf/doctor.py`, `src/aiwf/conformance.py`
- RP compiler/projection: `src/aiwf/compilers/rp.py`, `src/aiwf/compilers/base.py`
- Compatibility policy: `docs/compatibility-policy.md`
- Reference harness: `tools/rp-cli-stub/src/rp_cli_stub/cli.py`
- Validation: `tests/test_adapter_rp.py`, `tests/test_doctor.py`, `tests/test_conformance_rp.py`, `tests/test_compile.py`, `tests/test_adapter_contracts.py`
- CI/release posture: `.github/workflows/ci.yml`, `.github/workflows/release-check.yml`, `.github/workflows/testpypi-release.yml`

## Capability inventory: RP runtime/provider boundary

| Capability | Layer owner | aiwf-known fact | RP runtime assumption | Primary evidence | Validation method | Status | Confidence | Drift risk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Native runtime contract declaration | aiwf core | RP contracts declare `command_candidates = ["rp", "rp-cli"]`, install hint, and protocol version `1`. The same shape is emitted in `rp-projection.json`. | A real RepoPrompt runtime on PATH actually matches one of those commands and meaningfully implements protocol v1. | `src/aiwf/adapters/rp_agent.py`, `src/aiwf/adapters/base.py`, `src/aiwf/compilers/rp.py`, `tests/fixtures/rp_projection_compat.json`, `tests/test_compile.py` | Contract + compat fixture assertions | **Implemented + validated** | High | Low |
| Stable RP manual path | aiwf core | RP manual handoff is the default variant, writes prompt artifacts, and resumes from stored `host_contract`. Product docs call this the stable/default RP path. | None beyond ordinary file/artifact handling. | `src/aiwf/adapters/rp_agent.py`, `src/aiwf/adapters/__init__.py`, `docs/INSTALL_GUIDE.md`, `docs/QUICKSTART.md`, `tests/test_adapter_rp.py`, `tests/test_cli.py`, `tests/fixtures/run_metadata_rp_manual_no_native_runtime.json` | Adapter tests + CLI flow + metadata restore fixture | **Implemented + validated** | High | Low |
| Protocol probe invocation | aiwf core | Auto RP attempts `--aiwf-protocol-version`, caches the result, and uses probe success to select structured mode. | A real RP runtime returns a valid `aiwf-rp-native` JSON probe response. | `src/aiwf/adapters/rp_agent.py`, `docs/RP_NATIVE_PROTOCOL.md`, `tests/test_adapter_rp.py`, `tests/test_conformance_rp.py` | Fake runtime + stub conformance | **Implemented + assumed** | Medium | Medium |
| Structured request envelope generation | aiwf core | `aiwf` builds JSON requests containing protocol/version, request type, stage, prompt, context, options, and metadata. | A real RP runtime accepts and correctly interprets that envelope. | `src/aiwf/adapters/rp_agent.py`, `docs/RP_NATIVE_PROTOCOL.md`, `tests/test_adapter_rp.py` | Fake runtime assertions | **Implemented + assumed** | Medium | Medium |
| Structured `ok` response handling | aiwf core | `aiwf` parses protocol payloads and returns `content` for `status = ok`. | A real RP runtime emits valid payloads with non-empty `content`. | `src/aiwf/adapters/rp_agent.py`, `tests/test_adapter_rp.py`, `src/aiwf/conformance.py`, `tests/test_conformance_rp.py` | Fake runtime + stub conformance | **Implemented + assumed** | Medium | Medium |
| Structured error / partial response handling | aiwf core | `aiwf` maps structured protocol errors, supports `partial`, and converts `EXECUTION_TIMEOUT` to adapter timeout semantics. | A real RP runtime emits the documented error shapes and codes. | `src/aiwf/adapters/rp_agent.py`, `docs/RP_NATIVE_PROTOCOL.md`, `tests/test_adapter_rp.py` | Fake runtime tests | **Implemented + assumed** | Medium | Medium |
| Legacy raw-text fallback | aiwf core | If probe fails or protocol negotiation falls back, `aiwf` reverts to raw stdin/stdout handling. | A real legacy RP runtime behaves as a plain text subprocess. | `src/aiwf/adapters/rp_agent.py`, `docs/RP_NATIVE_PROTOCOL.md`, `tests/test_adapter_rp.py`, `tools/rp-cli-stub/src/rp_cli_stub/cli.py`, `tests/test_conformance_rp.py` | Adapter tests + stub conformance | **Implemented + assumed** | Medium | Low |
| Unsupported-version downgrade path | aiwf core | `UNSUPPORTED_VERSION` responses cause `aiwf` to clear the selected protocol version and retry in legacy mode. | A real RP runtime uses the documented error code and detail payload. | `src/aiwf/adapters/rp_agent.py`, `docs/RP_NATIVE_PROTOCOL.md`, `tests/test_adapter_rp.py`, `tools/rp-cli-stub/src/rp_cli_stub/cli.py` | Fake runtime + stub behavior | **Implemented + assumed** | Medium | Medium |
| RP doctor readiness reporting | aiwf core | `doctor` reports whether an RP binary exists, whether protocol negotiation is detected, and which protocol version was observed. It also warns that manual handoff remains stable. | PATH resolution points to the real RepoPrompt runtime rather than a stub or unrelated binary. | `src/aiwf/doctor.py`, `tests/test_doctor.py`, `.github/workflows/ci.yml` | Mocked tests + stub-based CI smoke | **Implemented + assumed** | Medium | Medium |
| RP conformance command | aiwf core | `aiwf conformance rp` runs probe, plan, execute, review, invalid-request, unsupported-version, and legacy-raw checks against an executable. | Passing conformance against a real RepoPrompt runtime would meaningfully certify protocol behavior. | `src/aiwf/conformance.py`, `tests/test_conformance_rp.py`, `.github/workflows/ci.yml`, `.github/workflows/release-check.yml`, `.github/workflows/testpypi-release.yml` | Fake runtime + stub-only CI/release smoke | **Implemented + assumed** | Medium | Medium |
| Reference RP protocol harness | aiwf core | This repo ships `rp-cli-stub`, which implements the probe, valid envelope handling, structured errors, and legacy raw mode. | The stub is only a reference harness; it is not the product runtime. | `tools/rp-cli-stub/src/rp_cli_stub/cli.py`, `docs/RP_NATIVE_PROTOCOL.md`, `tests/test_conformance_rp.py`, workflows | Stub code + tests + CI usage | **Implemented + validated** | High | Low |
| Real RepoPrompt runtime certification | external RP runtime | Repo docs explicitly say the official target is the real RepoPrompt app / MCP CLI runtime. | A real shipped runtime exists, is reachable, and matches the documented protocol behavior. | `docs/INSTALL_GUIDE.md`, `docs/RP_NATIVE_PROTOCOL.md`, `README.md`, workflows caveats | Docs only; no real-runtime artifact in repo | **Gap** | None | High |
| Protocol feature tokens beyond baseline probe | external RP runtime | The spec defines a `capabilities` array in the probe response, but `aiwf` does not consume capability tokens beyond basic presence. | A future real runtime may advertise meaningful tokens such as streaming or partial-result support. | `docs/RP_NATIVE_PROTOCOL.md`, `src/aiwf/conformance.py`, `tools/rp-cli-stub/src/rp_cli_stub/cli.py` | Spec/reference only | **Documented-only** | Low | Medium |

## Current posture summary

- **Strongly validated in-repo:** RP manual handoff, persisted host contract surfaces, projection/compile emission, and the presence of a reference protocol harness.
- **Implemented but not real-runtime-certified:** protocol probe, request/response envelope handling, structured error handling, legacy fallback, doctor signals, and conformance reporting.
- **Still external/unknown:** whether a real RepoPrompt runtime currently satisfies `aiwf-rp-native/v1` in production conditions.

## Boundary note

This document deliberately separates **repo truth** from **runtime truth**:

- If a claim is backed only by `docs/RP_NATIVE_PROTOCOL.md`, `rp-cli-stub`, or fake-runtime tests, treat it as a statement about **aiwf readiness** or **reference behavior**, not proof about the real external RepoPrompt runtime.
- Any future end-to-end certification should update this inventory using evidence from a real RP binary, not only the in-repo stub.
