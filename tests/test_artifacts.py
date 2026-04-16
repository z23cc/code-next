from __future__ import annotations

import json
from pathlib import Path

import pytest

from aiwf.artifacts import ArtifactStore
from aiwf.exceptions import ArtifactError, ErrorCode
from aiwf.models import (
    ReviewReportContent,
    RpBridgeCaptureArtifact,
    RpBridgeCaptureRecord,
    RpBridgeSeedingArtifact,
    RpBridgeToolCall,
    RunDiagnostics,
    RunGateEvidence,
    RunHostDiagnostics,
    RunProvenance,
    RunProvenanceArtifact,
    RunReviewEvidence,
    RunStatus,
    TaskSpec,
    VerifyReport,
    VerifyReportContent,
    WorkReceipt,
    WorkReceiptContent,
)
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
    assert exc_info.value.error_code is ErrorCode.MISSING_ARTIFACT


def test_read_validated_artifact_returns_typed_known_artifacts(tmp_path: Path) -> None:
    manager = RunStateManager(tmp_path / ".ai")
    run_id = manager.init_run(TaskSpec(title="Validated Artifacts", body="Read typed known artifacts."))
    run_dir = tmp_path / ".ai" / "runs" / run_id
    store = ArtifactStore(run_dir)

    store.write_verify_report(VerifyReport(gate_set="default", cwd=str(tmp_path), passed=True, results=[]))
    store.write_review_report({"summary": "Looks good", "issues": [], "mode": "manual", "prompt_file": "review.md"})
    store.write_work_receipt(WorkReceipt(run_id=run_id, status=RunStatus.passed, summary="Completed milestone two."))

    verify_report = store.read_validated_artifact("verify-report.json")
    review_report = store.read_validated_artifact("review-report.json")
    work_receipt = store.read_validated_artifact("work-receipt.json")

    assert isinstance(verify_report, VerifyReportContent)
    assert isinstance(review_report, ReviewReportContent)
    assert isinstance(work_receipt, WorkReceiptContent)
    assert verify_report.passed is True
    assert review_report.summary == "Looks good"
    assert work_receipt.status is RunStatus.passed


def test_read_validated_artifact_rejects_malformed_verify_report_with_field_errors(tmp_path: Path) -> None:
    manager = RunStateManager(tmp_path / ".ai")
    run_id = manager.init_run(TaskSpec(title="Bad Verify Report", body="Reject malformed verify-report content."))
    run_dir = tmp_path / ".ai" / "runs" / run_id
    store = ArtifactStore(run_dir)
    (run_dir / "verify-report.json").write_text(json.dumps({"gate_set": "default", "cwd": str(tmp_path), "results": []}), encoding="utf-8")

    with pytest.raises(ArtifactError) as exc_info:
        store.read_validated_artifact("verify-report.json")

    message = str(exc_info.value)
    assert "Artifact content failed validation" in message
    assert "passed" in message
    assert "stage=read_validated_artifact" in message
    assert exc_info.value.error_code is ErrorCode.INVALID_ARTIFACT


def test_read_validated_artifact_rejects_malformed_review_report_with_field_errors(tmp_path: Path) -> None:
    manager = RunStateManager(tmp_path / ".ai")
    run_id = manager.init_run(TaskSpec(title="Bad Review Report", body="Reject malformed review-report content."))
    run_dir = tmp_path / ".ai" / "runs" / run_id
    store = ArtifactStore(run_dir)
    (run_dir / "review-report.json").write_text(
        json.dumps({"summary": "Looks good", "issues": "not-a-list", "mode": "manual", "prompt_file": "review.md"}),
        encoding="utf-8",
    )

    with pytest.raises(ArtifactError) as exc_info:
        store.read_validated_artifact("review-report.json")

    message = str(exc_info.value)
    assert "Artifact content failed validation" in message
    assert "issues" in message
    assert exc_info.value.error_code is ErrorCode.INVALID_ARTIFACT


def test_read_validated_artifact_rejects_malformed_work_receipt_with_field_errors(tmp_path: Path) -> None:
    manager = RunStateManager(tmp_path / ".ai")
    run_id = manager.init_run(TaskSpec(title="Bad Receipt", body="Reject malformed work-receipt content."))
    run_dir = tmp_path / ".ai" / "runs" / run_id
    store = ArtifactStore(run_dir)
    (run_dir / "work-receipt.json").write_text(
        json.dumps({"run_id": run_id, "status": "passed", "summary": "ok", "artifacts": "not-a-list", "notes": [], "risks": [], "finished_at": "2026-04-16T00:00:00Z"}),
        encoding="utf-8",
    )

    with pytest.raises(ArtifactError) as exc_info:
        store.read_validated_artifact("work-receipt.json")

    message = str(exc_info.value)
    assert "Artifact content failed validation" in message
    assert "artifacts" in message
    assert exc_info.value.error_code is ErrorCode.INVALID_ARTIFACT


