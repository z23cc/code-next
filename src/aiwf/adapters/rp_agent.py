"""RepoPrompt agent adapter implementation."""

from __future__ import annotations

import fnmatch
import json
import subprocess
from pathlib import Path
from typing import Any, Sequence

from aiwf.adapters.base import BridgeContract, HostCapabilities, HostContract, NativeRuntimeContract, ReviewArtifactContract
from aiwf.adapters.rp_bridge_normalize import (
    RpBridgeNormalizationError,
    normalize_implement_capture,
    normalize_review_capture,
)
from aiwf.adapters.rp_cli_bridge import RpCliBridgeClient
from aiwf.exceptions import AdapterError, ErrorCode
from aiwf.models import (
    RpBridgeAgentLogArtifact,
    RpBridgeAgentTranscriptArtifact,
    RpBridgeManagedAgentRecord,
    RpBridgeResolvedIdentity,
    RpBridgeRunConfig,
    RpBridgeSeedingArtifact,
    RpBridgeToolCall,
    RunStatus,
    StageResult,
    TaskSpec,
)


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
        "Install the real RepoPrompt app / MCP CLI runtime on PATH (for example `rp` or `rp-cli`) "
        "to try RP experimental auto/native execution; manual handoff remains the stable supported path."
    ),
    protocol_version=_RP_PROTOCOL_VERSION,
)

