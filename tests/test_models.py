from __future__ import annotations

import pytest
from pydantic import ValidationError

from aiwf.models import GateSet, RunMeta, RunStatus, RunbookSpec, TaskSpec


def test_task_spec_populates_slug_and_defaults() -> None:
    task = TaskSpec(title="Implement Milestone One", body="Finish the M1 scaffold.")

    assert task.slug == "implement-milestone-one"
    assert task.runbook == "default"
    assert task.gates == "default"
    assert task.policy == "repo-policy"


def test_runbook_and_gate_models_validate_nested_data() -> None:
    runbook = RunbookSpec(
        name="default",
        stages=[{"name": "discover", "outputs": ["context-pack.md"]}],
        body="Use the default workflow.",
    )
    gate_set = GateSet(gates=[{"name": "lint", "command": "ruff check src/ tests/"}])

    assert runbook.stages[0].name == "discover"
    assert runbook.stages[0].outputs == ["context-pack.md"]
    assert gate_set.gates[0].timeout_seconds == 120


def test_run_meta_uses_enum_status() -> None:
    meta = RunMeta(
        run_id="run-123",
        run_dir=".ai/runs/run-123",
        task_title="Example Task",
        task_slug="example-task",
        status=RunStatus.running,
    )

    assert meta.status is RunStatus.running


def test_task_spec_requires_title() -> None:
    with pytest.raises(ValidationError):
        TaskSpec(body="Missing the required title field.")
