from __future__ import annotations

from pathlib import Path

import pytest

from aiwf.adapters.rp_agent import RpAgentAdapter
from aiwf.exceptions import AdapterError
from aiwf.models import RunStatus, TaskSpec


def test_rp_agent_adapter_generates_manual_handoff_outputs(tmp_path: Path) -> None:
    repo_root, run_dir, task = _create_workspace(tmp_path)
    adapter = RpAgentAdapter(repo_root=repo_root)

    context = adapter.discover(task, run_dir)
    plan = adapter.plan(task, context)
    result = adapter.execute(task, plan, run_dir)
    review = adapter.review(task, run_dir)

    assert adapter.host_contract.adapter == "rp"
    assert adapter.host_contract.mode == "manual"
    assert adapter.host_contract.capabilities.supports_auto_execution is False
    assert adapter.host_contract.capabilities.requires_explicit_review_handoff is True
    assert adapter.host_contract.review.required_run_artifacts == ("verify-report.json",)
    assert adapter.host_contract.review.expected_report_mode == "manual"
    assert adapter.host_contract.review.linked_report_artifact_field == "prompt_file"
    assert adapter.host_contract.native_runtime.enabled is True
    assert adapter.host_contract.native_runtime.command_candidates == ("rp", "rp-cli")
    assert "RepoPrompt Context Pack" in context
    assert "Suggested RepoPrompt Brief" in plan
    assert result.status is RunStatus.blocked
    assert result.metadata["mode"] == "manual"
    assert (run_dir / "rp-agent-implement-prompt.md").exists()
    assert review["mode"] == "manual"
    assert review["verify_report_file"] == "verify-report.json"
    assert review["diagnostics_file"] == "run-diagnostics.json"
    assert review["provenance_file"] == "run-provenance.json"
    assert review["evidence_summary"] == {
        "verify": "gate_set=default passed=True",
        "gate_results": [],
        "diagnostics": "status=needs_review reviewable=True resumable=False reason=Ready for review.",
        "provenance": "gate_report=verify-report.json review_linked_artifacts=0 review_required_artifacts_available=1",
        "changed_files": [],
        "diff_summary": [],
    }
    assert review["evidence_files"] == [
        "context-pack.md",
        "exec-plan.md",
        "verify-report.json",
        "run-diagnostics.json",
        "run-provenance.json",
        "work-receipt.json",
        "rp-agent-implement-prompt.md",
    ]
    assert (run_dir / "rp-agent-review-prompt.md").exists()
    prompt_text = (run_dir / "rp-agent-review-prompt.md").read_text(encoding="utf-8")
    assert "run-diagnostics.json" in prompt_text
    assert "run-provenance.json" in prompt_text
    assert "Evidence summary:" in prompt_text
    assert "verify: gate_set=default passed=True" in prompt_text
    assert "diagnostics: status=needs_review reviewable=True resumable=False" in prompt_text
    assert "provenance: gate_report=" in prompt_text


def test_rp_agent_adapter_review_includes_compact_gate_and_change_evidence(tmp_path: Path, monkeypatch) -> None:
    repo_root, run_dir, task = _create_workspace(tmp_path)
    (run_dir / "verify-report.json").write_text(
        (
            '{"gate_set":"default","passed":false,"results":['
            '{"name":"lint","passed":true,"returncode":0,"timed_out":false,"duration_seconds":0.25},'
            '{"name":"pytest","passed":false,"returncode":1,"timed_out":false,"duration_seconds":1.25}'
            ']}\n'
        ),
        encoding="utf-8",
    )
    adapter = RpAgentAdapter(repo_root=repo_root)
    monkeypatch.setattr(
        adapter,
        "_collect_repo_change_evidence",
        lambda: ([" M src/main.py", "?? tests/test_main.py"], ["src/main.py | 3 ++-", "tests/test_main.py | 8 ++++++++"]),
    )

    review = adapter.review(task, run_dir)

    assert review["evidence_summary"]["gate_results"] == [
        "lint: passed (rc=0, 0.25s)",
        "pytest: failed (rc=1, 1.25s)",
    ]
    assert review["evidence_summary"]["changed_files"] == [" M src/main.py", "?? tests/test_main.py"]
    assert review["evidence_summary"]["diff_summary"] == [
        "src/main.py | 3 ++-",
        "tests/test_main.py | 8 ++++++++",
    ]
    prompt_text = (run_dir / "rp-agent-review-prompt.md").read_text(encoding="utf-8")
    assert "- gate: pytest: failed (rc=1, 1.25s)" in prompt_text
    assert "- changed files:" in prompt_text
    assert "  -  M src/main.py" in prompt_text
    assert "- diff summary:" in prompt_text
    assert "  - src/main.py | 3 ++-" in prompt_text


