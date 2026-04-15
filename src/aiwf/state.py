"""Run state initialization and transition helpers."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

from pydantic import ValidationError

from aiwf.exceptions import StateError
from aiwf.models import EventRecord, RunMeta, RunStatus, TaskSpec, slugify, utc_now


class RunStateManager:
    """Manage `.ai/runs/<run_id>/` state for workflow execution."""

    _ALLOWED_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
        RunStatus.queued: {RunStatus.running, RunStatus.failed, RunStatus.canceled},
        RunStatus.running: {
            RunStatus.blocked,
            RunStatus.needs_review,
            RunStatus.passed,
            RunStatus.failed,
            RunStatus.canceled,
        },
        RunStatus.blocked: {
            RunStatus.running,
            RunStatus.needs_review,
            RunStatus.failed,
            RunStatus.canceled,
        },
        RunStatus.needs_review: {
            RunStatus.running,
            RunStatus.passed,
            RunStatus.failed,
            RunStatus.canceled,
        },
        RunStatus.passed: set(),
        RunStatus.failed: {RunStatus.running, RunStatus.canceled},
        RunStatus.canceled: set(),
    }

    def __init__(self, ai_root: str | Path = ".ai") -> None:
        self.ai_root = Path(ai_root)
        self.runs_dir = self.ai_root / "runs"

    def init_run(self, task_spec: TaskSpec, *, task_path: str | Path | None = None) -> str:
        """Create the run directory, snapshot, and initial event."""
        self.runs_dir.mkdir(parents=True, exist_ok=True)

        run_id = self._generate_run_id(task_spec.slug or task_spec.title)
        run_dir = self.runs_dir / run_id
        try:
            run_dir.mkdir(parents=False, exist_ok=False)
        except FileExistsError as exc:
            raise StateError("Run directory already exists", path=run_dir, stage="init_run") from exc

        meta = RunMeta(
            run_id=run_id,
            run_dir=str(run_dir),
            task_title=task_spec.title,
            task_slug=task_spec.slug or slugify(task_spec.title),
            task_path=str(task_path) if task_path is not None else None,
            runbook=task_spec.runbook,
            gate_set=task_spec.gates,
            policy=task_spec.policy,
        )
        self._write_run_meta(meta)
        self.append_event(
            run_id,
            EventRecord(
                event="run_initialized",
                status=meta.status,
                stage="init",
                data={"task_slug": meta.task_slug},
            ),
        )
        return run_id

    def transition(
        self,
        run_id: str,
        new_status: RunStatus | str,
        *,
        stage: str | None = None,
        data: dict[str, object] | None = None,
        error: str | None = None,
    ) -> RunMeta:
        """Validate and persist a run status transition."""
        meta = self.load_run(run_id)
        target_status = RunStatus(new_status)
        allowed = self._ALLOWED_TRANSITIONS[meta.status]
        if target_status not in allowed:
            raise StateError(
                f"Illegal transition from {meta.status.value} to {target_status.value}",
                path=self._run_json_path(run_id),
                stage=stage or "transition",
            )

        payload = dict(data or {})
        payload.update({"from": meta.status.value, "to": target_status.value})
        updated = meta.model_copy(
            update={
                "status": target_status,
                "updated_at": utc_now(),
                "last_completed_stage": stage or meta.last_completed_stage,
                "error": error,
            }
        )
        self._write_run_meta(updated)
        self.append_event(
            run_id,
            EventRecord(
                event="status_transition",
                status=target_status,
                stage=stage,
                data=payload,
            ),
        )
        return updated

    def load_run(self, run_id: str) -> RunMeta:
        """Load the current `run.json` snapshot."""
        run_json_path = self._run_json_path(run_id)
        try:
            content = run_json_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise StateError("Run snapshot does not exist", path=run_json_path, stage="load_run") from exc
        except OSError as exc:
            raise StateError("Failed to read run snapshot", path=run_json_path, stage="load_run") from exc

        try:
            return RunMeta.model_validate_json(content)
        except ValidationError as exc:
            raise StateError("Invalid run snapshot", path=run_json_path, stage="load_run") from exc

    def append_event(self, run_id: str, event_record: EventRecord) -> None:
        """Append a single JSON event line to `events.ndjson`."""
        run_dir = self._require_run_dir(run_id)
        events_path = run_dir / "events.ndjson"
        try:
            with events_path.open("a", encoding="utf-8") as handle:
                handle.write(event_record.model_dump_json())
                handle.write("\n")
        except OSError as exc:
            raise StateError("Failed to append event", path=events_path, stage="append_event") from exc

    def load_events(self, run_id: str) -> list[EventRecord]:
        """Load parsed append-only run events from `events.ndjson`."""
        run_dir = self._require_run_dir(run_id)
        events_path = run_dir / "events.ndjson"
        try:
            lines = events_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError as exc:
            raise StateError("Run events do not exist", path=events_path, stage="load_events") from exc
        except OSError as exc:
            raise StateError("Failed to read run events", path=events_path, stage="load_events") from exc

        events: list[EventRecord] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                events.append(EventRecord.model_validate_json(line))
            except ValidationError as exc:
                raise StateError("Invalid run event record", path=events_path, stage="load_events") from exc
        return events

    def update_run(
        self,
        run_id: str,
        *,
        last_completed_stage: str | None = None,
        error: str | None = None,
        data: dict[str, object] | None = None,
    ) -> RunMeta:
        """Persist non-status run metadata updates and append an audit event."""
        meta = self.load_run(run_id)
        merged_data = dict(meta.data)
        if data:
            merged_data.update(data)
        updated = meta.model_copy(
            update={
                "updated_at": utc_now(),
                "last_completed_stage": last_completed_stage or meta.last_completed_stage,
                "error": error if error is not None else meta.error,
                "data": merged_data,
            }
        )
        self._write_run_meta(updated)
        self.append_event(
            run_id,
            EventRecord(
                event="run_updated",
                stage=last_completed_stage,
                data={
                    "last_completed_stage": updated.last_completed_stage,
                    "data": data or {},
                    "error": updated.error,
                },
            ),
        )
        return updated

    def _generate_run_id(self, task_slug: str) -> str:
        timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        compact_slug = slugify(task_slug)
        for _ in range(10):
            run_id = f"{timestamp}_{compact_slug}_{secrets.token_hex(2)}"
            if not (self.runs_dir / run_id).exists():
                return run_id
        raise StateError("Unable to generate a unique run_id", path=self.runs_dir, stage="init_run")

    def _write_run_meta(self, meta: RunMeta) -> None:
        run_json_path = self._run_json_path(meta.run_id)
        try:
            run_json_path.write_text(
                json.dumps(meta.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise StateError("Failed to write run snapshot", path=run_json_path, stage="write_run") from exc

    def _require_run_dir(self, run_id: str) -> Path:
        run_dir = self.runs_dir / run_id
        if not run_dir.exists():
            raise StateError("Run directory does not exist", path=run_dir, stage="state_lookup")
        if not run_dir.is_dir():
            raise StateError("Run path is not a directory", path=run_dir, stage="state_lookup")
        return run_dir

    def _run_json_path(self, run_id: str) -> Path:
        return self.runs_dir / run_id / "run.json"
