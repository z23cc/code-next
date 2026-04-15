from __future__ import annotations

import json
import sys
from pathlib import Path

from aiwf.adapters.stub import StubRunnerAdapter
from aiwf.engine import WorkflowEngine
from aiwf.models import RunStatus
from aiwf.state import RunStateManager


def test_phase_one_end_to_end_artifact_contract_and_resume(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_workspace(tmp_path, gate_command=_python_exit_command(1))
    engine = WorkflowEngine(
        StubRunnerAdapter(),
        ai_root=ai_root,
        repo_root=repo_root,
    )

    plan_run_id = engine.run_plan(task_path)
    plan_run_dir = ai_root / "runs" / plan_run_id
    plan_meta = RunStateManager(ai_root).load_run(plan_run_id)

    assert plan_meta.status is RunStatus.passed
    assert (plan_run_dir / "run.json").exists()
    assert (plan_run_dir / "events.ndjson").exists()
    assert (plan_run_dir / "context-pack.md").exists()
    assert (plan_run_dir / "exec-plan.md").exists()
    assert (plan_run_dir / "work-receipt.json").exists()

    implement_run_id = engine.run_implement(task_path)
    implement_run_dir = ai_root / "runs" / implement_run_id
    failed_meta = RunStateManager(ai_root).load_run(implement_run_id)
    failed_verify_report = json.loads((implement_run_dir / "verify-report.json").read_text(encoding="utf-8"))

    assert failed_meta.status is RunStatus.failed
    assert failed_verify_report["passed"] is False
    assert (implement_run_dir / "events.ndjson").exists()
    assert (implement_run_dir / "work-receipt.json").exists()

    (ai_root / "gates" / "default.yaml").write_text(
        _gates_yaml(_python_print_command("gate-fixed")),
        encoding="utf-8",
    )
    resumed_run_id = engine.resume(implement_run_id)
    resumed_meta = RunStateManager(ai_root).load_run(resumed_run_id)
    receipt = json.loads((implement_run_dir / "work-receipt.json").read_text(encoding="utf-8"))

    assert resumed_run_id == implement_run_id
    assert resumed_meta.status is RunStatus.passed
    assert (implement_run_dir / "review-report.json").exists()
    assert receipt["status"] == "passed"


def _create_workspace(
    tmp_path: Path,
    *,
    gate_command: str,
) -> tuple[Path, Path, Path]:
    repo_root = tmp_path / "repo"
    ai_root = repo_root / ".ai"
    (ai_root / "tasks").mkdir(parents=True)
    (ai_root / "runbooks").mkdir()
    (ai_root / "gates").mkdir()
    (ai_root / "policies").mkdir()

    task_path = ai_root / "tasks" / "integration-task.md"
    task_path.write_text(
        "\n".join(
            [
                "---",
                "title: Integration Task",
                "slug: integration-task",
                "runbook: default",
                "gates: default",
                "policy: repo-policy",
                "---",
                "",
                "# Goal",
                "",
                "Exercise the full Phase 1 workflow.",
            ]
        ),
        encoding="utf-8",
    )
    (ai_root / "runbooks" / "default.md").write_text(
        "\n".join(
            [
                "---",
                "name: default",
                "description: integration runbook",
                "stages:",
                "  - name: discover",
                "  - name: plan",
                "  - name: implement",
                "  - name: review",
                "---",
                "",
                "# Integration Runbook",
            ]
        ),
        encoding="utf-8",
    )
    (ai_root / "policies" / "repo-policy.md").write_text(
        "# Policy\n\nKeep workflow artifacts auditable.\n",
        encoding="utf-8",
    )
    (ai_root / "gates" / "default.yaml").write_text(_gates_yaml(gate_command), encoding="utf-8")
    return task_path, ai_root, repo_root


def _gates_yaml(command: str) -> str:
    escaped_command = command.replace("'", "''")
    return "\n".join(
        [
            "name: default",
            "description: integration gates",
            "gates:",
            "  - name: check",
            f"    command: '{escaped_command}'",
            "    timeout_seconds: 30",
        ]
    )


def _python_print_command(message: str) -> str:
    return f"{sys.executable} -c \"print('{message}')\""


def _python_exit_command(code: int) -> str:
    return f"{sys.executable} -c \"import sys; sys.exit({code})\""