def test_rp_agent_adapter_discover_raises_for_missing_repo_root(tmp_path: Path) -> None:
    _, run_dir, task = _create_workspace(tmp_path)
    adapter = RpAgentAdapter(repo_root=tmp_path / "missing-repo")

    with pytest.raises(AdapterError) as exc_info:
        adapter.discover(task, run_dir)

    assert "stage=discover" in str(exc_info.value)


def test_rp_agent_adapter_snapshot_respects_gitignore_and_common_noise(tmp_path: Path) -> None:
    repo_root, run_dir, task = _create_workspace(tmp_path)
    (repo_root / ".gitignore").write_text(
        "\n".join(
            [
                "*.log",
                "ignored-dir/",
                "nested/generated.txt",
                "!keep.log",
            ]
        ),
        encoding="utf-8",
    )
    (repo_root / "src").mkdir()
    (repo_root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (repo_root / "ignored.log").write_text("ignored\n", encoding="utf-8")
    (repo_root / "keep.log").write_text("kept\n", encoding="utf-8")
    (repo_root / "ignored-dir").mkdir()
    (repo_root / "ignored-dir" / "value.txt").write_text("noise\n", encoding="utf-8")
    (repo_root / "nested").mkdir()
    (repo_root / "nested" / "generated.txt").write_text("noise\n", encoding="utf-8")
    (repo_root / "dist").mkdir()
    (repo_root / "dist" / "bundle.js").write_text("noise\n", encoding="utf-8")
    (repo_root / ".pytest_cache").mkdir()
    (repo_root / ".pytest_cache" / "state").write_text("noise\n", encoding="utf-8")

    adapter = RpAgentAdapter(repo_root=repo_root)

    context = adapter.discover(task, run_dir)

    assert "- README.md" in context
    assert "- src/main.py" in context
    assert "- keep.log" in context
    assert "ignored.log" not in context
    assert "ignored-dir/value.txt" not in context
    assert "nested/generated.txt" not in context
    assert "dist/bundle.js" not in context
    assert ".pytest_cache/state" not in context


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
    (run_dir / "context-pack.md").write_text("# Context\n", encoding="utf-8")
    (run_dir / "exec-plan.md").write_text("# Plan\n", encoding="utf-8")
    (run_dir / "verify-report.json").write_text(
        '{"gate_set":"default","passed":true,"results":[]}\n',
        encoding="utf-8",
    )
    (run_dir / "run-diagnostics.json").write_text(
        '{"status":"needs_review","status_reason":"Ready for review.","reviewable":true,"resumable":false}\n',
        encoding="utf-8",
    )
    (run_dir / "run-provenance.json").write_text(
        '{"gate_evidence":{"report":{"path":"verify-report.json"}},"review_evidence":{"linked_artifacts":[],"available_required_artifacts":[{"name":"verify-report.json","path":"verify-report.json"}]}}\n',
        encoding="utf-8",
    )
    (run_dir / "work-receipt.json").write_text('{"summary":"ok"}\n', encoding="utf-8")
    task = TaskSpec(
        title="RepoPrompt Adapter Task",
        slug="repoprompt-adapter-task",
        runbook="default",
        gates="default",
        policy="repo-policy",
        body="Implement the RepoPrompt adapter test workflow.",
    )
    return repo_root, run_dir, task
