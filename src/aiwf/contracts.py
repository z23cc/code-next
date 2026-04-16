"""Contract linting and observability helpers for host/review boundaries."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from aiwf.adapters.base import AdapterSpec, BridgeContract, HostContract, NativeRuntimeContract, ReviewArtifactContract


@dataclass(frozen=True)
class ContractLintIssue:
    """A single lint failure for a host/review contract surface."""

    code: str
    message: str


@dataclass(frozen=True)
class ContractLintResult:
    """Lint result for a concrete contract subject."""

    subject: str
    issues: tuple[ContractLintIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues


@dataclass(frozen=True)
class ReviewBoundaryStatus:
    """Whether a run has the artifacts required to begin review."""

    ready: bool
    missing_required_artifacts: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewEvidenceStatus:
    """Completeness summary for persisted review evidence."""

    status: Literal["not_started", "complete", "incomplete"] = "not_started"
    mode: str | None = None
    missing_report_fields: tuple[str, ...] = ()
    missing_linked_artifacts: tuple[str, ...] = ()
    linked_artifacts: tuple[str, ...] = ()
    mode_mismatch: str | None = None


def lint_contract_registry(specs: Mapping[str, AdapterSpec]) -> list[ContractLintResult]:
    """Lint a registry of built-in adapter specs."""
    results: list[ContractLintResult] = []
    for adapter_name, spec in specs.items():
        spec_issues: list[ContractLintIssue] = []
        if spec.name != adapter_name:
            spec_issues.append(
                ContractLintIssue(
                    code="adapter-name-mismatch",
                    message=f"registry key {adapter_name!r} does not match spec.name {spec.name!r}",
                )
            )
        if not spec.variants:
            spec_issues.append(
                ContractLintIssue(
                    code="missing-variants",
                    message="adapter spec must declare at least one host contract variant",
                )
            )
        if spec.default_mode not in spec.variants:
            spec_issues.append(
                ContractLintIssue(
                    code="missing-default-variant",
                    message=f"default_mode {spec.default_mode!r} is not declared in variants",
                )
            )
        if spec_issues:
            results.append(ContractLintResult(subject=f"{adapter_name} (adapter spec)", issues=tuple(spec_issues)))

        for mode, contract in spec.variants.items():
            issues = list(lint_host_contract(contract, subject=f"{adapter_name}/{mode}").issues)
            if contract.adapter != adapter_name:
                issues.append(
                    ContractLintIssue(
                        code="adapter-field-mismatch",
                        message=f"contract.adapter {contract.adapter!r} does not match adapter {adapter_name!r}",
                    )
                )
            if contract.mode != mode:
                issues.append(
                    ContractLintIssue(
                        code="mode-field-mismatch",
                        message=f"contract.mode {contract.mode!r} does not match registry variant {mode!r}",
                    )
                )
            results.append(ContractLintResult(subject=f"{adapter_name}/{mode}", issues=tuple(issues)))
    return results


def lint_host_contract(contract: HostContract, *, subject: str = "host contract") -> ContractLintResult:
    """Lint a single host/review contract."""
    issues: list[ContractLintIssue] = []
    if not contract.adapter.strip():
        issues.append(ContractLintIssue(code="missing-adapter", message="contract adapter must be non-empty"))
    if contract.mode == "auto" and not contract.capabilities.supports_auto_execution:
        issues.append(
            ContractLintIssue(
                code="auto-without-capability",
                message="auto contracts must declare supports_auto_execution=True",
            )
        )

    review = contract.review
    issues.extend(_lint_review_contract(review, contract=contract))
    issues.extend(_lint_native_runtime_contract(contract.native_runtime))
    issues.extend(_lint_bridge_contract(contract.bridge))
    return ContractLintResult(subject=subject, issues=tuple(issues))


def review_contract_fields(review: ReviewArtifactContract) -> tuple[str, ...]:
    """Return review report fields in a stable operator-facing order."""
    ordered: list[str] = []
    for field_name in review.required_report_string_fields:
        if field_name not in ordered:
            ordered.append(field_name)
    for field_name in review.required_report_list_fields:
        if field_name not in ordered:
            ordered.append(field_name)
    return tuple(ordered)


def assess_review_boundary(
    contract: HostContract,
    *,
    available_artifact_names: Collection[str],
) -> ReviewBoundaryStatus:
    """Report whether the run has the required artifacts to begin review."""
    available = set(available_artifact_names)
    missing_required_artifacts = tuple(
        artifact_name
        for artifact_name in contract.review.required_run_artifacts
        if artifact_name not in available
    )
    return ReviewBoundaryStatus(
        ready=not missing_required_artifacts,
        missing_required_artifacts=missing_required_artifacts,
    )


def assess_review_evidence(
    contract: HostContract,
    review_report: Mapping[str, object] | None,
    *,
    available_artifact_names: Collection[str],
) -> ReviewEvidenceStatus:
    """Report whether stored review evidence satisfies the host contract."""
    if review_report is None:
        return ReviewEvidenceStatus(status="not_started")

    review = contract.review
    missing_report_fields: list[str] = []
    for field_name in review.required_report_string_fields:
        if _non_empty_string(review_report.get(field_name)) is None:
            missing_report_fields.append(field_name)
    for field_name in review.required_report_list_fields:
        if not isinstance(review_report.get(field_name), list):
            missing_report_fields.append(field_name)

    linked_artifacts: tuple[str, ...] = ()
    missing_linked_artifacts: tuple[str, ...] = ()
    if review.linked_report_artifact_field is not None:
        linked_artifact = _non_empty_string(review_report.get(review.linked_report_artifact_field))
        if linked_artifact is not None:
            linked_artifacts = (linked_artifact,)
            if linked_artifact not in set(available_artifact_names):
                missing_linked_artifacts = (linked_artifact,)
        elif review.linked_report_artifact_field not in missing_report_fields:
            missing_report_fields.append(review.linked_report_artifact_field)

    mode = _non_empty_string(review_report.get("mode"))
    mode_mismatch: str | None = None
    if review.expected_report_mode is not None and mode != review.expected_report_mode:
        reported_mode = mode or "-"
        mode_mismatch = f"expected={review.expected_report_mode} reported={reported_mode}"

    status: Literal["not_started", "complete", "incomplete"] = "complete"
    if missing_report_fields or missing_linked_artifacts or mode_mismatch is not None:
        status = "incomplete"

    return ReviewEvidenceStatus(
        status=status,
        mode=mode,
        missing_report_fields=tuple(missing_report_fields),
        missing_linked_artifacts=missing_linked_artifacts,
        linked_artifacts=linked_artifacts,
        mode_mismatch=mode_mismatch,
    )


def _lint_review_contract(review: ReviewArtifactContract, *, contract: HostContract) -> list[ContractLintIssue]:
    issues: list[ContractLintIssue] = []
    duplicates = _find_duplicates(review.required_run_artifacts)
    if duplicates:
        issues.append(
            ContractLintIssue(
                code="duplicate-required-run-artifacts",
                message=f"required_run_artifacts contains duplicates: {', '.join(duplicates)}",
            )
        )

    string_duplicates = _find_duplicates(review.required_report_string_fields)
    if string_duplicates:
        issues.append(
            ContractLintIssue(
                code="duplicate-required-report-string-fields",
                message=f"required_report_string_fields contains duplicates: {', '.join(string_duplicates)}",
            )
        )

    list_duplicates = _find_duplicates(review.required_report_list_fields)
    if list_duplicates:
        issues.append(
            ContractLintIssue(
                code="duplicate-required-report-list-fields",
                message=f"required_report_list_fields contains duplicates: {', '.join(list_duplicates)}",
            )
        )

    overlap = sorted(set(review.required_report_string_fields) & set(review.required_report_list_fields))
    if overlap:
        issues.append(
            ContractLintIssue(
                code="report-field-type-overlap",
                message=f"review report fields cannot be both string and list fields: {', '.join(overlap)}",
            )
        )

    if review.expected_report_mode is not None and review.expected_report_mode != contract.mode:
        issues.append(
            ContractLintIssue(
                code="expected-report-mode-mismatch",
                message=(
                    f"expected_report_mode {review.expected_report_mode!r} must match "
                    f"contract.mode {contract.mode!r}"
                ),
            )
        )
    if review.expected_report_mode is not None and "mode" not in review.required_report_string_fields:
        issues.append(
            ContractLintIssue(
                code="missing-mode-report-field",
                message="contracts with expected_report_mode must require the report `mode` string field",
            )
        )
    if review.linked_report_artifact_field is not None and (
        review.linked_report_artifact_field not in review.required_report_string_fields
    ):
        issues.append(
            ContractLintIssue(
                code="untracked-linked-artifact-field",
                message=(
                    "linked_report_artifact_field must also appear in required_report_string_fields "
                    f"(missing {review.linked_report_artifact_field!r})"
                ),
            )
        )
    return issues


def _lint_native_runtime_contract(native_runtime: NativeRuntimeContract) -> list[ContractLintIssue]:
    issues: list[ContractLintIssue] = []
    duplicates = _find_duplicates(native_runtime.command_candidates)
    if duplicates:
        issues.append(
            ContractLintIssue(
                code="duplicate-native-runtime-command-candidates",
                message=f"native runtime command_candidates contains duplicates: {', '.join(duplicates)}",
            )
        )
    if native_runtime.enabled and not native_runtime.command_candidates:
        issues.append(
            ContractLintIssue(
                code="missing-native-runtime-command-candidates",
                message="enabled native runtime contracts must declare at least one command candidate",
            )
        )
    if not native_runtime.enabled and native_runtime.command_candidates:
        issues.append(
            ContractLintIssue(
                code="disabled-native-runtime-has-command-candidates",
                message="disabled native runtime contracts must not declare command candidates",
            )
        )
    return issues


def _lint_bridge_contract(bridge: BridgeContract) -> list[ContractLintIssue]:
    issues: list[ContractLintIssue] = []
    mode_duplicates = _find_duplicates(bridge.supported_modes)
    if mode_duplicates:
        issues.append(
            ContractLintIssue(
                code="duplicate-bridge-supported-modes",
                message=f"bridge supported_modes contains duplicates: {', '.join(mode_duplicates)}",
            )
        )

    command_duplicates = _find_duplicates(bridge.command_candidates)
    if command_duplicates:
        issues.append(
            ContractLintIssue(
                code="duplicate-bridge-command-candidates",
                message=f"bridge command_candidates contains duplicates: {', '.join(command_duplicates)}",
            )
        )

    destructive_duplicates = _find_duplicates(bridge.destructive_capabilities)
    if destructive_duplicates:
        issues.append(
            ContractLintIssue(
                code="duplicate-bridge-destructive-capabilities",
                message=(
                    "bridge destructive_capabilities contains duplicates: "
                    f"{', '.join(destructive_duplicates)}"
                ),
            )
        )

    if bridge.enabled and not bridge.command_candidates:
        issues.append(
            ContractLintIssue(
                code="missing-bridge-command-candidates",
                message="enabled bridge contracts must declare at least one command candidate",
            )
        )
    if bridge.enabled and bridge.default_mode not in bridge.supported_modes:
        issues.append(
            ContractLintIssue(
                code="bridge-default-mode-not-supported",
                message="enabled bridge contracts must include default_mode in supported_modes",
            )
        )
    if not bridge.enabled and (
        bridge.default_mode != "disabled"
        or bridge.supported_modes != ("disabled",)
        or bridge.command_candidates
        or bridge.install_hint is not None
        or bridge.allows_mutations
        or bridge.destructive_capabilities
    ):
        issues.append(
            ContractLintIssue(
                code="disabled-bridge-has-config",
                message="disabled bridge contracts must use the default disabled configuration",
            )
        )
    if not bridge.allows_mutations and bridge.destructive_capabilities:
        issues.append(
            ContractLintIssue(
                code="bridge-destructive-capabilities-without-mutations",
                message="bridge destructive_capabilities requires allows_mutations=true",
            )
        )
    return issues


def _find_duplicates(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for item in items:
        if item in seen and item not in duplicates:
            duplicates.append(item)
        seen.add(item)
    return duplicates


def _non_empty_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = [
    "ContractLintIssue",
    "ContractLintResult",
    "ReviewBoundaryStatus",
    "ReviewEvidenceStatus",
    "assess_review_boundary",
    "assess_review_evidence",
    "lint_contract_registry",
    "lint_host_contract",
    "review_contract_fields",
]
