"""Artifact persistence helpers for workflow runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar, cast

from pydantic import BaseModel, ValidationError

from aiwf.exceptions import ArtifactError, ErrorCode
from aiwf.models import (
    RpBridgeAgentLogArtifactContent,
    RpBridgeAgentTranscriptArtifactContent,
    EventRecord,
    ReviewReportContent,
    RpBridgeCaptureArtifactContent,
    RpBridgeSeedingArtifactContent,
    VerifyReportContent,
    WorkReceiptContent,
)
from aiwf.state import RunStateManager


ArtifactModelT = TypeVar("ArtifactModelT", bound=BaseModel)

_VALIDATED_ARTIFACT_SCHEMAS: dict[str, type[BaseModel]] = {
    "verify-report.json": VerifyReportContent,
    "review-report.json": ReviewReportContent,
    "rp-bridge-agent-log.json": RpBridgeAgentLogArtifactContent,
    "rp-bridge-agent-transcript.json": RpBridgeAgentTranscriptArtifactContent,
    "rp-bridge-capture.json": RpBridgeCaptureArtifactContent,
    "rp-bridge-seeding.json": RpBridgeSeedingArtifactContent,
    "work-receipt.json": WorkReceiptContent,
}


class ArtifactStore:
    """Write and read standard run artifacts within a run directory."""

    def __init__(self, run_dir: str | Path, state_manager: RunStateManager | None = None) -> None:
        self.run_dir = Path(run_dir)
        self.run_id = self.run_dir.name
        self._ensure_run_dir()
        self._state_manager = state_manager or RunStateManager(self._infer_ai_root())

    def write_text_artifact(self, name: str, content: str) -> Path:
        """Persist an arbitrary text artifact."""
        return self._write_text_artifact(name, content)

    def write_context_pack(self, content: str) -> Path:
        """Persist `context-pack.md`."""
        return self._write_text_artifact("context-pack.md", content)

    def write_exec_plan(self, content: str) -> Path:
        """Persist `exec-plan.md`."""
        return self._write_text_artifact("exec-plan.md", content)

    def write_json_artifact(self, name: str, payload: BaseModel | dict[str, Any]) -> Path:
        """Persist an arbitrary JSON artifact."""
        return self._write_json_artifact(name, payload)

    def write_verify_report(self, report: BaseModel | dict[str, Any]) -> Path:
        """Persist `verify-report.json`."""
        return self._write_json_artifact("verify-report.json", report)

    def write_review_report(self, report: BaseModel | dict[str, Any]) -> Path:
        """Persist `review-report.json`."""
        return self._write_json_artifact("review-report.json", report)

    def write_work_receipt(self, receipt: BaseModel | dict[str, Any]) -> Path:
        """Persist `work-receipt.json`."""
        return self._write_json_artifact("work-receipt.json", receipt)

    def write_run_diagnostics(self, diagnostics: BaseModel | dict[str, Any]) -> Path:
        """Persist `run-diagnostics.json`."""
        return self._write_json_artifact("run-diagnostics.json", diagnostics)

    def write_run_provenance(self, provenance: BaseModel | dict[str, Any]) -> Path:
        """Persist `run-provenance.json`."""
        return self._write_json_artifact("run-provenance.json", provenance)

    def read_artifact(self, name: str) -> str | dict[str, Any]:
        """Read a stored artifact by filename."""
        artifact_path = self.run_dir / name
        content = self._read_artifact_text(artifact_path, stage="read_artifact")

        if artifact_path.suffix == ".json":
            return self._parse_json_artifact(content, artifact_path, stage="read_artifact")

        return content

    def read_validated_artifact(
        self,
        name: str,
        schema_cls: type[ArtifactModelT] | None = None,
    ) -> ArtifactModelT:
        """Read and validate a known JSON artifact against a registered or supplied schema."""
        artifact_path = self.run_dir / name
        content = self._read_artifact_text(artifact_path, stage="read_validated_artifact")
        parsed = self._parse_json_artifact(content, artifact_path, stage="read_validated_artifact")
        resolved_schema = schema_cls or self.validation_schema_for(name)
        if resolved_schema is None:
            raise ArtifactError(
                f"Artifact {name!r} does not have a registered validation schema",
                path=artifact_path,
                stage="read_validated_artifact",
                error_code=ErrorCode.INVALID_ARTIFACT,
            )
        try:
            return cast(ArtifactModelT, resolved_schema.model_validate(parsed))
        except ValidationError as exc:
            raise ArtifactError(
                f"Artifact content failed validation: {self._format_validation_errors(exc)}",
                path=artifact_path,
                stage="read_validated_artifact",
                error_code=ErrorCode.INVALID_ARTIFACT,
            ) from exc

    @classmethod
    def validation_schema_for(cls, name: str) -> type[BaseModel] | None:
        """Return the registered validation schema for a known artifact filename."""
        return _VALIDATED_ARTIFACT_SCHEMAS.get(name)

    def _write_text_artifact(self, filename: str, content: str) -> Path:
        artifact_path = self.run_dir / filename
        try:
            artifact_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise ArtifactError(
                "Failed to write artifact",
                path=artifact_path,
                stage="write_artifact",
                error_code=ErrorCode.INVALID_ARTIFACT,
            ) from exc
        self._record_artifact_written(filename)
        return artifact_path

    def _write_json_artifact(self, filename: str, payload: BaseModel | dict[str, Any]) -> Path:
        artifact_path = self.run_dir / filename
        data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        try:
            artifact_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise ArtifactError(
                "Failed to write artifact",
                path=artifact_path,
                stage="write_artifact",
                error_code=ErrorCode.INVALID_ARTIFACT,
            ) from exc
        self._record_artifact_written(filename)
        return artifact_path

    def _read_artifact_text(self, artifact_path: Path, *, stage: str) -> str:
        try:
            return artifact_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ArtifactError(
                "Artifact does not exist",
                path=artifact_path,
                stage=stage,
                error_code=ErrorCode.MISSING_ARTIFACT,
            ) from exc
        except OSError as exc:
            raise ArtifactError(
                "Failed to read artifact",
                path=artifact_path,
                stage=stage,
                error_code=ErrorCode.INVALID_ARTIFACT,
            ) from exc

    def _parse_json_artifact(self, content: str, artifact_path: Path, *, stage: str) -> dict[str, Any]:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ArtifactError(
                "Artifact JSON is invalid",
                path=artifact_path,
                stage=stage,
                error_code=ErrorCode.INVALID_ARTIFACT,
            ) from exc
        if not isinstance(parsed, dict):
            raise ArtifactError(
                "Artifact JSON must be an object",
                path=artifact_path,
                stage=stage,
                error_code=ErrorCode.INVALID_ARTIFACT,
            )
        return parsed

    def _format_validation_errors(self, exc: ValidationError) -> str:
        details: list[str] = []
        for error in exc.errors(include_url=False):
            location = ".".join(str(part) for part in error.get("loc", ()))
            message = str(error.get("msg", "Validation error"))
            details.append(f"{location}: {message}" if location else message)
        return "; ".join(details)

    def _record_artifact_written(self, filename: str) -> None:
        self._state_manager.append_event(
            self.run_id,
            EventRecord(
                event="artifact_written",
                data={"artifact": filename},
            ),
        )

    def _ensure_run_dir(self) -> None:
        if not self.run_dir.exists():
            raise ArtifactError(
                "Run directory does not exist",
                path=self.run_dir,
                stage="artifact_init",
                error_code=ErrorCode.MISSING_ARTIFACT,
            )
        if not self.run_dir.is_dir():
            raise ArtifactError(
                "Run path is not a directory",
                path=self.run_dir,
                stage="artifact_init",
                error_code=ErrorCode.INVALID_ARTIFACT,
            )

    def _infer_ai_root(self) -> Path:
        if self.run_dir.parent.name == "runs":
            return self.run_dir.parent.parent
        raise ArtifactError(
            "Run directory must live under `.ai/runs/<run_id>`",
            path=self.run_dir,
            stage="artifact_init",
            error_code=ErrorCode.INVALID_ARTIFACT,
        )
