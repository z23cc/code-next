from __future__ import annotations

from pathlib import Path

import pytest

from aiwf.adapters.codex import CodexAdapter
from aiwf.exceptions import AdapterError
from aiwf.models import RunStatus, TaskSpec


def test_codex_adapter_generates_manual_handoff_outputs(tmp_path: Path) -> None:
    repo_root, run_dir, task = _create_workspace(tmp_path)
    adapter = CodexAdapter(repo_root=repo_root)

    context = adapter.discover(task, run_dir)
    plan = adapter.plan(task, context)
    result = adapter.execute(task, plan, run_dir)
    review = adapter.review(task, run_dir)

    assert adapter.host_contract.adapter == "codex"
    assert adapter.host_contract.mode == "manual"
    assert adapter.host_contract.capabilities.supports_auto_execution is False
    assert adapter.host_contract.capabilities.requires_explicit_review_handoff is True
    assert adapter.host_contract.review.required_run_artifacts == ("verify-report.json",)
    assert adapter.host_contract.review.expected_report_mode == "manual"
    assert adapter.host_contract.review.linked_report_artifact_field == "prompt_file"
    assert "Codex Context Pack" in context
    assert "Suggested Codex Brief" in plan
    assert result.status is RunStatus.blocked
    assert result.metadata["mode"] == "manual"
    assert (run_dir / "codex-implement-prompt.md").exists()
    assert review["mode"] == "manual"
    assert (run_dir / "codex-review-prompt.md").exists()


def test_codex_adapter_discover_raises_for_missing_repo_root(tmp_path: Path) -> None:
    _, run_dir, task = _create_workspace(tmp_path)
    adapter = CodexAdapter(repo_root=tmp_path / "missing-repo")

    with pytest.raises(AdapterError) as exc_info:
        adapter.discover(task, run_dir)

    assert "stage=discover" in str(exc_info.value)


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
        title="Codex Adapter Task",
        slug="codex-adapter-task",
        runbook="default",
        gates="default",
        policy="repo-policy",
        body="Implement the Codex adapter test workflow.",
    )
    return repo_root, run_dir, task
