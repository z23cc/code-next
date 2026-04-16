"""Core data models shared across the aiwf workflow kernel."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from re import sub
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, field_validator, model_validator

from aiwf.exceptions import ErrorCode


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def slugify(value: str) -> str:
    """Produce a filesystem-friendly slug."""
    normalized = sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "task"


class ModelBase(BaseModel):
    """Shared Pydantic defaults for aiwf models."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class RunStatus(str, Enum):
    """Finite state machine states for a workflow run."""

    queued = "queued"
    running = "running"
    blocked = "blocked"
    needs_review = "needs_review"
    passed = "passed"
    failed = "failed"
    canceled = "canceled"


StagePauseStatus = Literal["blocked", "needs_review"]
RpBridgeMode = Literal["disabled", "manual-assist"]


class StageSpec(ModelBase):
    """A logical stage within a runbook."""

    name: str
    description: str = ""
    outputs: list[str] = Field(default_factory=list)
    required: bool = True
    retry_limit: int = 0
    pause_on: list[StagePauseStatus] = Field(default_factory=list)

    @field_validator("retry_limit")
    @classmethod
    def validate_retry_limit(cls, value: int) -> int:
        if value < 0:
            raise ValueError("retry_limit must be greater than or equal to 0")
        return value

    @field_validator("pause_on")
    @classmethod
    def validate_pause_on(cls, value: list[StagePauseStatus]) -> list[StagePauseStatus]:
        duplicates: list[str] = []
        seen: set[str] = set()
        for status in value:
            if status in seen and status not in duplicates:
                duplicates.append(status)
            seen.add(status)
        if duplicates:
            raise ValueError(f"pause_on contains duplicate statuses: {', '.join(duplicates)}")
        return value


class TaskSpec(ModelBase):
    """Task input loaded from `.ai/tasks/*.md`."""

    title: str
    slug: str | None = None
    runbook: str = "default"
    gates: str = "default"
    policy: str = "repo-policy"
    body: str = ""

    @model_validator(mode="before")
    @classmethod
    def populate_slug(cls, data: Any) -> Any:
        if isinstance(data, dict):
            updated = dict(data)
            if not updated.get("slug") and updated.get("title"):
                updated["slug"] = slugify(str(updated["title"]))
            return updated
        return data


class RunbookSpec(ModelBase):
    """Runbook definition loaded from `.ai/runbooks/*.md`."""

    name: str
    description: str = ""
    stages: list[StageSpec] = Field(default_factory=list)
    body: str = ""

    @field_validator("stages")
    @classmethod
    def validate_unique_stage_names(cls, value: list[StageSpec]) -> list[StageSpec]:
        duplicates: list[str] = []
        seen: set[str] = set()
        for stage in value:
            if stage.name in seen and stage.name not in duplicates:
                duplicates.append(stage.name)
            seen.add(stage.name)
        if duplicates:
            raise ValueError(f"runbook stages must be unique: {', '.join(duplicates)}")
        return value


