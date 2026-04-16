from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

from typer.testing import CliRunner

from aiwf.adapters.base import HostCapabilities, HostContract, ReviewArtifactContract
from aiwf.adapters.claude_code import ClaudeCodeAdapter
from aiwf.adapters.rp_agent import RpAgentAdapter
from aiwf.cli import app
from aiwf.engine import WorkflowEngine
from aiwf.exceptions import ErrorCode
from aiwf.models import RpBridgeRunConfig, RunStatus, TaskSpec
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


def test_cli_rp_bridge_plan_command_persists_bridge_metadata(tmp_path: Path) -> None:
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
            "--bridge",
            "--bridge-workspace",
            "workspace-alpha",
        ],
    )

    assert result.exit_code == 0
    run_id = next((ai_root / "runs").iterdir()).name
    meta = RunStateManager(ai_root).load_run(run_id)
    assert meta.data["host_contract"]["adapter"] == "rp"
    assert meta.data["rp_bridge"] == {
        "mode": "manual-assist",
        "workspace": "workspace-alpha",
        "tab": None,
        "context_id": None,
        "agent_role": None,
        "timeout_seconds": None,
        "export_transcript": False,
    }


def test_cli_rp_bridge_manual_handoff_flow_uses_stored_metadata(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    bridge_payload = {
        "mode": "manual-assist",
        "workspace": "workspace-alpha",
        "tab": "implement-tab",
        "context_id": "ctx-123",
        "agent_role": "implementer",
        "timeout_seconds": 900,
        "export_transcript": True,
    }

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
            "--bridge",
            "--bridge-workspace",
            "workspace-alpha",
            "--bridge-tab",
            "implement-tab",
            "--bridge-context-id",
            "ctx-123",
            "--bridge-agent-role",
            "implementer",
            "--bridge-timeout",
            "900",
            "--bridge-export-transcript",
        ],
    )

    assert implement_result.exit_code == 0
    run_id = next((ai_root / "runs").iterdir()).name
    meta = RunStateManager(ai_root).load_run(run_id)
    assert meta.data["rp_bridge"] == bridge_payload
    assert "RepoPrompt Bridge Context" in (ai_root / "runs" / run_id / "rp-agent-implement-prompt.md").read_text(encoding="utf-8")

    blocked_inspect_result = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--ai-root",
            str(ai_root),
        ],
    )
    assert blocked_inspect_result.exit_code == 0
    assert "bridge=mode=manual-assist" in blocked_inspect_result.stdout
    assert "workspace=workspace-alpha" in blocked_inspect_result.stdout
    assert "tab=implement-tab" in blocked_inspect_result.stdout
    assert "context_id=ctx-123" in blocked_inspect_result.stdout
    assert "agent_role=implementer" in blocked_inspect_result.stdout
    assert "bridge_summary=RepoPrompt manual-assist is active for implement;" in blocked_inspect_result.stdout
    assert "bridge_handoff_artifacts=rp-agent-implement-prompt.md" in blocked_inspect_result.stdout
    assert "Open or reuse a RepoPrompt session with workspace=workspace-alpha" in blocked_inspect_result.stdout
    assert "implementation handoff" in blocked_inspect_result.stdout

    blocked_inspect_json_result = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--ai-root",
            str(ai_root),
            "--json",
        ],
    )
    assert blocked_inspect_json_result.exit_code == 0
    blocked_inspect_payload = json.loads(blocked_inspect_json_result.stdout)
    assert blocked_inspect_payload["rp_bridge"] == bridge_payload
    assert blocked_inspect_payload["diagnostics"]["bridge"]["mode"] == "manual-assist"
    assert blocked_inspect_payload["diagnostics"]["bridge"]["workspace"] == "workspace-alpha"
    assert blocked_inspect_payload["diagnostics"]["bridge"]["tab"] == "implement-tab"
    assert blocked_inspect_payload["diagnostics"]["bridge"]["context_id"] == "ctx-123"
    assert blocked_inspect_payload["diagnostics"]["bridge"]["agent_role"] == "implementer"
    assert blocked_inspect_payload["diagnostics"]["bridge"]["timeout_seconds"] == 900
    assert blocked_inspect_payload["diagnostics"]["bridge"]["export_transcript"] is True
    assert blocked_inspect_payload["diagnostics"]["bridge"]["handoff_artifacts"] == ["rp-agent-implement-prompt.md"]
    assert blocked_inspect_payload["diagnostics"]["bridge"]["seeding_artifact"] == "rp-bridge-seeding.json"
    assert blocked_inspect_payload["diagnostics"]["bridge"]["seeding_status"] in {"skipped", "failed"}

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
    needs_review_payload = json.loads(
        runner.invoke(
            app,
            [
                "inspect",
                run_id,
                "--ai-root",
                str(ai_root),
                "--json",
            ],
        ).stdout
    )
    assert needs_review_payload["diagnostics"]["bridge"]["summary"] == (
        "RepoPrompt manual-assist metadata is persisted from implement and will be restored into the review "
        "handoff prompt when review starts."
    )

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
    assert "RepoPrompt Bridge Context" in (ai_root / "runs" / run_id / "rp-agent-review-prompt.md").read_text(encoding="utf-8")

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
    assert "bridge=mode=manual-assist" in inspect_result.stdout
    assert "workspace=workspace-alpha" in inspect_result.stdout
    assert "tab=implement-tab" in inspect_result.stdout
    assert "context_id=ctx-123" in inspect_result.stdout
    assert "agent_role=implementer" in inspect_result.stdout
    assert "bridge_summary=RepoPrompt manual-assist is active for review;" in inspect_result.stdout
    assert "bridge_handoff_artifacts=rp-agent-review-prompt.md" in inspect_result.stdout

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
    inspect_payload = json.loads(inspect_json_result.stdout)
    assert inspect_payload["rp_bridge"] == bridge_payload
    assert inspect_payload["diagnostics"]["bridge"]["handoff_artifacts"] == ["rp-agent-review-prompt.md"]
    assert inspect_payload["review_report"]["bridge"] == bridge_payload

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
    resumed_meta = RunStateManager(ai_root).load_run(run_id)
    assert resumed_meta.status.value == "passed"
    assert resumed_meta.data["rp_bridge"] == bridge_payload


