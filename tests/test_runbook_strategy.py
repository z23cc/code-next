from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from aiwf.adapters.claude_code import ClaudeCodeAdapter
from aiwf.adapters.stub import StubRunnerAdapter
from aiwf.engine import WorkflowEngine
from aiwf.exceptions import StateError
from aiwf.models import RunStatus
from aiwf.state import RunStateManager


def test_runbook_strategy_explicit_default_boundaries_preserve_manual_review_flow(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(
        tmp_path,
        runbook_name="explicit-default",
        stage_blocks={
            "discover": ["required: true"],
            "plan": ["required: true"],
            "implement": ["required: true", "pause_on:", "  - blocked", "  - needs_review"],
            "review": ["required: true", "pause_on:", "  - blocked"],
        },
    )
    engine = WorkflowEngine(
        ClaudeCodeAdapter(repo_root=repo_root, auto=False),
        ai_root=ai_root,
        repo_root=repo_root,
    )

    run_id = engine.run_implement(task_path)
    meta = RunStateManager(ai_root).load_run(run_id)
    assert meta.status is RunStatus.blocked
    assert meta.last_completed_stage == "implement"

    engine.resume(run_id)
    meta = RunStateManager(ai_root).load_run(run_id)
    assert meta.status is RunStatus.needs_review
    assert meta.last_completed_stage == "gates"

    engine.run_review(run_id)
    meta = RunStateManager(ai_root).load_run(run_id)
    assert meta.status is RunStatus.blocked
    assert meta.last_completed_stage == "review"

    engine.resume(run_id)
    final_meta = RunStateManager(ai_root).load_run(run_id)
    assert final_meta.status is RunStatus.passed
    assert final_meta.last_completed_stage == "review"


def test_runbook_strategy_optional_review_skips_review_stage(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(
        tmp_path,
        runbook_name="skip-review",
        stage_blocks={
            "review": ["required: false"],
        },
    )
    engine = WorkflowEngine(StubRunnerAdapter(), ai_root=ai_root, repo_root=repo_root)

    run_id = engine.run_implement(task_path)
    run_dir = ai_root / "runs" / run_id
    meta = RunStateManager(ai_root).load_run(run_id)
    receipt = json.loads((run_dir / "work-receipt.json").read_text(encoding="utf-8"))

    assert meta.status is RunStatus.passed
    assert meta.last_completed_stage == "gates"
    assert receipt["status"] == "passed"
    assert "Review stage skipped by runbook strategy." in receipt["notes"]
    assert (run_dir / "verify-report.json").exists()
    assert not (run_dir / "review-report.json").exists()


def test_runbook_strategy_implement_retry_limit_retries_gate_verification(tmp_path: Path) -> None:
    counter_path = tmp_path / "gate-counter.txt"
    gate_command = (
        f"{sys.executable} -c "
        f"\"from pathlib import Path; path = Path(r'{counter_path}'); "
        "count = int(path.read_text() if path.exists() else '0') + 1; "
        "path.write_text(str(count)); "
        "raise SystemExit(0 if count >= 2 else 1)\""
    )
    task_path, ai_root, repo_root = _create_ai_workspace(
        tmp_path,
        runbook_name="retry-gates",
        gate_command=gate_command,
        stage_blocks={
            "implement": ["retry_limit: 1"],
        },
    )
    engine = WorkflowEngine(StubRunnerAdapter(), ai_root=ai_root, repo_root=repo_root)

    run_id = engine.run_implement(task_path)
    run_dir = ai_root / "runs" / run_id
    meta = RunStateManager(ai_root).load_run(run_id)
    verify_report = json.loads((run_dir / "verify-report.json").read_text(encoding="utf-8"))

    assert meta.status is RunStatus.passed
    assert counter_path.read_text(encoding="utf-8") == "2"
    assert verify_report["passed"] is True


def test_runbook_strategy_rejects_unsupported_configuration_early(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(
        tmp_path,
        runbook_name="invalid-strategy",
        stage_blocks={
            "plan": ["required: false"],
        },
    )
    engine = WorkflowEngine(StubRunnerAdapter(), ai_root=ai_root, repo_root=repo_root)

    with pytest.raises(StateError, match="cannot be optional"):
        engine.run_implement(task_path)

    runs_dir = ai_root / "runs"
    assert not runs_dir.exists() or not any(runs_dir.iterdir())


def test_runbook_strategy_rejects_disallowed_runtime_pause_boundary(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(
        tmp_path,
        runbook_name="disallow-implement-block",
        stage_blocks={
            "implement": ["pause_on:", "  - needs_review"],
        },
    )
    engine = WorkflowEngine(
        ClaudeCodeAdapter(repo_root=repo_root, auto=False),
        ai_root=ai_root,
        repo_root=repo_root,
    )

    with pytest.raises(StateError, match="does not allow 'blocked' pause at stage 'implement'"):
        engine.run_implement(task_path)


def _create_ai_workspace(
    tmp_path: Path,
    *,
    runbook_name: str,
    gate_command: str | None = None,
    stage_blocks: dict[str, list[str]] | None = None,
) -> tuple[Path, Path, Path]:
    repo_root = tmp_path / "repo"
    ai_root = repo_root / ".ai"
    (ai_root / "tasks").mkdir(parents=True)
    (ai_root / "runbooks").mkdir()
    (ai_root / "gates").mkdir()
    (ai_root / "policies").mkdir()

    task_path = ai_root / "tasks" / "sample.md"
    task_path.write_text(
        "\n".join(
            [
                "---",
                "title: Strategy Task",
                "slug: strategy-task",
                f"runbook: {runbook_name}",
                "gates: default",
                "policy: repo-policy",
                "---",
                "",
                "# Goal",
                "",
                "Exercise minimal runbook strategy behavior.",
            ]
        ),
        encoding="utf-8",
    )
    (ai_root / "runbooks" / f"{runbook_name}.md").write_text(
        _runbook_yaml(runbook_name, stage_blocks=stage_blocks or {}),
        encoding="utf-8",
    )
    (ai_root / "policies" / "repo-policy.md").write_text(
        "# Policy\n\nUse strategy-aware orchestration for tests.\n",
        encoding="utf-8",
    )
    (ai_root / "gates" / "default.yaml").write_text(
        _gates_yaml(gate_command or _python_print_command("gate-pass")),
        encoding="utf-8",
    )
    return task_path, ai_root, repo_root


def _runbook_yaml(runbook_name: str, *, stage_blocks: dict[str, list[str]]) -> str:
    stage_names = ["discover", "plan", "implement", "review"]
    lines = [
        "---",
        f"name: {runbook_name}",
        "description: strategy test runbook",
        "stages:",
    ]
    for stage_name in stage_names:
        lines.append(f"  - name: {stage_name}")
        for extra_line in stage_blocks.get(stage_name, []):
            lines.append(f"    {extra_line}")
    lines.extend(["---", "", "# Runbook"])
    return "\n".join(lines)


def _gates_yaml(command: str) -> str:
    escaped_command = command.replace("'", "''")
    return "\n".join(
        [
            "name: default",
            "description: test gates",
            "gates:",
            "  - name: check",
            f"    command: '{escaped_command}'",
            "    timeout_seconds: 30",
        ]
    )


def _python_print_command(message: str) -> str:
    return f"{sys.executable} -c \"print('{message}')\""
