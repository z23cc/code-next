# Compatibility Policy for Run Metadata, Host Contracts, and Host Projections

This document turns the current de facto compatibility rules into an explicit policy for three persisted surfaces:

- run metadata in `.ai/runs/<run_id>/run.json`
- stored `host_contract` payloads persisted with runs
- compiled `*-projection.json` and `install-surface.json` outputs

It is intentionally grounded in the current implementation and test fixtures, not a hypothetical future schema.

## Canonical authorities in this repo

The following files are the normative anchors for this policy:

- Host contract schema: `src/aiwf/adapters/base.py`
- Built-in adapter variants and restore behavior: `src/aiwf/adapters/__init__.py`
- RP contract defaults: `src/aiwf/adapters/rp_agent.py`
- Shared projection and install-surface schema builders: `src/aiwf/compilers/base.py`
- Host-specific projection contract versions and workflow fields:
  - `src/aiwf/compilers/claude.py`
  - `src/aiwf/compilers/codex.py`
  - `src/aiwf/compilers/rp.py`
- Contract linting and review/evidence semantics: `src/aiwf/contracts.py`
- Projection compatibility fixtures:
  - `tests/fixtures/claude_projection_compat.json`
  - `tests/fixtures/codex_projection_compat.json`
  - `tests/fixtures/rp_projection_compat.json`
- Run metadata compatibility fixtures:
  - `tests/fixtures/run_metadata_legacy_adapter_auto.json`
  - `tests/fixtures/run_metadata_host_contract_no_review.json`
  - `tests/fixtures/run_metadata_rp_manual_no_native_runtime.json`
- Enforcing tests:
  - `tests/test_compile.py`
  - `tests/test_adapter_contracts.py`

If this document and those files diverge, update the code/tests first or update this policy in the same change.

## 1. Durable run metadata format

### 1.1 Write-path rule

The durable run-metadata format is `run.json.data.host_contract`, written as `HostContract.to_metadata()`.

New code should write the full explicit object, not only legacy top-level flags.

The stable shape is currently:

- `data.host_contract.adapter`
- `data.host_contract.mode`
- `data.host_contract.capabilities.supports_auto_execution`
- `data.host_contract.capabilities.requires_explicit_review_handoff`
- `data.host_contract.review.required_run_artifacts`
- `data.host_contract.review.required_report_string_fields`
- `data.host_contract.review.required_report_list_fields`
- `data.host_contract.review.expected_report_mode`
- `data.host_contract.review.linked_report_artifact_field`
- `data.host_contract.native_runtime.enabled`
- `data.host_contract.native_runtime.command_candidates`
- `data.host_contract.native_runtime.install_hint`
- `data.host_contract.bridge.enabled`
- `data.host_contract.bridge.default_mode`
- `data.host_contract.bridge.supported_modes`
- `data.host_contract.bridge.command_candidates`
- `data.host_contract.bridge.install_hint`
- `data.rp_bridge.mode`
- `data.rp_bridge.workspace`
- `data.rp_bridge.tab`
- `data.rp_bridge.context_id`
- `data.rp_bridge.agent_role`
- `data.rp_bridge.timeout_seconds`
- `data.rp_bridge.export_transcript`

This shape is defined by `HostContract`, `HostCapabilities`, `ReviewArtifactContract`, `NativeRuntimeContract`, and `BridgeContract` in `src/aiwf/adapters/base.py`, plus `RpBridgeRunConfig` in `src/aiwf/models.py`. `data.rp_bridge` is written only when the experimental RP bridge groundwork is active for a run.

### 1.2 Read-path compatibility rules

`restore_host_contract()` in `src/aiwf/adapters/__init__.py` is the compatibility boundary for persisted runs.

It must continue to accept all currently protected legacy shapes:

1. Legacy `data.adapter` + `data.auto` metadata with no explicit `host_contract`
2. Explicit `data.host_contract` objects that omit `review`
3. Explicit `data.host_contract` objects that omit `native_runtime`
4. Explicit `data.host_contract` objects that omit `bridge`
5. Run metadata that omits `data.rp_bridge` entirely (meaning bridge is inactive for that run)

The current fixtures intentionally cover those cases:

- `run_metadata_legacy_adapter_auto.json`
- `run_metadata_host_contract_no_review.json`
- `run_metadata_rp_manual_no_native_runtime.json`