def test_cli_inspect_surfaces_bridge_seeding_artifact_and_status(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    fake_cli = _write_fake_rp_bridge_cli(tmp_path, mode="seed-ok")
    bridge_config = RpBridgeRunConfig(mode="manual-assist", workspace="workspace-alpha", context_id="ctx-123")
    engine = WorkflowEngine(
        RpAgentAdapter(repo_root=repo_root, bridge_config=bridge_config, rp_command=[str(fake_cli)]),
        ai_root=ai_root,
        repo_root=repo_root,
        bridge_config=bridge_config,
    )

    run_id = engine.run_implement(task_path)

    inspect_result = runner.invoke(app, ["inspect", run_id, "--ai-root", str(ai_root)])

    assert inspect_result.exit_code == 0
    assert "bridge_seeding_artifact=rp-bridge-seeding.json" in inspect_result.stdout
    assert "bridge_seeding_status=seeded" in inspect_result.stdout
    assert "bridge_seeding_summary=Bridge context seeding prepared the aiwf run artifacts" in inspect_result.stdout
    assert "bridge_seeding=" in inspect_result.stdout

    inspect_json_result = runner.invoke(app, ["inspect", run_id, "--ai-root", str(ai_root), "--json"])

    assert inspect_json_result.exit_code == 0
    payload = json.loads(inspect_json_result.stdout)
    assert payload["bridge_seeding"]["status"] == "seeded"
    assert payload["diagnostics"]["bridge"]["seeding_status"] == "seeded"
    assert payload["artifacts"]["bridge_seeding"].endswith("rp-bridge-seeding.json")



def test_cli_inspect_surfaces_bridge_seeding_failure_without_breaking_manual_handoff(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    fake_cli = _write_fake_rp_bridge_cli(tmp_path, mode="seed-manage-fail")
    bridge_config = RpBridgeRunConfig(mode="manual-assist", workspace="workspace-alpha")
    engine = WorkflowEngine(
        RpAgentAdapter(repo_root=repo_root, bridge_config=bridge_config, rp_command=[str(fake_cli)]),
        ai_root=ai_root,
        repo_root=repo_root,
        bridge_config=bridge_config,
    )

    run_id = engine.run_implement(task_path)

    inspect_json_result = runner.invoke(app, ["inspect", run_id, "--ai-root", str(ai_root), "--json"])

    assert inspect_json_result.exit_code == 0
    payload = json.loads(inspect_json_result.stdout)
    assert payload["bridge_seeding"]["status"] == "failed"
    assert payload["diagnostics"]["bridge"]["seeding_status"] == "failed"
    assert "manually add context-pack.md and exec-plan.md" in payload["diagnostics"]["next_actions"][0]



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

    seen: list[tuple[HostContract | None, RpBridgeRunConfig | None]] = []

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
        bridge_config: RpBridgeRunConfig | None = None,
    ) -> FakeEngine:
        assert ai_root_arg == ai_root
        assert repo_root_arg == repo_root
        assert adapter_name is None
        assert auto is False
        seen.append((host_contract, bridge_config))
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
        (
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
            ),
            None,
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

    seen: list[tuple[HostContract | None, RpBridgeRunConfig | None]] = []

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
        bridge_config: RpBridgeRunConfig | None = None,
    ) -> FakeEngine:
        assert ai_root_arg == ai_root
        assert repo_root_arg == repo_root
        assert adapter_name is None
        assert auto is False
        seen.append((host_contract, bridge_config))
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
        (
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
            ),
            None,
        )
    ]


