"""RepoPrompt agent adapter placeholder for a later milestone."""

from __future__ import annotations

from pathlib import Path

from aiwf.models import StageResult, TaskSpec


class RpAgentAdapter:
    """Phase-two placeholder adapter."""

    def discover(self, task: TaskSpec, run_dir: Path) -> str:
        raise NotImplementedError("RpAgentAdapter is planned for a later milestone.")

    def plan(self, task: TaskSpec, context: str) -> str:
        raise NotImplementedError("RpAgentAdapter is planned for a later milestone.")

    def execute(self, task: TaskSpec, plan: str, run_dir: Path) -> StageResult:
        raise NotImplementedError("RpAgentAdapter is planned for a later milestone.")

    def review(self, task: TaskSpec, run_dir: Path) -> dict[str, object]:
        raise NotImplementedError("RpAgentAdapter is planned for a later milestone.")
