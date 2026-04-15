from __future__ import annotations

from pathlib import Path

import pytest

from aiwf.adapters import build_adapter, restore_host_contract
from aiwf.adapters.base import HostCapabilities, HostContract, ReviewArtifactContract


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
        build_adapter("rp", tmp_path, auto=True)


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