def test_cli_rejects_bridge_when_adapter_is_not_rp(tmp_path: Path) -> None:
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
            "claude",
            "--bridge",
        ],
    )

    assert result.exit_code == 1
    assert "supported with --adapter rp" in result.stdout


def test_cli_rejects_bridge_when_auto_mode_is_requested(tmp_path: Path) -> None:
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
            "rp",
            "--auto",
            "--bridge",
        ],
    )

    assert result.exit_code == 1
    assert "only supported with RP manual mode" in result.stdout


def test_cli_rejects_unsupported_bridge_mode(tmp_path: Path) -> None:
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
            "--bridge",
            "--bridge-mode",
            "managed-agent",
        ],
    )

    assert result.exit_code == 1
    assert "not supported in this slice" in result.stdout


def test_cli_review_builds_engine_from_stored_bridge_metadata(tmp_path: Path, monkeypatch) -> None:
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
    state_manager = RunStateManager(ai_root)
    state_manager.update_run(
        run_id,
        data={
            "host_contract": {
                "adapter": "rp",
                "mode": "manual",
                "capabilities": {
                    "supports_auto_execution": False,
                    "requires_explicit_review_handoff": True,
                },
            },
            "rp_bridge": {
                "mode": "manual-assist",
                "workspace": "workspace-alpha",
                "tab": "implement-tab",
                "context_id": "ctx-123",
                "agent_role": "implementer",
                "timeout_seconds": 900,
                "export_transcript": True,
            },
        },
    )

    seen: list[tuple[HostContract | None, RpBridgeRunConfig | None]] = []

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
        bridge_config: RpBridgeRunConfig | None = None,
    ) -> FakeEngine:
        assert ai_root_arg == ai_root
        assert repo_root_arg == repo_root
        assert adapter_name is None
        assert auto is False
        seen.append((host_contract, bridge_config))
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
    assert len(seen) == 1
    seen_host_contract, seen_bridge_config = seen[0]
    assert seen_host_contract is not None
    assert seen_host_contract.adapter == "rp"
    assert seen_host_contract.mode == "manual"
    assert seen_host_contract.review.linked_report_artifact_field == "prompt_file"
    assert seen_host_contract.bridge.enabled is True
    assert seen_bridge_config == RpBridgeRunConfig(
        mode="manual-assist",
        workspace="workspace-alpha",
        tab="implement-tab",
        context_id="ctx-123",
        agent_role="implementer",
        timeout_seconds=900,
        export_transcript=True,
    )


def test_cli_resume_builds_engine_from_stored_bridge_metadata(tmp_path: Path, monkeypatch) -> None:
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
    state_manager = RunStateManager(ai_root)
    state_manager.update_run(
        run_id,
        data={
            "host_contract": {
                "adapter": "rp",
                "mode": "manual",
                "capabilities": {
                    "supports_auto_execution": False,
                    "requires_explicit_review_handoff": True,
                },
            },
            "rp_bridge": {
                "mode": "manual-assist",
                "workspace": "workspace-alpha",
                "tab": "implement-tab",
                "context_id": "ctx-123",
                "agent_role": "implementer",
                "timeout_seconds": 900,
                "export_transcript": True,
            },
        },
    )

    seen: list[tuple[HostContract | None, RpBridgeRunConfig | None]] = []

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
        bridge_config: RpBridgeRunConfig | None = None,
    ) -> FakeEngine:
        assert ai_root_arg == ai_root
        assert repo_root_arg == repo_root
        assert adapter_name is None
        assert auto is False
        seen.append((host_contract, bridge_config))
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
    assert len(seen) == 1
    seen_host_contract, seen_bridge_config = seen[0]
    assert seen_host_contract is not None
    assert seen_host_contract.adapter == "rp"
    assert seen_host_contract.mode == "manual"
    assert seen_host_contract.review.linked_report_artifact_field == "prompt_file"
    assert seen_host_contract.bridge.enabled is True
    assert seen_bridge_config == RpBridgeRunConfig(
        mode="manual-assist",
        workspace="workspace-alpha",
        tab="implement-tab",
        context_id="ctx-123",
        agent_role="implementer",
        timeout_seconds=900,
        export_transcript=True,
    )


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


