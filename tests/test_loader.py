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
    assert all(stage.required is True for stage in runbook.stages)
    assert all(stage.retry_limit == 0 for stage in runbook.stages)
    assert all(stage.pause_on == [] for stage in runbook.stages)
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


def test_load_runbook_accepts_minimal_strategy_fields(tmp_path: Path) -> None:
    runbook_path = tmp_path / "strategy.md"
    runbook_path.write_text(
        "\n".join(
            [
                "---",
                "name: strategy",
                "stages:",
                "  - name: discover",
                "    pause_on:",
                "      - blocked",
                "  - name: review",
                "    required: false",
                "    retry_limit: 1",
                "    pause_on:",
                "      - needs_review",
                "---",
                "",
                "# Strategy Runbook",
            ]
        ),
        encoding="utf-8",
    )

    runbook = load_runbook(runbook_path)

    assert runbook.stages[0].pause_on == ["blocked"]
    assert runbook.stages[1].required is False
    assert runbook.stages[1].retry_limit == 1
    assert runbook.stages[1].pause_on == ["needs_review"]


def test_load_runbook_rejects_invalid_strategy_fields(tmp_path: Path) -> None:
    runbook_path = tmp_path / "invalid-strategy.md"
    runbook_path.write_text(
        "\n".join(
            [
                "---",
                "name: invalid-strategy",
                "stages:",
                "  - name: plan",
                "    retry_limit: -1",
                "  - name: plan",
                "---",
                "",
                "# Invalid Strategy Runbook",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(LoadError) as exc_info:
        load_runbook(runbook_path)

    assert "stage=load_runbook" in str(exc_info.value)
