"""RepoPrompt agent adapter implementation."""

from __future__ import annotations

from pathlib import Path

from aiwf.adapters.base import HostCapabilities, HostContract, ReviewArtifactContract
from aiwf.exceptions import AdapterError
from aiwf.models import RunStatus, StageResult, TaskSpec


class RpAgentAdapter:
    """Manual-first RepoPrompt agent adapter."""

    def __init__(self, repo_root: str | Path = ".", *, max_snapshot_entries: int = 60) -> None:
        self.repo_root = Path(repo_root)
        self.max_snapshot_entries = max_snapshot_entries
        self.host_contract = HostContract(
            adapter="rp",
            mode="manual",
            capabilities=HostCapabilities(
                supports_auto_execution=False,
                requires_explicit_review_handoff=True,
            ),
            review=ReviewArtifactContract(
                required_run_artifacts=("verify-report.json",),
                required_report_string_fields=("summary", "mode", "prompt_file"),
                required_report_list_fields=("issues",),
                expected_report_mode="manual",
                linked_report_artifact_field="prompt_file",
            ),
        )

    def discover(self, task: TaskSpec, run_dir: Path) -> str:
        """Build a RepoPrompt-oriented local context pack without invoking an external host."""
        if not self.repo_root.exists():
            raise AdapterError("Repository root does not exist", path=self.repo_root, stage="discover")
        if not self.repo_root.is_dir():
            raise AdapterError("Repository root is not a directory", path=self.repo_root, stage="discover")

        repo_snapshot = "\n".join(f"- {entry}" for entry in self._snapshot_repo())
        policy_text = self._read_optional_text(self.repo_root / ".ai" / "policies" / f"{task.policy}.md")
        runbook_text = self._read_optional_text(self.repo_root / ".ai" / "runbooks" / f"{task.runbook}.md")

        return "\n".join(
            [
                f"# RepoPrompt Context Pack for {task.title}",
                "",
                f"- task_slug: {task.slug}",
                f"- runbook: {task.runbook}",
                f"- policy: {task.policy}",
                f"- run_dir: {run_dir}",
                "",
                "## Task Body",
                task.body or "_No task body provided._",
                "",
                "## Repository Snapshot",
                repo_snapshot or "- _No files discovered_",
                "",
                "## Policy Excerpt",
                policy_text or "_Policy file not found or empty._",
                "",
                "## Runbook Excerpt",
                runbook_text or "_Runbook file not found or empty._",
            ]
        )

    def plan(self, task: TaskSpec, context: str) -> str:
        """Return a manual-friendly RepoPrompt planning brief."""
        prompt = self._build_plan_prompt(task, context)
        return "\n".join(
            [
                f"# RepoPrompt Agent Plan for {task.title}",
                "",
                "This run is using the RepoPrompt agent adapter MVP.",
                "Use the brief below in a RepoPrompt-capable agent session and preserve the aiwf artifact/state contract.",
                "",
                "## Suggested RepoPrompt Brief",
                "```text",
                prompt,
                "```",
            ]
        )

    def execute(self, task: TaskSpec, plan: str, run_dir: Path) -> StageResult:
        """Write an implementation handoff brief and block for external agent execution."""
        prompt = self._build_execute_prompt(task, plan, run_dir)
        prompt_path = run_dir / "rp-agent-implement-prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        return StageResult(
            stage="implement",
            status=RunStatus.blocked,
            summary=f"RepoPrompt implementation handoff prompt written for {task.title}",
            outputs=[prompt_path.name],
            metadata={"mode": "manual", "prompt_file": prompt_path.name},
        )

    def review(self, task: TaskSpec, run_dir: Path) -> dict[str, object]:
        """Write a review handoff brief and block for external agent review."""
        prompt = self._build_review_prompt(task, run_dir)
        prompt_path = run_dir / "rp-agent-review-prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        return {
            "summary": f"RepoPrompt review handoff prompt written for {task.title}",
            "issues": [],
            "mode": "manual",
            "prompt_file": prompt_path.name,
        }

    def _build_plan_prompt(self, task: TaskSpec, context: str) -> str:
        return "\n".join(
            [
                f"Task: {task.title}",
                "",
                "Generate a concise implementation plan for this repository task.",
                "Follow existing aiwf workflow, artifact, and resume semantics.",
                "Keep the MVP pragmatic and avoid unrelated architecture redesign.",
                "",
                "Task details:",
                task.body or "(no task body provided)",
                "",
                "Context:",
                context,
            ]
        )

    def _build_execute_prompt(self, task: TaskSpec, plan: str, run_dir: Path) -> str:
        return "\n".join(
            [
                f"Task: {task.title}",
                "",
                f"Run directory: {run_dir}",
                "Implement the approved plan in the repository.",
                "Preserve the aiwf artifact/state contract and prepare the repo for deterministic gates.",
                "Do not redesign the host abstraction; keep changes scoped to the task.",
                "",
                "Plan:",
                plan,
            ]
        )

    def _build_review_prompt(self, task: TaskSpec, run_dir: Path) -> str:
        return "\n".join(
            [
                f"Task: {task.title}",
                "",
                f"Run directory: {run_dir}",
                "Review the current implementation results and existing run artifacts.",
                "Focus on correctness, missing validation, and follow-up work.",
                "",
                "Inspect at minimum:",
                f"- {run_dir / 'context-pack.md'}",
                f"- {run_dir / 'exec-plan.md'}",
                f"- {run_dir / 'verify-report.json'}",
            ]
        )

    def _snapshot_repo(self) -> list[str]:
        entries: list[str] = []
        # TODO: consider .gitignore-aware or configurable exclusions if the MVP snapshot becomes too noisy.
        skipped = {".git", ".venv", ".ai", "__pycache__", ".mypy_cache", ".pytest_cache", "node_modules"}
        for path in sorted(self.repo_root.rglob("*")):
            if any(part in skipped for part in path.parts):
                continue
            if path.is_dir():
                continue
            try:
                relative = path.relative_to(self.repo_root)
            except ValueError:
                continue
            entries.append(str(relative))
            if len(entries) >= self.max_snapshot_entries:
                break
        return entries

    def _read_optional_text(self, path: Path) -> str:
        if not path.exists() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8").strip()