def test_cli_run_plan_help_marks_stub_internal_and_rp_auto_experimental() -> None:
    result = runner.invoke(app, ["run", "plan", "--help"])

    assert result.exit_code == 0
    assert "internal/test-only" in result.stdout
    assert "--auto" in result.stdout
    assert "experimental" in result.stdout
    assert "--bridge" in result.stdout
    assert "--bridge-workspace" in result.stdout


def test_cli_conformance_rp_help_targets_real_repoprompt_runtime() -> None:
    result = runner.invoke(app, ["conformance", "rp", "--help"])

    assert result.exit_code == 0
    assert "official target is the real RepoPrompt app" in result.stdout
    assert "rp-cli-stub" in result.stdout
    assert "reference/test-only" in result.stdout


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


def test_cli_inspect_bridge_probe_surfaces_read_only_tool_probe(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    fake_cli = _write_fake_rp_bridge_cli(tmp_path, mode="ok")

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
            "--bridge",
            "--bridge-workspace",
            "workspace-alpha",
        ],
    )
    assert implement_result.exit_code == 0
    run_id = next((ai_root / "runs").iterdir()).name

    state_manager = RunStateManager(ai_root)
    meta = state_manager.load_run(run_id)
    host_contract = json.loads(json.dumps(meta.data["host_contract"]))
    host_contract["bridge"]["command_candidates"] = [str(fake_cli)]
    state_manager.update_run(run_id, data={**meta.data, "host_contract": host_contract})

    inspect_result = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--ai-root",
            str(ai_root),
            "--bridge-probe",
        ],
    )

    assert inspect_result.exit_code == 0
    assert "bridge_probe=available" in inspect_result.stdout
    assert fake_cli.name in inspect_result.stdout
    assert "bridge_probe_tools=file_search,manage_selection,workspace_context" in inspect_result.stdout

    inspect_json_result = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--ai-root",
            str(ai_root),
            "--bridge-probe",
            "--json",
        ],
    )

    assert inspect_json_result.exit_code == 0
    payload = json.loads(inspect_json_result.stdout)
    assert payload["bridge_probe"]["available"] is True
    assert payload["bridge_probe"]["path"] == str(fake_cli)
    assert [tool["name"] for tool in payload["bridge_probe"]["tools"]] == ["file_search", "manage_selection", "workspace_context"]
    assert payload["bridge_probe"]["error"] is None


def test_cli_inspect_bridge_probe_reports_missing_candidate_non_destructively(tmp_path: Path) -> None:
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
            "--bridge",
        ],
    )
    assert implement_result.exit_code == 0
    run_id = next((ai_root / "runs").iterdir()).name

    state_manager = RunStateManager(ai_root)
    meta = state_manager.load_run(run_id)
    host_contract = json.loads(json.dumps(meta.data["host_contract"]))
    host_contract["bridge"]["command_candidates"] = ["/path/does/not/exist/rp-cli"]
    state_manager.update_run(run_id, data={**meta.data, "host_contract": host_contract})

    inspect_json_result = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--ai-root",
            str(ai_root),
            "--bridge-probe",
            "--json",
        ],
    )

    assert inspect_json_result.exit_code == 0
    payload = json.loads(inspect_json_result.stdout)
    assert payload["bridge_probe"]["available"] is False
    assert payload["bridge_probe"]["error"]["code"] == "NOT_INSTALLED"
    assert payload["diagnostics"]["status"] == "blocked"


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


def test_cli_inspect_diff_reports_no_changes_for_fresh_run(tmp_path: Path) -> None:
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
            "--diff",
            "--json",
        ],
    )

    assert inspect_result.exit_code == 0
    payload = json.loads(inspect_result.stdout)
    assert payload["diff"]["mode"] == "current"
    assert payload["diff"]["has_changes"] is False
    assert payload["diff"]["field_changes"] == {}
    assert payload["diff"]["artifact_changes"] == {"added": [], "removed": [], "modified": []}


