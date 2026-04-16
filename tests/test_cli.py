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

EXPECTED_BRIDGE_TOOLS = [
    "manage_workspaces",
    "bind_context",
    "manage_selection",
    "workspace_context",
    "context_builder",
    "ask_oracle",
    "agent_run",
    "agent_manage",
    "read_file",
    "file_search",
]


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
        "composition": "manage-selection",
        "use_oracle_for_review": False,
        "resolved": None,
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
        "composition": "manage-selection",
        "use_oracle_for_review": False,
        "resolved": None,
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
    expected_review_bridge = dict(bridge_payload)
    expected_review_bridge.pop("resolved", None)
    assert inspect_payload["review_report"]["bridge"] == expected_review_bridge

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


def test_cli_rp_bridge_p8_options_persist_and_oracle_artifact_is_separate(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    fake_cli = _write_fake_rp_bridge_cli(tmp_path, mode="seed-ok")
    fake_path = f"{fake_cli.parent}:{Path(sys.executable).parent}:{Path.cwd()}"

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
            "--bridge-composition",
            "context-builder",
            "--bridge-use-oracle-for-review",
        ],
        env={"PATH": fake_path},
    )

    assert implement_result.exit_code == 0
    run_id = next((ai_root / "runs").iterdir()).name
    run_dir = ai_root / "runs" / run_id
    meta = RunStateManager(ai_root).load_run(run_id)
    assert meta.data["rp_bridge"]["composition"] == "context-builder"
    assert meta.data["rp_bridge"]["use_oracle_for_review"] is True
    assert (run_dir / "rp-bridge-context-builder.json").exists()

    resume_result = runner.invoke(
        app,
        ["resume", run_id, "--ai-root", str(ai_root), "--repo-root", str(repo_root)],
        env={"PATH": fake_path},
    )
    assert resume_result.exit_code == 0

    review_result = runner.invoke(
        app,
        ["run", "review", "--run-id", run_id, "--ai-root", str(ai_root), "--repo-root", str(repo_root)],
        env={"PATH": fake_path},
    )
    assert review_result.exit_code == 0
    review_report = json.loads((run_dir / "review-report.json").read_text(encoding="utf-8"))
    assert review_report["bridge_oracle_artifact"] == "rp-bridge-oracle.json"
    assert (run_dir / "rp-bridge-oracle.json").exists()

    inspect_result = runner.invoke(app, ["inspect", run_id, "--ai-root", str(ai_root), "--json"])
    assert inspect_result.exit_code == 0
    inspect_payload = json.loads(inspect_result.stdout)
    assert inspect_payload["rp_bridge"]["composition"] == "context-builder"
    assert inspect_payload["rp_bridge"]["use_oracle_for_review"] is True
    assert inspect_payload["diagnostics"]["bridge"]["context_builder_artifact"] == "rp-bridge-context-builder.json"
    assert inspect_payload["diagnostics"]["bridge"]["oracle_artifact"] == "rp-bridge-oracle.json"
    assert inspect_payload["diagnostics"]["bridge"]["oracle_status"] == "ok"



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



