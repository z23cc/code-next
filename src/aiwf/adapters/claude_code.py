"""Claude Code adapter implementations."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

from aiwf.exceptions import AdapterError
from aiwf.models import RunStatus, StageResult, TaskSpec


class ClaudeCodeAdapter:
    """Thin Claude Code adapter with manual-first and optional auto subprocess modes."""

    def __init__(
        self,
        repo_root: str | Path = ".",
        *,
        auto: bool = False,
        claude_command: Sequence[str] | None = None,
        max_snapshot_entries: int = 60,
        claude_timeout: int = 300,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.auto = auto
        self.claude_command = list(claude_command) if claude_command is not None else ["claude", "--print"]
        self.max_snapshot_entries = max_snapshot_entries
        self.claude_timeout = claude_timeout

    def discover(self, task: TaskSpec, run_dir: Path) -> str:
        """Build a local repository context pack. Always local; never calls Claude CLI."""
        if not self.repo_root.exists():
            raise AdapterError("Repository root does not exist", path=self.repo_root, stage="discover")
        if not self.repo_root.is_dir():
            raise AdapterError("Repository root is not a directory", path=self.repo_root, stage="discover")

        repo_snapshot = "\n".join(f"- {entry}" for entry in self._snapshot_repo())
        policy_text = self._read_optional_text(self.repo_root / ".ai" / "policies" / f"{task.policy}.md")
        runbook_text = self._read_optional_text(self.repo_root / ".ai" / "runbooks" / f"{task.runbook}.md")

        return "\n".join(
            [
                f"# Claude Context Pack for {task.title}",
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
        """Return a plan artifact or Claude-generated output."""
        prompt = self._build_plan_prompt(task, context)
        if self.auto:
            return self._run_claude(prompt, stage="plan")

        return "\n".join(
            [
                f"# Claude Code Plan for {task.title}",
                "",
                "This run is using the manual-friendly Claude adapter mode.",
                "Copy the prompt below into Claude Code and refine the plan if needed.",
                "",
                "## Suggested Claude Prompt",
                "```text",
                prompt,
                "```",
            ]
        )

    def execute(self, task: TaskSpec, plan: str, run_dir: Path) -> StageResult:
        """Prepare or execute implementation via Claude Code."""
        prompt = self._build_execute_prompt(task, plan, run_dir)
        if self.auto:
            response = self._run_claude(prompt, stage="implement", path=run_dir)
            response_path = run_dir / "claude-implement-response.md"
            response_path.write_text(response, encoding="utf-8")
            return StageResult(
                stage="implement",
                status=RunStatus.passed,
                summary=f"Claude auto execution completed for {task.title}",
                outputs=[response_path.name],
                metadata={"mode": "auto", "response_file": response_path.name},
            )

        prompt_path = run_dir / "claude-implement-prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        return StageResult(
            stage="implement",
            status=RunStatus.passed,
            summary=f"Manual Claude implementation prompt written for {task.title}",
            outputs=[prompt_path.name],
            metadata={"mode": "manual", "prompt_file": prompt_path.name},
        )

    def review(self, task: TaskSpec, run_dir: Path) -> dict[str, object]:
        """Prepare or execute a Claude review step."""
        prompt = self._build_review_prompt(task, run_dir)
        if self.auto:
            response = self._run_claude(prompt, stage="review", path=run_dir)
            response_path = run_dir / "claude-review-response.md"
            response_path.write_text(response, encoding="utf-8")
            return {
                "summary": f"Claude auto review completed for {task.title}",
                "issues": [],
                "mode": "auto",
                "response_file": response_path.name,
                "response_excerpt": response.splitlines()[0] if response else "",
            }

        prompt_path = run_dir / "claude-review-prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        return {
            "summary": f"Manual Claude review prompt written for {task.title}",
            "issues": [],
            "mode": "manual",
            "prompt_file": prompt_path.name,
        }

    def _build_plan_prompt(self, task: TaskSpec, context: str) -> str:
        return "\n".join(
            [
                f"Task: {task.title}",
                "",
                "Generate an implementation plan for this repository task.",
                "Preserve the existing aiwf artifact/state contract.",
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
                "Implement the approved plan and prepare the repo for deterministic gates.",
                "Preserve the aiwf artifact/state contract.",
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
                "Review the current implementation results, gates, and artifacts.",
                "Call out risks, missing tests, and follow-up work.",
            ]
        )

    def _run_claude(self, prompt: str, *, stage: str, path: Path | None = None) -> str:
        try:
            completed = subprocess.run(
                self.claude_command,
                cwd=self.repo_root,
                input=prompt,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.claude_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise AdapterError("Claude CLI timed out", path=path or self.repo_root, stage=stage) from exc
        except FileNotFoundError as exc:
            raise AdapterError("Claude CLI is not available", path=path or self.repo_root, stage=stage) from exc
        except OSError as exc:
            raise AdapterError("Failed to invoke Claude CLI", path=path or self.repo_root, stage=stage) from exc

        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "Claude CLI returned a failure"
            raise AdapterError(message, path=path or self.repo_root, stage=stage)
        return completed.stdout.strip()

    def _snapshot_repo(self) -> list[str]:
        entries: list[str] = []
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