### 1.3 Backfill rule

When stored run metadata includes `host_contract.adapter` and `host_contract.mode` but omits `review`, `native_runtime`, and/or `bridge`, `restore_host_contract()` backfills the missing sections from the current built-in default contract for that adapter/mode.

That backfill behavior is part of the compatibility policy, not an incidental implementation detail.

### 1.4 Legacy retention rule

Do not remove accepted-on-read support for a persisted run shape until all of the following are true:

- the change is intentional and documented
- the old fixture coverage is updated in the same PR
- a replacement migration or versioning story exists for already-written runs

Practical consequence: deleting support for `adapter` + `auto` or for partial `host_contract` payloads is a breaking change.

Note: For `NativeRuntimeContract` evolution related to the RP native I/O protocol, see `docs/RP_NATIVE_PROTOCOL.md`.

## 2. Stable projection and install-surface contract

The stable compiled projection surface is the JSON contract protected by `tests/test_compile.py` and the `tests/fixtures/*projection_compat.json` files.

### 2.1 Projection fields treated as stable

For each host projection, the following fields are currently compatibility-sensitive:

- `schema_version`
- `projection_name`
- `host.name`
- `host.display_name`
- `host.stored_runtime_key`
- `host.default_variant`
- `host.variants.<mode>` as full `HostContract.to_metadata()` payloads
- `artifacts.bundle`
- `artifacts.install_surface`
- `artifacts.manifest`
- `commands.plan`
- `commands.implement`
- `commands.review`
- `commands.resume`
- `workflow_contract.plan.*`
- `workflow_contract.implement.*`
- `workflow_contract.review.*`
- `workflow_contract.resume.*`

In practice, the exact stable subtree is whatever is asserted by:

- `_auto_capable_projection_compat_view()`
- `_manual_projection_compat_view()`
- `_common_projection_contract_view()`

in `tests/test_compile.py`.

That means the stable surface includes not only host contract fields, but also current workflow boundary fields such as:

- `plan.primary_artifacts`
- `plan.auto_entrypoint` for RP
- `implement.manual_handoff_artifact`
- `implement.auto_stage_output_artifact` for RP
- `implement.resume_boundary`
- `review.requires_status`
- `review.required_run_artifacts`
- `review.report_contract.<mode>`
- `resume.restores_run_metadata`

### 2.2 Install-surface fields treated as stable

The stable install-surface contract is the output of `build_install_surface_document()` in `src/aiwf/compilers/base.py`.

The currently stable fields are:

- `schema_version`
- `host.key`
- `host.name`
- `host.display_name`
- `install_strategy`
- `default_output_dir`
- `generated_assets[*].role`
- `generated_assets[*].relative_path`
- `generated_assets[*].managed_by_compiler`
- `external_assets[*].path`
- `external_assets[*].owner`
- `external_assets[*].managed_by_compiler`
- `external_assets[*].rationale`

`resolved_output_dir` is required as a field and is asserted in `tests/test_compile.py`, but its exact value is environment-specific and is not frozen in the compat fixtures.

### 2.3 Projection inputs and hashes

Exact `projection_inputs` rows and hash values are not treated as cross-environment stable output.

Instead, the compat fixtures intentionally freeze a normalized summary of:

- projection input entry keys
- input kind counts on the canonical test corpus
- projection hash key names

This is why the fixtures compare summary views rather than raw `projection_inputs` and `projection_hashes` payloads.

## 3. Breaking vs non-breaking changes

### 3.1 Breaking changes

Unless explicit compatibility work is added, the following are breaking:

- removing or renaming any persisted `host_contract` field listed in section 1.1
- changing the meaning of an existing `host_contract` field
- removing accepted legacy read support currently covered by `tests/test_adapter_contracts.py`
- changing `required_run_artifacts`
- changing `required_report_string_fields` or `required_report_list_fields`
- changing `expected_report_mode`
- changing `linked_report_artifact_field`
- removing `bridge` from RP variants or removing accepted-on-read support for missing `bridge` / `rp_bridge`
- removing a supported host variant or changing `host.default_variant`
- renaming projection keys currently frozen by the compat fixtures
- renaming generated asset roles or changing compiler ownership semantics
- changing `resume.restores_run_metadata` away from `host_contract`

