"""Stub adapter used for M3 orchestration and tests."""

from __future__ import annotations

from pathlib import Path

from aiwf.adapters.base import HostCapabilities, HostContract, ReviewArtifactContract
from aiwf.exceptions import AdapterError
from aiwf.models import RunStatus, StageResult, TaskSpec


class StubRunnerAdapter:
    """Deterministic in-process adapter for orchestration tests."""

    def __init__(self, fail_stages: set[str] | None = None) -> None:
        self.fail_stages = fail_stages or set()
        self.host_contract = HostContract(
            adapter="stub",
            mode="manual",
            capabilities=HostCapabilities(
                supports_auto_execution=False,
                requires_explicit_review_handoff=False,
            ),
            review=ReviewArtifactContract(
                required_run_artifacts=("verify-report.json",),
                required_report_string_fields=("summary",),
                required_report_list_fields=("issues",),
            ),
        )

    def discover(self, task: TaskSpec, run_dir: Path) -> str:
        self._maybe_fail("discover", run_dir)
        return "\n".join(
            [
                f"# Context Pack for {task.title}",
                "",
                f"- task_slug: {task.slug}",
                f"- run_dir: {run_dir}",
                f"- policy: {task.policy}",
            ]
        )

    def plan(self, task: TaskSpec, context: str) -> str:
        self._maybe_fail("plan")
        return "\n".join(
            [
                f"# Execution Plan for {task.title}",
                "",
                "1. Review context",
                "2. Apply implementation changes",
                "3. Validate and review results",
                "",
                "## Context Summary",
                context,
            ]
        )

    def execute(self, task: TaskSpec, plan: str, run_dir: Path) -> StageResult:
        self._maybe_fail("implement", run_dir)
        return StageResult(
            stage="implement",
            status=RunStatus.passed,
            summary=f"Stub implementation completed for {task.title}",
            outputs=["verify-report.json", "review-report.json", "work-receipt.json"],
            metadata={"plan_excerpt": plan.splitlines()[0] if plan else "", "run_dir": str(run_dir)},
        )

    def review(self, task: TaskSpec, run_dir: Path) -> dict[str, object]:
        self._maybe_fail("review", run_dir)
        return {
            "summary": f"Stub review completed for {task.title}",
            "issues": [],
            "run_dir": str(run_dir),
        }

    def _maybe_fail(self, stage: str, run_dir: Path | None = None) -> None:
        if stage in self.fail_stages:
            raise AdapterError(
                f"Stub adapter forced failure during {stage}",
                path=run_dir,
                stage=stage,
            )
