"""Adapter implementations and registry helpers for aiwf."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from aiwf.adapters.base import AdapterSpec, HostCapabilities, HostContract, ReviewArtifactContract, RunnerAdapter
from aiwf.adapters.claude_code import ClaudeCodeAdapter
from aiwf.adapters.codex import CodexAdapter
from aiwf.adapters.rp_agent import RpAgentAdapter
from aiwf.adapters.stub import StubRunnerAdapter


def _build_claude_adapter(repo_root: Path, contract: HostContract) -> RunnerAdapter:
    return ClaudeCodeAdapter(repo_root=repo_root, auto=contract.auto)


def _build_rp_adapter(repo_root: Path, contract: HostContract) -> RunnerAdapter:
    del contract
    return RpAgentAdapter(repo_root=repo_root)


def _build_codex_adapter(repo_root: Path, contract: HostContract) -> RunnerAdapter:
    del contract
    return CodexAdapter(repo_root=repo_root)


def _build_stub_adapter(repo_root: Path, contract: HostContract) -> RunnerAdapter:
    del repo_root, contract
    return StubRunnerAdapter()


ADAPTER_SPECS: dict[str, AdapterSpec] = {
    "claude": AdapterSpec(
        name="claude",
        variants={
            "manual": HostContract(
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
            "auto": HostContract(
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
        },
        factory=_build_claude_adapter,
    ),
    "rp": AdapterSpec(
        name="rp",
        variants={
            "manual": HostContract(
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
        },
        factory=_build_rp_adapter,
    ),
    "codex": AdapterSpec(
        name="codex",
        variants={
            "manual": HostContract(
                adapter="codex",
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
        },
        factory=_build_codex_adapter,
    ),
    "stub": AdapterSpec(
        name="stub",
        variants={
            "manual": HostContract(
                adapter="stub",
                mode="manual",
                capabilities=HostCapabilities(
                    supports_auto_execution=False,
                    requires_explicit_review_handoff=False,
                ),
                review=ReviewArtifactContract(
                    required_run_artifacts=("verify-report.json",),
                    required_report_string_fields=("summary",),
                    required_report_list_fields=("issues",),
                ),
            )
        },
        factory=_build_stub_adapter,
    ),
}

ADAPTER_NAMES = tuple(ADAPTER_SPECS)


def resolve_adapter_contract(adapter_name: str, *, auto: bool = False) -> HostContract:
    """Resolve the explicit host contract for a requested adapter mode."""
    spec = ADAPTER_SPECS.get(adapter_name)
    if spec is None:
        raise ValueError(f"Unknown adapter: {adapter_name}")
    return spec.resolve_contract(auto=auto)


def build_adapter(adapter_name: str, repo_root: str | Path, *, auto: bool = False) -> tuple[RunnerAdapter, HostContract]:
    """Build an adapter instance and its resolved host contract."""
    contract = resolve_adapter_contract(adapter_name, auto=auto)
    adapter = build_adapter_from_contract(contract, repo_root)
    return adapter, contract


def build_adapter_from_contract(contract: HostContract, repo_root: str | Path) -> RunnerAdapter:
    """Build an adapter instance from an explicit stored host contract."""
    spec = ADAPTER_SPECS.get(contract.adapter)
    if spec is None:
        raise ValueError(f"Unknown adapter in stored host contract: {contract.adapter}")
    adapter = spec.factory(Path(repo_root), contract)
    if adapter.host_contract != contract:
        raise ValueError(f"Stored host contract is not supported by adapter {contract.adapter}")
    return adapter


def restore_host_contract(data: Mapping[str, object]) -> HostContract:
    """Restore a host contract from persisted run metadata.

    Prefer the explicit `host_contract` payload, but accept legacy
    `adapter` + `auto` metadata for backward compatibility.
    """

    raw_contract = data.get("host_contract")
    if raw_contract is not None:
        if not isinstance(raw_contract, Mapping):
            raise ValueError("stored host_contract must be an object")
        contract_data = dict(raw_contract)
        if "review" not in contract_data:
            adapter_name = contract_data.get("adapter")
            mode = contract_data.get("mode")
            if isinstance(adapter_name, str) and mode in {"manual", "auto"}:
                default_contract = resolve_adapter_contract(adapter_name.strip(), auto=(mode == "auto"))
                contract_data["review"] = default_contract.review.to_metadata()
        return HostContract.from_metadata(contract_data)

    adapter_name = data.get("adapter")
    auto = data.get("auto")
    if not isinstance(adapter_name, str) or not adapter_name.strip():
        raise ValueError("stored adapter must be a non-empty string")
    if not isinstance(auto, bool):
        raise ValueError("stored auto flag must be a boolean")
    return resolve_adapter_contract(adapter_name.strip(), auto=auto)


__all__ = [
    "ADAPTER_NAMES",
    "ADAPTER_SPECS",
    "AdapterSpec",
    "HostCapabilities",
    "HostContract",
    "ReviewArtifactContract",
    "RunnerAdapter",
    "ClaudeCodeAdapter",
    "CodexAdapter",
    "RpAgentAdapter",
    "StubRunnerAdapter",
    "build_adapter",
    "build_adapter_from_contract",
    "resolve_adapter_contract",
    "restore_host_contract",
]