class GateCommand(ModelBase):
    """A single deterministic validation command."""

    name: str
    command: str
    timeout_seconds: int = 120

    @field_validator("timeout_seconds")
    @classmethod
    def validate_timeout_seconds(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("timeout_seconds must be greater than 0")
        return value


class GateSet(ModelBase):
    """A named collection of gate commands."""

    name: str = "default"
    description: str = ""
    gates: list[GateCommand] = Field(default_factory=list)


class EventRecord(ModelBase):
    """A single append-only run event."""

    ts: datetime = Field(default_factory=utc_now)
    event: str
    status: RunStatus | None = None
    stage: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class RunMeta(ModelBase):
    """Current run snapshot stored in `run.json`."""

    model_config = ConfigDict(extra="ignore", use_enum_values=False)

    run_id: str
    run_dir: str
    task_title: str
    task_slug: str
    task_path: str | None = None
    runbook: str | None = None
    gate_set: str | None = None
    policy: str | None = None
    status: RunStatus = RunStatus.queued
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_completed_stage: str | None = None
    error: str | None = None
    error_code: ErrorCode | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class RpBridgeRunConfig(ModelBase):
    """Validated per-run RepoPrompt bridge configuration persisted in run metadata."""

    mode: RpBridgeMode
    workspace: StrictStr | None = None
    tab: StrictStr | None = None
    context_id: StrictStr | None = None
    agent_role: StrictStr | None = None
    timeout_seconds: StrictInt | None = None
    export_transcript: StrictBool = False

    @field_validator("workspace", "tab", "context_id", "agent_role")
    @classmethod
    def validate_optional_non_empty_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def validate_timeout_seconds(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value <= 0:
            raise ValueError("timeout_seconds must be greater than 0")
        return value


class WorkReceipt(ModelBase):
    """Final run summary written at the end of workflow execution."""

    run_id: str
    status: RunStatus
    summary: str = ""
    artifacts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime = Field(default_factory=utc_now)


class RunArtifactRef(ModelBase):
    """A key artifact reference surfaced in run diagnostics."""

    name: str
    path: str


class RunTimelineEntry(ModelBase):
    """A timeline entry summarizing a meaningful run event."""

    ts: datetime
    event: str
    stage: str | None = None
    status: RunStatus | None = None


class RunHostDiagnostics(ModelBase):
    """Host contract summary relevant to operator action."""

    adapter: str
    mode: str
    supports_auto_execution: bool
    requires_explicit_review_handoff: bool


class RunDiagnostics(ModelBase):
    """Structured diagnostics/explainability surface for a workflow run."""

    run_id: str
    workflow: str
    status: RunStatus
    last_completed_stage: str | None = None
    status_reason: str
    resumable: bool = False
    reviewable: bool = False
    resume_command: str | None = None
    review_command: str | None = None
    next_actions: list[str] = Field(default_factory=list)
    error: str | None = None
    error_code: ErrorCode | None = None
    host: RunHostDiagnostics
    key_artifacts: list[RunArtifactRef] = Field(default_factory=list)
    stage_timeline: list[RunTimelineEntry] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)


class RunProvenanceArtifact(ModelBase):
    """A navigable artifact index entry with stage/category provenance."""

    name: str
    path: str
    stage: str | None = None
    category: str
    related_artifacts: list[str] = Field(default_factory=list)


class RunGateEvidence(ModelBase):
    """Gate evidence references surfaced for later operator tooling."""

    report: RunArtifactRef | None = None
    gate_set: str | None = None
    passed: bool | None = None


class RunReviewEvidence(ModelBase):
    """Review evidence references surfaced from the host contract/report."""

    report: RunArtifactRef | None = None
    mode: str | None = None
    linked_report_artifact_field: str | None = None
    linked_artifacts: list[RunArtifactRef] = Field(default_factory=list)
    required_run_artifacts: list[str] = Field(default_factory=list)
    available_required_artifacts: list[RunArtifactRef] = Field(default_factory=list)


class RunProvenance(ModelBase):
    """Run-level artifact/evidence navigation surface."""

    run_id: str
    workflow: str
    status: RunStatus
    last_completed_stage: str | None = None
    host: RunHostDiagnostics
    artifact_index: list[RunProvenanceArtifact] = Field(default_factory=list)
    gate_evidence: RunGateEvidence = Field(default_factory=RunGateEvidence)
    review_evidence: RunReviewEvidence = Field(default_factory=RunReviewEvidence)
    generated_at: datetime = Field(default_factory=utc_now)


class StageResult(ModelBase):
    """Result object returned by a single workflow stage."""

    stage: str
    status: RunStatus
    summary: str = ""
    outputs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GateResult(ModelBase):
    """Result for a single gate command execution."""

    name: str
    command: str
    passed: bool
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    duration_seconds: float = 0.0


class VerifyReport(ModelBase):
    """Aggregated verification report for a gate set run."""

    gate_set: str
    cwd: str
    passed: bool
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime = Field(default_factory=utc_now)
    results: list[GateResult] = Field(default_factory=list)


class ArtifactSchemaBase(BaseModel):
    """Strict runtime-validation model base for persisted artifact content."""

    model_config = ConfigDict(use_enum_values=False)


class GateResultContent(ArtifactSchemaBase):
    """Strict artifact schema for a single gate result payload."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    name: StrictStr
    command: StrictStr
    passed: StrictBool
    returncode: StrictInt | None = None
    stdout: StrictStr = ""
    stderr: StrictStr = ""
    timed_out: StrictBool = False
    duration_seconds: StrictFloat | StrictInt = 0.0

    @field_validator("name", "command")
    @classmethod
    def validate_non_empty_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value


class VerifyReportContent(ArtifactSchemaBase):
    """Strict artifact schema for `verify-report.json`."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    gate_set: StrictStr
    cwd: StrictStr
    passed: StrictBool
    started_at: datetime
    finished_at: datetime
    results: list[GateResultContent] = Field(default_factory=list)

    @field_validator("gate_set", "cwd")
    @classmethod
    def validate_non_empty_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value


class ReviewEvidenceSummaryContent(ArtifactSchemaBase):
    """Strict artifact schema for optional review evidence summaries."""

    model_config = ConfigDict(extra="allow", use_enum_values=False)

    verify: StrictStr | None = None
    gate_results: list[StrictStr] = Field(default_factory=list)
    diagnostics: StrictStr | None = None
    provenance: StrictStr | None = None
    changed_files: list[StrictStr] = Field(default_factory=list)
    diff_summary: list[StrictStr] = Field(default_factory=list)

    @field_validator("verify", "diagnostics", "provenance")
    @classmethod
    def validate_optional_non_empty_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value


class ReviewReportContent(ArtifactSchemaBase):
    """Strict artifact schema for `review-report.json` with host-specific extensions allowed."""

    model_config = ConfigDict(extra="allow", use_enum_values=False)

    summary: StrictStr
    issues: list[Any] = Field(default_factory=list)
    mode: StrictStr | None = None
    prompt_file: StrictStr | None = None
    response_file: StrictStr | None = None
    response_excerpt: StrictStr | None = None
    verify_report_file: StrictStr | None = None
    diagnostics_file: StrictStr | None = None
    provenance_file: StrictStr | None = None
    evidence_files: list[StrictStr] = Field(default_factory=list)
    evidence_summary: ReviewEvidenceSummaryContent | None = None
    run_dir: StrictStr | None = None

    @field_validator(
        "summary",
        "mode",
        "prompt_file",
        "response_file",
        "verify_report_file",
        "diagnostics_file",
        "provenance_file",
        "run_dir",
    )
    @classmethod
    def validate_non_empty_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value


class WorkReceiptContent(ArtifactSchemaBase):
    """Strict artifact schema for `work-receipt.json`."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    run_id: StrictStr
    status: RunStatus
    summary: StrictStr = ""
    artifacts: list[StrictStr] = Field(default_factory=list)
    risks: list[StrictStr] = Field(default_factory=list)
    notes: list[StrictStr] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value
