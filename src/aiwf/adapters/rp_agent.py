"""RepoPrompt agent adapter implementation."""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any

from aiwf.adapters.base import HostCapabilities, HostContract, ReviewArtifactContract
from aiwf.exceptions import AdapterError
from aiwf.models import RunStatus, StageResult, TaskSpec


# Safety-net exclusions applied before `.gitignore` rules.
# These intentionally cannot be re-included via negation patterns.
_SKIPPED_PATH_PARTS = {
    ".ai",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    ".ruff_cache",
    ".tox",
    ".nox",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "htmlcov",
}


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
        evidence_files = self._review_evidence_files(run_dir)
        return {
            # Contract-required fields validated by the shared review contract.
            "summary": f"RepoPrompt review handoff prompt written for {task.title}",
            "issues": [],
            "mode": "manual",
            "prompt_file": prompt_path.name,
            # Informational evidence pointers for operator tooling and manual review.
            "verify_report_file": "verify-report.json",
            "diagnostics_file": "run-diagnostics.json",
            "provenance_file": "run-provenance.json",
            "evidence_files": evidence_files,
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
        verify_summary = self._summarize_verify_report(run_dir / "verify-report.json")
        diagnostics_summary = self._summarize_diagnostics(run_dir / "run-diagnostics.json")
        provenance_summary = self._summarize_provenance(run_dir / "run-provenance.json")
        evidence_files = self._review_evidence_files(run_dir)

        return "\n".join(
            [
                f"Task: {task.title}",
                "",
                f"Run directory: {run_dir}",
                "Review the current implementation results and existing run artifacts.",
                "Focus on correctness, missing validation, follow-up work, and any mismatch between artifacts and run state.",
                "",
                "Inspect at minimum:",
                f"- {run_dir / 'context-pack.md'}",
                f"- {run_dir / 'exec-plan.md'}",
                f"- {run_dir / 'verify-report.json'}",
                f"- {run_dir / 'run-diagnostics.json'}",
                f"- {run_dir / 'run-provenance.json'}",
                "",
                "Available review evidence files:",
                *[f"- {run_dir / name}" for name in evidence_files],
                "",
                "Evidence summary:",
                f"- verify: {verify_summary}",
                f"- diagnostics: {diagnostics_summary}",
                f"- provenance: {provenance_summary}",
                "",
                "Review checklist:",
                "- Confirm the implementation artifacts align with the task and execution plan.",
                "- Use verify diagnostics/provenance to call out missing validation or suspicious gaps.",
                "- Record concrete issues and follow-up work before the run is resumed.",
            ]
        )

    def _snapshot_repo(self) -> list[str]:
        entries: list[str] = []
        ignore_matcher = _GitIgnoreMatcher.from_repo_root(self.repo_root)
        for path in sorted(self.repo_root.rglob("*")):
            if any(part in _SKIPPED_PATH_PARTS for part in path.parts):
                continue
            if path.is_dir():
                continue
            try:
                relative = path.relative_to(self.repo_root)
            except ValueError:
                continue
            if ignore_matcher.matches(relative):
                continue
            entries.append(str(relative))
            if len(entries) >= self.max_snapshot_entries:
                break
        return entries

    def _read_optional_text(self, path: Path) -> str:
        if not path.exists() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def _review_evidence_files(self, run_dir: Path) -> list[str]:
        preferred = [
            "context-pack.md",
            "exec-plan.md",
            "verify-report.json",
            "run-diagnostics.json",
            "run-provenance.json",
            "work-receipt.json",
            "rp-agent-implement-prompt.md",
        ]
        return [name for name in preferred if (run_dir / name).exists()]

    def _summarize_verify_report(self, path: Path) -> str:
        payload = self._read_optional_json(path)
        if payload is None:
            return "verify report missing"
        gate_set = self._json_string(payload, "gate_set") or "-"
        passed = payload.get("passed", "-")
        failed_gates = [
            str(result.get("name")).strip()
            for result in payload.get("results", [])
            if isinstance(result, dict) and result.get("passed") is False and isinstance(result.get("name"), str)
        ]
        failure_suffix = f" failed={','.join(failed_gates)}" if failed_gates else ""
        return f"gate_set={gate_set} passed={passed}{failure_suffix}"

    def _summarize_diagnostics(self, path: Path) -> str:
        payload = self._read_optional_json(path)
        if payload is None:
            return "run diagnostics missing"
        status = self._json_string(payload, "status") or "-"
        reason = self._json_string(payload, "status_reason") or "-"
        reviewable = payload.get("reviewable")
        resumable = payload.get("resumable")
        return f"status={status} reviewable={reviewable} resumable={resumable} reason={reason}"

    def _summarize_provenance(self, path: Path) -> str:
        payload = self._read_optional_json(path)
        if payload is None:
            return "run provenance missing"
        review_evidence = payload.get("review_evidence")
        gate_evidence = payload.get("gate_evidence")
        linked_count = 0
        required_available_count = 0
        gate_report = "-"
        if isinstance(review_evidence, dict):
            linked = review_evidence.get("linked_artifacts")
            available_required = review_evidence.get("available_required_artifacts")
            if isinstance(linked, list):
                linked_count = len(linked)
            if isinstance(available_required, list):
                required_available_count = len(available_required)
        if isinstance(gate_evidence, dict):
            report = gate_evidence.get("report")
            if isinstance(report, dict):
                gate_report = self._json_string(report, "path") or "-"
        return (
            f"gate_report={gate_report} "
            f"review_linked_artifacts={linked_count} "
            f"review_required_artifacts_available={required_available_count}"
        )

    def _read_optional_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists() or not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _json_string(self, payload: dict[str, Any], key: str) -> str | None:
        value = payload.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None


class _GitIgnoreMatcher:
    """Very small `.gitignore` matcher for RP snapshot filtering."""

    def __init__(self, rules: list[tuple[bool, str, bool, bool]]) -> None:
        self._rules = rules

    @classmethod
    def from_repo_root(cls, repo_root: Path) -> _GitIgnoreMatcher:
        """Load rules from the repository root `.gitignore` only."""
        ignore_file = repo_root / ".gitignore"
        if not ignore_file.exists() or not ignore_file.is_file():
            return cls([])
        try:
            lines = ignore_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return cls([])

        rules: list[tuple[bool, str, bool, bool]] = []
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            negated = line.startswith("!")
            if negated:
                line = line[1:].strip()
            dir_only = line.endswith("/")
            pattern = line.rstrip("/")
            anchored = pattern.startswith("/")
            pattern = pattern.lstrip("/")
            if pattern:
                rules.append((negated, pattern, dir_only, anchored))
        return cls(rules)

    def matches(self, relative_path: Path) -> bool:
        relative_posix = relative_path.as_posix()
        parts = relative_path.parts
        ignored = False
        for negated, pattern, dir_only, anchored in self._rules:
            if self._matches_pattern(relative_posix, parts, pattern, dir_only=dir_only, anchored=anchored):
                ignored = not negated
        return ignored

    def _matches_pattern(
        self,
        relative_posix: str,
        parts: tuple[str, ...],
        pattern: str,
        *,
        dir_only: bool,
        anchored: bool,
    ) -> bool:
        if dir_only:
            return any(fnmatch.fnmatch(part, pattern) for part in parts[:-1])
        if "/" not in pattern:
            return any(fnmatch.fnmatch(part, pattern) for part in parts)
        if anchored:
            return fnmatch.fnmatch(relative_posix, pattern)
        return any(fnmatch.fnmatch("/".join(parts[index:]), pattern) for index in range(len(parts)))