def test_cli_rp_bridge_capture_round_trip_restores_review_flow_with_fake_cli(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    fake_cli = _write_fake_rp_bridge_cli(tmp_path, mode="seed-capture-ok")
    fake_path = f"{fake_cli.parent}:{Path(sys.executable).parent}:{Path.cwd()}"

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
            "--bridge-context-id",
            "ctx-123",
            "--bridge-timeout",
            "30",
        ],
        env={"PATH": fake_path},
    )

    assert implement_result.exit_code == 0
    run_id = next((ai_root / "runs").iterdir()).name
    run_dir = ai_root / "runs" / run_id

    capture_implement_result = runner.invoke(
        app,
        [
            "rp",
            "bridge",
            "capture",
            run_id,
            "--stage",
            "implement",
            "--source",
            "implement-response.md",
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
        env={"PATH": fake_path},
    )

    assert capture_implement_result.exit_code == 0
    assert "rp bridge capture completed" in capture_implement_result.stdout
    assert (run_dir / "rp-agent-implement-response.md").read_text(encoding="utf-8") == "# Implemented from RepoPrompt\n"

    implement_capture = json.loads((run_dir / "rp-bridge-capture.json").read_text(encoding="utf-8"))
    assert implement_capture["captures"][0]["stage"] == "implement"
    assert implement_capture["captures"][0]["status"] == "captured"
    assert implement_capture["captures"][0]["response_artifact"] == "rp-agent-implement-response.md"

    inspect_after_implement = runner.invoke(app, ["inspect", run_id, "--ai-root", str(ai_root), "--json"])
    assert inspect_after_implement.exit_code == 0
    inspect_payload = json.loads(inspect_after_implement.stdout)
    assert inspect_payload["bridge_capture"]["captures"][0]["stage"] == "implement"
    assert inspect_payload["artifacts"]["bridge_capture"].endswith("rp-bridge-capture.json")
    artifact_names = {artifact["name"] for artifact in inspect_payload["provenance"]["artifact_index"]}
    assert "rp-bridge-capture.json" in artifact_names
    assert "rp-agent-implement-response.md" in artifact_names

    resume_result = runner.invoke(
        app,
        ["resume", run_id, "--ai-root", str(ai_root), "--repo-root", str(repo_root)],
        env={"PATH": fake_path},
    )
    assert resume_result.exit_code == 0
    assert "status=needs_review" in resume_result.stdout

    review_result = runner.invoke(
        app,
        ["run", "review", "--run-id", run_id, "--ai-root", str(ai_root), "--repo-root", str(repo_root)],
        env={"PATH": fake_path},
    )
    assert review_result.exit_code == 0
    assert (run_dir / "rp-agent-review-prompt.md").exists()

    capture_review_result = runner.invoke(
        app,
        [
            "rp",
            "bridge",
            "capture",
            run_id,
            "--stage",
            "review",
            "--source",
            "review-response.json",
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
        env={"PATH": fake_path},
    )

    assert capture_review_result.exit_code == 0
    review_report = json.loads((run_dir / "review-report.json").read_text(encoding="utf-8"))
    capture_artifact = json.loads((run_dir / "rp-bridge-capture.json").read_text(encoding="utf-8"))
    assert review_report["summary"] == "Looks good overall"
    assert review_report["issues"] == [{"severity": "low", "message": "Add one regression test"}]
    assert review_report["mode"] == "manual"
    assert review_report["prompt_file"] == "rp-agent-review-prompt.md"
    assert review_report["response_file"] == "rp-agent-review-response.md"
    assert (run_dir / "rp-agent-review-response.md").exists()
    assert {capture["stage"] for capture in capture_artifact["captures"]} == {"implement", "review"}

    inspect_text = runner.invoke(app, ["inspect", run_id, "--ai-root", str(ai_root)])
    assert inspect_text.exit_code == 0
    assert "bridge_capture=" in inspect_text.stdout
    assert "bridge_capture_status=implement:captured,review:captured" in inspect_text.stdout

    final_resume = runner.invoke(
        app,
        ["resume", run_id, "--ai-root", str(ai_root), "--repo-root", str(repo_root)],
        env={"PATH": fake_path},
    )
    assert final_resume.exit_code == 0
    assert RunStateManager(ai_root).load_run(run_id).status.value == "passed"



def test_cli_rp_bridge_capture_review_refuses_missing_required_fields(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    fake_cli = _write_fake_rp_bridge_cli(tmp_path, mode="seed-capture-review-invalid")
    fake_path = f"{fake_cli.parent}:{Path(sys.executable).parent}:{Path.cwd()}"

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
        env={"PATH": fake_path},
    )
    assert implement_result.exit_code == 0
    run_id = next((ai_root / "runs").iterdir()).name

    resume_result = runner.invoke(
        app,
        ["resume", run_id, "--ai-root", str(ai_root), "--repo-root", str(repo_root)],
        env={"PATH": fake_path},
    )
    assert resume_result.exit_code == 0

    review_result = runner.invoke(
        app,
        ["run", "review", "--run-id", run_id, "--ai-root", str(ai_root), "--repo-root", str(repo_root)],
        env={"PATH": fake_path},
    )
    assert review_result.exit_code == 0

    capture_result = runner.invoke(
        app,
        [
            "rp",
            "bridge",
            "capture",
            run_id,
            "--stage",
            "review",
            "--source",
            "review-response.json",
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
        env={"PATH": fake_path},
    )

    assert capture_result.exit_code == 1
    assert "Review capture is missing required" in capture_result.stdout
    assert "summary" in capture_result.stdout

    run_dir = ai_root / "runs" / run_id
    review_report = json.loads((run_dir / "review-report.json").read_text(encoding="utf-8"))
    capture_artifact = json.loads((run_dir / "rp-bridge-capture.json").read_text(encoding="utf-8"))
    assert review_report["summary"].startswith("RepoPrompt review handoff prompt written")
    assert capture_artifact["captures"][0]["stage"] == "review"
    assert capture_artifact["captures"][0]["status"] == "refused"
    assert "missing required string field 'summary'" in capture_artifact["captures"][0]["summary"]
    assert RunStateManager(ai_root).load_run(run_id).status.value == "blocked"



def test_cli_rp_managed_agent_flow_completes_end_to_end_with_fake_cli(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    fake_cli = _write_fake_rp_bridge_cli(tmp_path, mode="managed-complete")
    fake_path = f"{fake_cli.parent}:{Path(sys.executable).parent}:{Path.cwd()}"

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
            "--bridge-mode",
            "managed-agent",
            "--bridge-workspace",
            "workspace-alpha",
            "--bridge-context-id",
            "ctx-123",
        ],
        env={"PATH": fake_path},
    )

    assert implement_result.exit_code == 0
    assert "status=needs_review" in implement_result.stdout
    run_id = next((ai_root / "runs").iterdir()).name
    run_dir = ai_root / "runs" / run_id
    assert (run_dir / "rp-agent-implement-response.md").exists()
    assert (run_dir / "rp-bridge-agent-log.json").exists()

    review_result = runner.invoke(
        app,
        ["run", "review", "--run-id", run_id, "--ai-root", str(ai_root), "--repo-root", str(repo_root)],
        env={"PATH": fake_path},
    )

    assert review_result.exit_code == 0
    assert "review completed" in review_result.stdout
    assert (run_dir / "rp-agent-review-response.md").exists()
    assert (run_dir / "review-report.json").exists()
    inspect_json = runner.invoke(app, ["inspect", run_id, "--ai-root", str(ai_root), "--json"])
    assert inspect_json.exit_code == 0
    payload = json.loads(inspect_json.stdout)
    assert payload["diagnostics"]["bridge"]["mode"] == "managed-agent"
    assert payload["diagnostics"]["bridge"]["agent_log_artifact"] == "rp-bridge-agent-log.json"
    assert payload["diagnostics"]["bridge"]["agent_status"] == "completed"
    assert payload["bridge_agent_log"]["sessions"][-1]["stage"] == "review"
    assert payload["review_report"]["bridge_agent"]["status"] == "completed"
    assert RunStateManager(ai_root).load_run(run_id).status.value == "passed"



def test_cli_rp_managed_agent_implement_waiting_for_input_blocks_and_resume_continues_session(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    fake_cli = _write_fake_rp_bridge_cli(tmp_path, mode="managed-implement-wait-then-complete")
    fake_path = f"{fake_cli.parent}:{Path(sys.executable).parent}:{Path.cwd()}"

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
            "--bridge-mode",
            "managed-agent",
            "--bridge-workspace",
            "workspace-alpha",
            "--bridge-context-id",
            "ctx-123",
            "--bridge-export-transcript",
        ],
        env={"PATH": fake_path},
    )

    assert implement_result.exit_code == 0
    assert "status=blocked" in implement_result.stdout
    run_id = next((ai_root / "runs").iterdir()).name
    meta = RunStateManager(ai_root).load_run(run_id)
    assert meta.status.value == "blocked"
    assert meta.last_completed_stage == "plan"

    inspect_json = runner.invoke(app, ["inspect", run_id, "--ai-root", str(ai_root), "--json"])
    assert inspect_json.exit_code == 0
    inspect_payload = json.loads(inspect_json.stdout)
    assert inspect_payload["diagnostics"]["bridge"]["agent_status"] == "waiting_for_input"
    assert "session_id=implement-session-123" in inspect_payload["diagnostics"]["next_actions"][0]

    resume_result = runner.invoke(
        app,
        ["resume", run_id, "--ai-root", str(ai_root), "--repo-root", str(repo_root)],
        env={"PATH": fake_path},
    )

    assert resume_result.exit_code == 0
    assert "status=needs_review" in resume_result.stdout
    run_dir = ai_root / "runs" / run_id
    agent_log = json.loads((run_dir / "rp-bridge-agent-log.json").read_text(encoding="utf-8"))
    implement_sessions = [session for session in agent_log["sessions"] if session["stage"] == "implement"]
    assert [session["status"] for session in implement_sessions] == ["waiting_for_input", "completed"]
    assert implement_sessions[-1]["recovery"] == "resumed"
    assert implement_sessions[-1]["transcript_artifact"] == "rp-bridge-agent-implement-transcript.json"
    assert implement_sessions[-1]["handoff_artifact"] == "rp-bridge-agent-implement-handoff.xml"
    start_count = int((tmp_path / "managed-implement-wait-then-complete-start-count.txt").read_text(encoding="utf-8"))
    assert start_count == 1

    inspect_after_resume = runner.invoke(app, ["inspect", run_id, "--ai-root", str(ai_root), "--json"])
    assert inspect_after_resume.exit_code == 0
    inspect_payload_after_resume = json.loads(inspect_after_resume.stdout)
    assert inspect_payload_after_resume["diagnostics"]["bridge"]["agent_recovery"] == "resumed"
    assert inspect_payload_after_resume["rp_bridge"]["resolved"]["resolved_workspace_name"] == "workspace-alpha"
    assert inspect_payload_after_resume["rp_bridge"]["resolved"]["resolved_context_id"] == "ctx-456"
    assert (run_dir / "rp-bridge-agent-implement-transcript.json").exists()
    assert (run_dir / "rp-bridge-agent-implement-handoff.xml").exists()



def test_cli_rp_managed_agent_implement_failure_marks_run_failed(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    fake_cli = _write_fake_rp_bridge_cli(tmp_path, mode="managed-implement-failed")
    fake_path = f"{fake_cli.parent}:{Path(sys.executable).parent}:{Path.cwd()}"

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
            "--bridge-mode",
            "managed-agent",
        ],
        env={"PATH": fake_path},
    )

    assert implement_result.exit_code == 1
    run_id = next((ai_root / "runs").iterdir()).name
    inspect_json = runner.invoke(app, ["inspect", run_id, "--ai-root", str(ai_root), "--json"])
    assert inspect_json.exit_code == 0
    payload = json.loads(inspect_json.stdout)
    assert payload["diagnostics"]["status"] == "failed"
    assert payload["diagnostics"]["error_code"] == "BRIDGE_AGENT_FAILURE"
    assert payload["bridge_agent_log"]["sessions"][-1]["status"] == "failed"



