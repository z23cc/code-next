from __future__ import annotations

import json
from pathlib import Path

import pytest

from aiwf.exceptions import StateError
from aiwf.models import RunStatus, TaskSpec
from aiwf.state import RunStateManager


def test_init_run_creates_snapshot_and_event(tmp_path: Path) -> None:
    manager = RunStateManager(tmp_path / ".ai")
    task = TaskSpec(title="Ship Milestone One", body="Implement the M1 scaffold.")

    run_id = manager.init_run(task, task_path=".ai/tasks/m1.md")
    run = manager.load_run(run_id)
    run_dir = tmp_path / ".ai" / "runs" / run_id

    assert run.status is RunStatus.queued
    assert run.task_path == ".ai/tasks/m1.md"
    assert (run_dir / "run.json").exists()

    event_lines = (run_dir / "events.ndjson").read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    first_event = json.loads(event_lines[0])
    assert first_event["event"] == "run_initialized"


def test_transition_updates_snapshot_and_appends_event(tmp_path: Path) -> None:
    manager = RunStateManager(tmp_path / ".ai")
    run_id = manager.init_run(TaskSpec(title="Transition Task", body="Track state transitions."))

    updated = manager.transition(run_id, RunStatus.running, stage="plan", data={"step": "discover"})
    event_lines = (
        (tmp_path / ".ai" / "runs" / run_id / "events.ndjson").read_text(encoding="utf-8").splitlines()
    )
    last_event = json.loads(event_lines[-1])

    assert updated.status is RunStatus.running
    assert updated.last_completed_stage == "plan"
    assert len(event_lines) == 2
    assert last_event["data"]["from"] == "queued"
    assert last_event["data"]["to"] == "running"
    assert last_event["data"]["step"] == "discover"


def test_illegal_transition_raises_state_error(tmp_path: Path) -> None:
    manager = RunStateManager(tmp_path / ".ai")
    run_id = manager.init_run(TaskSpec(title="Bad Transition", body="Invalid state jump."))

    with pytest.raises(StateError) as exc_info:
        manager.transition(run_id, RunStatus.passed)

    assert "Illegal transition" in str(exc_info.value)
    assert "path=" in str(exc_info.value)


def test_loading_missing_run_raises_state_error(tmp_path: Path) -> None:
    manager = RunStateManager(tmp_path / ".ai")

    with pytest.raises(StateError) as exc_info:
        manager.load_run("missing-run")

    assert "stage=load_run" in str(exc_info.value)
