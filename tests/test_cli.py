from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from aiwf.cli import app
from aiwf.adapters.base import HostCapabilities, HostContract, ReviewArtifactContract
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
            "rp",
            "--auto",
        ],
    )

    assert result.exit_code == 1
    assert "does not support auto mode" in result.stdout


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
    assert "host=adapter=claude mode=manual" in inspect_result.stdout
    assert "next_actions:" in inspect_result.stdout
    assert "artifacts:" in inspect_result.stdout
    assert "claude-implement-prompt.md" in inspect_result.stdout
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
    assert "review_evidence=mode=manual" in inspect_result.stdout
    assert "review_links:" in inspect_result.stdout
    assert "claude-review-prompt.md" in inspect_result.stdout


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