RP_BRIDGE_CONTRACT = BridgeContract(
    enabled=True,
    default_mode="manual-assist",
    supported_modes=("disabled", "manual-assist", "managed-agent"),
    command_candidates=("rp", "rp-cli"),
    install_hint=(
        "Install the real RepoPrompt app / MCP CLI runtime on PATH (for example `rp` or `rp-cli`) "
        "to use the experimental RP bridge (manual-assist or managed-agent); manual handoff remains the stable supported path."
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
    bridge=RP_BRIDGE_CONTRACT,
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
        bridge_config: RpBridgeRunConfig | None = None,
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
        if bridge_config is not None and self.auto:
            raise ValueError("Bridge is currently only supported with RP manual mode")
        if bridge_config is not None and not self.host_contract.bridge.enabled:
            raise ValueError("RpAgentAdapter received bridge_config but host contract does not support bridge")
        if bridge_config is not None and bridge_config.mode not in self.host_contract.bridge.supported_modes:
            raise ValueError("RpAgentAdapter bridge_config mode is not supported by the host contract")
        self.bridge_config = bridge_config
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
        if self.auto:
            prompt = self._build_execute_prompt(task, plan, run_dir)
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

        if self._is_managed_agent_bridge():
            return self._execute_managed_agent(task, plan, run_dir)

        bridge_seeding = self._seed_bridge_context(run_dir)
        prompt = self._build_execute_prompt(task, plan, run_dir, bridge_seeding=bridge_seeding)
        prompt_path = run_dir / "rp-agent-implement-prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        outputs = [prompt_path.name]
        metadata: dict[str, object] = {"mode": "manual", "prompt_file": prompt_path.name}
        bridge_metadata = self._bridge_metadata()
        if bridge_metadata is not None:
            metadata["bridge"] = bridge_metadata
        if bridge_seeding is not None:
            outputs.append("rp-bridge-seeding.json")
            metadata["bridge_seeding_artifact"] = "rp-bridge-seeding.json"
            metadata["bridge_seeding_status"] = bridge_seeding.status
        return StageResult(
            stage="implement",
            status=RunStatus.blocked,
            summary=f"RepoPrompt implementation handoff prompt written for {task.title}",
            outputs=outputs,
            metadata=metadata,
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

        if self._is_managed_agent_bridge():
            return self._review_managed_agent(
                task,
                run_dir,
                prompt=prompt,
                evidence_files=evidence_files,
                evidence_summary=evidence_summary,
            )

        prompt_path = run_dir / "rp-agent-review-prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        review_report = {
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
        bridge_metadata = self._bridge_metadata()
        if bridge_metadata is not None:
            review_report["bridge"] = bridge_metadata
        return review_report

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

    def _build_execute_prompt(
        self,
        task: TaskSpec,
        plan: str,
        run_dir: Path,
        *,
        bridge_seeding: RpBridgeSeedingArtifact | None = None,
    ) -> str:
        lines = [
            f"Task: {task.title}",
            "",
            f"Run directory: {run_dir}",
            *self._render_bridge_context_block(stage="implement", bridge_seeding=bridge_seeding),
            "Implement the approved plan in the repository.",
            "Preserve the aiwf artifact/state contract and prepare the repo for deterministic gates.",
            "Do not redesign the host abstraction; keep changes scoped to the task.",
            "",
            "Plan:",
            plan,
        ]
        return "\n".join(lines)

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
            *self._render_bridge_context_block(stage="review"),
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

    def _render_bridge_context_block(
        self,
        *,
        stage: str,
        bridge_seeding: RpBridgeSeedingArtifact | None = None,
    ) -> list[str]:
        bridge_config = self._active_bridge_config()
        if bridge_config is None:
            return []

        stage_label = "implementation" if stage == "implement" else stage
        lines = [
            "",
            f"## RepoPrompt Bridge Context ({bridge_config.mode})",
            f"- workspace: {bridge_config.workspace or '(unset — pick one in RepoPrompt)'}",
            f"- tab: {bridge_config.tab or '(unset)'}",
            f"- context_id: {bridge_config.context_id or '(unset)'}",
            f"- agent_role: {bridge_config.agent_role or '(unset)'}",
        ]
        if bridge_config.resolved is not None:
            resolved = bridge_config.resolved
            lines.extend(
                [
                    f"- resolved_workspace_id: {resolved.resolved_workspace_id or '(unresolved)'}",
                    f"- resolved_window_id: {resolved.resolved_window_id or '(unresolved)'}",
                    f"- resolved_tab_id: {resolved.resolved_tab_id or '(unresolved)'}",
                    f"- resolved_context_id: {resolved.resolved_context_id or '(unresolved)'}",
                ]
            )
        if stage == "implement" and bridge_seeding is not None:
            lines.extend(
                [
                    f"- bridge_seeding_artifact: rp-bridge-seeding.json",
                    f"- bridge_seeding_status: {bridge_seeding.status}",
                    f"- bridge_seeding_summary: {bridge_seeding.summary}",
                ]
            )
        lines.extend(
            [
                "",
                f"Operator steps before completing the {stage_label} handoff:",
                "- Bind your RepoPrompt session to the workspace/tab above or your active session.",
            ]
        )
        if bridge_config.mode == "managed-agent":
            lines.extend(
                [
                    f"- aiwf will drive the RepoPrompt managed-agent lifecycle for this {stage_label} stage.",
                    "- Use the prompt artifact only for inspect/debugging or if the managed-agent session asks for operator input.",
                    "",
                ]
            )
            return lines
        if stage == "implement" and bridge_seeding is not None and bridge_seeding.status == "seeded":
            lines.append("- Confirm the seeded aiwf artifacts are present in RepoPrompt context before implementing.")
        else:
            lines.append("- Add the current aiwf run artifacts to your RepoPrompt context.")
        lines.extend(
            [
                f"- Continue the {stage_label} handoff in RepoPrompt using this brief.",
                "",
            ]
        )
        return lines

    def _active_bridge_config(self) -> RpBridgeRunConfig | None:
        if self.bridge_config is None or self.bridge_config.mode == "disabled":
            return None
        return self.bridge_config

    def _is_managed_agent_bridge(self) -> bool:
        bridge_config = self._active_bridge_config()
        return bridge_config is not None and bridge_config.mode == "managed-agent"

    def _bridge_metadata(self) -> dict[str, object] | None:
        bridge_config = self._active_bridge_config()
        if bridge_config is None:
            return None
        return bridge_config.model_dump(mode="json", exclude_none=True)

    def _resolved_bridge_targets(self, bridge_config: RpBridgeRunConfig) -> tuple[str | None, str | None, str | None]:
        resolved = bridge_config.resolved
        workspace = resolved.resolved_workspace_name if resolved is not None else None
        tab = resolved.resolved_tab_name if resolved is not None else None
        context_id = resolved.resolved_context_id if resolved is not None else None
        return workspace or bridge_config.workspace, tab or bridge_config.tab, context_id or bridge_config.context_id

    def _update_bridge_resolved_identity(
        self,
        bridge_config: RpBridgeRunConfig,
        *,
        workspace_id: str | None = None,
        workspace_name: str | None = None,
        window_id: int | None = None,
        tab_id: str | None = None,
        tab_name: str | None = None,
        context_id: str | None = None,
    ) -> None:
        resolved = bridge_config.resolved.model_copy(deep=True) if bridge_config.resolved is not None else RpBridgeResolvedIdentity()
        if workspace_id:
            resolved.resolved_workspace_id = workspace_id
        if workspace_name:
            resolved.resolved_workspace_name = workspace_name
        if window_id is not None:
            resolved.resolved_window_id = window_id
        if tab_id:
            resolved.resolved_tab_id = tab_id
        if tab_name:
            resolved.resolved_tab_name = tab_name
        if context_id:
            resolved.resolved_context_id = context_id
        bridge_config.resolved = resolved

    def _extract_tab_binding(
        self,
        windows: Sequence[dict[str, object]],
        *,
        tab_hint: str | None,
    ) -> tuple[str | None, str | None, str | None, int | None]:
        normalized_tab_hint = tab_hint.strip().casefold() if isinstance(tab_hint, str) and tab_hint.strip() else None
        for window in windows:
            window_id = self._json_int(window, "window_id") or self._json_int(window, "id")
            for tabs_key in ("tabs", "compose_tabs"):
                raw_tabs = window.get(tabs_key)
                if not isinstance(raw_tabs, list):
                    continue
                for raw_tab in raw_tabs:
                    if not isinstance(raw_tab, dict):
                        continue
                    tab_id = self._json_string(raw_tab, "id") or self._json_string(raw_tab, "tab_id")
                    tab_name = self._json_string(raw_tab, "name") or self._json_string(raw_tab, "tab")
                    context_id = self._json_string(raw_tab, "context_id")
                    if normalized_tab_hint is None:
                        if context_id:
                            return tab_id, tab_name, context_id, window_id
                        continue
                    if tab_id and tab_id.casefold() == normalized_tab_hint:
                        return tab_id, tab_name, context_id, window_id
                    if tab_name and tab_name.casefold() == normalized_tab_hint:
                        return tab_id, tab_name, context_id, window_id
        return None, None, None, None

    def _execute_managed_agent(self, task: TaskSpec, plan: str, run_dir: Path) -> StageResult:
        bridge_config = self._require_bridge_config_mode("managed-agent")
        bridge_seeding = self._seed_bridge_context(run_dir)
        prompt = self._build_execute_prompt(task, plan, run_dir, bridge_seeding=bridge_seeding)
        prompt_path = run_dir / "rp-agent-implement-prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        outputs = [prompt_path.name]
        if bridge_seeding is not None:
            outputs.append("rp-bridge-seeding.json")

        record, response_text = self._run_managed_agent_session(
            run_dir,
            stage="implement",
            prompt=prompt,
            prompt_artifact=prompt_path.name,
            response_artifact="rp-agent-implement-response.md",
            workspace=bridge_config.workspace,
            tab=bridge_config.tab,
            context_id=bridge_config.context_id,
            agent_role=bridge_config.agent_role,
        )
        outputs.append("rp-bridge-agent-log.json")
        if record.transcript_artifact is not None:
            outputs.append(record.transcript_artifact)
        if record.handoff_artifact is not None:
            outputs.append(record.handoff_artifact)
        if record.status == "waiting_for_input":
            metadata: dict[str, object] = {
                "mode": "manual",
                "prompt_file": prompt_path.name,
                "bridge": self._bridge_metadata() or {},
                "bridge_agent": {
                    "status": record.status,
                    "session_id": record.session_id,
                    "log_artifact": "rp-bridge-agent-log.json",
                    "recovery": record.recovery,
                    "transcript_artifact": record.transcript_artifact,
                    "handoff_artifact": record.handoff_artifact,
                },
                "blocked_resume_stage": "plan",
                "agent_log_artifact": "rp-bridge-agent-log.json",
            }
            if bridge_seeding is not None:
                metadata["bridge_seeding_artifact"] = "rp-bridge-seeding.json"
                metadata["bridge_seeding_status"] = bridge_seeding.status
            return StageResult(
                stage="implement",
                status=RunStatus.blocked,
                summary=f"RepoPrompt managed-agent implement is waiting for operator input for {task.title}",
                outputs=outputs,
                metadata=metadata,
            )

        if response_text is None:
            raise AdapterError(
                "RepoPrompt managed-agent implement completed without a usable response payload",
                path=run_dir,
                stage="implement",
                error_code=ErrorCode.BRIDGE_AGENT_FAILURE,
            )
        response_path = run_dir / "rp-agent-implement-response.md"
        response_path.write_text(normalize_implement_capture(response_text), encoding="utf-8")
        outputs.append(response_path.name)
        metadata = {
            "mode": "manual",
            "prompt_file": prompt_path.name,
            "response_file": response_path.name,
            "bridge": self._bridge_metadata() or {},
            "bridge_agent": {
                "status": record.status,
                "session_id": record.session_id,
                "log_artifact": "rp-bridge-agent-log.json",
                "recovery": record.recovery,
                "transcript_artifact": record.transcript_artifact,
                "handoff_artifact": record.handoff_artifact,
            },
            "agent_log_artifact": "rp-bridge-agent-log.json",
        }
        if bridge_seeding is not None:
            metadata["bridge_seeding_artifact"] = "rp-bridge-seeding.json"
            metadata["bridge_seeding_status"] = bridge_seeding.status
        return StageResult(
            stage="implement",
            status=RunStatus.passed,
            summary=f"RepoPrompt managed-agent execution completed for {task.title}",
            outputs=outputs,
            metadata=metadata,
        )

    def _review_managed_agent(
        self,
        task: TaskSpec,
        run_dir: Path,
        *,
        prompt: str,
        evidence_files: list[str],
        evidence_summary: dict[str, object],
    ) -> dict[str, object]:
        bridge_config = self._require_bridge_config_mode("managed-agent")
        prompt_path = run_dir / "rp-agent-review-prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        record, response_text = self._run_managed_agent_session(
            run_dir,
            stage="review",
            prompt=prompt,
            prompt_artifact=prompt_path.name,
            response_artifact="rp-agent-review-response.md",
            workspace=bridge_config.workspace,
            tab=bridge_config.tab,
            context_id=bridge_config.context_id,
            agent_role=bridge_config.agent_role,
        )
        review_report: dict[str, object] = {
            "summary": (
                f"RepoPrompt managed-agent review is waiting for operator input for {task.title}"
                if record.status == "waiting_for_input"
                else f"RepoPrompt managed-agent review completed for {task.title}"
            ),
            "issues": [],
            "mode": "manual",
            "prompt_file": prompt_path.name,
            "verify_report_file": "verify-report.json",
            "diagnostics_file": "run-diagnostics.json",
            "provenance_file": "run-provenance.json",
            "evidence_files": evidence_files,
            "evidence_summary": evidence_summary,
            "bridge": self._bridge_metadata() or {},
            "bridge_agent": {
                "status": record.status,
                "session_id": record.session_id,
                "log_artifact": "rp-bridge-agent-log.json",
                "recovery": record.recovery,
                "transcript_artifact": record.transcript_artifact,
                "handoff_artifact": record.handoff_artifact,
            },
        }
        if record.status == "waiting_for_input":
            return review_report

        if response_text is None:
            raise AdapterError(
                "RepoPrompt managed-agent review completed without a usable response payload",
                path=run_dir,
                stage="review",
                error_code=ErrorCode.BRIDGE_AGENT_FAILURE,
            )
        response_path = run_dir / "rp-agent-review-response.md"
        response_path.write_text(normalize_implement_capture(response_text), encoding="utf-8")
        review_report["response_file"] = response_path.name
        try:
            normalized_review = normalize_review_capture(
                response_text,
                contract=self.host_contract.review,
                linked_artifact_name=prompt_path.name,
                response_artifact_name=response_path.name,
                existing_report=review_report,
            )
        except RpBridgeNormalizationError as exc:
            raise AdapterError(
                f"RepoPrompt managed-agent review output could not be normalized: {exc}",
                path=run_dir / response_path.name,
                stage="review",
                error_code=ErrorCode.BRIDGE_AGENT_FAILURE,
            ) from exc
        normalized_review["bridge"] = self._bridge_metadata() or {}
        normalized_review["bridge_agent"] = review_report["bridge_agent"]
        return normalized_review

    def _run_managed_agent_session(
        self,
        run_dir: Path,
        *,
        stage: str,
        prompt: str,
        prompt_artifact: str,
        response_artifact: str,
        workspace: str | None,
        tab: str | None,
        context_id: str | None,
        agent_role: str | None,
    ) -> tuple[RpBridgeManagedAgentRecord, str | None]:
        bridge_config = self._require_bridge_config_mode("managed-agent")
        client = self._build_bridge_client(bridge_config)
        if client is None:
            raise AdapterError(
                "RepoPrompt managed-agent bridge command is not available",
                path=run_dir,
                stage=stage,
                error_code=ErrorCode.ADAPTER_UNAVAILABLE,
            )

        calls: list[RpBridgeToolCall] = []
        waiting_record = self._latest_managed_agent_record(run_dir, stage=stage, status="waiting_for_input")
        session_id = waiting_record.session_id if waiting_record is not None else None
        resolved_workspace, resolved_tab, resolved_context_id = self._resolved_bridge_targets(bridge_config)
        if resolved_workspace is None:
            resolved_workspace = workspace
        if resolved_tab is None:
            resolved_tab = tab
        if resolved_context_id is None:
            resolved_context_id = context_id
        recovery: str = "initial"

        if session_id is not None:
            recovery = "resumed"
            resume_result = client.agent_manage_resume_session(session_id)
            calls.append(
                self._bridge_call(
                    step="agent_manage_resume_session",
                    tool="agent_manage.resume_session",
                    ok=resume_result.ok,
                    command=resume_result.command,
                    summary=(
                        f"Resumed RepoPrompt managed-agent session {resume_result.session_id or session_id}"
                        if resume_result.ok
                        else self._bridge_error_summary(
                            resume_result.error,
                            fallback="RepoPrompt managed-agent session recovery surface was unavailable",
                        )
                    ),
                    error=resume_result.error,
                    detail={
                        "session_id": resume_result.session_id or session_id,
                        "status": resume_result.status,
                    },
                )
            )
            if resume_result.ok and resume_result.session_id:
                session_id = resume_result.session_id

        start_result = None
        if session_id is None:
            start_result = client.agent_run_start(
                prompt,
                workspace=resolved_workspace,
                tab=resolved_tab,
                context_id=resolved_context_id,
                agent_role=agent_role,
                stage=stage,
            )
            calls.append(
                self._bridge_call(
                    step="agent_run_start",
                    tool="agent_run.start",
                    ok=start_result.ok,
                    command=start_result.command,
                    summary=(
                        f"Started RepoPrompt managed-agent session {start_result.session_id}"
                        if start_result.ok and start_result.session_id
                        else self._bridge_error_summary(start_result.error, fallback="Failed to start RepoPrompt managed-agent session")
                    ),
                    error=start_result.error,
                    detail={
                        "session_id": start_result.session_id,
                        "status": start_result.status,
                    },
                )
            )
            if not start_result.ok or start_result.session_id is None:
                start_transport_unavailable = self._is_bridge_transport_unavailable_error(start_result.error)
                failure_summary = (
                    "RepoPrompt managed-agent is unavailable in this bridge runtime; rerun with --bridge-mode manual-assist."
                    if start_transport_unavailable
                    else "RepoPrompt managed-agent session failed before execution could start."
                )
                record = RpBridgeManagedAgentRecord(
                    stage=stage,
                    session_id=start_result.session_id,
                    status="failed",
                    workspace=resolved_workspace,
                    tab=resolved_tab,
                    context_id=resolved_context_id,
                    agent_role=agent_role,
                    prompt_artifact=prompt_artifact,
                    recovery=recovery,
                    summary=failure_summary,
                    log=start_result.raw_payload or {},
                    calls=calls,
                )
                self._append_bridge_agent_log_artifact(run_dir, record)
                error_message = self._bridge_error_summary(start_result.error, fallback=failure_summary)
                if start_transport_unavailable and "manual-assist" not in error_message:
                    error_message = f"{error_message}; rerun with --bridge-mode manual-assist."
                raise AdapterError(
                    error_message,
                    path=run_dir,
                    stage=stage,
                    error_code=ErrorCode.ADAPTER_UNAVAILABLE if start_transport_unavailable else ErrorCode.BRIDGE_AGENT_FAILURE,
                )
            session_id = start_result.session_id
            resolved_workspace = start_result.workspace or resolved_workspace
            resolved_tab = start_result.tab or resolved_tab
            resolved_context_id = start_result.context_id or resolved_context_id
            self._update_bridge_resolved_identity(
                bridge_config,
                workspace_name=resolved_workspace,
                tab_name=resolved_tab,
                context_id=resolved_context_id,
            )

        snapshot_result = None
        if recovery == "resumed" and session_id is not None:
            poll_result = client.agent_run_poll(
                session_id,
                workspace=resolved_workspace,
                tab=resolved_tab,
                context_id=resolved_context_id,
            )
            calls.append(
                self._bridge_call(
                    step="agent_run_poll",
                    tool="agent_run.poll",
                    ok=poll_result.ok,
                    command=poll_result.command,
                    summary=(
                        f"Polled RepoPrompt managed-agent session {session_id} with status {poll_result.status}"
                        if poll_result.ok and poll_result.status
                        else self._bridge_error_summary(poll_result.error, fallback="RepoPrompt managed-agent poll failed")
                    ),
                    error=poll_result.error,
                    detail={"session_id": session_id, "status": poll_result.status},
                )
            )
            if poll_result.ok:
                resolved_workspace = poll_result.workspace or resolved_workspace
                resolved_tab = poll_result.tab or resolved_tab
                resolved_context_id = poll_result.context_id or resolved_context_id
                self._update_bridge_resolved_identity(
                    bridge_config,
                    workspace_name=resolved_workspace,
                    tab_name=resolved_tab,
                    context_id=resolved_context_id,
                )
                snapshot_result = poll_result

        wait_result = snapshot_result
        wait_attempt = 0
        while wait_result is None or wait_result.status in {"running", "started"}:
            wait_result = client.agent_run_wait(
                session_id,
                workspace=resolved_workspace,
                tab=resolved_tab,
                context_id=resolved_context_id,
            )
            calls.append(
                self._bridge_call(
                    step="agent_run_wait" if wait_attempt == 0 else f"agent_run_wait_retry_{wait_attempt}",
                    tool="agent_run.wait",
                    ok=wait_result.ok,
                    command=wait_result.command,
                    summary=(
                        f"RepoPrompt managed-agent session {session_id} reached status {wait_result.status}"
                        if wait_result.ok and wait_result.status
                        else self._bridge_error_summary(wait_result.error, fallback="RepoPrompt managed-agent wait failed")
                    ),
                    error=wait_result.error,
                    detail={"session_id": session_id, "status": wait_result.status, "attempt": wait_attempt},
                )
            )
            if not wait_result.ok or wait_result.status not in {"running", "started"} or wait_attempt >= 1:
                break
            wait_attempt += 1
        if wait_result.ok:
            self._update_bridge_resolved_identity(
                bridge_config,
                workspace_name=wait_result.workspace or resolved_workspace,
                tab_name=wait_result.tab or resolved_tab,
                context_id=wait_result.context_id or resolved_context_id,
            )

        log_payload: dict[str, Any] = {}
        log_output: str | None = None
        transcript_artifact: str | None = None
        handoff_artifact: str | None = None
        if session_id is not None:
            log_result = client.agent_log(
                session_id,
                workspace=resolved_workspace,
                tab=resolved_tab,
                context_id=resolved_context_id,
            )
            calls.append(
                self._bridge_call(
                    step="agent_log",
                    tool="agent_manage.get_log",
                    ok=log_result.ok,
                    command=log_result.command,
                    summary=(
                        f"Captured RepoPrompt managed-agent log for session {session_id}"
                        if log_result.ok
                        else self._bridge_error_summary(log_result.error, fallback="Failed to capture RepoPrompt managed-agent log")
                    ),
                    error=log_result.error,
                    detail={"session_id": session_id, "status": log_result.status},
                )
            )
            if log_result.ok:
                log_payload = log_result.log
                log_output = log_result.output
            if bridge_config.export_transcript:
                transcript_artifact, handoff_artifact = self._capture_managed_agent_session_artifacts(
                    run_dir,
                    stage=stage,
                    session_id=session_id,
                    log_result=log_result,
                    client=client,
                    calls=calls,
                )

        if wait_result.ok:
            resolved_workspace = wait_result.workspace or resolved_workspace
            resolved_tab = wait_result.tab or resolved_tab
            resolved_context_id = wait_result.context_id or resolved_context_id
            self._update_bridge_resolved_identity(
                bridge_config,
                workspace_name=resolved_workspace,
                tab_name=resolved_tab,
                context_id=resolved_context_id,
            )
            resolved_workspace, resolved_tab, resolved_context_id = self._refresh_bridge_binding_identity(
                client,
                bridge_config,
                calls,
                workspace=resolved_workspace,
                tab=resolved_tab,
                context_id=resolved_context_id,
            )

        if not wait_result.ok:
            timeout = wait_result.error is not None and wait_result.error.code == "TIMEOUT"
            transport_unavailable = self._is_bridge_transport_unavailable_error(wait_result.error)
            status = "timeout" if timeout else "failed"
            record = RpBridgeManagedAgentRecord(
                stage=stage,
                session_id=session_id,
                status=status,
                workspace=resolved_workspace,
                tab=resolved_tab,
                context_id=resolved_context_id,
                agent_role=agent_role,
                prompt_artifact=prompt_artifact,
                transcript_artifact=transcript_artifact,
                handoff_artifact=handoff_artifact,
                recovery=recovery,
                summary=(
                    "RepoPrompt managed-agent session timed out while waiting for a terminal state."
                    if timeout
                    else (
                        "RepoPrompt managed-agent is unavailable in this bridge runtime; rerun with --bridge-mode manual-assist."
                        if transport_unavailable
                        else "RepoPrompt managed-agent session failed while waiting for a terminal state."
                    )
                ),
                log=log_payload,
                calls=calls,
            )
            self._append_bridge_agent_log_artifact(run_dir, record)
            error_message = self._bridge_error_summary(wait_result.error, fallback=record.summary)
            if transport_unavailable and "manual-assist" not in error_message:
                error_message = f"{error_message}; rerun with --bridge-mode manual-assist."
            raise AdapterError(
                error_message,
                path=run_dir,
                stage=stage,
                error_code=(
                    ErrorCode.ADAPTER_TIMEOUT
                    if timeout
                    else ErrorCode.ADAPTER_UNAVAILABLE
                    if transport_unavailable
                    else ErrorCode.BRIDGE_AGENT_FAILURE
                ),
            )

        terminal_status = wait_result.status or "failed"
        response_text = wait_result.output or log_output
        if terminal_status == "completed":
            record = RpBridgeManagedAgentRecord(
                stage=stage,
                session_id=session_id,
                status="completed",
                workspace=wait_result.workspace or resolved_workspace,
                tab=wait_result.tab or resolved_tab,
                context_id=wait_result.context_id or resolved_context_id,
                agent_role=agent_role,
                prompt_artifact=prompt_artifact,
                response_artifact=response_artifact,
                transcript_artifact=transcript_artifact,
                handoff_artifact=handoff_artifact,
                recovery=recovery,
                summary="RepoPrompt managed-agent session completed successfully.",
                log=log_payload or (wait_result.raw_payload or {}),
                calls=calls,
            )
            self._append_bridge_agent_log_artifact(run_dir, record)
            return record, response_text

        if terminal_status in {"waiting_for_input", "running"}:
            summary = (
                "RepoPrompt managed-agent session is waiting for operator input."
                if terminal_status == "waiting_for_input"
                else "RepoPrompt managed-agent session is still running; resume after it reaches a wait/completion checkpoint."
            )
            record = RpBridgeManagedAgentRecord(
                stage=stage,
                session_id=session_id,
                status="waiting_for_input",
                workspace=wait_result.workspace or resolved_workspace,
                tab=wait_result.tab or resolved_tab,
                context_id=wait_result.context_id or resolved_context_id,
                agent_role=agent_role,
                prompt_artifact=prompt_artifact,
                transcript_artifact=transcript_artifact,
                handoff_artifact=handoff_artifact,
                recovery=recovery,
                summary=summary,
                log=log_payload or (wait_result.raw_payload or {}),
                calls=calls,
            )
            self._append_bridge_agent_log_artifact(run_dir, record)
            return record, response_text

        if terminal_status == "timeout":
            record = RpBridgeManagedAgentRecord(
                stage=stage,
                session_id=session_id,
                status="timeout",
                workspace=wait_result.workspace or resolved_workspace,
                tab=wait_result.tab or resolved_tab,
                context_id=wait_result.context_id or resolved_context_id,
                agent_role=agent_role,
                prompt_artifact=prompt_artifact,
                transcript_artifact=transcript_artifact,
                handoff_artifact=handoff_artifact,
                recovery=recovery,
                summary="RepoPrompt managed-agent session reported timeout.",
                log=log_payload or (wait_result.raw_payload or {}),
                calls=calls,
            )
            self._append_bridge_agent_log_artifact(run_dir, record)
            raise AdapterError(
                record.summary,
                path=run_dir,
                stage=stage,
                error_code=ErrorCode.ADAPTER_TIMEOUT,
            )

        if terminal_status == "cancelled":
            record = RpBridgeManagedAgentRecord(
                stage=stage,
                session_id=session_id,
                status="cancelled",
                workspace=wait_result.workspace or resolved_workspace,
                tab=wait_result.tab or resolved_tab,
                context_id=wait_result.context_id or resolved_context_id,
                agent_role=agent_role,
                prompt_artifact=prompt_artifact,
                transcript_artifact=transcript_artifact,
                handoff_artifact=handoff_artifact,
                recovery=recovery,
                summary="RepoPrompt managed-agent session was cancelled.",
                log=log_payload or (wait_result.raw_payload or {}),
                calls=calls,
            )
            self._append_bridge_agent_log_artifact(run_dir, record)
            raise AdapterError(
                record.summary,
                path=run_dir,
                stage=stage,
                error_code=ErrorCode.BRIDGE_AGENT_FAILURE,
            )

        record = RpBridgeManagedAgentRecord(
            stage=stage,
            session_id=session_id,
            status="failed",
            workspace=wait_result.workspace or resolved_workspace,
            tab=wait_result.tab or resolved_tab,
            context_id=wait_result.context_id or resolved_context_id,
            agent_role=agent_role,
            prompt_artifact=prompt_artifact,
            transcript_artifact=transcript_artifact,
            handoff_artifact=handoff_artifact,
            recovery=recovery,
            summary=f"RepoPrompt managed-agent session ended with status {terminal_status}.",
            log=log_payload or (wait_result.raw_payload or {}),
            calls=calls,
        )
        self._append_bridge_agent_log_artifact(run_dir, record)
        raise AdapterError(
            record.summary,
            path=run_dir,
            stage=stage,
            error_code=ErrorCode.BRIDGE_AGENT_FAILURE,
        )

    def _require_bridge_config_mode(self, mode: str) -> RpBridgeRunConfig:
        bridge_config = self._active_bridge_config()
        if bridge_config is None or bridge_config.mode != mode:
            raise AdapterError(
                f"RepoPrompt bridge mode {mode!r} is not active for this run",
                path=self.repo_root,
                stage="bridge",
                error_code=ErrorCode.STATE_VIOLATION,
            )
        return bridge_config

    def _latest_managed_agent_record(
        self,
        run_dir: Path,
        *,
        stage: str,
        status: str | None = None,
    ) -> RpBridgeManagedAgentRecord | None:
        artifact_path = run_dir / "rp-bridge-agent-log.json"
        if not artifact_path.exists():
            return None
        try:
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
            artifact = RpBridgeAgentLogArtifact.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValueError):
            return None
        for record in reversed(artifact.sessions):
            if record.stage != stage:
                continue
            if status is not None and record.status != status:
                continue
            return record
        return None

    def _append_bridge_agent_log_artifact(self, run_dir: Path, record: RpBridgeManagedAgentRecord) -> None:
        artifact_path = run_dir / "rp-bridge-agent-log.json"
        sessions: list[RpBridgeManagedAgentRecord] = []
        if artifact_path.exists():
            try:
                payload = json.loads(artifact_path.read_text(encoding="utf-8"))
                existing = RpBridgeAgentLogArtifact.model_validate(payload)
                sessions = list(existing.sessions)
            except (OSError, json.JSONDecodeError, ValueError):
                sessions = []
        sessions.append(record)
        artifact = RpBridgeAgentLogArtifact(sessions=sessions)
        artifact_path.write_text(
            json.dumps(artifact.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _capture_managed_agent_session_artifacts(
        self,
        run_dir: Path,
        *,
        stage: str,
        session_id: str,
        log_result: object,
        client: RpCliBridgeClient,
        calls: list[RpBridgeToolCall],
    ) -> tuple[str | None, str | None]:
        transcript_artifact = f"rp-bridge-agent-{stage}-transcript.json"
        transcript_markdown_artifact = f"rp-bridge-agent-{stage}-transcript.md"
        handoff_artifact = f"rp-bridge-agent-{stage}-handoff.xml"

        transcript_result = client.agent_manage_transcript(session_id)
        transcript_tool = (
            "agent_manage.get_transcript"
            if transcript_result.source_operation == "get_transcript"
            else "agent_manage.get_log"
        )
        calls.append(
            self._bridge_call(
                step="agent_manage_transcript",
                tool=transcript_tool,
                ok=transcript_result.ok,
                command=transcript_result.command,
                summary=(
                    f"Captured RepoPrompt managed-agent transcript for session {session_id}"
                    if transcript_result.ok
                    else self._bridge_error_summary(
                        transcript_result.error,
                        fallback="RepoPrompt managed-agent transcript export was unavailable",
                    )
                ),
                error=transcript_result.error,
                detail={
                    "session_id": session_id,
                    "status": transcript_result.status,
                    "source_operation": transcript_result.source_operation,
                },
            )
        )

        transcript_text = transcript_result.transcript if transcript_result.ok else getattr(log_result, "output", None)
        transcript_events: list[dict[str, object]] = []
        handoff_summary = transcript_result.handoff_summary if transcript_result.ok else None
        if transcript_result.ok:
            transcript_events = [event for event in transcript_result.events if isinstance(event, dict)]
        elif getattr(log_result, "ok", False):
            log_payload = getattr(log_result, "log", {})
            raw_events = log_payload.get("events") if isinstance(log_payload, dict) else None
            transcript_events = [event for event in raw_events if isinstance(event, dict)] if isinstance(raw_events, list) else []

        if transcript_text or transcript_events:
            transcript_payload = RpBridgeAgentTranscriptArtifact(
                session_id=session_id,
                transcript=transcript_text,
                events=transcript_events,
                handoff_summary=handoff_summary,
            )
            (run_dir / transcript_artifact).write_text(
                json.dumps(transcript_payload.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            if transcript_text:
                (run_dir / transcript_markdown_artifact).write_text(transcript_text, encoding="utf-8")
        else:
            transcript_artifact = None

        handoff_result = client.agent_manage_extract_handoff(
            session_id,
            output_path=str((run_dir / handoff_artifact).resolve()),
            inline=False,
        )
        calls.append(
            self._bridge_call(
                step="agent_manage_extract_handoff",
                tool="agent_manage.extract_handoff",
                ok=handoff_result.ok,
                command=handoff_result.command,
                summary=(
                    f"Exported RepoPrompt managed-agent handoff for session {session_id}"
                    if handoff_result.ok
                    else self._bridge_error_summary(
                        handoff_result.error,
                        fallback="RepoPrompt managed-agent handoff export was unavailable",
                    )
                ),
                error=handoff_result.error,
                detail={
                    "session_id": session_id,
                    "output_path": handoff_result.output_path,
                    "status": handoff_result.status,
                },
            )
        )
        if not handoff_result.ok:
            return transcript_artifact, None
        handoff_path = run_dir / handoff_artifact
        if handoff_result.handoff_xml and not handoff_path.exists():
            handoff_path.write_text(handoff_result.handoff_xml, encoding="utf-8")
        if transcript_artifact is not None:
            transcript_path = run_dir / transcript_artifact
            try:
                payload = json.loads(transcript_path.read_text(encoding="utf-8"))
                transcript_payload = RpBridgeAgentTranscriptArtifact.model_validate(payload)
                transcript_payload.handoff_summary = handoff_result.handoff_summary or (
                    f"Handoff exported to {handoff_result.output_path or handoff_artifact}"
                )
                transcript_path.write_text(
                    json.dumps(transcript_payload.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            except (OSError, json.JSONDecodeError, ValueError):
                pass
        return transcript_artifact, handoff_artifact if handoff_path.exists() else None

    def _refresh_bridge_binding_identity(
        self,
        client: RpCliBridgeClient,
        bridge_config: RpBridgeRunConfig,
        calls: list[RpBridgeToolCall],
        *,
        workspace: str | None,
        tab: str | None,
        context_id: str | None,
    ) -> tuple[str | None, str | None, str | None]:
        status_result = client.bind_context_status()
        calls.append(
            self._bridge_call(
                step="bind_context_status",
                tool="bind_context.status",
                ok=status_result.ok,
                command=status_result.command,
                summary=(
                    "Captured bind_context status snapshot for managed-agent recovery"
                    if status_result.ok
                    else self._bridge_error_summary(
                        status_result.error,
                        fallback="RepoPrompt bind_context status probe was unavailable",
                    )
                ),
                error=status_result.error,
                detail={
                    "workspace": status_result.workspace,
                    "workspace_id": status_result.workspace_id,
                    "window_id": status_result.window_id,
                    "tab": status_result.tab,
                    "tab_id": status_result.tab_id,
                    "context_id": status_result.context_id,
                },
            )
        )
        if not status_result.ok:
            return workspace, tab, context_id
        resolved_workspace = status_result.workspace or workspace
        resolved_tab = status_result.tab or tab
        resolved_context_id = status_result.context_id or context_id
        self._update_bridge_resolved_identity(
            bridge_config,
            workspace_id=status_result.workspace_id,
            workspace_name=resolved_workspace,
            window_id=status_result.window_id,
            tab_id=status_result.tab_id,
            tab_name=resolved_tab,
            context_id=resolved_context_id,
        )
        return resolved_workspace, resolved_tab, resolved_context_id

    def _resolve_bridge_identity(
        self,
        *,
        client: RpCliBridgeClient,
        bridge_config: RpBridgeRunConfig,
        calls: list[RpBridgeToolCall],
        attempted_tools: list[str],
    ) -> tuple[str | None, str | None, str | None]:
        resolved_workspace, resolved_tab, resolved_context_id = self._resolved_bridge_targets(bridge_config)
        resolved_window_id = bridge_config.resolved.resolved_window_id if bridge_config.resolved is not None else None
        repo_working_dir = str(self.repo_root.resolve())

        if bridge_config.workspace:
            attempted_tools.append("manage_workspaces")
            workspace_result = client.manage_workspaces_resolve(bridge_config.workspace)
            calls.append(
                self._bridge_call(
                    step="manage_workspaces_resolve",
                    tool="manage_workspaces.list",
                    ok=workspace_result.ok,
                    command=workspace_result.command,
                    summary=(
                        f"Resolved RepoPrompt workspace {workspace_result.workspace or bridge_config.workspace}"
                        if workspace_result.ok
                        else self._bridge_error_summary(
                            workspace_result.error,
                            fallback="RepoPrompt workspace resolution was skipped",
                        )
                    ),
                    error=workspace_result.error,
                    detail={
                        "workspace": workspace_result.workspace,
                        "workspace_id": workspace_result.workspace_id,
                        "window_ids": list(workspace_result.window_ids),
                        "matched_by": workspace_result.matched_by,
                    },
                )
            )
            if workspace_result.ok:
                resolved_workspace = workspace_result.workspace or resolved_workspace
                resolved_window_id = workspace_result.window_ids[0] if workspace_result.window_ids else resolved_window_id
                self._update_bridge_resolved_identity(
                    bridge_config,
                    workspace_id=workspace_result.workspace_id,
                    workspace_name=workspace_result.workspace or bridge_config.workspace,
                    window_id=resolved_window_id,
                )

        bind_list_result = None
        if bridge_config.tab and resolved_window_id is not None:
            attempted_tools.append("bind_context")
            bind_list_result = client.bind_context_list(window_id=resolved_window_id)
            calls.append(
                self._bridge_call(
                    step="bind_context_list",
                    tool="bind_context.list",
                    ok=bind_list_result.ok,
                    command=bind_list_result.command,
                    summary=(
                        f"Loaded bind_context window inventory for window {resolved_window_id}"
                        if bind_list_result.ok
                        else self._bridge_error_summary(
                            bind_list_result.error,
                            fallback="RepoPrompt bind_context inventory was unavailable",
                        )
                    ),
                    error=bind_list_result.error,
                    detail={"window_id": resolved_window_id, "tab": bridge_config.tab},
                )
            )
            if bind_list_result.ok:
                tab_id, tab_name, matched_context_id, matched_window_id = self._extract_tab_binding(
                    bind_list_result.windows,
                    tab_hint=bridge_config.tab,
                )
                if matched_window_id is not None:
                    resolved_window_id = matched_window_id
                if tab_name:
                    resolved_tab = tab_name
                if matched_context_id:
                    resolved_context_id = matched_context_id
                self._update_bridge_resolved_identity(
                    bridge_config,
                    window_id=resolved_window_id,
                    tab_id=tab_id,
                    tab_name=tab_name,
                    context_id=matched_context_id,
                )

        if resolved_context_id:
            attempted_tools.append("bind_context")
            bind_result = client.bind_context_bind(context_id=resolved_context_id)
        else:
            attempted_tools.append("bind_context")
            bind_result = client.bind_context_bind(
                working_dirs=[repo_working_dir],
                window_id=resolved_window_id,
            )
        calls.append(
            self._bridge_call(
                step="bind_context_bind",
                tool="bind_context.bind",
                ok=bind_result.ok,
                command=bind_result.command,
                summary=(
                    f"Bound RepoPrompt context {bind_result.context_id or resolved_context_id or '(window affinity)'}"
                    if bind_result.ok
                    else self._bridge_error_summary(
                        bind_result.error,
                        fallback="RepoPrompt context binding was unavailable",
                    )
                ),
                error=bind_result.error,
                detail={
                    "workspace": bind_result.workspace,
                    "workspace_id": bind_result.workspace_id,
                    "window_id": bind_result.window_id,
                    "tab": bind_result.tab,
                    "tab_id": bind_result.tab_id,
                    "context_id": bind_result.context_id,
                },
            )
        )
        if bind_result.ok:
            resolved_workspace = bind_result.workspace or resolved_workspace
            resolved_tab = bind_result.tab or resolved_tab
            resolved_context_id = bind_result.context_id or resolved_context_id
            self._update_bridge_resolved_identity(
                bridge_config,
                workspace_id=bind_result.workspace_id,
                workspace_name=bind_result.workspace or resolved_workspace,
                window_id=bind_result.window_id or resolved_window_id,
                tab_id=bind_result.tab_id,
                tab_name=bind_result.tab or resolved_tab,
                context_id=bind_result.context_id or resolved_context_id,
            )

        return self._resolved_bridge_targets(bridge_config)

    def _seed_bridge_context(self, run_dir: Path) -> RpBridgeSeedingArtifact | None:
        bridge_config = self._active_bridge_config()
        if bridge_config is None:
            return None

        selected_artifacts = [name for name in ("context-pack.md", "exec-plan.md") if (run_dir / name).exists()]
        seed_paths = self._bridge_seed_paths(run_dir, selected_artifacts)
        calls: list[RpBridgeToolCall] = []
        client = self._build_bridge_client(bridge_config)
        if client is None:
            artifact = RpBridgeSeedingArtifact(
                mode=bridge_config.mode,
                status="skipped",
                workspace=bridge_config.workspace,
                tab=bridge_config.tab,
                context_id=bridge_config.context_id,
                agent_role=bridge_config.agent_role,
                summary=(
                    "Bridge context seeding was skipped because no RP bridge command candidate was available; "
                    "manually add the aiwf run artifacts before continuing the handoff."
                ),
                selected_artifacts=selected_artifacts,
                selected_paths=seed_paths,
                attempted_tools=[],
                calls=[],
            )
            self._write_bridge_seeding_artifact(run_dir, artifact)
            return artifact

        try:
            probe_result = client.probe_available()
            tool_names = [tool.name for tool in probe_result.tools] if probe_result.available else []
            calls.append(
                self._bridge_call(
                    step="probe_available",
                    tool="probe_available",
                    ok=probe_result.available,
                    command=probe_result.command,
                    summary=(
                        f"Bridge capability probe is available with tools: {', '.join(tool_names)}"
                        if probe_result.available
                        else self._bridge_error_summary(probe_result.error, fallback="Bridge tool discovery failed")
                    ),
                    error=probe_result.error,
                    detail={"tools": tool_names},
                )
            )
            if not probe_result.available:
                artifact = RpBridgeSeedingArtifact(
                    mode=bridge_config.mode,
                    status="failed",
                    workspace=bridge_config.workspace,
                    tab=bridge_config.tab,
                    context_id=bridge_config.context_id,
                    agent_role=bridge_config.agent_role,
                    summary=(
                        "Bridge context seeding failed during tool discovery; manually add the aiwf run artifacts "
                        "before continuing the handoff."
                    ),
                    selected_artifacts=selected_artifacts,
                    selected_paths=seed_paths,
                    attempted_tools=[],
                    calls=calls,
                )
                self._write_bridge_seeding_artifact(run_dir, artifact)
                return artifact

            attempted_tools: list[str] = []
            resolved_workspace, _, current_context_id = self._resolve_bridge_identity(
                client=client,
                bridge_config=bridge_config,
                calls=calls,
                attempted_tools=attempted_tools,
            )
            attempted_tools.append("workspace_context")
            context_result = client.workspace_context(resolved_workspace)
            calls.append(
                self._bridge_call(
                    step="workspace_context_before",
                    tool="workspace_context",
                    ok=context_result.ok,
                    command=context_result.command,
                    summary=(
                        f"Loaded workspace context snapshot with {len(context_result.selected_paths)} selected path(s)"
                        if context_result.ok
                        else self._bridge_error_summary(context_result.error, fallback="Workspace context snapshot failed")
                    ),
                    error=context_result.error,
                    detail={
                        "workspace": context_result.workspace,
                        "context_id": context_result.context_id,
                        "selected_paths": list(context_result.selected_paths),
                    },
                )
            )
            if context_result.ok and context_result.context_id:
                current_context_id = context_result.context_id

            attempted_tools.append("manage_selection")
            manage_result = client.manage_selection_add(
                seed_paths,
                workspace=resolved_workspace,
                tab=bridge_config.tab,
                context_id=current_context_id,
            )
            calls.append(
                self._bridge_call(
                    step="manage_selection_add",
                    tool="manage_selection",
                    ok=manage_result.ok,
                    command=manage_result.command,
                    summary=(
                        f"Seeded {len(manage_result.added_paths or seed_paths)} aiwf artifact path(s) into RepoPrompt context"
                        if manage_result.ok
                        else self._bridge_error_summary(manage_result.error, fallback="manage_selection failed")
                    ),
                    error=manage_result.error,
                    detail={
                        "workspace": manage_result.workspace,
                        "context_id": manage_result.context_id,
                        "selected_paths": list(manage_result.selected_paths),
                        "added_paths": list(manage_result.added_paths),
                    },
                )
            )
            attempted_tool_names = sorted({name for name in attempted_tools if name})
            if not manage_result.ok:
                artifact = RpBridgeSeedingArtifact(
                    mode=bridge_config.mode,
                    status="failed",
                    workspace=resolved_workspace or bridge_config.workspace,
                    tab=bridge_config.tab,
                    context_id=current_context_id,
                    agent_role=bridge_config.agent_role,
                    summary=(
                        "Bridge context seeding failed while updating RepoPrompt selection; manually add the aiwf run "
                        "artifacts before continuing the handoff."
                    ),
                    selected_artifacts=selected_artifacts,
                    selected_paths=seed_paths,
                    attempted_tools=attempted_tool_names,
                    calls=calls,
                )
                self._write_bridge_seeding_artifact(run_dir, artifact)
                return artifact

            final_context_id = manage_result.context_id or current_context_id
            final_selected_paths = list(manage_result.selected_paths or manage_result.added_paths or seed_paths)
            if final_context_id:
                self._update_bridge_resolved_identity(
                    bridge_config,
                    workspace_name=manage_result.workspace or resolved_workspace or bridge_config.workspace,
                    context_id=final_context_id,
                )
            artifact = RpBridgeSeedingArtifact(
                mode=bridge_config.mode,
                status="seeded",
                workspace=manage_result.workspace or resolved_workspace or bridge_config.workspace,
                tab=bridge_config.tab,
                context_id=final_context_id,
                agent_role=bridge_config.agent_role,
                summary=(
                    "Bridge context seeding prepared the aiwf run artifacts in RepoPrompt; manual handoff still "
                    "requires reviewing the implementation brief."
                ),
                selected_artifacts=selected_artifacts,
                selected_paths=final_selected_paths,
                attempted_tools=attempted_tool_names,
                calls=calls,
            )
            self._write_bridge_seeding_artifact(run_dir, artifact)
            return artifact
        except Exception as exc:
            artifact = RpBridgeSeedingArtifact(
                mode=bridge_config.mode,
                status="failed",
                workspace=bridge_config.workspace,
                tab=bridge_config.tab,
                context_id=bridge_config.context_id,
                agent_role=bridge_config.agent_role,
                summary=(
                    "Bridge context seeding hit an unexpected error; manually add the aiwf run artifacts before "
                    "continuing the handoff."
                ),
                selected_artifacts=selected_artifacts,
                selected_paths=seed_paths,
                attempted_tools=[],
                calls=[
                    *calls,
                    RpBridgeToolCall(
                        step="seed_bridge_context",
                        tool="bridge_client",
                        ok=False,
                        command=[],
                        summary=f"Unexpected bridge seeding failure: {exc}",
                        error_code="UNEXPECTED_ERROR",
                        error_message=str(exc),
                        detail={},
                    ),
                ],
            )
            self._write_bridge_seeding_artifact(run_dir, artifact)
            return artifact

    def _build_bridge_client(self, bridge_config: RpBridgeRunConfig) -> RpCliBridgeClient | None:
        if self.rp_command is not None:
            return RpCliBridgeClient(tuple(self.rp_command), timeout_seconds=bridge_config.timeout_seconds or 5)
        return RpCliBridgeClient.from_command_candidates(
            self.host_contract.bridge.command_candidates,
            timeout_seconds=bridge_config.timeout_seconds or 5,
        )

    def _bridge_seed_paths(self, run_dir: Path, artifact_names: list[str]) -> list[str]:
        paths: list[str] = []
        for artifact_name in artifact_names:
            artifact_path = run_dir / artifact_name
            try:
                paths.append(artifact_path.relative_to(self.repo_root).as_posix())
            except ValueError:
                paths.append(str(artifact_path))
        return paths

    def _write_bridge_seeding_artifact(self, run_dir: Path, artifact: RpBridgeSeedingArtifact) -> None:
        artifact_path = run_dir / "rp-bridge-seeding.json"
        artifact_path.write_text(json.dumps(artifact.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _bridge_call(
        self,
        *,
        step: str,
        tool: str,
        ok: bool,
        command: Sequence[str],
        summary: str,
        error: object = None,
        detail: dict[str, object] | None = None,
    ) -> RpBridgeToolCall:
        error_code = getattr(error, "code", None) if error is not None else None
        error_message = getattr(error, "message", None) if error is not None else None
        return RpBridgeToolCall(
            step=step,
            tool=tool,
            ok=ok,
            command=[str(part) for part in command],
            summary=summary,
            error_code=error_code,
            error_message=error_message,
            detail=detail or {},
        )

    def _bridge_error_summary(self, error: object, *, fallback: str) -> str:
        if error is None:
            return fallback
        code = getattr(error, "code", None)
        message = getattr(error, "message", None)
        if isinstance(code, str) and code.strip() and isinstance(message, str) and message.strip():
            return f"{code}: {message}"
        if isinstance(message, str) and message.strip():
            return message
        return fallback

    def _is_bridge_transport_unavailable_error(self, error: object) -> bool:
        if error is None:
            return False
        code = getattr(error, "code", None)
        return code in {"BRIDGE_TOOL_INVOCATION_UNSUPPORTED", "TOOL_UNAVAILABLE"}

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
            "rp-bridge-seeding.json",
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

    def _json_int(self, payload: dict[str, Any], key: str) -> int | None:
        value = payload.get(key)
        return value if isinstance(value, int) else None


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
