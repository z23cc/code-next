"""RepoPrompt agent adapter implementation."""

from __future__ import annotations

import fnmatch
import json
import subprocess
from pathlib import Path
from typing import Any, Sequence

from aiwf.adapters.base import HostCapabilities, HostContract, NativeRuntimeContract, ReviewArtifactContract
from aiwf.exceptions import AdapterError, ErrorCode
from aiwf.models import RunStatus, StageResult, TaskSpec


# Safety-net exclusions applied before `.gitignore` rules.
# These intentionally cannot be re-included via negation patterns.
_MAX_REVIEW_SUMMARY_ITEMS = 8
_RP_PROTOCOL_NAME = "aiwf-rp-native"
_RP_PROTOCOL_VERSION = 1
_RP_PROTOCOL_PROBE_ARGUMENT = "--aiwf-protocol-version"
_RP_REQUEST_TYPE_BY_STAGE = {
    "plan": "plan",
    "implement": "execute",
    "review": "review",
}


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

RP_AUTO_CONTRACT = HostContract(
    adapter="rp",
    mode="auto",
    capabilities=HostCapabilities(
        supports_auto_execution=True,
        requires_explicit_review_handoff=False,
    ),
    review=ReviewArtifactContract(
        required_run_artifacts=("verify-report.json",),
        required_report_string_fields=("summary", "mode", "response_file"),
        required_report_list_fields=("issues",),
        expected_report_mode="auto",
        linked_report_artifact_field="response_file",
    ),
    native_runtime=RP_NATIVE_RUNTIME,
)


