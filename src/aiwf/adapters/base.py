"""Adapter protocol definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from aiwf.models import StageResult, TaskSpec


class RunnerAdapter(Protocol):
    """Protocol implemented by workflow execution adapters."""

    def discover(self, task: TaskSpec, run_dir: Path) -> str:
        """Return context pack content for a task."""

    def plan(self, task: TaskSpec, context: str) -> str:
        """Return execution plan content for a task."""

    def execute(self, task: TaskSpec, plan: str, run_dir: Path) -> StageResult:
        """Execute implementation work and return a stage result."""

    def review(self, task: TaskSpec, run_dir: Path) -> dict[str, object]:
        """Return review report content."""
