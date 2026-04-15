from __future__ import annotations

import json
from pathlib import Path

import pytest

from aiwf.adapters import ADAPTER_SPECS, build_adapter, restore_host_contract
from aiwf.adapters.base import (
    AdapterSpec,
    HostCapabilities,
    HostContract,
    NativeRuntimeContract,
    ReviewArtifactContract,
)
from aiwf.contracts import lint_contract_registry, lint_host_contract
from aiwf.models import RunMeta


def test_restore_host_contract_prefers_explicit_metadata() -> None:
    contract = restore_host_contract(
        {
            "host_contract": {
                "adapter": "rp",
                "mode": "manual",
                "capabilities": {
                    "supports_auto_execution": False,
                    "requires_explicit_review_handoff": True,
                },
            },
            "adapter": "stub",
            "auto": False,
        }
    )

    assert contract == HostContract(
        adapter="rp",
        mode="manual",
        capabilities=HostCapabilities(
            supports_auto_execution=False,
            requires_explicit_review_handoff=True,
        ),
        review=ReviewArtifactContract(
            required_run_artifacts=("verify-report.json",),
            required_report_string_fields=("summary", "mode", "prompt_file"),
            required_report_list_fields=("issues",),
            expected_report_mode="manual",
            linked_report_artifact_field="prompt_file",
        ),
        native_runtime=NativeRuntimeContract(
            enabled=True,
            command_candidates=("rp", "rp-cli"),
            install_hint=(
                "Install a RepoPrompt runtime on PATH (for example `rp` or `rp-cli`) "
                "to make RP native-ready; manual handoff remains supported."
            ),
            protocol_version=1,
        ),
    )


def test_restore_host_contract_accepts_legacy_metadata() -> None:
    contract = restore_host_contract({"adapter": "claude", "auto": True})

    assert contract == HostContract(
        adapter="claude",
        mode="auto",
        capabilities=HostCapabilities(
            supports_auto_execution=True,
            requires_explicit_review_handoff=False,
        ),
        review=ReviewArtifactContract(
            required_run_artifacts=("verify-report.json",),
            required_report_string_fields=("summary", "mode", "response_file"),
            required_report_list_fields=("issues",),
            expected_report_mode="auto",
            linked_report_artifact_field="response_file",
        ),
    )


def test_build_adapter_rejects_unsupported_auto_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not support auto mode"):
        build_adapter("codex", tmp_path, auto=True)


def test_build_adapter_supports_rp_auto_mode(tmp_path: Path) -> None:
    adapter, contract = build_adapter("rp", tmp_path, auto=True)

    assert contract == HostContract(
        adapter="rp",
        mode="auto",
        capabilities=HostCapabilities(
            supports_auto_execution=True,
            requires_explicit_review_handoff=False,
        ),
        review=ReviewArtifactContract(
            required_run_artifacts=("verify-report.json",),
            required_report_string_fields=("summary", "mode", "response_file"),
            required_report_list_fields=("issues",),
            expected_report_mode="auto",
            linked_report_artifact_field="response_file",
        ),
        native_runtime=NativeRuntimeContract(
            enabled=True,
            command_candidates=("rp", "rp-cli"),
            install_hint=(
                "Install a RepoPrompt runtime on PATH (for example `rp` or `rp-cli`) "
                "to make RP native-ready; manual handoff remains supported."
            ),
            protocol_version=1,
        ),
    )
    assert adapter.host_contract == contract


def test_native_runtime_contract_protocol_version_round_trip_and_backfill() -> None:
    current = NativeRuntimeContract.from_metadata(
        {
            "enabled": True,
            "command_candidates": ["rp", "rp-cli"],
            "install_hint": "Install rp.",
            "protocol_version": 1,
        }
    )
    legacy = NativeRuntimeContract.from_metadata(
        {
            "enabled": True,
            "command_candidates": ["rp"],
            "install_hint": "Install rp.",
        }
    )

    assert current == NativeRuntimeContract(
        enabled=True,
        command_candidates=("rp", "rp-cli"),
        install_hint="Install rp.",
        protocol_version=1,
    )
    assert current.to_metadata()["protocol_version"] == 1
    assert legacy.protocol_version is None


def test_builtin_adapter_contracts_pass_lint() -> None:
    results = lint_contract_registry(ADAPTER_SPECS)

    assert results
    assert all(result.ok for result in results)


def test_lint_host_contract_flags_linked_artifact_field_not_tracked() -> None:
    result = lint_host_contract(
        HostContract(
            adapter="broken",
            mode="manual",
            capabilities=HostCapabilities(
                supports_auto_execution=False,
                requires_explicit_review_handoff=True,
            ),
            review=ReviewArtifactContract(
                required_run_artifacts=("verify-report.json",),
                required_report_string_fields=("summary", "mode"),
                required_report_list_fields=("issues",),
                expected_report_mode="manual",
                linked_report_artifact_field="prompt_file",
            ),
        ),
        subject="broken/manual",
    )

    assert result.subject == "broken/manual"
    assert not result.ok
    assert {issue.code for issue in result.issues} == {"untracked-linked-artifact-field"}


