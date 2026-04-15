"""Adapter protocol definitions and host capability contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, cast

from aiwf.models import StageResult, TaskSpec


HostMode = Literal["manual", "auto"]


@dataclass(frozen=True)
class HostCapabilities:
    """Declarative runtime capabilities exposed by an adapter/host boundary."""

    supports_auto_execution: bool = False
    requires_explicit_review_handoff: bool = False

    def to_metadata(self) -> dict[str, object]:
        return {
            "supports_auto_execution": self.supports_auto_execution,
            "requires_explicit_review_handoff": self.requires_explicit_review_handoff,
        }

    @classmethod
    def from_metadata(cls, data: Mapping[str, object]) -> HostCapabilities:
        supports_auto_execution = data.get("supports_auto_execution")
        requires_explicit_review_handoff = data.get("requires_explicit_review_handoff")
        if not isinstance(supports_auto_execution, bool):
            raise ValueError("host contract capabilities.supports_auto_execution must be a boolean")
        if not isinstance(requires_explicit_review_handoff, bool):
            raise ValueError("host contract capabilities.requires_explicit_review_handoff must be a boolean")
        return cls(
            supports_auto_execution=supports_auto_execution,
            requires_explicit_review_handoff=requires_explicit_review_handoff,
        )


@dataclass(frozen=True)
class ReviewArtifactContract:
    """Explicit runtime expectations for review prerequisites and evidence."""

    required_run_artifacts: tuple[str, ...] = ()
    required_report_string_fields: tuple[str, ...] = ("summary",)
    required_report_list_fields: tuple[str, ...] = ("issues",)
    expected_report_mode: HostMode | None = None
    linked_report_artifact_field: str | None = None

    def to_metadata(self) -> dict[str, object]:
        return {
            "required_run_artifacts": list(self.required_run_artifacts),
            "required_report_string_fields": list(self.required_report_string_fields),
            "required_report_list_fields": list(self.required_report_list_fields),
            "expected_report_mode": self.expected_report_mode,
            "linked_report_artifact_field": self.linked_report_artifact_field,
        }

    @classmethod
    def from_metadata(cls, data: Mapping[str, object]) -> ReviewArtifactContract:
        required_run_artifacts = cls._read_string_sequence(data, "required_run_artifacts")
        required_report_string_fields = cls._read_string_sequence(data, "required_report_string_fields")
        required_report_list_fields = cls._read_string_sequence(data, "required_report_list_fields")
        expected_report_mode = data.get("expected_report_mode")
        linked_report_artifact_field = data.get("linked_report_artifact_field")

        if expected_report_mode is not None and expected_report_mode not in {"manual", "auto"}:
            raise ValueError("review contract expected_report_mode must be 'manual', 'auto', or null")
        if linked_report_artifact_field is not None and (
            not isinstance(linked_report_artifact_field, str) or not linked_report_artifact_field.strip()
        ):
            raise ValueError("review contract linked_report_artifact_field must be a non-empty string or null")
        normalized_expected_report_mode = cast(HostMode | None, expected_report_mode)

        return cls(
            required_run_artifacts=required_run_artifacts,
            required_report_string_fields=required_report_string_fields,
            required_report_list_fields=required_report_list_fields,
            expected_report_mode=normalized_expected_report_mode,
            linked_report_artifact_field=linked_report_artifact_field.strip()
            if isinstance(linked_report_artifact_field, str)
            else None,
        )

    @staticmethod
    def _read_string_sequence(data: Mapping[str, object], key: str) -> tuple[str, ...]:
        raw_value = data.get(key, [])
        if not isinstance(raw_value, list):
            raise ValueError(f"review contract {key} must be a list")
        values: list[str] = []
        for item in raw_value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"review contract {key} entries must be non-empty strings")
            values.append(item.strip())
        return tuple(values)


@dataclass(frozen=True)
class NativeRuntimeContract:
    """Optional contract scaffolding for a future native runtime bridge."""

    enabled: bool = False
    command_candidates: tuple[str, ...] = ()
    install_hint: str | None = None
    protocol_version: int | None = None

    def to_metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {
            "enabled": self.enabled,
            "command_candidates": list(self.command_candidates),
            "install_hint": self.install_hint,
        }
        if self.protocol_version is not None:
            metadata["protocol_version"] = self.protocol_version
        return metadata

    @classmethod
    def from_metadata(cls, data: Mapping[str, object]) -> NativeRuntimeContract:
        enabled = data.get("enabled", False)
        command_candidates = cls._read_string_sequence(data, "command_candidates")
        install_hint = data.get("install_hint")
        protocol_version = data.get("protocol_version")
        if not isinstance(enabled, bool):
            raise ValueError("native runtime contract enabled must be a boolean")
        if install_hint is not None and (not isinstance(install_hint, str) or not install_hint.strip()):
            raise ValueError("native runtime contract install_hint must be a non-empty string or null")
        if protocol_version is not None and (not isinstance(protocol_version, int) or isinstance(protocol_version, bool)):
            raise ValueError("native runtime contract protocol_version must be an integer or null")
        if isinstance(protocol_version, int) and protocol_version <= 0:
            raise ValueError("native runtime contract protocol_version must be greater than 0")
        if enabled and not command_candidates:
            raise ValueError("enabled native runtime contracts must declare at least one command candidate")
        return cls(
            enabled=enabled,
            command_candidates=command_candidates,
            install_hint=install_hint.strip() if isinstance(install_hint, str) else None,
            protocol_version=protocol_version if isinstance(protocol_version, int) else None,
        )

    @staticmethod
    def _read_string_sequence(data: Mapping[str, object], key: str) -> tuple[str, ...]:
        raw_value = data.get(key, [])
        if not isinstance(raw_value, list):
            raise ValueError(f"native runtime contract {key} must be a list")
        values: list[str] = []
        for item in raw_value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"native runtime contract {key} entries must be non-empty strings")
            values.append(item.strip())
        return tuple(values)


@dataclass(frozen=True)
class HostContract:
    """Explicit contract persisted with each run and exposed by adapters."""

    adapter: str
    mode: HostMode = "manual"
    capabilities: HostCapabilities = HostCapabilities()
    review: ReviewArtifactContract = field(default_factory=ReviewArtifactContract)
    native_runtime: NativeRuntimeContract = field(default_factory=NativeRuntimeContract)

    @property
    def auto(self) -> bool:
        return self.mode == "auto"

    def to_metadata(self) -> dict[str, object]:
        return {
            "adapter": self.adapter,
            "mode": self.mode,
            "capabilities": self.capabilities.to_metadata(),
            "review": self.review.to_metadata(),
            "native_runtime": self.native_runtime.to_metadata(),
        }

    @classmethod
    def from_metadata(cls, data: Mapping[str, object]) -> HostContract:
        adapter = data.get("adapter")
        mode = data.get("mode")
        capabilities = data.get("capabilities")
        review = data.get("review")
        native_runtime = data.get("native_runtime")
        if not isinstance(adapter, str) or not adapter.strip():
            raise ValueError("host contract adapter must be a non-empty string")
        if mode not in {"manual", "auto"}:
            raise ValueError("host contract mode must be 'manual' or 'auto'")
        if not isinstance(capabilities, Mapping):
            raise ValueError("host contract capabilities must be an object")
        if review is None:
            review = {}
        if not isinstance(review, Mapping):
            raise ValueError("host contract review must be an object")
        if native_runtime is None:
            native_runtime = {}
        if not isinstance(native_runtime, Mapping):
            raise ValueError("host contract native_runtime must be an object")
        normalized_mode = cast(HostMode, mode)
        return cls(
            adapter=adapter.strip(),
            mode=normalized_mode,
            capabilities=HostCapabilities.from_metadata(capabilities),
            review=ReviewArtifactContract.from_metadata(review),
            native_runtime=NativeRuntimeContract.from_metadata(native_runtime),
        )


class RunnerAdapter(Protocol):
    """Protocol implemented by workflow execution adapters."""

    host_contract: HostContract

    def discover(self, task: TaskSpec, run_dir: Path) -> str:
        """Return context pack content for a task."""

    def plan(self, task: TaskSpec, context: str) -> str:
        """Return execution plan content for a task."""

    def execute(self, task: TaskSpec, plan: str, run_dir: Path) -> StageResult:
        """Execute implementation work and return a stage result."""

    def review(self, task: TaskSpec, run_dir: Path) -> dict[str, object]:
        """Return review report content."""


AdapterFactory = Callable[[Path, HostContract], RunnerAdapter]


@dataclass(frozen=True)
class AdapterSpec:
    """Declarative registry entry for a concrete adapter."""

    name: str
    variants: dict[HostMode, HostContract]
    factory: AdapterFactory
    default_mode: HostMode = "manual"

    def resolve_contract(self, *, auto: bool = False) -> HostContract:
        requested_mode: HostMode = "auto" if auto else self.default_mode
        contract = self.variants.get(requested_mode)
        if contract is None:
            if auto:
                raise ValueError(f"Adapter {self.name} does not support auto mode")
            raise ValueError(f"Adapter {self.name} does not define a {requested_mode} contract")
        return contract
