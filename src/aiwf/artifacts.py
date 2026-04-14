"""Artifact persistence helpers for workflow runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from aiwf.exceptions import ArtifactError
from aiwf.models import EventRecord
from aiwf.state import RunStateManager


class ArtifactStore:
    """Write and read standard run artifacts within a run directory."""

    def __init__(self, run_dir: str | Path, state_manager: RunStateManager | None = None) -> None:
        self.run_dir = Path(run_dir)
        self.run_id = self.run_dir.name
        self._ensure_run_dir()
        self._state_manager = state_manager or RunStateManager(self._infer_ai_root())

    def write_context_pack(self, content: str) -> Path:
        """Persist `context-pack.md`."""
        return self._write_text_artifact("context-pack.md", content)

    def write_exec_plan(self, content: str) -> Path:
        """Persist `exec-plan.md`."""
        return self._write_text_artifact("exec-plan.md", content)

    def write_verify_report(self, report: BaseModel | dict[str, Any]) -> Path:
        """Persist `verify-report.json`."""
        return self._write_json_artifact("verify-report.json", report)

    def write_review_report(self, report: BaseModel | dict[str, Any]) -> Path:
        """Persist `review-report.json`."""
        return self._write_json_artifact("review-report.json", report)

    def write_work_receipt(self, receipt: BaseModel | dict[str, Any]) -> Path:
        """Persist `work-receipt.json`."""
        return self._write_json_artifact("work-receipt.json", receipt)

    def read_artifact(self, name: str) -> str | dict[str, Any]:
        """Read a stored artifact by filename."""
        artifact_path = self.run_dir / name
        try:
            content = artifact_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ArtifactError("Artifact does not exist", path=artifact_path, stage="read_artifact") from exc
        except OSError as exc:
            raise ArtifactError("Failed to read artifact", path=artifact_path, stage="read_artifact") from exc

        if artifact_path.suffix == ".json":
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as exc:
                raise ArtifactError(
                    "Artifact JSON is invalid",
                    path=artifact_path,
                    stage="read_artifact",
                ) from exc
            if not isinstance(parsed, dict):
                raise ArtifactError(
                    "Artifact JSON must be an object",
                    path=artifact_path,
                    stage="read_artifact",
                )
            return parsed

        return content

    def _write_text_artifact(self, filename: str, content: str) -> Path:
        artifact_path = self.run_dir / filename
        try:
            artifact_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise ArtifactError("Failed to write artifact", path=artifact_path, stage="write_artifact") from exc
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
            raise ArtifactError("Failed to write artifact", path=artifact_path, stage="write_artifact") from exc
        self._record_artifact_written(filename)
        return artifact_path

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
            raise ArtifactError("Run directory does not exist", path=self.run_dir, stage="artifact_init")
        if not self.run_dir.is_dir():
            raise ArtifactError("Run path is not a directory", path=self.run_dir, stage="artifact_init")

    def _infer_ai_root(self) -> Path:
        if self.run_dir.parent.name == "runs":
            return self.run_dir.parent.parent
        raise ArtifactError(
            "Run directory must live under `.ai/runs/<run_id>`",
            path=self.run_dir,
            stage="artifact_init",
        )