def test_artifact_store_writes_and_reads_run_diagnostics(tmp_path: Path) -> None:
    manager = RunStateManager(tmp_path / ".ai")
    run_id = manager.init_run(TaskSpec(title="Diagnostics Artifact", body="Store diagnostics artifact."))
    run_dir = tmp_path / ".ai" / "runs" / run_id
    store = ArtifactStore(run_dir)

    store.write_run_diagnostics(
        RunDiagnostics(
            run_id=run_id,
            workflow="implement",
            status=RunStatus.blocked,
            status_reason="Run is blocked at implement waiting for operator action.",
            resumable=True,
            next_actions=[f"Run `uv run aiwf resume {run_id}` when ready."],
            error_code=ErrorCode.STATE_VIOLATION,
            host=RunHostDiagnostics(
                adapter="claude",
                mode="manual",
                supports_auto_execution=True,
                requires_explicit_review_handoff=True,
            ),
        )
    )

    diagnostics = store.read_artifact("run-diagnostics.json")

    assert diagnostics["status"] == "blocked"
    assert diagnostics["resumable"] is True
    assert diagnostics["error_code"] == "STATE_VIOLATION"
    assert diagnostics["host"]["adapter"] == "claude"


def test_artifact_store_writes_and_reads_run_provenance(tmp_path: Path) -> None:
    manager = RunStateManager(tmp_path / ".ai")
    run_id = manager.init_run(TaskSpec(title="Provenance Artifact", body="Store provenance artifact."))
    run_dir = tmp_path / ".ai" / "runs" / run_id
    store = ArtifactStore(run_dir)

    store.write_run_provenance(
        RunProvenance(
            run_id=run_id,
            workflow="implement",
            status=RunStatus.needs_review,
            last_completed_stage="gates",
            host=RunHostDiagnostics(
                adapter="claude",
                mode="manual",
                supports_auto_execution=True,
                requires_explicit_review_handoff=True,
            ),
            artifact_index=[
                RunProvenanceArtifact(
                    name="verify-report.json",
                    path=str(run_dir / "verify-report.json"),
                    stage="gates",
                    category="gate_report",
                )
            ],
            gate_evidence=RunGateEvidence(
                gate_set="default",
                passed=True,
            ),
            review_evidence=RunReviewEvidence(
                required_run_artifacts=["verify-report.json"],
            ),
        )
    )

    provenance = store.read_artifact("run-provenance.json")

    assert provenance["status"] == "needs_review"
    assert provenance["artifact_index"][0]["stage"] == "gates"
    assert provenance["gate_evidence"]["passed"] is True
    assert provenance["review_evidence"]["required_run_artifacts"] == ["verify-report.json"]


def test_artifact_store_validates_rp_bridge_seeding_artifact(tmp_path: Path) -> None:
    manager = RunStateManager(tmp_path / ".ai")
    run_id = manager.init_run(TaskSpec(title="Bridge seeding", body="Store seeding artifact."))
    run_dir = tmp_path / ".ai" / "runs" / run_id
    store = ArtifactStore(run_dir)

    (run_dir / "rp-bridge-seeding.json").write_text(
        json.dumps(
            RpBridgeSeedingArtifact(
                mode="manual-assist",
                status="seeded",
                workspace="workspace-alpha",
                summary="Seeded aiwf artifacts into RepoPrompt context.",
                selected_artifacts=["context-pack.md", "exec-plan.md"],
                selected_paths=[".ai/runs/run-1/context-pack.md", ".ai/runs/run-1/exec-plan.md"],
                attempted_tools=["manage_selection"],
                calls=[
                    RpBridgeToolCall(
                        step="manage_selection_add",
                        tool="manage_selection",
                        ok=True,
                        command=["rp", "--manage-selection"],
                        summary="Seeded 2 aiwf artifact path(s) into RepoPrompt context",
                    )
                ],
            ).model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    artifact = store.read_validated_artifact("rp-bridge-seeding.json")

    assert artifact.status == "seeded"
    assert artifact.calls[0].tool == "manage_selection"


def test_artifact_store_validates_rp_bridge_capture_artifact(tmp_path: Path) -> None:
    manager = RunStateManager(tmp_path / ".ai")
    run_id = manager.init_run(TaskSpec(title="Bridge capture", body="Store capture artifact."))
    run_dir = tmp_path / ".ai" / "runs" / run_id
    store = ArtifactStore(run_dir)

    (run_dir / "rp-bridge-capture.json").write_text(
        json.dumps(
            RpBridgeCaptureArtifact(
                captures=[
                    RpBridgeCaptureRecord(
                        stage="implement",
                        source="implement-response.md",
                        status="captured",
                        workspace="workspace-alpha",
                        context_id="ctx-123",
                        response_artifact="rp-agent-implement-response.md",
                        summary="Captured RepoPrompt implement response into rp-agent-implement-response.md",
                        calls=[
                            RpBridgeToolCall(
                                step="capture_implement",
                                tool="read_file",
                                ok=True,
                                command=["rp", "--read-file"],
                                summary="Captured RepoPrompt source via read_file",
                            )
                        ],
                    )
                ]
            ).model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    artifact = store.read_validated_artifact("rp-bridge-capture.json")

    assert artifact.captures[0].stage == "implement"
    assert artifact.captures[0].response_artifact == "rp-agent-implement-response.md"
