from __future__ import annotations

import pytest

from aiwf.adapters.base import ReviewArtifactContract
from aiwf.adapters.rp_bridge_normalize import (
    RpBridgeNormalizationError,
    normalize_implement_capture,
    normalize_review_capture,
)


def test_normalize_implement_capture_accepts_plain_text() -> None:
    assert normalize_implement_capture("Implemented change\n") == "Implemented change\n"


def test_normalize_implement_capture_extracts_json_content_field() -> None:
    assert normalize_implement_capture('{"content": "# Done\\n"}') == "# Done\n"


def test_normalize_review_capture_preserves_contract_fields_deterministically() -> None:
    contract = ReviewArtifactContract(
        required_run_artifacts=("verify-report.json",),
        required_report_string_fields=("summary", "mode", "prompt_file"),
        required_report_list_fields=("issues",),
        expected_report_mode="manual",
        linked_report_artifact_field="prompt_file",
    )

    report = normalize_review_capture(
        '{"summary": "Looks good", "issues": [{"severity": "low", "message": "Add one more regression test"}]}',
        contract=contract,
        linked_artifact_name="rp-agent-review-prompt.md",
        response_artifact_name="rp-agent-review-response.md",
        existing_report={
            "verify_report_file": "verify-report.json",
            "diagnostics_file": "run-diagnostics.json",
            "provenance_file": "run-provenance.json",
        },
    )

    assert report["summary"] == "Looks good"
    assert report["issues"] == [{"severity": "low", "message": "Add one more regression test"}]
    assert report["mode"] == "manual"
    assert report["prompt_file"] == "rp-agent-review-prompt.md"
    assert report["response_file"] == "rp-agent-review-response.md"
    assert report["verify_report_file"] == "verify-report.json"
    assert "response_excerpt" in report


def test_normalize_review_capture_refuses_missing_required_fields() -> None:
    contract = ReviewArtifactContract(
        required_report_string_fields=("summary", "mode", "prompt_file"),
        required_report_list_fields=("issues",),
        expected_report_mode="manual",
        linked_report_artifact_field="prompt_file",
    )

    with pytest.raises(RpBridgeNormalizationError, match="missing required string field 'summary'"):
        normalize_review_capture(
            '{"issues": []}',
            contract=contract,
            linked_artifact_name="rp-agent-review-prompt.md",
            response_artifact_name="rp-agent-review-response.md",
        )
