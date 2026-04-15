from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

from aiwf.adapters.base import HostCapabilities, HostContract, ReviewArtifactContract
from aiwf.adapters.claude_code import ClaudeCodeAdapter
from aiwf.cli import app
from aiwf.engine import WorkflowEngine
from aiwf.models import RunStatus, TaskSpec
from aiwf.state import RunStateManager


runner = CliRunner()


def test_cli_run_plan_command_succeeds(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)

    result = runner.invoke(
        app,
        [
            "run",
            "plan",
            "--task",
            str(task_path),
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
            "--adapter",
            "stub",
        ],
    )

    assert result.exit_code == 0
    assert "plan completed" in result.stdout
    assert any((ai_root / "runs").iterdir())


def test_cli_run_implement_command_succeeds(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)

    result = runner.invoke(
        app,
        [
            "run",
            "implement",
            "--task",
            str(task_path),
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
            "--adapter",
            "stub",
        ],
    )

    assert result.exit_code == 0
    assert "implement completed" in result.stdout


def test_cli_run_review_command_uses_existing_run(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)

    implement_result = runner.invoke(
        app,
        [
            "run",
            "implement",
            "--task",
            str(task_path),
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )
    assert implement_result.exit_code == 0
    run_id = next((ai_root / "runs").iterdir()).name

    gates_result = runner.invoke(
        app,
        [
            "resume",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )
    assert gates_result.exit_code == 0
    assert "status=needs_review" in gates_result.stdout

    review_result = runner.invoke(
        app,
        [
            "run",
            "review",
            "--run-id",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert review_result.exit_code == 0
    assert "status=blocked" in review_result.stdout
    assert "diagnostics=" in review_result.stdout
    assert "provenance=" in review_result.stdout
    assert (ai_root / "runs" / run_id / "review-report.json").exists()
    assert (ai_root / "runs" / run_id / "claude-review-prompt.md").exists()


def test_cli_resume_command_succeeds_after_gate_fix(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path, gate_command=_python_exit_command(1))
    implement_result = runner.invoke(
        app,
        [
            "run",
            "implement",
            "--task",
            str(task_path),
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
            "--adapter",
            "stub",
        ],
    )

    assert implement_result.exit_code == 1
    run_id = next((ai_root / "runs").iterdir()).name

    (ai_root / "gates" / "default.yaml").write_text(
        _gates_yaml(_python_print_command("fixed")),
        encoding="utf-8",
    )
    resume_result = runner.invoke(
        app,
        [
            "resume",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert resume_result.exit_code == 0
    assert "resume completed" in resume_result.stdout


def test_cli_resume_uses_stored_adapter_when_not_provided(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path, gate_command=_python_exit_command(1))
    implement_result = runner.invoke(
        app,
        [
            "run",
            "implement",
            "--task",
            str(task_path),
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
            "--adapter",
            "stub",
        ],
    )

    assert implement_result.exit_code == 1
    run_id = next((ai_root / "runs").iterdir()).name
    (ai_root / "gates" / "default.yaml").write_text(
        _gates_yaml(_python_print_command("fixed")),
        encoding="utf-8",
    )

    resume_result = runner.invoke(
        app,
        [
            "resume",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert resume_result.exit_code == 0
    assert "resume completed" in resume_result.stdout


def test_cli_defaults_to_claude_adapter_for_plan(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)

    result = runner.invoke(
        app,
        [
            "run",
            "plan",
            "--task",
            str(task_path),
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert result.exit_code == 0
    run_id = next((ai_root / "runs").iterdir()).name
    meta = RunStateManager(ai_root).load_run(run_id)
    plan_text = (ai_root / "runs" / run_id / "exec-plan.md").read_text(encoding="utf-8")

    assert meta.data["host_contract"]["adapter"] == "claude"
    assert meta.data["host_contract"]["mode"] == "manual"
    assert "Claude Code Plan" in plan_text


def test_cli_resume_uses_stored_claude_adapter_when_not_provided(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path, gate_command=_python_exit_command(1))
    implement_result = runner.invoke(
        app,
        [
            "run",
            "implement",
            "--task",
            str(task_path),
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert implement_result.exit_code == 0
    assert "status=blocked" in implement_result.stdout
    assert "reason=Run is blocked at implement" in implement_result.stdout
    assert "inspect=uv run aiwf inspect" in implement_result.stdout
    run_id = next((ai_root / "runs").iterdir()).name
    meta = RunStateManager(ai_root).load_run(run_id)
    assert meta.data["host_contract"]["adapter"] == "claude"
    assert meta.data["host_contract"]["mode"] == "manual"
    assert meta.status.value == "blocked"

    (ai_root / "gates" / "default.yaml").write_text(
        _gates_yaml(_python_print_command("fixed")),
        encoding="utf-8",
    )

    resume_result = runner.invoke(
        app,
        [
            "resume",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert resume_result.exit_code == 0
    assert "status=needs_review" in resume_result.stdout
    assert "diagnostics=" in resume_result.stdout
    review_result = runner.invoke(
        app,
        [
            "run",
            "review",
            "--run-id",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert review_result.exit_code == 0
    assert "status=blocked" in review_result.stdout
    assert "provenance=" in review_result.stdout

    final_resume = runner.invoke(
        app,
        [
            "resume",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert final_resume.exit_code == 0
    assert "resume completed" in final_resume.stdout
    resumed_meta = RunStateManager(ai_root).load_run(run_id)
    assert resumed_meta.status.value == "passed"
    assert (ai_root / "runs" / run_id / "review-report.json").exists()


def test_cli_rp_adapter_manual_handoff_flow_uses_stored_metadata(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)

    implement_result = runner.invoke(
        app,
        [
            "run",
            "implement",
            "--task",
            str(task_path),
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
            "--adapter",
            "rp",
        ],
    )

    assert implement_result.exit_code == 0
    assert "status=blocked" in implement_result.stdout
    assert "inspect=uv run aiwf inspect" in implement_result.stdout
    run_id = next((ai_root / "runs").iterdir()).name
    meta = RunStateManager(ai_root).load_run(run_id)
    assert meta.data["host_contract"]["adapter"] == "rp"
    assert meta.data["host_contract"]["mode"] == "manual"
    assert (ai_root / "runs" / run_id / "rp-agent-implement-prompt.md").exists()

    resume_result = runner.invoke(
        app,
        [
            "resume",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert resume_result.exit_code == 0
    assert "status=needs_review" in resume_result.stdout

    review_result = runner.invoke(
        app,
        [
            "run",
            "review",
            "--run-id",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert review_result.exit_code == 0
    assert "status=blocked" in review_result.stdout
    assert "inspect=uv run aiwf inspect" in review_result.stdout
    assert (ai_root / "runs" / run_id / "rp-agent-review-prompt.md").exists()

    final_resume = runner.invoke(
        app,
        [
            "resume",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert final_resume.exit_code == 0
    assert "resume completed" in final_resume.stdout
    resumed_meta = RunStateManager(ai_root).load_run(run_id)
    assert resumed_meta.status.value == "passed"
    assert (ai_root / "runs" / run_id / "review-report.json").exists()


def test_cli_codex_adapter_manual_handoff_flow_uses_stored_metadata(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)

    implement_result = runner.invoke(
        app,
        [
            "run",
            "implement",
            "--task",
            str(task_path),
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
            "--adapter",
            "codex",
        ],
    )

    assert implement_result.exit_code == 0
    assert "status=blocked" in implement_result.stdout
    assert "inspect=uv run aiwf inspect" in implement_result.stdout
    run_id = next((ai_root / "runs").iterdir()).name
    meta = RunStateManager(ai_root).load_run(run_id)
    assert meta.data["host_contract"]["adapter"] == "codex"
    assert meta.data["host_contract"]["mode"] == "manual"
    assert meta.data["host_contract"]["review"]["linked_report_artifact_field"] == "prompt_file"
    assert (ai_root / "runs" / run_id / "codex-implement-prompt.md").exists()

    resume_result = runner.invoke(
        app,
        [
            "resume",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert resume_result.exit_code == 0
    assert "status=needs_review" in resume_result.stdout

    review_result = runner.invoke(
        app,
        [
            "run",
            "review",
            "--run-id",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert review_result.exit_code == 0
    assert "status=blocked" in review_result.stdout
    assert "inspect=uv run aiwf inspect" in review_result.stdout
    assert (ai_root / "runs" / run_id / "codex-review-prompt.md").exists()

    final_resume = runner.invoke(
        app,
        [
            "resume",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert final_resume.exit_code == 0
    assert "resume completed" in final_resume.stdout
    resumed_meta = RunStateManager(ai_root).load_run(run_id)
    assert resumed_meta.status.value == "passed"
    assert (ai_root / "runs" / run_id / "review-report.json").exists()


def test_cli_review_builds_engine_from_stored_run_metadata(tmp_path: Path, monkeypatch) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    implement_result = runner.invoke(
        app,
        [
            "run",
            "implement",
            "--task",
            str(task_path),
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )
    assert implement_result.exit_code == 0
    run_id = next((ai_root / "runs").iterdir()).name
    gates_result = runner.invoke(
        app,
        [
            "resume",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )
    assert gates_result.exit_code == 0
    state_manager = RunStateManager(ai_root)
    state_manager.update_run(
        run_id,
        data={
            "host_contract": {
                "adapter": "claude",
                "mode": "auto",
                "capabilities": {
                    "supports_auto_execution": True,
                    "requires_explicit_review_handoff": False,
                },
            }
        },
    )

    seen: list[HostContract | None] = []

    class FakeEngine:
        def run_review(self, captured_run_id: str) -> str:
            assert captured_run_id == run_id
            return captured_run_id

    def fake_build_engine(
        ai_root_arg: Path,
        repo_root_arg: Path,
        *,
        adapter_name: str | None = None,
        auto: bool = False,
        host_contract: HostContract | None = None,
    ) -> FakeEngine:
        assert ai_root_arg == ai_root
        assert repo_root_arg == repo_root
        assert adapter_name is None
        assert auto is False
        seen.append(host_contract)
        return FakeEngine()

    monkeypatch.setattr("aiwf.cli._build_engine", fake_build_engine)

    result = runner.invoke(
        app,
        [
            "run",
            "review",
            "--run-id",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert result.exit_code == 0
    assert seen == [
        HostContract(
            adapter="claude",
            mode="auto",
            capabilities=HostCapabilities(
                supports_auto_execution=True,
                requires_explicit_review_handoff=False,
            ),
            review=ReviewArtifactContract(
                required_run_artifacts=("verify-report.json",),
                required_report_string_fields=("summary", "mode", "response_file"),
                required_report_list_fields=("issues",),
                expected_report_mode="auto",
                linked_report_artifact_field="response_file",
            ),
        )
    ]


def test_cli_resume_builds_engine_from_stored_run_metadata(tmp_path: Path, monkeypatch) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    implement_result = runner.invoke(
        app,
        [
            "run",
            "implement",
            "--task",
            str(task_path),
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )
    assert implement_result.exit_code == 0
    run_id = next((ai_root / "runs").iterdir()).name
    state_manager = RunStateManager(ai_root)
    state_manager.update_run(
        run_id,
        data={
            "host_contract": {
                "adapter": "claude",
                "mode": "auto",
                "capabilities": {
                    "supports_auto_execution": True,
                    "requires_explicit_review_handoff": False,
                },
            }
        },
    )

    seen: list[HostContract | None] = []

    class FakeEngine:
        def resume(self, captured_run_id: str) -> str:
            assert captured_run_id == run_id
            return captured_run_id

    def fake_build_engine(
        ai_root_arg: Path,
        repo_root_arg: Path,
        *,
        adapter_name: str | None = None,
        auto: bool = False,
        host_contract: HostContract | None = None,
    ) -> FakeEngine:
        assert ai_root_arg == ai_root
        assert repo_root_arg == repo_root
        assert adapter_name is None
        assert auto is False
        seen.append(host_contract)
        return FakeEngine()

    monkeypatch.setattr("aiwf.cli._build_engine", fake_build_engine)

    result = runner.invoke(
        app,
        [
            "resume",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert result.exit_code == 0
    assert seen == [
        HostContract(
            adapter="claude",
            mode="auto",
            capabilities=HostCapabilities(
                supports_auto_execution=True,
                requires_explicit_review_handoff=False,
            ),
            review=ReviewArtifactContract(
                required_run_artifacts=("verify-report.json",),
                required_report_string_fields=("summary", "mode", "response_file"),
                required_report_list_fields=("issues",),
                expected_report_mode="auto",
                linked_report_artifact_field="response_file",
            ),
        )
    ]


def test_cli_rejects_auto_when_adapter_contract_does_not_support_it(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)

    result = runner.invoke(
        app,
        [
            "run",
            "plan",
            "--task",
            str(task_path),
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
            "--adapter",
            "codex",
            "--auto",
        ],
    )

    assert result.exit_code == 1
    assert "does not support auto mode" in result.stdout


def test_cli_contract_lint_command_succeeds() -> None:
    result = runner.invoke(app, ["contracts", "lint"])

    assert result.exit_code == 0
    assert "ok claude/manual" in result.stdout
    assert "ok claude/auto" in result.stdout
    assert "ok rp/manual" in result.stdout
    assert "ok stub/manual" in result.stdout
    assert "contract lint completed" in result.stdout


def test_cli_inspect_command_surfaces_diagnostics_and_provenance(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)

    implement_result = runner.invoke(
        app,
        [
            "run",
            "implement",
            "--task",
            str(task_path),
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert implement_result.exit_code == 0
    run_id = next((ai_root / "runs").iterdir()).name

    inspect_result = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--ai-root",
            str(ai_root),
        ],
    )

    assert inspect_result.exit_code == 0
    assert f"run_id={run_id}" in inspect_result.stdout
    assert "reason=Run is blocked at implement" in inspect_result.stdout
    assert "host_contract=adapter=claude mode=manual" in inspect_result.stdout
    assert "review_contract=required_run_artifacts=verify-report.json" in inspect_result.stdout
    assert "review_boundary=waiting missing_required_artifacts=verify-report.json" in inspect_result.stdout
    assert "review_evidence=not_started mode=-" in inspect_result.stdout
    assert "next_actions:" in inspect_result.stdout
    assert "diagnostics=" in inspect_result.stdout
    assert "provenance=" in inspect_result.stdout


def test_cli_inspect_command_surfaces_gate_and_review_evidence(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)

    implement_result = runner.invoke(
        app,
        [
            "run",
            "implement",
            "--task",
            str(task_path),
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert implement_result.exit_code == 0
    run_id = next((ai_root / "runs").iterdir()).name

    gates_result = runner.invoke(
        app,
        [
            "resume",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )
    assert gates_result.exit_code == 0

    review_result = runner.invoke(
        app,
        [
            "run",
            "review",
            "--run-id",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )
    assert review_result.exit_code == 0

    inspect_result = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--ai-root",
            str(ai_root),
        ],
    )

    assert inspect_result.exit_code == 0
    assert "gate_evidence=gate_set=default passed=True" in inspect_result.stdout
    assert "review_boundary=ready missing_required_artifacts=-" in inspect_result.stdout
    assert "review_evidence=complete mode=manual" in inspect_result.stdout
    assert "missing_report_fields=-" in inspect_result.stdout
    assert "missing_linked_artifacts=-" in inspect_result.stdout
    assert "review_linked_artifacts=claude-review-prompt.md" in inspect_result.stdout


def test_cli_inspect_json_surfaces_machine_readable_runtime_state(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)

    implement_result = runner.invoke(
        app,
        [
            "run",
            "implement",
            "--task",
            str(task_path),
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )
    assert implement_result.exit_code == 0
    run_id = next((ai_root / "runs").iterdir()).name

    inspect_result = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--ai-root",
            str(ai_root),
            "--json",
        ],
    )

    assert inspect_result.exit_code == 0
    payload = json.loads(inspect_result.stdout)
    assert payload["ok"] is True
    assert payload["run_id"] == run_id
    assert payload["diagnostics"]["status"] == "blocked"
    assert payload["diagnostics"]["error_code"] is None
    assert payload["diagnostics"]["host"]["adapter"] == "claude"
    assert payload["provenance"]["status"] == "blocked"
    assert payload["review_report"] is None
    assert payload["host_contract"]["adapter"] == "claude"
    assert payload["host_contract"]["mode"] == "manual"
    assert payload["review_boundary"] == {
        "ready": False,
        "missing_required_artifacts": ["verify-report.json"],
    }
    assert payload["review_evidence"] == {
        "status": "not_started",
        "mode": None,
        "missing_report_fields": [],
        "missing_linked_artifacts": [],
        "linked_artifacts": [],
        "mode_mismatch": None,
    }
    assert payload["artifacts"]["diagnostics"].endswith("run-diagnostics.json")
    assert payload["artifacts"]["provenance"].endswith("run-provenance.json")
    assert payload["artifacts"]["review_report"] is None


def test_cli_inspect_surfaces_structured_error_codes_for_failed_runs(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path, gate_command=_python_exit_command(1))

    implement_result = runner.invoke(
        app,
        [
            "run",
            "implement",
            "--task",
            str(task_path),
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )
    assert implement_result.exit_code == 0

    run_id = next((ai_root / "runs").iterdir()).name

    resume_result = runner.invoke(
        app,
        [
            "resume",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )
    assert resume_result.exit_code == 1

    inspect_result = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--ai-root",
            str(ai_root),
        ],
    )
    assert inspect_result.exit_code == 0
    assert "error_code=GATE_FAILURE" in inspect_result.stdout

    inspect_json_result = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--ai-root",
            str(ai_root),
            "--json",
        ],
    )
    assert inspect_json_result.exit_code == 0
    payload = json.loads(inspect_json_result.stdout)
    assert payload["diagnostics"]["status"] == "failed"
    assert payload["diagnostics"]["error_code"] == "GATE_FAILURE"


def test_cli_inspect_json_includes_review_report_evidence_summary_for_rp_runs(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)

    implement_result = runner.invoke(
        app,
        [
            "run",
            "implement",
            "--task",
            str(task_path),
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
            "--adapter",
            "rp",
        ],
    )
    assert implement_result.exit_code == 0
    run_id = next((ai_root / "runs").iterdir()).name

    resume_result = runner.invoke(
        app,
        [
            "resume",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )
    assert resume_result.exit_code == 0

    review_result = runner.invoke(
        app,
        [
            "run",
            "review",
            "--run-id",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )
    assert review_result.exit_code == 0

    inspect_result = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--ai-root",
            str(ai_root),
            "--json",
        ],
    )

    assert inspect_result.exit_code == 0
    payload = json.loads(inspect_result.stdout)
    assert payload["ok"] is True
    assert payload["host_contract"]["adapter"] == "rp"
    assert payload["review_report"]["prompt_file"] == "rp-agent-review-prompt.md"
    assert payload["review_report"]["evidence_summary"]["verify"].startswith("gate_set=default passed=True")
    assert payload["review_report"]["evidence_summary"]["changed_files"] == []
    assert payload["review_report"]["evidence_summary"]["diff_summary"] == []
    assert payload["review_evidence"]["status"] == "complete"
    assert payload["review_evidence"]["linked_artifacts"] == ["rp-agent-review-prompt.md"]
    assert payload["artifacts"]["review_report"].endswith("review-report.json")


def test_cli_inspect_verbose_surfaces_artifact_index_and_review_links(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)

    implement_result = runner.invoke(
        app,
        [
            "run",
            "implement",
            "--task",
            str(task_path),
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )
    assert implement_result.exit_code == 0
    run_id = next((ai_root / "runs").iterdir()).name

    gates_result = runner.invoke(
        app,
        [
            "resume",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )
    assert gates_result.exit_code == 0

    review_result = runner.invoke(
        app,
        [
            "run",
            "review",
            "--run-id",
            run_id,
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )
    assert review_result.exit_code == 0

    inspect_result = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--ai-root",
            str(ai_root),
            "--verbose",
        ],
    )

    assert inspect_result.exit_code == 0
    assert "review_links:" in inspect_result.stdout
    assert "claude-review-prompt.md" in inspect_result.stdout
    assert "artifacts:" in inspect_result.stdout


def test_cli_inspect_command_surfaces_auto_host_runtime_evidence(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    engine = WorkflowEngine(
        ClaudeCodeAdapter(
            repo_root=repo_root,
            auto=True,
            claude_command=[
                sys.executable,
                "-c",
                "import sys; print('stdin:' + ('yes' if sys.stdin.read() else 'no'))",
            ],
        ),
        ai_root=ai_root,
        repo_root=repo_root,
    )
    run_id = engine.run_implement(task_path)

    inspect_result = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--ai-root",
            str(ai_root),
        ],
    )

    assert inspect_result.exit_code == 0
    assert f"run_id={run_id}" in inspect_result.stdout
    assert "workflow=implement" in inspect_result.stdout
    assert "status=passed" in inspect_result.stdout
    assert "last_completed_stage=review" in inspect_result.stdout
    assert "host_contract=adapter=claude mode=auto" in inspect_result.stdout
    assert "review_boundary=ready missing_required_artifacts=-" in inspect_result.stdout
    assert "review_evidence=complete mode=auto" in inspect_result.stdout
    assert "review_linked_artifacts=claude-review-response.md" in inspect_result.stdout
    assert "diagnostics=" in inspect_result.stdout
    assert "provenance=" in inspect_result.stdout


def test_cli_inspect_command_fails_for_missing_run(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "inspect",
            "missing-run",
            "--ai-root",
            str(tmp_path / ".ai"),
        ],
    )

    assert result.exit_code == 1
    assert "inspect failed:" in result.stdout
    assert "missing-run" in result.stdout


def test_cli_inspect_json_reports_missing_run_errors(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "inspect",
            "missing-run",
            "--ai-root",
            str(tmp_path / ".ai"),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["run_id"] == "missing-run"
    assert "missing-run" in payload["error"]


def test_cli_list_command_shows_human_readable_columns(tmp_path: Path) -> None:
    _, ai_root, _ = _create_ai_workspace(tmp_path)
    run_id = _seed_run(ai_root, workflow="implement", status=RunStatus.passed, adapter="stub")

    result = runner.invoke(app, ["list", "--ai-root", str(ai_root), "--limit", "10"])

    assert result.exit_code == 0
    assert "run_id\tstatus\tworkflow\tadapter\tcreated_at\tlast_completed_stage" in result.stdout
    assert run_id in result.stdout
    assert "\tpassed\timplement\tstub\t" in result.stdout


def test_cli_list_command_supports_json_output_and_status_filter(tmp_path: Path) -> None:
    _, ai_root, _ = _create_ai_workspace(tmp_path)
    kept_run_id = _seed_run(ai_root, workflow="plan", status=RunStatus.passed, adapter="claude")
    _seed_run(ai_root, workflow="plan", status=RunStatus.failed, adapter="rp")

    result = runner.invoke(
        app,
        [
            "list",
            "--ai-root",
            str(ai_root),
            "--status",
            "passed",
            "--json",
            "--limit",
            "10",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert [entry["run_id"] for entry in payload] == [kept_run_id]
    assert payload[0]["status"] == "passed"
    assert payload[0]["workflow"] == "plan"
    assert payload[0]["adapter"] == "claude"


def test_cli_clean_command_dry_run_preserves_runs(tmp_path: Path) -> None:
    _, ai_root, _ = _create_ai_workspace(tmp_path)
    for _ in range(3):
        _seed_run(ai_root, workflow="implement", status=RunStatus.passed, adapter="stub")

    before = {path.name for path in (ai_root / "runs").iterdir() if path.is_dir()}

    result = runner.invoke(
        app,
        [
            "clean",
            "--ai-root",
            str(ai_root),
            "--keep",
            "1",
            "--dry-run",
        ],
    )

    after = {path.name for path in (ai_root / "runs").iterdir() if path.is_dir()}
    assert result.exit_code == 0
    assert before == after
    assert "Would delete 2 run(s)." in result.stdout


def test_cli_clean_command_uses_safe_default_statuses(tmp_path: Path) -> None:
    _, ai_root, _ = _create_ai_workspace(tmp_path)
    running_run = _seed_run(ai_root, workflow="implement", status=RunStatus.running, adapter="stub")
    blocked_run = _seed_run(ai_root, workflow="implement", status=RunStatus.blocked, adapter="stub")
    passed_run = _seed_run(ai_root, workflow="implement", status=RunStatus.passed, adapter="stub")

    result = runner.invoke(
        app,
        [
            "clean",
            "--ai-root",
            str(ai_root),
            "--keep",
            "0",
        ],
    )

    assert result.exit_code == 0
    runs_dir = ai_root / "runs"
    assert (runs_dir / running_run).exists()
    assert (runs_dir / blocked_run).exists()
    assert not (runs_dir / passed_run).exists()


def test_cli_clean_command_supports_status_and_workflow_filters(tmp_path: Path) -> None:
    _, ai_root, _ = _create_ai_workspace(tmp_path)
    failed_plan_run = _seed_run(ai_root, workflow="plan", status=RunStatus.failed, adapter="claude")
    failed_implement_run = _seed_run(ai_root, workflow="implement", status=RunStatus.failed, adapter="claude")

    result = runner.invoke(
        app,
        [
            "clean",
            "--ai-root",
            str(ai_root),
            "--status",
            "failed",
            "--workflow",
            "plan",
            "--keep",
            "0",
        ],
    )

    assert result.exit_code == 0
    runs_dir = ai_root / "runs"
    assert not (runs_dir / failed_plan_run).exists()
    assert (runs_dir / failed_implement_run).exists()


def _seed_run(
    ai_root: Path,
    *,
    workflow: str,
    status: RunStatus,
    adapter: str,
) -> str:
    state = RunStateManager(ai_root)
    run_id = state.init_run(
        TaskSpec(
            title=f"{workflow} {status.value}",
            runbook="default",
            gates="default",
            policy="repo-policy",
        )
    )

    if status != RunStatus.queued:
        state.transition(run_id, RunStatus.running, stage="discover")
        if status != RunStatus.running:
            state.transition(run_id, status, stage="review")

    state.update_run(
        run_id,
        last_completed_stage="review",
        data={
            "workflow": workflow,
            "host_contract": {
                "adapter": adapter,
                "mode": "manual",
            },
        },
    )
    return run_id


def _create_ai_workspace(
    tmp_path: Path,
    *,
    gate_command: str | None = None,
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
                "title: Sample Task",
                "slug: sample-task",
                "runbook: default",
                "gates: default",
                "policy: repo-policy",
                "---",
                "",
                "# Goal",
                "",
                "Exercise the CLI workflow.",
            ]
        ),
        encoding="utf-8",
    )
    (ai_root / "runbooks" / "default.md").write_text(
        "\n".join(
            [
                "---",
                "name: default",
                "description: default runbook",
                "stages:",
                "  - name: discover",
                "  - name: plan",
                "  - name: implement",
                "  - name: review",
                "---",
                "",
                "# Runbook",
            ]
        ),
        encoding="utf-8",
    )
    (ai_root / "policies" / "repo-policy.md").write_text(
        "# Policy\n\nUse stub orchestration for tests.\n",
        encoding="utf-8",
    )
    (ai_root / "gates" / "default.yaml").write_text(
        _gates_yaml(gate_command or _python_print_command("gate-pass")),
        encoding="utf-8",
    )
    return task_path, ai_root, repo_root


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
    import sys

    return f"{sys.executable} -c \"print('{message}')\""


def _python_exit_command(code: int) -> str:
    import sys

    return f"{sys.executable} -c \"import sys; sys.exit({code})\""
