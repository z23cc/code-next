from __future__ import annotations

from pathlib import Path

import pytest

from aiwf.exceptions import LoadError
from aiwf.loader import load_gate_set, load_policy, load_runbook, load_task


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_load_seed_files_from_repo() -> None:
    task = load_task(REPO_ROOT / ".ai" / "tasks" / "TEMPLATE.md")
    runbook = load_runbook(REPO_ROOT / ".ai" / "runbooks" / "default.md")
    gate_set = load_gate_set(REPO_ROOT / ".ai" / "gates" / "default.yaml")
    policy = load_policy(REPO_ROOT / ".ai" / "policies" / "repo-policy.md")

    assert task.slug == "example-aiwf-task"
    assert task.runbook == "default"
    assert [stage.name for stage in runbook.stages] == ["discover", "plan", "implement", "review"]
    assert [gate.name for gate in gate_set.gates] == ["lint", "typecheck", "test"]
    assert "aiwf" in policy.lower()


def test_load_task_missing_file_raises_load_error(tmp_path: Path) -> None:
    with pytest.raises(LoadError) as exc_info:
        load_task(tmp_path / "missing.md")

    assert "path=" in str(exc_info.value)
    assert "stage=load_task" in str(exc_info.value)


def test_load_gate_set_invalid_yaml_raises_load_error(tmp_path: Path) -> None:
    gate_path = tmp_path / "broken.yaml"
    gate_path.write_text("gates: [\n", encoding="utf-8")

    with pytest.raises(LoadError) as exc_info:
        load_gate_set(gate_path)

    assert "path=" in str(exc_info.value)
    assert "stage=load_gate_set" in str(exc_info.value)