def test_cli_inspect_diff_reports_status_and_artifact_deltas(tmp_path: Path) -> None:
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

    run_dir = ai_root / "runs" / run_id
    (run_dir / "manual-note.md").write_text("operator note\n", encoding="utf-8")
    RunStateManager(ai_root).transition(
        run_id,
        RunStatus.failed,
        stage="implement",
        error="manual intervention required",
        error_code=ErrorCode.STATE_VIOLATION,
    )

    inspect_result = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--ai-root",
            str(ai_root),
            "--diff",
        ],
    )

    assert inspect_result.exit_code == 0
    assert "diff=changes_detected" in inspect_result.stdout
    assert "diff_field_changes:" in inspect_result.stdout
    assert "- status: blocked -> failed" in inspect_result.stdout
    assert "manual-note.md" in inspect_result.stdout

    inspect_json_result = runner.invoke(
        app,
        [
            "inspect",
            run_id,
            "--ai-root",
            str(ai_root),
            "--diff",
            "--json",
        ],
    )
    assert inspect_json_result.exit_code == 0
    payload = json.loads(inspect_json_result.stdout)
    assert payload["diff"]["mode"] == "current"
    assert payload["diff"]["has_changes"] is True
    assert payload["diff"]["field_changes"]["status"] == {"from": "blocked", "to": "failed"}
    assert payload["diff"]["field_changes"]["error_code"] == {"from": None, "to": "STATE_VIOLATION"}
    assert [artifact["name"] for artifact in payload["diff"]["artifact_changes"]["added"]] == ["manual-note.md"]


def test_cli_inspect_diff_run_reports_run_to_run_delta(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)

    blocked_result = runner.invoke(
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
    assert blocked_result.exit_code == 0
    blocked_run_id = next((ai_root / "runs").iterdir()).name

    auto_engine = WorkflowEngine(
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
    passed_run_id = auto_engine.run_implement(task_path)

    inspect_result = runner.invoke(
        app,
        [
            "inspect",
            blocked_run_id,
            "--ai-root",
            str(ai_root),
            "--diff-run",
            passed_run_id,
            "--json",
        ],
    )

    assert inspect_result.exit_code == 0
    payload = json.loads(inspect_result.stdout)
    assert payload["diff"]["mode"] == "run_to_run"
    assert payload["diff"]["compare_run_id"] == passed_run_id
    assert payload["diff"]["field_changes"]["status"] == {"from": "blocked", "to": "passed"}
    added_names = {artifact["name"] for artifact in payload["diff"]["artifact_changes"]["added"]}
    removed_names = {artifact["name"] for artifact in payload["diff"]["artifact_changes"]["removed"]}
    assert {"verify-report.json", "review-report.json", "work-receipt.json"} <= added_names
    assert "claude-implement-prompt.md" in removed_names


def test_cli_inspect_rejects_diff_and_diff_run_together(tmp_path: Path) -> None:
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
            "--diff",
            "--diff-run",
            run_id,
        ],
    )

    assert inspect_result.exit_code == 1
    assert "Cannot use --diff and --diff-run together" in inspect_result.stdout


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


def _write_fake_rp_bridge_cli(tmp_path: Path, *, mode: str) -> Path:
    script_path = tmp_path / f"fake-rp-bridge-cli-{mode}.py"
    script_path.write_text(
        (
            f"#!{sys.executable}\n"
            "import json\n"
            "import sys\n"
            "import time\n"
            "\n"
            f"MODE = {mode!r}\n"
            "\n"
            "if '--list-tools' in sys.argv:\n"
            "    if MODE == 'timeout':\n"
            "        time.sleep(10)\n"
            "    if MODE == 'malformed':\n"
            "        sys.stdout.write('not-json\\n')\n"
            "        raise SystemExit(0)\n"
            "    if MODE == 'fail':\n"
            "        sys.stderr.write('tool listing failed\\n')\n"
            "        raise SystemExit(9)\n"
            "    sys.stdout.write(json.dumps({'tools': [{'name': 'file_search'}, {'name': 'manage_selection'}, {'name': 'workspace_context'}]}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if '--workspace-context' in sys.argv:\n"
            "    workspace = sys.argv[-1] if len(sys.argv) >= 3 else None\n"
            "    sys.stdout.write(json.dumps({'workspace': workspace, 'context_id': 'ctx-123', 'selected_paths': ['src/example.py']}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if '--manage-selection' in sys.argv:\n"
            "    payload = json.loads(sys.argv[-1])\n"
            "    if MODE == 'seed-manage-fail':\n"
            "        sys.stderr.write('manage selection failed\\n')\n"
            "        raise SystemExit(7)\n"
            "    paths = payload.get('paths', [])\n"
            "    sys.stdout.write(json.dumps({'workspace': payload.get('workspace'), 'context_id': payload.get('context_id'), 'selected_paths': paths, 'added_paths': paths}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "sys.stderr.write('unsupported invocation\\n')\n"
            "raise SystemExit(2)\n"
        ),
        encoding="utf-8",
    )
    script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR)
    return script_path
