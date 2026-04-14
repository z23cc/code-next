from __future__ import annotations

import json
from pathlib import Path

import pytest

from aiwf.artifacts import ArtifactStore
from aiwf.exceptions import ArtifactError
from aiwf.models import RunStatus, TaskSpec, VerifyReport, WorkReceipt
from aiwf.state import RunStateManager


def test_artifact_store_writes_and_reads_standard_artifacts(tmp_path: Path) -> None:
    manager = RunStateManager(tmp_path / ".ai")
    run_id = manager.init_run(TaskSpec(title="Persist Artifacts", body="Store all standard artifacts."))
    run_dir = tmp_path / ".ai" / "runs" / run_id
    store = ArtifactStore(run_dir)

    store.write_context_pack("# Context\n")
    store.write_exec_plan("# Plan\n")
    store.write_verify_report(
        VerifyReport(gate_set="default", cwd=str(tmp_path), passed=True, results=[])
    )
    store.write_review_report({"summary": "Looks good", "issues": []})
    store.write_work_receipt(
        WorkReceipt(run_id=run_id, status=RunStatus.passed, summary="Completed milestone two.")
    )

    assert store.read_artifact("context-pack.md") == "# Context\n"
    assert store.read_artifact("exec-plan.md") == "# Plan\n"

    verify_report = store.read_artifact("verify-report.json")
    review_report = store.read_artifact("review-report.json")
    receipt = store.read_artifact("work-receipt.json")

    assert verify_report["passed"] is True
    assert review_report["summary"] == "Looks good"
    assert receipt["status"] == "passed"

    event_lines = (run_dir / "events.ndjson").read_text(encoding="utf-8").splitlines()
    artifact_events = [json.loads(line) for line in event_lines if json.loads(line)["event"] == "artifact_written"]
    assert len(artifact_events) == 5
    assert artifact_events[-1]["data"]["artifact"] == "work-receipt.json"


def test_artifact_store_requires_run_directory_under_ai_runs(tmp_path: Path) -> None:
    invalid_run_dir = tmp_path / "standalone-run"
    invalid_run_dir.mkdir()

    with pytest.raises(ArtifactError) as exc_info:
        ArtifactStore(invalid_run_dir)

    assert "stage=artifact_init" in str(exc_info.value)


def test_read_artifact_raises_for_missing_artifact(tmp_path: Path) -> None:
    manager = RunStateManager(tmp_path / ".ai")
    run_id = manager.init_run(TaskSpec(title="Missing Artifact", body="Attempt to read absent file."))
    store = ArtifactStore(tmp_path / ".ai" / "runs" / run_id)

    with pytest.raises(ArtifactError) as exc_info:
        store.read_artifact("missing.md")

    assert "path=" in str(exc_info.value)