class RpAgentAdapter:
    """RepoPrompt adapter with manual fallback and a minimal native execution path."""

    def __init__(
        self,
        repo_root: str | Path = ".",
        *,
        auto: bool | None = None,
        host_contract: HostContract | None = None,
        rp_command: Sequence[str] | None = None,
        max_snapshot_entries: int = 60,
        rp_timeout: int = 300,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.max_snapshot_entries = max_snapshot_entries
        if host_contract is None:
            host_contract = RP_AUTO_CONTRACT if auto else RP_MANUAL_CONTRACT
        elif auto is not None and auto != host_contract.auto:
            raise ValueError("RpAgentAdapter auto flag does not match supplied host contract")
        self.host_contract = host_contract
        if self.host_contract.adapter != "rp":
            raise ValueError("RpAgentAdapter requires an rp host contract")
        if self.host_contract.mode not in {"manual", "auto"}:
            raise ValueError("RpAgentAdapter only supports manual or auto host contracts")
        self.auto = self.host_contract.auto
        self.rp_command = list(rp_command) if rp_command is not None else None
        self.rp_timeout = rp_timeout
        self._selected_rp_command: tuple[str, ...] | None = None
        self._selected_protocol_version: int | None = None

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
        """Return a RepoPrompt planning brief or native runtime output."""
        prompt = self._build_plan_prompt(task, context)
        if self.auto:
            return self._run_rp(prompt, stage="plan", task=task)
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
        """Write a manual handoff brief or execute via a native RepoPrompt runtime."""
        prompt = self._build_execute_prompt(task, plan, run_dir)
        if self.auto:
            response = self._run_rp(prompt, stage="implement", path=run_dir, task=task)
            response_path = run_dir / "rp-agent-implement-response.md"
            response_path.write_text(response, encoding="utf-8")
            return StageResult(
                stage="implement",
                status=RunStatus.passed,
                summary=f"RepoPrompt native execution completed for {task.title}",
                outputs=[response_path.name],
                metadata={"mode": "auto", "response_file": response_path.name},
            )

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
        """Write a manual review handoff brief or execute native review."""
        evidence_summary = self._build_review_evidence_summary(run_dir)
        prompt = self._build_review_prompt(task, run_dir, evidence_summary=evidence_summary)
        evidence_files = self._review_evidence_files(run_dir)
        if self.auto:
            response = self._run_rp(prompt, stage="review", path=run_dir, task=task)
            response_path = run_dir / "rp-agent-review-response.md"
            response_path.write_text(response, encoding="utf-8")
            return {
                "summary": f"RepoPrompt native review completed for {task.title}",
                "issues": [],
                "mode": "auto",
                "response_file": response_path.name,
                "response_excerpt": response.splitlines()[0] if response else "",
                "verify_report_file": "verify-report.json",
                "diagnostics_file": "run-diagnostics.json",
                "provenance_file": "run-provenance.json",
                "evidence_files": evidence_files,
                "evidence_summary": evidence_summary,
            }

        prompt_path = run_dir / "rp-agent-review-prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
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

    def _run_rp(
        self,
        prompt: str,
        *,
        stage: str,
        path: Path | None = None,
        task: TaskSpec | None = None,
    ) -> str:
        command, protocol_version = self._resolve_rp_runtime(stage=stage, path=path)
        runtime_input = prompt
        if protocol_version is not None:
            runtime_input = json.dumps(
                self._build_protocol_request(prompt, stage=stage, path=path, task=task, version=protocol_version),
                ensure_ascii=False,
            )

        completed = self._invoke_rp_runtime(command, runtime_input, stage=stage, path=path)
        if protocol_version is not None:
            payload = self._load_protocol_payload(completed.stdout)
            if payload is not None:
                if self._should_fallback_to_legacy(payload):
                    self._selected_protocol_version = None
                    return self._handle_legacy_rp_result(
                        self._invoke_rp_runtime(command, prompt, stage=stage, path=path),
                        stage=stage,
                        path=path,
                    )
                return self._handle_protocol_response(payload, stage=stage, path=path)
        return self._handle_legacy_rp_result(completed, stage=stage, path=path)

    def _resolve_rp_runtime(self, *, stage: str, path: Path | None = None) -> tuple[list[str], int | None]:
        if self._selected_rp_command is not None:
            return list(self._selected_rp_command), self._selected_protocol_version

        commands = [self.rp_command] if self.rp_command is not None else [
            [candidate] for candidate in self.host_contract.native_runtime.command_candidates
        ]
        missing_runtime = False
        for command in commands:
            runtime_available, protocol_version = self._probe_rp_protocol(command)
            if not runtime_available:
                missing_runtime = True
                continue
            self._selected_rp_command = tuple(command)
            self._selected_protocol_version = protocol_version
            return list(self._selected_rp_command), self._selected_protocol_version

        if missing_runtime:
            raise AdapterError(
                "RepoPrompt native runtime is not available",
                path=path or self.repo_root,
                stage=stage,
                error_code=ErrorCode.ADAPTER_UNAVAILABLE,
            )
        raise AdapterError(
            "RepoPrompt native runtime is not configured",
            path=path or self.repo_root,
            stage=stage,
            error_code=ErrorCode.ADAPTER_UNAVAILABLE,
        )

    def _probe_rp_protocol(self, command: Sequence[str]) -> tuple[bool, int | None]:
        try:
            completed = subprocess.run(
                [*command, _RP_PROTOCOL_PROBE_ARGUMENT],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=min(self.rp_timeout, 10),
            )
        except FileNotFoundError:
            return False, None
        except (OSError, subprocess.TimeoutExpired):
            return True, None

        payload = self._load_protocol_payload(completed.stdout)
        if completed.returncode == 0 and payload is not None:
            return True, _RP_PROTOCOL_VERSION
        return True, None

    def _invoke_rp_runtime(
        self,
        command: Sequence[str],
        runtime_input: str,
        *,
        stage: str,
        path: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                list(command),
                cwd=self.repo_root,
                input=runtime_input,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.rp_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise AdapterError(
                "RepoPrompt native runtime timed out",
                path=path or self.repo_root,
                stage=stage,
                error_code=ErrorCode.ADAPTER_TIMEOUT,
            ) from exc
        except FileNotFoundError as exc:
            raise AdapterError(
                "RepoPrompt native runtime is not available",
                path=path or self.repo_root,
                stage=stage,
                error_code=ErrorCode.ADAPTER_UNAVAILABLE,
            ) from exc
        except OSError as exc:
            raise AdapterError(
                "Failed to invoke RepoPrompt native runtime",
                path=path or self.repo_root,
                stage=stage,
                error_code=ErrorCode.ADAPTER_FAILURE,
            ) from exc

    def _build_protocol_request(
        self,
        prompt: str,
        *,
        stage: str,
        path: Path | None = None,
        task: TaskSpec | None = None,
        version: int,
    ) -> dict[str, Any]:
        context: dict[str, object] = {
            "adapter": "rp",
            "mode": "auto",
        }
        if task is not None:
            context["task_title"] = task.title
            if task.slug is not None:
                context["task_slug"] = task.slug
        if path is not None:
            run_dir = path if path.is_dir() else path.parent
            try:
                relative_run_dir = run_dir.relative_to(self.repo_root)
                context["run_dir"] = relative_run_dir.as_posix()
            except ValueError:
                context["run_dir"] = str(run_dir)
            context["run_id"] = run_dir.name
        return {
            "protocol": _RP_PROTOCOL_NAME,
            "version": version,
            "request_type": _RP_REQUEST_TYPE_BY_STAGE.get(stage, stage),
            "stage": stage,
            "prompt": prompt,
            "context": context,
            "options": {"timeout_seconds": self.rp_timeout},
            "metadata": {},
        }

    def _load_protocol_payload(self, raw_output: str) -> dict[str, Any] | None:
        stripped = raw_output.strip()
        if not stripped:
            return None
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("protocol") != _RP_PROTOCOL_NAME:
            return None
        version = payload.get("version")
        if not isinstance(version, int) or version < _RP_PROTOCOL_VERSION:
            return None
        return payload

    def _should_fallback_to_legacy(self, payload: dict[str, Any]) -> bool:
        if payload.get("status") != "error":
            return False
        error = payload.get("error")
        if not isinstance(error, dict):
            return False
        return error.get("code") == "UNSUPPORTED_VERSION"

    def _handle_protocol_response(self, payload: dict[str, Any], *, stage: str, path: Path | None = None) -> str:
        status = payload.get("status")
        content = payload.get("content")
        if status == "ok":
            if not isinstance(content, str):
                raise AdapterError(
                    "RepoPrompt native runtime returned an invalid protocol response",
                    path=path or self.repo_root,
                    stage=stage,
                    error_code=ErrorCode.ADAPTER_FAILURE,
                )
            return content.strip()
        if status not in {"error", "partial"}:
            raise AdapterError(
                "RepoPrompt native runtime returned an invalid protocol status",
                path=path or self.repo_root,
                stage=stage,
                error_code=ErrorCode.ADAPTER_FAILURE,
            )

        error = payload.get("error")
        runtime_code = None
        runtime_message = "RepoPrompt native runtime returned an error"
        if isinstance(error, dict):
            code_value = error.get("code")
            message_value = error.get("message")
            if isinstance(code_value, str) and code_value.strip():
                runtime_code = code_value.strip()
            if isinstance(message_value, str) and message_value.strip():
                runtime_message = message_value.strip()
        message_parts = [runtime_message]
        if runtime_code is not None:
            message_parts.insert(0, f"[{runtime_code}]")
        partial_content = content.strip() if isinstance(content, str) and content.strip() else None
        if status == "partial" and partial_content is not None:
            message_parts.append(f"Partial result: {partial_content}")
        raise AdapterError(
            " ".join(message_parts),
            path=path or self.repo_root,
            stage=stage,
            error_code=self._map_protocol_error_code(runtime_code),
        )

    def _map_protocol_error_code(self, runtime_code: str | None) -> ErrorCode:
        if runtime_code == "EXECUTION_TIMEOUT":
            return ErrorCode.ADAPTER_TIMEOUT
        return ErrorCode.ADAPTER_FAILURE

    def _handle_legacy_rp_result(
        self,
        completed: subprocess.CompletedProcess[str],
        *,
        stage: str,
        path: Path | None = None,
    ) -> str:
        if completed.returncode != 0:
            message = (
                completed.stderr.strip()
                or completed.stdout.strip()
                or "RepoPrompt native runtime returned a failure"
            )
            raise AdapterError(
                message,
                path=path or self.repo_root,
                stage=stage,
                error_code=ErrorCode.ADAPTER_FAILURE,
            )
        return completed.stdout.strip()

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