A wording-only change can also be compatibility-sensitive when the field itself is fixture-protected, for example:

- `native_runtime.install_hint`
- `external_assets[*].rationale`

Those text changes usually do not require a schema bump by themselves, but they do require fixture updates in the same PR because the text is part of the current stable contract surface.

### 3.2 Non-breaking changes

The following are usually non-breaking:

- additive fields that existing readers ignore and that are outside the current compat views
- changes to environment-specific values like `resolved_output_dir`
- changes to generated hashes or timestamps
- changes to bundle markdown prose that do not alter the JSON projection/install-surface contracts
- new diagnostics/provenance fields outside the persisted host contract and projection compatibility views

Because the current fixture views are intentionally strict, an additive change may still require fixture updates even when it is not semantically breaking.

## 4. Version and schema bump expectations

### 4.1 Current baseline

Current version anchors are:

- projection document `schema_version = 2`
- install-surface document `schema_version = 1`
- Claude `projection_contract = "claude-host-projection-v3"`
- Codex `projection_contract = "codex-host-projection-v2"`
- RP `projection_contract = "rp-host-projection-v3"`
- stored runtime key = `host_contract`

### 4.2 Shared schema bumps

Bump projection `schema_version` when changing the shared projection document shape emitted by `build_projection_document()`.

Examples:

- renaming a shared top-level section
- changing the shared structure of `host`, `artifacts`, `commands`, `workflow_contract`, `projection_inputs`, or `projection_hashes`

Bump install-surface `schema_version` when changing the shared shape emitted by `build_install_surface_document()`.

Examples:

- renaming `generated_assets`
- changing the structure of `external_assets`
- changing the meaning of `install_strategy`

### 4.3 Host-specific contract bumps

Bump the host compiler's `projection_contract` string when the host-specific stable surface changes, even if the shared schema version does not.

Examples:

- changing supported variants for a host
- changing host command templates
- changing host-specific workflow fields such as `auto_entrypoint`
- changing stable install-surface ownership declarations for a host

For this repo, the conservative default is:

- shared-shape change -> bump shared schema version
- host-specific stable-surface change -> bump that host's `projection_contract`
- persisted run-metadata incompatibility -> add/keep read compatibility first; do not silently break old `run.json`

### 4.4 Run metadata versioning expectation

`host_contract` currently does not carry its own embedded schema version.

Because of that, incompatible run-metadata changes must not be shipped silently. If one ever becomes necessary, do this in order:

1. teach `restore_host_contract()` to read both old and new shapes
2. add/update legacy fixtures proving the old shape still restores
3. only then change the write path
4. if the change cannot be made additively, introduce an explicit new versioning mechanism instead of overloading the old shape

## 5. How to update compatibility fixtures

There is currently no dedicated fixture-regeneration script. Treat fixture updates as deliberate contract edits.

### 5.1 If you change run metadata compatibility

Update or add fixtures under `tests/fixtures/run_metadata_*.json`, then update `tests/test_adapter_contracts.py` so the expected restored `HostContract` is explicit.

At minimum, keep coverage for all accepted-on-read legacy forms.

### 5.2 If you change projection compatibility

Update the affected `tests/fixtures/*projection_compat.json` file(s) to match the normalized compat view used in `tests/test_compile.py`:

- `_auto_capable_projection_compat_view()` for Claude and RP
- `_manual_projection_compat_view()` for Codex
- `_common_projection_contract_view()` if the shared cross-host surface changes

Do not replace those fixtures with raw compiled projection output; the normalization is intentional and keeps volatile data out of the compatibility contract.

### 5.3 Required validation for this surface

Run at least:

```bash
uv run pytest tests/test_compile.py tests/test_adapter_contracts.py -q
```

If the change touches runtime persistence or inspect/review semantics, also run any neighboring targeted tests needed to prove the compatibility story still holds.

## 6. Practical review checklist for future changes

Before merging a change that touches these surfaces, confirm:

- Is `host_contract` still the durable run-metadata truth?
- Does `restore_host_contract()` still accept every legacy fixture we intentionally keep?
- Did any fixture-protected projection field change?
- If yes, is the change additive or breaking?
- Were the relevant `schema_version` / `projection_contract` values bumped when required?
- Were the fixtures and tests updated in the same PR?

That is the maintainability bar for compatibility work in this repo today.
