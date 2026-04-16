"""Deterministic normalization for RepoPrompt bridge capture artifacts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from aiwf.adapters.base import ReviewArtifactContract


class RpBridgeNormalizationError(ValueError):
    """Raised when captured bridge output cannot be normalized deterministically."""


def normalize_implement_capture(raw_content: str) -> str:
    """Normalize captured implement output into a stable markdown artifact."""
    payload = _extract_json_payload(raw_content)
    if isinstance(payload, dict):
        for key in ("content", "response", "markdown"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip() + "\n"
    text = raw_content.strip()
    if not text:
        raise RpBridgeNormalizationError("Implement capture was empty")
    return text + "\n"


def normalize_review_capture(
    raw_content: str,
    *,
    contract: ReviewArtifactContract,
    linked_artifact_name: str | None,
    response_artifact_name: str,
    existing_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize captured review output into a review-report payload."""
    payload = _extract_json_payload(raw_content)
    if not isinstance(payload, dict):
        raise RpBridgeNormalizationError(
            "Review capture must be JSON (or fenced JSON) with at least summary and issues fields"
        )

    summary = payload.get("summary")
    issues = payload.get("issues")
    if not isinstance(summary, str) or not summary.strip():
        raise RpBridgeNormalizationError("Review capture is missing required string field 'summary'")
    if not isinstance(issues, list):
        raise RpBridgeNormalizationError("Review capture is missing required list field 'issues'")

    report: dict[str, Any] = dict(existing_report or {})
    report["summary"] = summary.strip()
    report["issues"] = issues

    if contract.expected_report_mode is not None:
        report["mode"] = contract.expected_report_mode
    else:
        mode = payload.get("mode")
        if not isinstance(mode, str) or not mode.strip():
            raise RpBridgeNormalizationError("Review capture is missing required string field 'mode'")
        report["mode"] = mode.strip()

    if contract.linked_report_artifact_field is not None:
        linked_name = linked_artifact_name
        if linked_name is None:
            raw_linked = payload.get(contract.linked_report_artifact_field)
            if isinstance(raw_linked, str) and raw_linked.strip():
                linked_name = raw_linked.strip()
        if linked_name is None:
            raise RpBridgeNormalizationError(
                f"Review capture could not resolve linked artifact field {contract.linked_report_artifact_field!r}"
            )
        report[contract.linked_report_artifact_field] = linked_name

    report["response_file"] = response_artifact_name
    response_excerpt = _first_non_empty_line(raw_content)
    if response_excerpt is not None:
        report["response_excerpt"] = response_excerpt

    for field_name in contract.required_report_string_fields:
        value = report.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise RpBridgeNormalizationError(
                f"Normalized review capture is missing required string field {field_name!r}"
            )
    for field_name in contract.required_report_list_fields:
        if not isinstance(report.get(field_name), list):
            raise RpBridgeNormalizationError(
                f"Normalized review capture is missing required list field {field_name!r}"
            )
    return report


def _extract_json_payload(raw_content: str) -> dict[str, Any] | None:
    stripped = raw_content.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        return payload

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_content, flags=re.DOTALL)
    if fenced_match is None:
        return None
    try:
        payload = json.loads(fenced_match.group(1))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _first_non_empty_line(raw_content: str) -> str | None:
    for line in raw_content.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:200]
    return None


__all__ = [
    "RpBridgeNormalizationError",
    "normalize_implement_capture",
    "normalize_review_capture",
]
