"""RepoPrompt agent adapter implementation."""

from __future__ import annotations

import fnmatch
import json
import subprocess
from pathlib import Path
from typing import Any

from aiwf.adapters.base import HostCapabilities, HostContract, NativeRuntimeContract, ReviewArtifactContract
from aiwf.exceptions import AdapterError
from aiwf.models import RunStatus, StageResult, TaskSpec


# Safety-net exclusions applied before `.gitignore` rules.
# These intentionally cannot be re-included via negation patterns.
_MAX_REVIEW_SUMMARY_ITEMS = 8


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

RP_NATIVE_RUNTIME = NativeRuntimeContract(
    enabled=True,
    command_candidates=("rp", "rp-cli"),
    install_hint=(
        "Install a RepoPrompt runtime on PATH (for example `rp` or `rp-cli`) "
        "to make RP native-ready; manual handoff remains supported."
    ),
)

RP_MANUAL_CONTRACT = HostContract(
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
    native_runtime=RP_NATIVE_RUNTIME,
)


class RpAgentAdapter:
    """Manual-first RepoPrompt adapter with native-runtime contract scaffolding."""

    def __init__(
        self,
        repo_root: str | Path = ".",
        *,
        host_contract: HostContract | None = None,
        max_snapshot_entries: int = 60,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.max_snapshot_entries = max_snapshot_entries
        self.host_contract = host_contract or RP_MANUAL_CONTRACT
        if self.host_contract.adapter != "rp":
            raise ValueError("RpAgentAdapter requires an rp host contract")
        if self.host_contract.mode != "manual":
            raise ValueError("RpAgentAdapter currently supports manual mode only")

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
        evidence_summary = self._build_review_evidence_summary(run_dir)
        prompt = self._build_review_prompt(task, run_dir, evidence_summary=evidence_summary)
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
            "evidence_summary": evidence_summary,
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

    def _build_review_prompt(
        self,
        task: TaskSpec,
        run_dir: Path,
        *,
        evidence_summary: dict[str, object] | None = None,
    ) -> str:
        summary = evidence_summary or self._build_review_evidence_summary(run_dir)
        evidence_files = self._review_evidence_files(run_dir)

        lines = [
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
            f"- verify: {summary['verify']}",
        ]
        gate_results = summary.get("gate_results")
        if isinstance(gate_results, list) and gate_results:
            lines.extend(f"- gate: {line}" for line in gate_results)
        lines.extend(
            [
                f"- diagnostics: {summary['diagnostics']}",
                f"- provenance: {summary['provenance']}",
            ]
        )
        changed_files = summary.get("changed_files")
        if isinstance(changed_files, list) and changed_files:
            lines.extend([
                "- changed files:",
                *[f"  - {line}" for line in changed_files],
            ])
        diff_summary = summary.get("diff_summary")
        if isinstance(diff_summary, list) and diff_summary:
            lines.extend([
                "- diff summary:",
                *[f"  - {line}" for line in diff_summary],
            ])
        lines.extend(
            [
                "",
                "Review checklist:",
                "- Confirm the implementation artifacts align with the task and execution plan.",
                "- Use verify diagnostics/provenance to call out missing validation or suspicious gaps.",
                "- Record concrete issues and follow-up work before the run is resumed.",
            ]
        )
        return "\n".join(lines)

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

    def _build_review_evidence_summary(self, run_dir: Path) -> dict[str, object]:
        changed_files, diff_summary = self._collect_repo_change_evidence()
        return {
            "verify": self._summarize_verify_report(run_dir / "verify-report.json"),
            "gate_results": self._summarize_gate_results(run_dir / "verify-report.json"),
            "diagnostics": self._summarize_diagnostics(run_dir / "run-diagnostics.json"),
            "provenance": self._summarize_provenance(run_dir / "run-provenance.json"),
            "changed_files": changed_files,
            "diff_summary": diff_summary,
        }

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

    def _summarize_gate_results(self, path: Path) -> list[str]:
        payload = self._read_optional_json(path)
        if payload is None:
            return []
        results = payload.get("results")
        if not isinstance(results, list):
            return []
        summaries: list[str] = []
        for result in results:
            if not isinstance(result, dict):
                continue
            name = self._json_string(result, "name") or "gate"
            passed = result.get("passed")
            returncode = result.get("returncode")
            timed_out = result.get("timed_out")
            duration = result.get("duration_seconds")
            state = "passed" if passed is True else "failed" if passed is False else "unknown"
            details: list[str] = []
            if isinstance(returncode, int):
                details.append(f"rc={returncode}")
            if timed_out is True:
                details.append("timed_out")
            if isinstance(duration, int | float):
                details.append(f"{duration:.2f}s")
            suffix = f" ({', '.join(details)})" if details else ""
            summaries.append(f"{name}: {state}{suffix}")
        return self._limit_summary_items(summaries)

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

    def _collect_repo_change_evidence(self) -> tuple[list[str], list[str]]:
        changed_files = self._git_status_summary()
        diff_summary = self._git_diff_summary()
        return changed_files, diff_summary

    def _git_status_summary(self) -> list[str]:
        output = self._run_git_command(["status", "--short", "--untracked-files=all"])
        if not output:
            return []
        lines = [line.rstrip() for line in output.splitlines() if line.strip()]
        return self._limit_summary_items(lines)

    def _git_diff_summary(self) -> list[str]:
        summaries: list[str] = []
        for args in (
            ["diff", "--stat", "--find-renames", "--cached"],
            ["diff", "--stat", "--find-renames"],
        ):
            output = self._run_git_command(args)
            if not output:
                continue
            for line in output.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped[0].isdigit() and " file" in stripped and " changed" in stripped:
                    continue
                if stripped not in summaries:
                    summaries.append(stripped)
        return self._limit_summary_items(summaries)

    def _run_git_command(self, args: list[str]) -> str | None:
        try:
            completed = subprocess.run(
                ["git", "-C", str(self.repo_root), *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.strip()

    def _limit_summary_items(self, items: list[str]) -> list[str]:
        if len(items) <= _MAX_REVIEW_SUMMARY_ITEMS:
            return items
        remaining = len(items) - _MAX_REVIEW_SUMMARY_ITEMS
        return [*items[:_MAX_REVIEW_SUMMARY_ITEMS], f"... +{remaining} more"]

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
