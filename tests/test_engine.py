from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from aiwf.adapters import build_adapter_from_contract
from aiwf.adapters.claude_code import ClaudeCodeAdapter
from aiwf.adapters.codex import CodexAdapter
from aiwf.adapters.rp_agent import RpAgentAdapter
from aiwf.adapters.stub import StubRunnerAdapter
from aiwf.engine import WorkflowEngine
from aiwf.exceptions import AdapterError, ErrorCode, StateError
from aiwf.models import RunStatus
from aiwf.state import RunStateManager


def test_run_plan_creates_expected_artifacts(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    engine = WorkflowEngine(StubRunnerAdapter(), ai_root=ai_root, repo_root=repo_root)

    run_id = engine.run_plan(task_path)
    run_dir = ai_root / "runs" / run_id
    meta = RunStateManager(ai_root).load_run(run_id)

    assert meta.status is RunStatus.passed
    assert meta.data["workflow"] == "plan"
    assert meta.data["host_contract"]["adapter"] == "stub"
    assert meta.data["host_contract"]["mode"] == "manual"
    assert (run_dir / "context-pack.md").exists()
    assert (run_dir / "exec-plan.md").exists()
    assert (run_dir / "run-diagnostics.json").exists()
    assert (run_dir / "run-provenance.json").exists()
    assert (run_dir / "work-receipt.json").exists()


def test_run_implement_completes_full_stub_workflow(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    engine = WorkflowEngine(StubRunnerAdapter(), ai_root=ai_root, repo_root=repo_root)

    run_id = engine.run_implement(task_path)
    run_dir = ai_root / "runs" / run_id
    meta = RunStateManager(ai_root).load_run(run_id)
    verify_report = json.loads((run_dir / "verify-report.json").read_text(encoding="utf-8"))

    assert meta.status is RunStatus.passed
    assert meta.last_completed_stage == "review"
    assert verify_report["passed"] is True
    assert (run_dir / "run-diagnostics.json").exists()
    assert (run_dir / "run-provenance.json").exists()
    assert (run_dir / "review-report.json").exists()


def test_run_review_operates_on_existing_run_and_blocks_for_manual_claude(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    engine = WorkflowEngine(
        ClaudeCodeAdapter(repo_root=repo_root, auto=False),
        ai_root=ai_root,
        repo_root=repo_root,
    )

    run_id = engine.run_implement(task_path)
    engine.resume(run_id)
    reviewed_run_id = engine.run_review(run_id)
    run_dir = ai_root / "runs" / run_id
    meta = RunStateManager(ai_root).load_run(run_id)
    provenance = json.loads((run_dir / "run-provenance.json").read_text(encoding="utf-8"))

    assert reviewed_run_id == run_id
    assert meta.status is RunStatus.blocked
    assert meta.last_completed_stage == "review"
    assert (run_dir / "review-report.json").exists()
    assert (run_dir / "claude-review-prompt.md").exists()
    assert provenance["review_evidence"]["report"]["name"] == "review-report.json"
    assert provenance["review_evidence"]["mode"] == "manual"
    assert provenance["review_evidence"]["linked_artifacts"][0]["name"] == "claude-review-prompt.md"
    assert any(
        artifact["name"] == "review-report.json"
        and artifact["stage"] == "review"
        and artifact["category"] == "review_report"
        for artifact in provenance["artifact_index"]
    )
    assert not (run_dir / "work-receipt.json").exists()


def test_run_review_requires_contract_declared_verify_report_artifact(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    engine = WorkflowEngine(
        ClaudeCodeAdapter(repo_root=repo_root, auto=False),
        ai_root=ai_root,
        repo_root=repo_root,
    )

    run_id = engine.run_implement(task_path)
    engine.resume(run_id)
    verify_report = ai_root / "runs" / run_id / "verify-report.json"
    verify_report.unlink()

    with pytest.raises(StateError, match="missing required review artifact 'verify-report.json'"):
        engine.run_review(run_id)

    failed_meta = RunStateManager(ai_root).load_run(run_id)
    diagnostics = json.loads((ai_root / "runs" / run_id / "run-diagnostics.json").read_text(encoding="utf-8"))

    assert failed_meta.status is RunStatus.failed
    assert failed_meta.error_code is ErrorCode.MISSING_ARTIFACT
    assert diagnostics["error_code"] == "MISSING_ARTIFACT"


def test_run_review_rejects_malformed_verify_report_content_at_review_boundary(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    engine = WorkflowEngine(
        ClaudeCodeAdapter(repo_root=repo_root, auto=False),
        ai_root=ai_root,
        repo_root=repo_root,
    )

    run_id = engine.run_implement(task_path)
    engine.resume(run_id)
    verify_report = ai_root / "runs" / run_id / "verify-report.json"
    verify_report.write_text(json.dumps({"gate_set": "default", "cwd": str(repo_root), "results": []}), encoding="utf-8")

    with pytest.raises(StateError, match="Run review artifact 'verify-report.json' is invalid: Artifact content failed validation: passed"):
        engine.run_review(run_id)

    failed_meta = RunStateManager(ai_root).load_run(run_id)
    diagnostics = json.loads((ai_root / "runs" / run_id / "run-diagnostics.json").read_text(encoding="utf-8"))

    assert failed_meta.status is RunStatus.failed
    assert failed_meta.error_code is ErrorCode.INVALID_ARTIFACT
    assert diagnostics["error_code"] == "INVALID_ARTIFACT"


def test_run_review_fails_when_adapter_returns_review_report_missing_linked_prompt_artifact(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    engine = WorkflowEngine(
        ClaudeCodeAdapter(repo_root=repo_root, auto=False),
        ai_root=ai_root,
        repo_root=repo_root,
    )

    run_id = engine.run_implement(task_path)
    engine.resume(run_id)
    engine.adapter.review = lambda task, run_dir: {  # type: ignore[method-assign]
        "summary": "Manual review prepared",
        "issues": [],
        "mode": "manual",
    }

    with pytest.raises(StateError, match="missing required string field 'prompt_file'"):
        engine.run_review(run_id)


def test_resume_review_fails_when_persisted_linked_review_evidence_artifact_is_missing(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    engine = WorkflowEngine(
        ClaudeCodeAdapter(repo_root=repo_root, auto=False),
        ai_root=ai_root,
        repo_root=repo_root,
    )

    run_id = engine.run_implement(task_path)
    engine.resume(run_id)
    engine.run_review(run_id)
    prompt_artifact = ai_root / "runs" / run_id / "claude-review-prompt.md"
    prompt_artifact.unlink()

    with pytest.raises(StateError, match="Review evidence artifact 'claude-review-prompt.md'"):
        engine.resume(run_id)


def test_run_review_rejects_malformed_review_report_content_before_persisting(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    engine = WorkflowEngine(
        ClaudeCodeAdapter(repo_root=repo_root, auto=False),
        ai_root=ai_root,
        repo_root=repo_root,
    )

    run_id = engine.run_implement(task_path)
    engine.resume(run_id)

    def bad_review(task, run_dir):  # type: ignore[no-untyped-def]
        prompt_path = run_dir / "claude-review-prompt.md"
        prompt_path.write_text("# review\n", encoding="utf-8")
        return {
            "summary": "Manual Claude review prompt written",
            "issues": [],
            "mode": "manual",
            "prompt_file": prompt_path.name,
            "evidence_files": "not-a-list",
        }

    engine.adapter.review = bad_review  # type: ignore[method-assign]

    with pytest.raises(StateError, match="Review report content is invalid: .*evidence_files"):
        engine.run_review(run_id)


def test_manual_claude_implement_stops_after_prompt_handoff(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    engine = WorkflowEngine(
        ClaudeCodeAdapter(repo_root=repo_root, auto=False),
        ai_root=ai_root,
        repo_root=repo_root,
    )

    run_id = engine.run_implement(task_path)
    run_dir = ai_root / "runs" / run_id
    meta = RunStateManager(ai_root).load_run(run_id)
    diagnostics = json.loads((run_dir / "run-diagnostics.json").read_text(encoding="utf-8"))
    provenance = json.loads((run_dir / "run-provenance.json").read_text(encoding="utf-8"))

    assert meta.status is RunStatus.blocked
    assert meta.last_completed_stage == "implement"
    assert (run_dir / "claude-implement-prompt.md").exists()
    assert diagnostics["status"] == "blocked"
    assert diagnostics["status_reason"].startswith("Run is blocked at implement")
    assert diagnostics["resumable"] is True
    assert diagnostics["host"]["mode"] == "manual"
    assert any("claude-implement-prompt.md" in action for action in diagnostics["next_actions"])
    assert any(
        artifact["name"] == "claude-implement-prompt.md"
        and artifact["stage"] == "implement"
        and artifact["category"] == "handoff"
        for artifact in provenance["artifact_index"]
    )
    assert provenance["gate_evidence"]["report"] is None
    assert provenance["review_evidence"]["report"] is None
    assert not (run_dir / "verify-report.json").exists()
    assert not (run_dir / "review-report.json").exists()
    assert not (run_dir / "work-receipt.json").exists()


def test_manual_claude_resume_stops_at_needs_review_after_passing_gates(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    engine = WorkflowEngine(
        ClaudeCodeAdapter(repo_root=repo_root, auto=False),
        ai_root=ai_root,
        repo_root=repo_root,
    )

    run_id = engine.run_implement(task_path)
    resumed_run_id = engine.resume(run_id)
    run_dir = ai_root / "runs" / run_id
    meta = RunStateManager(ai_root).load_run(run_id)
    verify_report = json.loads((run_dir / "verify-report.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((run_dir / "run-diagnostics.json").read_text(encoding="utf-8"))
    provenance = json.loads((run_dir / "run-provenance.json").read_text(encoding="utf-8"))

    assert resumed_run_id == run_id
    assert meta.status is RunStatus.needs_review
    assert meta.last_completed_stage == "gates"
    assert verify_report["passed"] is True
    assert diagnostics["status"] == "needs_review"
    assert diagnostics["reviewable"] is True
    assert diagnostics["review_command"] == f"uv run aiwf run review --run-id {run_id}"
    assert diagnostics["status_reason"].startswith("Implementation completed verification")
    assert provenance["gate_evidence"]["report"]["name"] == "verify-report.json"
    assert provenance["gate_evidence"]["passed"] is True
    assert provenance["review_evidence"]["required_run_artifacts"] == ["verify-report.json"]
    assert provenance["review_evidence"]["available_required_artifacts"][0]["name"] == "verify-report.json"
    assert provenance["review_evidence"]["linked_artifacts"] == []
    assert not (run_dir / "review-report.json").exists()
    assert not (run_dir / "work-receipt.json").exists()


def test_manual_claude_resume_after_review_handoff_finalizes_run(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    engine = WorkflowEngine(
        ClaudeCodeAdapter(repo_root=repo_root, auto=False),
        ai_root=ai_root,
        repo_root=repo_root,
    )

    run_id = engine.run_implement(task_path)
    engine.resume(run_id)
    engine.run_review(run_id)
    resumed_run_id = engine.resume(run_id)
    run_dir = ai_root / "runs" / run_id
    meta = RunStateManager(ai_root).load_run(run_id)
    receipt = json.loads((run_dir / "work-receipt.json").read_text(encoding="utf-8"))

    assert resumed_run_id == run_id
    assert meta.status is RunStatus.passed
    assert meta.last_completed_stage == "review"
    assert receipt["status"] == "passed"


def test_resume_review_rejects_invalid_persisted_review_report_content(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    engine = WorkflowEngine(
        ClaudeCodeAdapter(repo_root=repo_root, auto=False),
        ai_root=ai_root,
        repo_root=repo_root,
    )

    run_id = engine.run_implement(task_path)
    engine.resume(run_id)
    engine.run_review(run_id)
    review_report = ai_root / "runs" / run_id / "review-report.json"
    review_report.write_text(
        json.dumps({"summary": "Manual Claude review prompt written", "issues": "not-a-list", "mode": "manual", "prompt_file": "claude-review-prompt.md"}),
        encoding="utf-8",
    )

    with pytest.raises(StateError, match="Stored review-report.json is invalid: Artifact content failed validation: issues"):
        engine.resume(run_id)


def test_auto_claude_run_implement_persists_passed_runtime_surfaces(tmp_path: Path) -> None:
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
    run_dir = ai_root / "runs" / run_id
    meta = RunStateManager(ai_root).load_run(run_id)
    diagnostics = json.loads((run_dir / "run-diagnostics.json").read_text(encoding="utf-8"))
    provenance = json.loads((run_dir / "run-provenance.json").read_text(encoding="utf-8"))
    review_report = json.loads((run_dir / "review-report.json").read_text(encoding="utf-8"))

    assert meta.status is RunStatus.passed
    assert meta.last_completed_stage == "review"
    assert (run_dir / "claude-implement-response.md").exists()
    assert (run_dir / "claude-review-response.md").exists()

    assert diagnostics["workflow"] == "implement"
    assert diagnostics["status"] == "passed"
    assert diagnostics["status_reason"] == "Run completed successfully."
    assert diagnostics["host"]["adapter"] == "claude"
    assert diagnostics["host"]["mode"] == "auto"
    assert diagnostics["host"]["requires_explicit_review_handoff"] is False
    assert diagnostics["resumable"] is False
    assert diagnostics["reviewable"] is False
    assert diagnostics["resume_command"] is None
    assert diagnostics["review_command"] is None
    assert {
        "run_id",
        "workflow",
        "status",
        "status_reason",
        "error_code",
        "host",
        "key_artifacts",
        "stage_timeline",
        "generated_at",
    } <= diagnostics.keys()

    assert provenance["status"] == "passed"
    assert provenance["host"]["mode"] == "auto"
    assert provenance["review_evidence"]["mode"] == "auto"
    assert provenance["review_evidence"]["report"]["name"] == "review-report.json"
    assert provenance["review_evidence"]["linked_artifacts"][0]["name"] == "claude-review-response.md"
    assert any(
        artifact["name"] == "claude-implement-response.md"
        and artifact["stage"] == "implement"
        and artifact["category"] == "stage_output"
        for artifact in provenance["artifact_index"]
    )
    assert any(
        artifact["name"] == "review-report.json" and artifact["stage"] == "review"
        for artifact in provenance["artifact_index"]
    )

    assert review_report["mode"] == "auto"
    assert review_report["response_file"] == "claude-review-response.md"


def test_auto_claude_failed_implement_persists_failed_runtime_surfaces(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    engine = WorkflowEngine(
        ClaudeCodeAdapter(
            repo_root=repo_root,
            auto=True,
            claude_command=[
                sys.executable,
                "-c",
                "import sys; prompt = sys.stdin.read(); is_plan = 'Generate an implementation plan' in prompt; print('plan ok') if is_plan else print('boom', file=sys.stderr); sys.exit(0 if is_plan else 1)",
            ],
        ),
        ai_root=ai_root,
        repo_root=repo_root,
    )

    with pytest.raises(AdapterError, match="boom"):
        engine.run_implement(task_path)

    run_id = next((ai_root / "runs").iterdir()).name
    run_dir = ai_root / "runs" / run_id
    meta = RunStateManager(ai_root).load_run(run_id)
    diagnostics = json.loads((run_dir / "run-diagnostics.json").read_text(encoding="utf-8"))
    provenance = json.loads((run_dir / "run-provenance.json").read_text(encoding="utf-8"))
    receipt = json.loads((run_dir / "work-receipt.json").read_text(encoding="utf-8"))

    assert meta.status is RunStatus.failed
    assert meta.last_completed_stage == "implement"
    assert (run_dir / "context-pack.md").exists()
    assert (run_dir / "exec-plan.md").exists()
    assert not (run_dir / "claude-implement-response.md").exists()
    assert not (run_dir / "verify-report.json").exists()
    assert not (run_dir / "review-report.json").exists()

    assert diagnostics["workflow"] == "implement"
    assert diagnostics["status"] == "failed"
    assert diagnostics["host"]["adapter"] == "claude"
    assert diagnostics["host"]["mode"] == "auto"
    assert diagnostics["resumable"] is True
    assert diagnostics["reviewable"] is False
    assert diagnostics["status_reason"].startswith("boom")
    assert diagnostics["error"].startswith("boom")
    assert diagnostics["error_code"] == "ADAPTER_FAILURE"
    assert any(artifact["name"] == "work-receipt.json" for artifact in diagnostics["key_artifacts"])

    assert provenance["status"] == "failed"
    assert provenance["host"]["mode"] == "auto"
    assert provenance["gate_evidence"]["report"] is None
    assert provenance["review_evidence"]["report"] is None
    assert provenance["review_evidence"]["mode"] is None
    assert any(
        artifact["name"] == "work-receipt.json" and artifact["category"] == "receipt"
        for artifact in provenance["artifact_index"]
    )

    assert receipt["status"] == "failed"
    assert "boom" in receipt["summary"]


def test_auto_rp_run_implement_completes_native_path(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    engine = WorkflowEngine(
        RpAgentAdapter(
            repo_root=repo_root,
            auto=True,
            rp_command=[sys.executable, "-c", "import sys; print('stdin:' + ('yes' if sys.stdin.read() else 'no'))"],
        ),
        ai_root=ai_root,
        repo_root=repo_root,
    )

    run_id = engine.run_implement(task_path)
    run_dir = ai_root / "runs" / run_id
    meta = RunStateManager(ai_root).load_run(run_id)
    diagnostics = json.loads((run_dir / "run-diagnostics.json").read_text(encoding="utf-8"))
    provenance = json.loads((run_dir / "run-provenance.json").read_text(encoding="utf-8"))
    review_report = json.loads((run_dir / "review-report.json").read_text(encoding="utf-8"))

    assert meta.status is RunStatus.passed
    assert meta.last_completed_stage == "review"
    assert (run_dir / "rp-agent-implement-response.md").read_text(encoding="utf-8") == "stdin:yes"
    assert (run_dir / "rp-agent-review-response.md").read_text(encoding="utf-8") == "stdin:yes"
    assert not (run_dir / "rp-agent-implement-prompt.md").exists()
    assert not (run_dir / "rp-agent-review-prompt.md").exists()

    assert diagnostics["status"] == "passed"
    assert diagnostics["host"]["adapter"] == "rp"
    assert diagnostics["host"]["mode"] == "auto"
    assert diagnostics["host"]["supports_auto_execution"] is True
    assert diagnostics["host"]["requires_explicit_review_handoff"] is False
    assert diagnostics["reviewable"] is False
    assert diagnostics["resumable"] is False

    assert provenance["host"]["adapter"] == "rp"
    assert provenance["host"]["mode"] == "auto"
    assert provenance["review_evidence"]["mode"] == "auto"
    assert provenance["review_evidence"]["linked_artifacts"][0]["name"] == "rp-agent-review-response.md"

    assert review_report["mode"] == "auto"
    assert review_report["response_file"] == "rp-agent-review-response.md"
    assert review_report["response_excerpt"] == "stdin:yes"


def test_manual_rp_adapter_blocks_for_handoffs_and_restores_metadata(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    engine = WorkflowEngine(
        RpAgentAdapter(repo_root=repo_root),
        ai_root=ai_root,
        repo_root=repo_root,
    )

    run_id = engine.run_implement(task_path)
    run_dir = ai_root / "runs" / run_id
    state_manager = RunStateManager(ai_root)
    blocked_meta = state_manager.load_run(run_id)

    assert blocked_meta.status is RunStatus.blocked
    assert blocked_meta.last_completed_stage == "implement"
    assert (run_dir / "rp-agent-implement-prompt.md").exists()

    resumed_engine = WorkflowEngine(
        StubRunnerAdapter(),
        ai_root=ai_root,
        repo_root=repo_root,
        adapter_resolver=lambda contract: build_adapter_from_contract(contract, repo_root),
    )

    resumed_run_id = resumed_engine.resume(run_id)
    needs_review_meta = state_manager.load_run(run_id)

    assert resumed_run_id == run_id
    assert needs_review_meta.status is RunStatus.needs_review
    assert needs_review_meta.last_completed_stage == "gates"
    assert isinstance(resumed_engine.adapter, RpAgentAdapter)
    assert resumed_engine.adapter_name == "rp"
    assert resumed_engine.adapter_auto is False
    assert (run_dir / "verify-report.json").exists()
    assert not (run_dir / "review-report.json").exists()

    reviewed_run_id = resumed_engine.run_review(run_id)
    reviewed_meta = state_manager.load_run(reviewed_run_id)

    assert reviewed_run_id == run_id
    assert reviewed_meta.status is RunStatus.blocked
    assert reviewed_meta.last_completed_stage == "review"
    assert (run_dir / "review-report.json").exists()
    assert (run_dir / "rp-agent-review-prompt.md").exists()
    assert not (run_dir / "work-receipt.json").exists()

    finalized_run_id = resumed_engine.resume(run_id)
    finalized_meta = state_manager.load_run(finalized_run_id)
    receipt = json.loads((run_dir / "work-receipt.json").read_text(encoding="utf-8"))

    assert finalized_run_id == run_id
    assert finalized_meta.status is RunStatus.passed
    assert finalized_meta.last_completed_stage == "review"
    assert receipt["status"] == "passed"


def test_manual_codex_adapter_blocks_for_handoffs_and_restores_metadata(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    engine = WorkflowEngine(
        CodexAdapter(repo_root=repo_root),
        ai_root=ai_root,
        repo_root=repo_root,
    )

    run_id = engine.run_implement(task_path)
    run_dir = ai_root / "runs" / run_id
    state_manager = RunStateManager(ai_root)
    blocked_meta = state_manager.load_run(run_id)

    assert blocked_meta.status is RunStatus.blocked
    assert blocked_meta.last_completed_stage == "implement"
    assert blocked_meta.data["host_contract"]["adapter"] == "codex"
    assert (run_dir / "codex-implement-prompt.md").exists()

    resumed_engine = WorkflowEngine(
        StubRunnerAdapter(),
        ai_root=ai_root,
        repo_root=repo_root,
        adapter_resolver=lambda contract: build_adapter_from_contract(contract, repo_root),
    )

    resumed_run_id = resumed_engine.resume(run_id)
    needs_review_meta = state_manager.load_run(run_id)

    assert resumed_run_id == run_id
    assert needs_review_meta.status is RunStatus.needs_review
    assert needs_review_meta.last_completed_stage == "gates"
    assert isinstance(resumed_engine.adapter, CodexAdapter)
    assert resumed_engine.adapter_name == "codex"
    assert resumed_engine.adapter_auto is False
    assert (run_dir / "verify-report.json").exists()
    assert not (run_dir / "review-report.json").exists()

    reviewed_run_id = resumed_engine.run_review(run_id)
    reviewed_meta = state_manager.load_run(reviewed_run_id)

    assert reviewed_run_id == run_id
    assert reviewed_meta.status is RunStatus.blocked
    assert reviewed_meta.last_completed_stage == "review"
    assert (run_dir / "review-report.json").exists()
    assert (run_dir / "codex-review-prompt.md").exists()
    assert not (run_dir / "work-receipt.json").exists()

    finalized_run_id = resumed_engine.resume(run_id)
    finalized_meta = state_manager.load_run(finalized_run_id)
    receipt = json.loads((run_dir / "work-receipt.json").read_text(encoding="utf-8"))

    assert finalized_run_id == run_id
    assert finalized_meta.status is RunStatus.passed
    assert finalized_meta.last_completed_stage == "review"
    assert receipt["status"] == "passed"


def test_failed_gate_run_can_resume_after_gate_fix(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path, gate_command=_python_exit_command(1))
    engine = WorkflowEngine(StubRunnerAdapter(), ai_root=ai_root, repo_root=repo_root)

    run_id = engine.run_implement(task_path)
    state_manager = RunStateManager(ai_root)
    failed_meta = state_manager.load_run(run_id)
    diagnostics = json.loads((ai_root / "runs" / run_id / "run-diagnostics.json").read_text(encoding="utf-8"))
    provenance = json.loads((ai_root / "runs" / run_id / "run-provenance.json").read_text(encoding="utf-8"))

    assert failed_meta.status is RunStatus.failed
    assert failed_meta.last_completed_stage == "gates"
    assert failed_meta.error_code is ErrorCode.GATE_FAILURE
    assert diagnostics["status"] == "failed"
    assert diagnostics["resumable"] is True
    assert diagnostics["status_reason"] == "Run failed during gates and requires fixes before resume."
    assert diagnostics["error_code"] == "GATE_FAILURE"
    assert any(artifact["name"] == "verify-report.json" for artifact in diagnostics["key_artifacts"])
    assert provenance["gate_evidence"]["report"]["name"] == "verify-report.json"
    assert provenance["gate_evidence"]["passed"] is False

    (ai_root / "gates" / "default.yaml").write_text(
        _gates_yaml(_python_print_command("gate-fixed")),
        encoding="utf-8",
    )

    resumed_run_id = engine.resume(run_id)
    resumed_meta = state_manager.load_run(resumed_run_id)
    review_report = json.loads((ai_root / "runs" / run_id / "review-report.json").read_text(encoding="utf-8"))

    assert resumed_run_id == run_id
    assert resumed_meta.status is RunStatus.passed
    assert review_report["summary"].startswith("Stub review completed")


def test_adapter_failure_writes_failed_receipt(tmp_path: Path) -> None:
    task_path, ai_root, repo_root = _create_ai_workspace(tmp_path)
    engine = WorkflowEngine(StubRunnerAdapter(fail_stages={"discover"}), ai_root=ai_root, repo_root=repo_root)

    try:
        engine.run_plan(task_path)
    except Exception:
        pass
    else:
        raise AssertionError("Expected run_plan to fail when the stub adapter fails discover")

    run_root = next((ai_root / "runs").iterdir())
    meta = RunStateManager(ai_root).load_run(run_root.name)
    receipt = json.loads((run_root / "work-receipt.json").read_text(encoding="utf-8"))

    assert meta.status is RunStatus.failed
    assert receipt["status"] == "failed"
    assert "discover" in receipt["summary"]


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
                "Exercise the stub workflow.",
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
    return f"{sys.executable} -c \"print('{message}')\""


def _python_exit_command(code: int) -> str:
    return f"{sys.executable} -c \"import sys; sys.exit({code})\""
