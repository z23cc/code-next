from __future__ import annotations

import sys
from pathlib import Path

import pytest

from aiwf.adapters.claude_code import ClaudeCodeAdapter
from aiwf.exceptions import AdapterError
from aiwf.models import RunStatus, TaskSpec


def test_claude_adapter_manual_mode_generates_expected_outputs(tmp_path: Path) -> None:
    repo_root, run_dir, task = _create_workspace(tmp_path)
    adapter = ClaudeCodeAdapter(repo_root=repo_root, auto=False)

    context = adapter.discover(task, run_dir)
    plan = adapter.plan(task, context)
    result = adapter.execute(task, plan, run_dir)
    review = adapter.review(task, run_dir)

    assert adapter.host_contract.adapter == "claude"
    assert adapter.host_contract.mode == "manual"
    assert adapter.host_contract.capabilities.supports_auto_execution is True
    assert adapter.host_contract.capabilities.requires_explicit_review_handoff is True
    assert adapter.host_contract.review.required_run_artifacts == ("verify-report.json",)
    assert adapter.host_contract.review.expected_report_mode == "manual"
    assert adapter.host_contract.review.linked_report_artifact_field == "prompt_file"
    assert "Claude Context Pack" in context
    assert "Suggested Claude Prompt" in plan
    assert result.status is RunStatus.blocked
    assert result.metadata["mode"] == "manual"
    assert (run_dir / "claude-implement-prompt.md").exists()
    assert review["mode"] == "manual"
    assert (run_dir / "claude-review-prompt.md").exists()


def test_claude_adapter_auto_mode_uses_subprocess_output(tmp_path: Path) -> None:
    repo_root, run_dir, task = _create_workspace(tmp_path)
    adapter = ClaudeCodeAdapter(
        repo_root=repo_root,
        auto=True,
        claude_command=[sys.executable, "-c", "import sys; print('stdin:' + ('yes' if sys.stdin.read() else 'no'))"],
    )

    context = adapter.discover(task, run_dir)
    plan = adapter.plan(task, context)
    result = adapter.execute(task, plan, run_dir)
    review = adapter.review(task, run_dir)

    assert adapter.host_contract.adapter == "claude"
    assert adapter.host_contract.mode == "auto"
    assert adapter.host_contract.capabilities.supports_auto_execution is True
    assert adapter.host_contract.capabilities.requires_explicit_review_handoff is False
    assert adapter.host_contract.review.required_run_artifacts == ("verify-report.json",)
    assert adapter.host_contract.review.expected_report_mode == "auto"
    assert adapter.host_contract.review.linked_report_artifact_field == "response_file"
    assert plan == "stdin:yes"
    assert result.metadata["mode"] == "auto"
    assert (run_dir / "claude-implement-response.md").read_text(encoding="utf-8") == "stdin:yes"
    assert review["mode"] == "auto"
    assert review["response_excerpt"] == "stdin:yes"


def test_claude_adapter_auto_mode_raises_when_cli_missing(tmp_path: Path) -> None:
    repo_root, run_dir, task = _create_workspace(tmp_path)
    adapter = ClaudeCodeAdapter(
        repo_root=repo_root,
        auto=True,
        claude_command=["missing-claude-binary-for-aiwf-tests"],
    )

    with pytest.raises(AdapterError) as exc_info:
        adapter.execute(task, "# plan", run_dir)

    assert "stage=implement" in str(exc_info.value)


def _create_workspace(tmp_path: Path) -> tuple[Path, Path, TaskSpec]:
    repo_root = tmp_path / "repo"
    run_dir = repo_root / ".ai" / "runs" / "test-run"
    (repo_root / ".ai" / "policies").mkdir(parents=True)
    (repo_root / ".ai" / "runbooks").mkdir(parents=True)
    run_dir.mkdir(parents=True)

    (repo_root / ".ai" / "policies" / "repo-policy.md").write_text(
        "# Policy\n\nKeep the workflow thin.\n",
        encoding="utf-8",
    )
    (repo_root / ".ai" / "runbooks" / "default.md").write_text(
        "# Runbook\n\nDefault runbook.\n",
        encoding="utf-8",
    )
    (repo_root / "README.md").write_text("# Example Repo\n", encoding="utf-8")
    task = TaskSpec(
        title="Claude Adapter Task",
        slug="claude-adapter-task",
        runbook="default",
        gates="default",
        policy="repo-policy",
        body="Implement the adapter test workflow.",
    )
    return repo_root, run_dir, task