def test_lint_contract_registry_flags_variant_metadata_mismatch() -> None:
    broken_spec = AdapterSpec(
        name="broken",
        default_mode="manual",
        variants={
            "manual": HostContract(
                adapter="other",
                mode="auto",
                capabilities=HostCapabilities(supports_auto_execution=False),
                review=ReviewArtifactContract(
                    required_report_string_fields=("summary",),
                    required_report_list_fields=("issues",),
                ),
            )
        },
        factory=lambda repo_root, contract: build_adapter("stub", repo_root)[0],
    )

    results = lint_contract_registry({"broken": broken_spec})

    result = next(result for result in results if result.subject == "broken/manual")
    assert not result.ok
    assert {issue.code for issue in result.issues} >= {
        "adapter-field-mismatch",
        "mode-field-mismatch",
        "auto-without-capability",
    }


def test_restore_host_contract_backfills_review_contract_for_item1_metadata() -> None:
    contract = restore_host_contract(
        {
            "host_contract": {
                "adapter": "claude",
                "mode": "manual",
                "capabilities": {
                    "supports_auto_execution": True,
                    "requires_explicit_review_handoff": True,
                },
            }
        }
    )

    assert contract == HostContract(
        adapter="claude",
        mode="manual",
        capabilities=HostCapabilities(
            supports_auto_execution=True,
            requires_explicit_review_handoff=True,
        ),
        review=ReviewArtifactContract(
            required_run_artifacts=("verify-report.json",),
            required_report_string_fields=("summary", "mode", "prompt_file"),
            required_report_list_fields=("issues",),
            expected_report_mode="manual",
            linked_report_artifact_field="prompt_file",
        ),
    )


def test_restore_host_contract_backfills_rp_auto_contract_defaults() -> None:
    contract = restore_host_contract(
        {
            "host_contract": {
                "adapter": "rp",
                "mode": "auto",
                "capabilities": {
                    "supports_auto_execution": True,
                    "requires_explicit_review_handoff": False,
                },
            }
        }
    )

    assert contract == HostContract(
        adapter="rp",
        mode="auto",
        capabilities=HostCapabilities(
            supports_auto_execution=True,
            requires_explicit_review_handoff=False,
        ),
        review=ReviewArtifactContract(
            required_run_artifacts=("verify-report.json",),
            required_report_string_fields=("summary", "mode", "response_file"),
            required_report_list_fields=("issues",),
            expected_report_mode="auto",
            linked_report_artifact_field="response_file",
        ),
        native_runtime=NativeRuntimeContract(
            enabled=True,
            command_candidates=("rp", "rp-cli"),
            install_hint=(
                "Install a RepoPrompt runtime on PATH (for example `rp` or `rp-cli`) "
                "to make RP native-ready; manual handoff remains supported."
            ),
            protocol_version=1,
        ),
    )


@pytest.mark.parametrize(
    ("fixture_name", "expected_contract"),
    [
        (
            "run_metadata_legacy_adapter_auto.json",
            HostContract(
                adapter="claude",
                mode="auto",
                capabilities=HostCapabilities(
                    supports_auto_execution=True,
                    requires_explicit_review_handoff=False,
                ),
                review=ReviewArtifactContract(
                    required_run_artifacts=("verify-report.json",),
                    required_report_string_fields=("summary", "mode", "response_file"),
                    required_report_list_fields=("issues",),
                    expected_report_mode="auto",
                    linked_report_artifact_field="response_file",
                ),
            ),
        ),
        (
            "run_metadata_host_contract_no_review.json",
            HostContract(
                adapter="claude",
                mode="manual",
                capabilities=HostCapabilities(
                    supports_auto_execution=True,
                    requires_explicit_review_handoff=True,
                ),
                review=ReviewArtifactContract(
                    required_run_artifacts=("verify-report.json",),
                    required_report_string_fields=("summary", "mode", "prompt_file"),
                    required_report_list_fields=("issues",),
                    expected_report_mode="manual",
                    linked_report_artifact_field="prompt_file",
                ),
            ),
        ),
        (
            "run_metadata_rp_manual_no_native_runtime.json",
            HostContract(
                adapter="rp",
                mode="manual",
                capabilities=HostCapabilities(
                    supports_auto_execution=False,
                    requires_explicit_review_handoff=True,
                ),
                review=ReviewArtifactContract(
                    required_run_artifacts=("verify-report.json",),
                    required_report_string_fields=("summary", "mode", "prompt_file"),
                    required_report_list_fields=("issues",),
                    expected_report_mode="manual",
                    linked_report_artifact_field="prompt_file",
                ),
                native_runtime=NativeRuntimeContract(
                    enabled=True,
                    command_candidates=("rp", "rp-cli"),
                    install_hint=(
                        "Install a RepoPrompt runtime on PATH (for example `rp` or `rp-cli`) "
                        "to make RP native-ready; manual handoff remains supported."
                    ),
                    protocol_version=1,
                ),
            ),
        ),
    ],
)
def test_restore_host_contract_accepts_legacy_run_metadata_fixtures(
    fixture_name: str,
    expected_contract: HostContract,
) -> None:
    fixture_path = Path(__file__).parent / "fixtures" / fixture_name
    run_meta = RunMeta.model_validate(json.loads(fixture_path.read_text(encoding="utf-8")))

    contract = restore_host_contract(run_meta.data)

    assert contract == expected_contract