def test_cli_rp_managed_agent_implement_timeout_marks_run_failed(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    fake_cli = _write_fake_rp_bridge_cli(tmp_path, mode="managed-implement-timeout")
    fake_path = f"{fake_cli.parent}:{Path(sys.executable).parent}:{Path.cwd()}"

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
            "--bridge-mode",
            "managed-agent",
        ],
        env={"PATH": fake_path},
    )

    assert implement_result.exit_code == 1
    run_id = next((ai_root / "runs").iterdir()).name
    inspect_json = runner.invoke(app, ["inspect", run_id, "--ai-root", str(ai_root), "--json"])
    assert inspect_json.exit_code == 0
    payload = json.loads(inspect_json.stdout)
    assert payload["diagnostics"]["status"] == "failed"
    assert payload["diagnostics"]["error_code"] == "ADAPTER_TIMEOUT"
    assert payload["bridge_agent_log"]["sessions"][-1]["status"] == "timeout"



def test_cli_rp_managed_agent_review_waiting_for_input_blocks_and_resume_completes(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    fake_cli = _write_fake_rp_bridge_cli(tmp_path, mode="managed-review-wait-then-complete")
    fake_path = f"{fake_cli.parent}:{Path(sys.executable).parent}:{Path.cwd()}"

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
            "--bridge-mode",
            "managed-agent",
        ],
        env={"PATH": fake_path},
    )
    assert implement_result.exit_code == 0
    run_id = next((ai_root / "runs").iterdir()).name

    review_result = runner.invoke(
        app,
        ["run", "review", "--run-id", run_id, "--ai-root", str(ai_root), "--repo-root", str(repo_root)],
        env={"PATH": fake_path},
    )

    assert review_result.exit_code == 0
    assert "status=blocked" in review_result.stdout
    meta = RunStateManager(ai_root).load_run(run_id)
    assert meta.status.value == "blocked"
    assert meta.last_completed_stage == "gates"
    inspect_json = runner.invoke(app, ["inspect", run_id, "--ai-root", str(ai_root), "--json"])
    assert inspect_json.exit_code == 0
    inspect_payload = json.loads(inspect_json.stdout)
    assert inspect_payload["diagnostics"]["bridge"]["agent_status"] == "waiting_for_input"
    assert "review session is ready to continue" in inspect_payload["diagnostics"]["next_actions"][1]

    resume_result = runner.invoke(
        app,
        ["resume", run_id, "--ai-root", str(ai_root), "--repo-root", str(repo_root)],
        env={"PATH": fake_path},
    )

    assert resume_result.exit_code == 0
    assert "resume completed" in resume_result.stdout
    assert RunStateManager(ai_root).load_run(run_id).status.value == "passed"
    agent_log = json.loads((ai_root / "runs" / run_id / "rp-bridge-agent-log.json").read_text(encoding="utf-8"))
    review_sessions = [session for session in agent_log["sessions"] if session["stage"] == "review"]
    assert [session["status"] for session in review_sessions] == ["waiting_for_input", "completed"]



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
            "totally-unsupported",
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
                "resolved": {
                    "resolved_workspace_id": "workspace-1",
                    "resolved_workspace_name": "workspace-alpha",
                    "resolved_window_id": 11,
                    "resolved_tab_id": "tab-1",
                    "resolved_tab_name": "implement-tab",
                    "resolved_context_id": "ctx-456",
                    "resolved_at": "2026-04-17T00:00:00Z",
                },
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
        resolved={
            "resolved_workspace_id": "workspace-1",
            "resolved_workspace_name": "workspace-alpha",
            "resolved_window_id": 11,
            "resolved_tab_id": "tab-1",
            "resolved_tab_name": "implement-tab",
            "resolved_context_id": "ctx-456",
            "resolved_at": "2026-04-17T00:00:00Z",
        },
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
                "resolved": {
                    "resolved_workspace_id": "workspace-1",
                    "resolved_workspace_name": "workspace-alpha",
                    "resolved_window_id": 11,
                    "resolved_tab_id": "tab-1",
                    "resolved_tab_name": "implement-tab",
                    "resolved_context_id": "ctx-456",
                    "resolved_at": "2026-04-17T00:00:00Z",
                },
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
        resolved={
            "resolved_workspace_id": "workspace-1",
            "resolved_workspace_name": "workspace-alpha",
            "resolved_window_id": 11,
            "resolved_tab_id": "tab-1",
            "resolved_tab_name": "implement-tab",
            "resolved_context_id": "ctx-456",
            "resolved_at": "2026-04-17T00:00:00Z",
        },
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
    assert "real RepoPrompt app / MCP CLI" in result.stdout
    assert "rp-cli-stub" in result.stdout
    assert "reference/test-only" in result.stdout
    assert "--certify-real-runtime" in result.stdout


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
    assert "bridge_probe_tools=" in inspect_result.stdout

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
    assert [tool["name"] for tool in payload["bridge_probe"]["tools"]] == EXPECTED_BRIDGE_TOOLS
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
            "from pathlib import Path\n"
            "\n"
            f"MODE = {mode!r}\n"
            f"STATE_DIR = Path({str(tmp_path)!r})\n"
            "\n"
            "def _tool_and_payload(argv):\n"
            "    if '-c' not in argv:\n"
            "        return None, {}\n"
            "    idx = argv.index('-c')\n"
            "    if idx + 1 >= len(argv):\n"
            "        return None, {}\n"
            "    tool = argv[idx + 1]\n"
            "    payload = {}\n"
            "    if '-j' in argv:\n"
            "        jidx = argv.index('-j')\n"
            "        if jidx + 1 < len(argv):\n"
            "            payload = json.loads(argv[jidx + 1])\n"
            "    return tool, payload\n"
            "\n"
            "if '--help' in sys.argv:\n"
            "    sys.stdout.write('usage: rp-cli -c TOOL -j JSON --raw-json --tools-schema\\n')\n"
            "    sys.stdout.write('tool mode with -c and -j and --raw-json\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if '--tools-schema' in sys.argv:\n"
            "    if MODE == 'timeout':\n"
            "        time.sleep(10)\n"
            "    if MODE == 'malformed':\n"
            "        sys.stdout.write('not-json\\n')\n"
            "        raise SystemExit(0)\n"
            "    if MODE == 'fail':\n"
            "        sys.stderr.write('tool schema failed\\n')\n"
            "        raise SystemExit(9)\n"
            "    sys.stdout.write(json.dumps({'tools': [{'name': 'manage_workspaces'}, {'name': 'bind_context'}, {'name': 'manage_selection'}, {'name': 'workspace_context'}, {'name': 'context_builder'}, {'name': 'ask_oracle'}, {'name': 'agent_run'}, {'name': 'agent_manage'}, {'name': 'read_file'}, {'name': 'file_search'}]}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "tool, payload = _tool_and_payload(sys.argv)\n"
            "if tool is None:\n"
            "    sys.stderr.write('unsupported invocation\\n')\n"
            "    raise SystemExit(2)\n"
            "\n"
            "if tool == 'file_search':\n"
            "    if MODE == 'timeout':\n"
            "        time.sleep(10)\n"
            "    if MODE == 'malformed':\n"
            "        sys.stdout.write('not-json\\n')\n"
            "        raise SystemExit(0)\n"
            "    if MODE == 'fail':\n"
            "        sys.stderr.write('tool listing failed\\n')\n"
            "        raise SystemExit(9)\n"
            "    sys.stdout.write(json.dumps({'count': 0, 'matches': []}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if tool == 'workspace_context':\n"
            "    sys.stdout.write(json.dumps({'workspace': payload.get('workspace'), 'context_id': 'ctx-123', 'selected_paths': ['src/example.py']}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if tool == 'manage_workspaces':\n"
            "    if payload.get('action') == 'list':\n"
            "        sys.stdout.write(json.dumps({'workspaces': [{'id': 'workspace-1', 'name': 'workspace-alpha', 'repo_paths': ['/tmp/repo-alpha'], 'window_ids': [11], 'is_hidden': False}]}))\n"
            "        sys.stdout.write('\\n')\n"
            "        raise SystemExit(0)\n"
            "    sys.stdout.write(json.dumps({'workspaces': []}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if tool == 'bind_context':\n"
            "    sys.stdout.write(json.dumps({'workspace': 'workspace-alpha', 'workspace_id': 'workspace-1', 'window_id': 11, 'tab': 'implement-tab', 'tab_id': 'tab-1', 'context_id': 'ctx-456', 'windows': [{'window_id': 11, 'tabs': [{'id': 'tab-1', 'name': 'implement-tab', 'context_id': 'ctx-456'}]}]}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if tool == 'manage_selection':\n"
            "    if MODE == 'seed-manage-fail':\n"
            "        sys.stderr.write('manage selection failed\\n')\n"
            "        raise SystemExit(7)\n"
            "    paths = payload.get('paths', [])\n"
            "    sys.stdout.write(json.dumps({'workspace': payload.get('workspace'), 'context_id': payload.get('context_id'), 'selected_paths': paths, 'added_paths': paths}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if tool == 'context_builder':\n"
            "    response_type = payload.get('response_type', 'clarify')\n"
            "    if MODE == 'context-builder-apply-fail' and response_type == 'plan':\n"
            "        sys.stderr.write('context builder apply failed\\n')\n"
            "        raise SystemExit(8)\n"
            "    response = 'context-builder preview' if response_type == 'clarify' else 'context-builder apply'\n"
            "    sys.stdout.write(json.dumps({'response_type': response_type, 'context_id': 'ctx-123', 'selected_paths': ['src/example.py'], 'response': response, 'export_path': '.ai/runs/test-run/context-builder.md'}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if tool == 'ask_oracle':\n"
            "    if MODE == 'oracle-fail':\n"
            "        sys.stderr.write('oracle failed\\n')\n"
            "        raise SystemExit(9)\n"
            "    sys.stdout.write(json.dumps({'mode': payload.get('mode', 'chat'), 'chat_id': 'oracle-chat-1', 'response': 'advisory oracle response', 'oracle_export_path': '.ai/runs/test-run/oracle.md'}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if tool == 'read_file':\n"
            "    if MODE == 'capture-read-fail':\n"
            "        sys.stderr.write('read file failed\\n')\n"
            "        raise SystemExit(6)\n"
            "    if MODE == 'capture-read-malformed':\n"
            "        sys.stdout.write(json.dumps({'workspace': payload.get('workspace'), 'context_id': payload.get('context_id'), 'body': 'missing content'}))\n"
            "        sys.stdout.write('\\n')\n"
            "        raise SystemExit(0)\n"
            "    source = payload.get('source')\n"
            "    if source == 'implement-response.md':\n"
            "        content = '# Implemented from RepoPrompt\\n'\n"
            "    elif source == 'review-response.json':\n"
            "        if MODE == 'seed-capture-review-invalid':\n"
            "            content = json.dumps({'issues': []})\n"
            "        else:\n"
            "            content = json.dumps({'summary': 'Looks good overall', 'issues': [{'severity': 'low', 'message': 'Add one regression test'}]})\n"
            "    else:\n"
            "        content = f'Captured {source}\\n'\n"
            "    sys.stdout.write(json.dumps({'workspace': payload.get('workspace'), 'context_id': payload.get('context_id'), 'content': content}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if tool == 'agent_run':\n"
            "    op = payload.get('op')\n"
            "    if op == 'start':\n"
            "        stage = payload.get('stage') or 'implement'\n"
            "        count_path = STATE_DIR / f'{MODE}-start-count.txt'\n"
            "        current_count = int(count_path.read_text(encoding='utf-8').strip()) if count_path.exists() else 0\n"
            "        count_path.write_text(str(current_count + 1), encoding='utf-8')\n"
            "        sys.stdout.write(json.dumps({'session_id': f'{stage}-session-123', 'status': 'started', 'workspace': payload.get('workspace'), 'tab': payload.get('tab'), 'context_id': payload.get('context_id')}))\n"
            "        sys.stdout.write('\\n')\n"
            "        raise SystemExit(0)\n"
            "    if op == 'wait':\n"
            "        session_id = payload.get('session_id')\n"
            "        stage = 'review' if str(session_id).startswith('review-') else 'implement'\n"
            "        state_file = STATE_DIR / f'{MODE}-{session_id}.state'\n"
            "        if MODE == 'managed-implement-failed' and stage == 'implement':\n"
            "            status = 'failed'\n"
            "            output = None\n"
            "        elif MODE == 'managed-implement-timeout' and stage == 'implement':\n"
            "            status = 'timeout'\n"
            "            output = None\n"
            "        elif MODE == 'managed-implement-wait-then-complete' and stage == 'implement' and not state_file.exists():\n"
            "            state_file.write_text('waiting\\n', encoding='utf-8')\n"
            "            status = 'waiting_for_input'\n"
            "            output = None\n"
            "        elif MODE == 'managed-implement-wait-then-complete' and stage == 'implement':\n"
            "            state_file.write_text('completed\\n', encoding='utf-8')\n"
            "            status = 'completed'\n"
            "            output = '# Managed implement output\\n'\n"
            "        elif MODE == 'managed-review-wait-then-complete' and stage == 'review' and not state_file.exists():\n"
            "            state_file.write_text('waiting\\n', encoding='utf-8')\n"
            "            status = 'waiting_for_input'\n"
            "            output = None\n"
            "        elif MODE == 'managed-review-wait-then-complete' and stage == 'review':\n"
            "            state_file.write_text('completed\\n', encoding='utf-8')\n"
            "            status = 'completed'\n"
            "            output = json.dumps({'summary': 'Managed review passed', 'issues': []})\n"
            "        elif stage == 'review':\n"
            "            status = 'completed'\n"
            "            output = json.dumps({'summary': 'Managed review passed', 'issues': []})\n"
            "        else:\n"
            "            status = 'completed'\n"
            "            output = '# Managed implement output\\n'\n"
            "        sys.stdout.write(json.dumps({'session_id': session_id, 'status': status, 'output': output, 'workspace': payload.get('workspace'), 'tab': payload.get('tab'), 'context_id': payload.get('context_id')}))\n"
            "        sys.stdout.write('\\n')\n"
            "        raise SystemExit(0)\n"
            "\n"
            "if tool == 'agent_manage':\n"
            "    session_id = payload.get('session_id')\n"
            "    op = payload.get('op')\n"
            "    stage = 'review' if str(session_id).startswith('review-') else 'implement'\n"
            "    state_file = STATE_DIR / f'{MODE}-{session_id}.state'\n"
            "    if op == 'resume_session':\n"
            "        sys.stdout.write(json.dumps({'session_id': session_id, 'status': 'waiting_for_input'}))\n"
            "        sys.stdout.write('\\n')\n"
            "        raise SystemExit(0)\n"
            "    if op == 'extract_handoff':\n"
            "        output_path = payload.get('output_path')\n"
            "        Path(output_path).write_text('<handoff />\\n', encoding='utf-8')\n"
            "        sys.stdout.write(json.dumps({'session_id': session_id, 'status': 'completed', 'output_path': output_path, 'handoff_summary': 'handoff ready'}))\n"
            "        sys.stdout.write('\\n')\n"
            "        raise SystemExit(0)\n"
            "    if MODE == 'managed-implement-failed' and stage == 'implement':\n"
            "        status = 'failed'\n"
            "        output = None\n"
            "    elif MODE == 'managed-implement-timeout' and stage == 'implement':\n"
            "        status = 'timeout'\n"
            "        output = None\n"
            "    elif MODE == 'managed-implement-wait-then-complete' and stage == 'implement' and state_file.exists() and state_file.read_text(encoding='utf-8').strip() == 'waiting':\n"
            "        status = 'waiting_for_input'\n"
            "        output = None\n"
            "    elif MODE == 'managed-review-wait-then-complete' and stage == 'review' and state_file.exists() and state_file.read_text(encoding='utf-8').strip() == 'waiting':\n"
            "        status = 'waiting_for_input'\n"
            "        output = None\n"
            "    elif stage == 'review':\n"
            "        status = 'completed'\n"
            "        output = json.dumps({'summary': 'Managed review passed', 'issues': []})\n"
            "    else:\n"
            "        status = 'completed'\n"
            "        output = '# Managed implement output\\n'\n"
            "    sys.stdout.write(json.dumps({'session_id': session_id, 'status': status, 'output': output, 'events': [{'kind': 'agent-log', 'stage': stage}], 'workspace': payload.get('workspace'), 'tab': payload.get('tab'), 'context_id': payload.get('context_id')}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "sys.stderr.write('unknown tool ' + str(tool) + '\\n')\n"
            "raise SystemExit(3)\n"
        ),
        encoding="utf-8",
    )
    script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR)
    for alias in (tmp_path / "rp", tmp_path / "rp-cli"):
        alias.write_text(script_path.read_text(encoding="utf-8"), encoding="utf-8")
        alias.chmod(alias.stat().st_mode | stat.S_IXUSR)
    return script_path
