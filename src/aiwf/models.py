"""Core data models shared across the aiwf workflow kernel."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from re import sub
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class StageSpec(ModelBase):
    """A logical stage within a runbook."""

    name: str
    description: str = ""
    outputs: list[str] = Field(default_factory=list)


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
    data: dict[str, Any] = Field(default_factory=dict)


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
