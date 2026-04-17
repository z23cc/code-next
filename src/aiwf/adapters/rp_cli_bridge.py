"""RepoPrompt CLI bridge client for probing and scoped context seeding."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence


@dataclass(frozen=True)
class RpBridgeError:
    """Structured bridge command failure."""

    code: str
    message: str
    retriable: bool
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RpToolInfo:
    """A single RepoPrompt tool discovered from the bridge CLI."""

    name: str
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RpToolListResult:
    """Typed result of a tool probe/capability summary."""

    ok: bool
    command: tuple[str, ...]
    path: str
    tools: tuple[RpToolInfo, ...] = ()
    error: RpBridgeError | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpWorkspaceInfo:
    """A single workspace entry discovered via `manage_workspaces`."""

    workspace_id: str | None = None
    name: str | None = None
    repo_paths: tuple[str, ...] = ()
    window_ids: tuple[int, ...] = ()
    is_hidden: bool | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RpWorkspaceListResult:
    """Typed result of `manage_workspaces action=list`."""

    ok: bool
    command: tuple[str, ...]
    path: str
    workspaces: tuple[RpWorkspaceInfo, ...] = ()
    error: RpBridgeError | None = None
    raw_payload: dict[str, Any] | list[Any] | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpWorkspaceResolveResult:
    """Typed result of resolving a workspace hint against RepoPrompt inventory."""

    ok: bool
    command: tuple[str, ...]
    path: str
    workspace: str | None = None
    workspace_id: str | None = None
    repo_paths: tuple[str, ...] = ()
    window_ids: tuple[int, ...] = ()
    is_hidden: bool | None = None
    matched_by: str | None = None
    error: RpBridgeError | None = None
    raw_payload: dict[str, Any] | list[Any] | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpWorkspaceContextResult:
    """Typed result of a workspace-context snapshot."""

    ok: bool
    command: tuple[str, ...]
    path: str
    workspace: str | None = None
    context_id: str | None = None
    selected_paths: tuple[str, ...] = ()
    prompt: str | None = None
    tokens: dict[str, Any] | None = None
    sections: dict[str, Any] | None = None
    export_path: str | None = None
    error: RpBridgeError | None = None
    raw_payload: dict[str, Any] | list[Any] | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpContextBuilderResult:
    """Typed result of a context_builder bridge call."""

    ok: bool
    command: tuple[str, ...]
    path: str
    flow: Literal["preview", "apply"]
    response_type: str
    context_id: str | None = None
    workspace: str | None = None
    selected_paths: tuple[str, ...] = ()
    response_text: str | None = None
    export_path: str | None = None
    error: RpBridgeError | None = None
    raw_payload: dict[str, Any] | list[Any] | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpAskOracleResult:
    """Typed result of an ask_oracle bridge call."""

    ok: bool
    command: tuple[str, ...]
    path: str
    mode: str
    chat_id: str | None = None
    response_text: str | None = None
    export_path: str | None = None
    error: RpBridgeError | None = None
    raw_payload: dict[str, Any] | list[Any] | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpManageSelectionResult:
    """Typed result of a scoped `manage_selection` mutation."""

    ok: bool
    command: tuple[str, ...]
    path: str
    workspace: str | None = None
    context_id: str | None = None
    selected_paths: tuple[str, ...] = ()
    added_paths: tuple[str, ...] = ()
    error: RpBridgeError | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpReadFileResult:
    """Typed result of a bridge-side `read_file` call."""

    ok: bool
    command: tuple[str, ...]
    path: str
    source: str
    content: str | None = None
    workspace: str | None = None
    context_id: str | None = None
    resolved_source: str | None = None
    start_line: int | None = None
    limit: int | None = None
    error: RpBridgeError | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpFileSearchMatch:
    """A single file_search match returned by the RP bridge."""

    path: str
    line: int | None = None
    snippet: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RpFileSearchResult:
    """Typed result of a bridge-side `file_search` call."""

    ok: bool
    command: tuple[str, ...]
    path: str
    query: str
    matches: tuple[RpFileSearchMatch, ...] = ()
    matched_paths: tuple[str, ...] = ()
    count: int | None = None
    truncated: bool = False
    error: RpBridgeError | None = None
    raw_payload: dict[str, Any] | list[Any] | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpApplyEditsResult:
    """Typed result of a bridge-side destructive `apply_edits` call."""

    ok: bool
    command: tuple[str, ...]
    path: str
    target_path: str
    changed_paths: tuple[str, ...] = ()
    summary: str | None = None
    error: RpBridgeError | None = None
    raw_payload: dict[str, Any] | list[Any] | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpFileActionResult:
    """Typed result of a bridge-side destructive `file_actions` call."""

    ok: bool
    command: tuple[str, ...]
    path: str
    action: str
    target_path: str
    changed_paths: tuple[str, ...] = ()
    summary: str | None = None
    error: RpBridgeError | None = None
    raw_payload: dict[str, Any] | list[Any] | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpBindContextResult:
    """Typed result of binding or inspecting RepoPrompt routing context."""

    ok: bool
    command: tuple[str, ...]
    path: str
    workspace: str | None = None
    workspace_id: str | None = None
    window_id: int | None = None
    tab: str | None = None
    tab_id: str | None = None
    context_id: str | None = None
    working_dirs: tuple[str, ...] = ()
    windows: tuple[dict[str, Any], ...] = ()
    error: RpBridgeError | None = None
    raw_payload: dict[str, Any] | list[Any] | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpAgentRunStartResult:
    """Typed result of starting a managed-agent bridge session."""

    ok: bool
    command: tuple[str, ...]
    path: str
    session_id: str | None = None
    status: str | None = None
    workspace: str | None = None
    tab: str | None = None
    context_id: str | None = None
    error: RpBridgeError | None = None
    raw_payload: dict[str, Any] | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpAgentRunWaitResult:
    """Typed result of waiting on a managed-agent bridge session."""

    ok: bool
    command: tuple[str, ...]
    path: str
    session_id: str
    status: str | None = None
    output: str | None = None
    workspace: str | None = None
    tab: str | None = None
    context_id: str | None = None
    error: RpBridgeError | None = None
    raw_payload: dict[str, Any] | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpAgentLogResult:
    """Typed result of reading a managed-agent bridge log."""

    ok: bool
    command: tuple[str, ...]
    path: str
    session_id: str
    status: str | None = None
    output: str | None = None
    log: dict[str, Any] = field(default_factory=dict)
    workspace: str | None = None
    tab: str | None = None
    context_id: str | None = None
    error: RpBridgeError | None = None
    raw_payload: dict[str, Any] | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpAgentRunCancelResult:
    """Typed result of cancelling a managed-agent session."""

    ok: bool
    command: tuple[str, ...]
    path: str
    session_id: str
    status: str | None = None
    workspace: str | None = None
    tab: str | None = None
    context_id: str | None = None
    error: RpBridgeError | None = None
    raw_payload: dict[str, Any] | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpAgentSessionInfo:
    """A single session discovered via `agent_manage op=list_sessions`."""

    session_id: str | None = None
    session_name: str | None = None
    status: str | None = None
    model_id: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RpAgentSessionListResult:
    """Typed result of browsing managed-agent sessions."""

    ok: bool
    command: tuple[str, ...]
    path: str
    sessions: tuple[RpAgentSessionInfo, ...] = ()
    error: RpBridgeError | None = None
    raw_payload: dict[str, Any] | list[Any] | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpAgentSessionResumeResult:
    """Typed result of `agent_manage op=resume_session`."""

    ok: bool
    command: tuple[str, ...]
    path: str
    session_id: str | None = None
    status: str | None = None
    error: RpBridgeError | None = None
    raw_payload: dict[str, Any] | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpAgentTranscriptResult:
    """Typed result of fetching managed-agent transcript/log content."""

    ok: bool
    command: tuple[str, ...]
    path: str
    session_id: str
    status: str | None = None
    transcript: str | None = None
    events: tuple[dict[str, Any], ...] = ()
    handoff_summary: str | None = None
    source_operation: str | None = None
    error: RpBridgeError | None = None
    raw_payload: dict[str, Any] | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpAgentHandoffResult:
    """Typed result of exporting a managed-agent handoff."""

    ok: bool
    command: tuple[str, ...]
    path: str
    session_id: str
    status: str | None = None
    handoff_xml: str | None = None
    handoff_summary: str | None = None
    output_path: str | None = None
    error: RpBridgeError | None = None
    raw_payload: dict[str, Any] | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpBridgeProbeResult:
    """Top-level availability result for a bridge candidate."""

    available: bool
    command: tuple[str, ...]
    path: str
    tools: tuple[RpToolInfo, ...] = ()
    error: RpBridgeError | None = None


class _ToolInvocationMode(Enum):
    COMMAND_MODE_RAW_JSON = "command_mode_raw_json"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class _RpInvocation:
    command: tuple[str, ...]
    path: str
    ok: bool
    stdout: str | None = None
    stderr: str | None = None
    error: RpBridgeError | None = None


_REPOPROMPT_MCP_TOOL_MANIFEST: tuple[RpToolInfo, ...] = (
    RpToolInfo(name="manage_workspaces"),
    RpToolInfo(name="bind_context"),
    RpToolInfo(name="manage_selection"),
    RpToolInfo(name="workspace_context"),
    RpToolInfo(name="context_builder"),
    RpToolInfo(name="ask_oracle"),
    RpToolInfo(name="agent_run"),
    RpToolInfo(name="agent_manage"),
    RpToolInfo(name="read_file"),
    RpToolInfo(name="file_search", description="Search files"),
    RpToolInfo(name="apply_edits", description="Apply direct file edits"),
    RpToolInfo(name="file_actions", description="Create, move, or delete files"),
)


def _resolve_candidate_path(candidate: str) -> str | None:
    raw = candidate.strip()
    if not raw:
        return None
    if any(sep in raw for sep in ("/", "\\")) or raw.startswith("."):
        path = Path(raw).expanduser()
        if path.exists() and path.is_file():
            return str(path)
        return None
    return shutil.which(raw)


class RpCliBridgeClient:
    """Safe client for probing and scoped context seeding via RepoPrompt CLI surfaces."""

    def __init__(self, command: Sequence[str], *, timeout_seconds: int = 5) -> None:
        resolved_command = tuple(str(part).strip() for part in command if str(part).strip())
        if not resolved_command:
            raise ValueError("RpCliBridgeClient requires a non-empty command")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")
        self.command = resolved_command
        self.timeout_seconds = timeout_seconds
        self._invocation_mode: _ToolInvocationMode | None = None
        self._invocation_detection_error: RpBridgeError | None = None
        self._detected_tools: tuple[RpToolInfo, ...] | None = None
        self._tool_schema_command: tuple[str, ...] | None = None

    @classmethod
    def from_command_candidates(
        cls,
        command_candidates: Sequence[str],
        *,
        timeout_seconds: int = 5,
    ) -> RpCliBridgeClient | None:
        for candidate in command_candidates:
            resolved = _resolve_candidate_path(candidate)
            if resolved is not None:
                return cls((resolved,), timeout_seconds=timeout_seconds)
        return None

    def probe_available(self) -> RpBridgeProbeResult:
        result = self.list_tools()
        return RpBridgeProbeResult(
            available=result.ok,
            command=result.command,
            path=result.path,
            tools=result.tools,
            error=result.error,
        )

    def list_tools(self) -> RpToolListResult:
        mode = self._detect_invocation_mode()
        if mode is _ToolInvocationMode.UNAVAILABLE:
            return RpToolListResult(
                ok=False,
                command=self.command,
                path=self.command[0],
                error=self._invocation_detection_error
                or RpBridgeError(
                    code="BRIDGE_TOOL_INVOCATION_UNSUPPORTED",
                    message="RP bridge does not expose a supported MCP tool invocation surface",
                    retriable=False,
                ),
            )
        return RpToolListResult(
            ok=True,
            command=self._tool_schema_command or self.command,
            path=self.command[0],
            tools=self._detected_tools or _REPOPROMPT_MCP_TOOL_MANIFEST,
        )

    def manage_workspaces_list(self, *, include_hidden: bool = False) -> RpWorkspaceListResult:
        capability_error = self._capability_error("manage_workspaces", operation="list")
        if capability_error is not None:
            return RpWorkspaceListResult(ok=False, command=self.command, path=self.command[0], error=capability_error)
        payload: dict[str, Any] = {"action": "list"}
        if include_hidden:
            payload["include_hidden"] = True
        invocation = self._invoke_tool("manage_workspaces", payload, context="manage_workspaces_list")
        if not invocation.ok:
            return RpWorkspaceListResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        response = self._load_json_payload(invocation, context="manage_workspaces_list")
        workspaces = self._extract_workspaces(response)
        return RpWorkspaceListResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            workspaces=workspaces,
            raw_payload=response,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def manage_workspaces_resolve(self, workspace: str, *, include_hidden: bool = True) -> RpWorkspaceResolveResult:
        normalized_workspace = workspace.strip()
        if not normalized_workspace:
            raise ValueError("manage_workspaces_resolve requires a non-empty workspace")
        listed = self.manage_workspaces_list(include_hidden=include_hidden)
        if not listed.ok:
            return RpWorkspaceResolveResult(
                ok=False,
                command=listed.command,
                path=listed.path,
                workspace=normalized_workspace,
                error=listed.error,
                raw_payload=listed.raw_payload,
                raw_stdout=listed.raw_stdout,
                raw_stderr=listed.raw_stderr,
            )
        lowered = normalized_workspace.casefold()
        for matcher, matched_by in (
            (lambda item: item.workspace_id and item.workspace_id.casefold() == lowered, "workspace_id"),
            (lambda item: item.name and item.name.casefold() == lowered, "name"),
        ):
            for item in listed.workspaces:
                if matcher(item):
                    return RpWorkspaceResolveResult(
                        ok=True,
                        command=listed.command,
                        path=listed.path,
                        workspace=item.name or normalized_workspace,
                        workspace_id=item.workspace_id,
                        repo_paths=item.repo_paths,
                        window_ids=item.window_ids,
                        is_hidden=item.is_hidden,
                        matched_by=matched_by,
                        raw_payload=listed.raw_payload,
                        raw_stdout=listed.raw_stdout,
                        raw_stderr=listed.raw_stderr,
                    )
        return RpWorkspaceResolveResult(
            ok=False,
            command=listed.command,
            path=listed.path,
            workspace=normalized_workspace,
            error=RpBridgeError(
                code="WORKSPACE_NOT_FOUND",
                message=f"RepoPrompt workspace {normalized_workspace!r} was not found",
                retriable=False,
            ),
            raw_payload=listed.raw_payload,
            raw_stdout=listed.raw_stdout,
            raw_stderr=listed.raw_stderr,
        )

    def bind_context_status(self) -> RpBindContextResult:
        return self._bind_context({"op": "status"}, context="bind_context_status")

    def bind_context_list(self, *, window_id: int | None = None) -> RpBindContextResult:
        payload: dict[str, Any] = {"op": "list"}
        if window_id is not None:
            payload["window_id"] = window_id
        return self._bind_context(payload, context="bind_context_list")

    def bind_context_bind(
        self,
        *,
        working_dirs: Sequence[str] | None = None,
        context_id: str | None = None,
        window_id: int | None = None,
        create_if_missing: bool = False,
        tab_name: str | None = None,
    ) -> RpBindContextResult:
        payload: dict[str, Any] = {"op": "bind"}
        normalized_dirs = [str(value).strip() for value in (working_dirs or ()) if str(value).strip()]
        if normalized_dirs:
            payload["working_dirs"] = ",".join(normalized_dirs) if len(normalized_dirs) > 1 else normalized_dirs[0]
        if context_id is not None:
            payload["context_id"] = context_id
        if window_id is not None:
            payload["window_id"] = window_id
        if create_if_missing:
            payload["create_if_missing"] = True
        if tab_name is not None:
            payload["tab_name"] = tab_name
        if set(payload) == {"op"}:
            raise ValueError("bind_context_bind requires working_dirs, context_id, or window_id")
        return self._bind_context(payload, context="bind_context_bind")

    def workspace_context(self, workspace: str | None = None) -> RpWorkspaceContextResult:
        capability_error = self._capability_error("workspace_context")
        if capability_error is not None:
            return RpWorkspaceContextResult(ok=False, command=self.command, path=self.command[0], error=capability_error)
        payload: dict[str, Any] = {}
        if workspace is not None:
            payload["workspace"] = workspace
        invocation = self._invoke_tool(
            "workspace_context",
            payload or None,
            context="workspace context",
        )
        if not invocation.ok:
            return RpWorkspaceContextResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        response = self._load_json_payload(invocation, context="workspace context")
        if not isinstance(response, dict):
            return RpWorkspaceContextResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                error=self._malformed_response_error(
                    invocation,
                    context="workspace context",
                    message="workspace context probe did not return a JSON object",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        raw_tokens = response.get("tokens")
        raw_sections = response.get("sections")
        return RpWorkspaceContextResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            workspace=self._optional_string(response.get("workspace")),
            context_id=self._optional_string(response.get("context_id")),
            selected_paths=self._extract_selected_paths(response),
            prompt=self._optional_string(response.get("prompt")),
            tokens=dict(raw_tokens) if isinstance(raw_tokens, Mapping) else None,
            sections=dict(raw_sections) if isinstance(raw_sections, Mapping) else None,
            export_path=self._optional_string(response.get("export_path"))
            or self._optional_string(response.get("path")),
            raw_payload=response,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def workspace_context_snapshot(
        self,
        *,
        include: Sequence[str] | None = None,
        path_display: str | None = None,
        copy_preset: str | None = None,
    ) -> RpWorkspaceContextResult:
        capability_error = self._capability_error("workspace_context", operation="snapshot")
        if capability_error is not None:
            return RpWorkspaceContextResult(ok=False, command=self.command, path=self.command[0], error=capability_error)
        payload: dict[str, Any] = {"op": "snapshot"}
        normalized_include = [item.strip() for item in (include or ()) if isinstance(item, str) and item.strip()]
        if normalized_include:
            payload["include"] = normalized_include
        if path_display is not None:
            payload["path_display"] = path_display
        if copy_preset is not None:
            payload["copy_preset"] = copy_preset
        invocation = self._invoke_tool("workspace_context", payload, context="workspace_context_snapshot")
        if not invocation.ok:
            return RpWorkspaceContextResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        response = self._load_json_payload(invocation, context="workspace_context_snapshot")
        if not isinstance(response, dict):
            return RpWorkspaceContextResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                error=self._malformed_response_error(
                    invocation,
                    context="workspace_context_snapshot",
                    message="workspace_context_snapshot did not return a JSON object",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        raw_tokens = response.get("tokens")
        return RpWorkspaceContextResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            workspace=self._optional_string(response.get("workspace")),
            context_id=self._optional_string(response.get("context_id")),
            selected_paths=self._extract_selected_paths(response),
            prompt=self._optional_string(response.get("prompt")),
            tokens=dict(raw_tokens) if isinstance(raw_tokens, Mapping) else None,
            sections={
                key: response.get(key)
                for key in ("selection", "code", "files", "tree")
                if response.get(key) is not None
            }
            or None,
            export_path=self._optional_string(response.get("path"))
            or self._optional_string(response.get("export_path")),
            raw_payload=response,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def context_builder_preview(self, instructions: str | None = None) -> RpContextBuilderResult:
        return self._context_builder_call(
            instructions=instructions,
            response_type="clarify",
            export_response=False,
            flow="preview",
        )

    def context_builder_apply(
        self,
        instructions: str,
        *,
        response_type: Literal["plan", "question", "review"] = "plan",
        export_response: bool = False,
    ) -> RpContextBuilderResult:
        normalized_instructions = instructions.strip()
        if not normalized_instructions:
            raise ValueError("context_builder_apply requires non-empty instructions")
        return self._context_builder_call(
            instructions=normalized_instructions,
            response_type=response_type,
            export_response=export_response,
            flow="apply",
        )

    def ask_oracle(
        self,
        message: str,
        *,
        mode: Literal["chat", "plan", "review"] = "chat",
        chat_id: str | None = None,
        new_chat: bool | None = None,
        export_response: bool = False,
    ) -> RpAskOracleResult:
        capability_error = self._capability_error("ask_oracle")
        if capability_error is not None:
            return RpAskOracleResult(ok=False, command=self.command, path=self.command[0], mode=mode, error=capability_error)
        normalized_message = message.strip()
        if not normalized_message:
            raise ValueError("ask_oracle requires a non-empty message")
        if not self._tool_property_supports_value("ask_oracle", "mode", mode):
            return RpAskOracleResult(
                ok=False,
                command=self.command,
                path=self.command[0],
                mode=mode,
                error=RpBridgeError(
                    code="TOOL_UNAVAILABLE",
                    message=f"RP bridge tool 'ask_oracle' does not support mode {mode!r}",
                    retriable=False,
                    detail={"tool": "ask_oracle", "mode": mode},
                ),
            )
        payload: dict[str, Any] = {"message": normalized_message, "mode": mode}
        if chat_id is not None:
            payload["chat_id"] = chat_id
        if new_chat is not None:
            payload["new_chat"] = new_chat
        if export_response:
            payload["export_response"] = True

        invocation = self._invoke_tool("ask_oracle", payload, context="ask_oracle")
        if not invocation.ok:
            return RpAskOracleResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                mode=mode,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        response = self._load_json_payload(invocation, context="ask_oracle")
        if response is not None and not isinstance(response, dict):
            return RpAskOracleResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                mode=mode,
                error=self._malformed_response_error(
                    invocation,
                    context="ask_oracle",
                    message="ask_oracle did not return a JSON object",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        mapping = response if isinstance(response, dict) else {}
        return RpAskOracleResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            mode=self._optional_string(mapping.get("mode")) or mode,
            chat_id=self._optional_string(mapping.get("chat_id")),
            response_text=self._extract_output_text(mapping)
            or self._optional_string(mapping.get("response"))
            or (invocation.stdout or "").strip()
            or None,
            export_path=self._optional_string(mapping.get("oracle_export_path"))
            or self._optional_string(mapping.get("export_path")),
            raw_payload=mapping or None,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def manage_selection_add(
        self,
        paths: Sequence[str],
        *,
        workspace: str | None = None,
        tab: str | None = None,
        context_id: str | None = None,
        mode: str = "full",
    ) -> RpManageSelectionResult:
        capability_error = self._capability_error("manage_selection")
        if capability_error is not None:
            return RpManageSelectionResult(ok=False, command=self.command, path=self.command[0], error=capability_error)
        normalized_paths = tuple(str(path).strip() for path in paths if str(path).strip())
        if not normalized_paths:
            raise ValueError("manage_selection_add requires at least one path")
        payload: dict[str, Any] = {
            "op": "add",
            "mode": mode,
            "paths": list(normalized_paths),
        }
        if workspace is not None:
            payload["workspace"] = workspace
        if tab is not None:
            payload["tab"] = tab
        if context_id is not None:
            payload["context_id"] = context_id

        invocation = self._invoke_tool("manage_selection", payload, context="manage_selection")
        if not invocation.ok:
            return RpManageSelectionResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        response = self._load_json_payload(invocation, context="manage_selection")
        if not isinstance(response, dict):
            return RpManageSelectionResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                error=self._malformed_response_error(
                    invocation,
                    context="manage_selection",
                    message="manage_selection did not return a JSON object",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        return RpManageSelectionResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            workspace=self._optional_string(response.get("workspace")) or workspace,
            context_id=self._optional_string(response.get("context_id")) or context_id,
            selected_paths=self._extract_selected_paths(response),
            added_paths=self._extract_string_list(response, keys=("added_paths", "paths", "resolved_paths")),
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def read_file(
        self,
        source: str,
        *,
        workspace: str | None = None,
        tab: str | None = None,
        context_id: str | None = None,
        start_line: int | None = None,
        limit: int | None = None,
    ) -> RpReadFileResult:
        capability_error = self._capability_error("read_file")
        if capability_error is not None:
            return RpReadFileResult(ok=False, command=self.command, path=self.command[0], source=source.strip(), error=capability_error)
        normalized_source = source.strip()
        if not normalized_source:
            raise ValueError("read_file requires a non-empty source")
        payload: dict[str, Any] = {"source": normalized_source}
        if workspace is not None:
            payload["workspace"] = workspace
        if tab is not None:
            payload["tab"] = tab
        if context_id is not None:
            payload["context_id"] = context_id
        if start_line is not None:
            payload["start_line"] = start_line
        if limit is not None:
            payload["limit"] = limit

        invocation = self._invoke_tool("read_file", payload, context="read_file")
        if not invocation.ok:
            return RpReadFileResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                source=normalized_source,
                start_line=start_line,
                limit=limit,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        response = self._load_json_payload(invocation, context="read_file")
        if not isinstance(response, dict):
            return RpReadFileResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                source=normalized_source,
                start_line=start_line,
                limit=limit,
                error=self._malformed_response_error(
                    invocation,
                    context="read_file",
                    message="read_file did not return a JSON object",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        content = response.get("content")
        if not isinstance(content, str):
            return RpReadFileResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                source=normalized_source,
                start_line=start_line,
                limit=limit,
                error=self._malformed_response_error(
                    invocation,
                    context="read_file",
                    message="read_file did not include string content",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        return RpReadFileResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            source=normalized_source,
            content=content,
            workspace=self._optional_string(response.get("workspace")) or workspace,
            context_id=self._optional_string(response.get("context_id")) or context_id,
            resolved_source=self._optional_string(response.get("source")) or self._optional_string(response.get("path")),
            start_line=start_line,
            limit=limit,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def file_search(
        self,
        query: str,
        *,
        scope_paths: Sequence[str] | None = None,
        max_results: int | None = 20,
        include_snippets: bool = True,
    ) -> RpFileSearchResult:
        capability_error = self._capability_error("file_search")
        normalized_query = query.strip()
        if capability_error is not None:
            return RpFileSearchResult(
                ok=False,
                command=self.command,
                path=self.command[0],
                query=normalized_query,
                error=capability_error,
            )
        if not normalized_query:
            raise ValueError("file_search requires a non-empty query")
        payload: dict[str, Any] = {"pattern": normalized_query}
        normalized_scope = [path.strip() for path in (scope_paths or ()) if isinstance(path, str) and path.strip()]
        if normalized_scope:
            payload["filter"] = {"paths": normalized_scope}
        if max_results is not None:
            payload["max_results"] = max_results
        payload["context_lines"] = 1 if include_snippets else 0

        invocation = self._invoke_tool("file_search", payload, context="file_search")
        if not invocation.ok:
            return RpFileSearchResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                query=normalized_query,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        response = self._load_json_payload(invocation, context="file_search")
        if response is not None and not isinstance(response, (dict, list)):
            return RpFileSearchResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                query=normalized_query,
                error=self._malformed_response_error(
                    invocation,
                    context="file_search",
                    message="file_search did not return a JSON object or list",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        parsed = self._extract_file_search_matches(response)
        return RpFileSearchResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            query=normalized_query,
            matches=parsed,
            matched_paths=tuple(sorted({match.path for match in parsed})),
            count=(len(parsed) if isinstance(response, list) else self._optional_int(response.get("count")) if isinstance(response, dict) else None),
            truncated=(self._optional_bool(response.get("truncated")) or False) if isinstance(response, dict) else False,
            raw_payload=response,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def apply_edits_commit(
        self,
        *,
        apply_token: str,
        path: str,
        rewrite: str | None = None,
        search: str | None = None,
        replace: str | None = None,
        edits: Sequence[Mapping[str, Any]] | None = None,
        all: bool | None = None,
        on_missing: Literal["error", "create"] | None = None,
        verbose: bool | None = None,
    ) -> RpApplyEditsResult:
        capability_error = self._capability_error("apply_edits")
        normalized_path = path.strip()
        if capability_error is not None:
            return RpApplyEditsResult(
                ok=False,
                command=self.command,
                path=self.command[0],
                target_path=normalized_path,
                error=capability_error,
            )
        if not apply_token.strip():
            raise ValueError("apply_edits_commit requires a non-empty apply_token")
        if not normalized_path:
            raise ValueError("apply_edits_commit requires a non-empty path")

        payload: dict[str, Any] = {"path": normalized_path}
        mode_count = 0
        if rewrite is not None:
            payload["rewrite"] = rewrite
            mode_count += 1
        if search is not None or replace is not None:
            if search is None or replace is None:
                raise ValueError("apply_edits_commit requires both search and replace for single replacement mode")
            payload["search"] = search
            payload["replace"] = replace
            mode_count += 1
        if edits is not None:
            payload["edits"] = [dict(item) for item in edits]
            mode_count += 1
        if mode_count != 1:
            raise ValueError("apply_edits_commit requires exactly one edit mode: rewrite, search/replace, or edits")
        if all is not None:
            payload["all"] = all
        if on_missing is not None:
            payload["on_missing"] = on_missing
        if verbose is not None:
            payload["verbose"] = verbose

        invocation = self._invoke_tool("apply_edits", payload, context="apply_edits_commit")
        if not invocation.ok:
            return RpApplyEditsResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                target_path=normalized_path,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        response = self._load_json_payload(invocation, context="apply_edits_commit")
        if response is not None and not isinstance(response, (dict, list)):
            return RpApplyEditsResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                target_path=normalized_path,
                error=self._malformed_response_error(
                    invocation,
                    context="apply_edits_commit",
                    message="apply_edits_commit did not return a JSON object or list",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        return RpApplyEditsResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            target_path=normalized_path,
            changed_paths=self._extract_changed_paths(response, fallback=normalized_path),
            summary=self._extract_response_summary(response),
            raw_payload=response,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def file_actions_commit(
        self,
        *,
        apply_token: str,
        action: Literal["create", "delete", "move"],
        path: str,
        content: str | None = None,
        new_path: str | None = None,
        if_exists: Literal["error", "overwrite"] | None = None,
    ) -> RpFileActionResult:
        capability_error = self._capability_error("file_actions")
        normalized_path = path.strip()
        if capability_error is not None:
            return RpFileActionResult(
                ok=False,
                command=self.command,
                path=self.command[0],
                action=action,
                target_path=normalized_path,
                error=capability_error,
            )
        if not apply_token.strip():
            raise ValueError("file_actions_commit requires a non-empty apply_token")
        if not normalized_path:
            raise ValueError("file_actions_commit requires a non-empty path")

        payload: dict[str, Any] = {"action": action, "path": normalized_path}
        if action == "create":
            if content is None:
                raise ValueError("file_actions_commit create action requires content")
            payload["content"] = content
            if if_exists is not None:
                payload["if_exists"] = if_exists
        if action == "move":
            if new_path is None or not new_path.strip():
                raise ValueError("file_actions_commit move action requires new_path")
            payload["new_path"] = new_path.strip()

        invocation = self._invoke_tool("file_actions", payload, context="file_actions_commit")
        if not invocation.ok:
            return RpFileActionResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                action=action,
                target_path=normalized_path,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        response = self._load_json_payload(invocation, context="file_actions_commit")
        if response is not None and not isinstance(response, (dict, list)):
            return RpFileActionResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                action=action,
                target_path=normalized_path,
                error=self._malformed_response_error(
                    invocation,
                    context="file_actions_commit",
                    message="file_actions_commit did not return a JSON object or list",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        return RpFileActionResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            action=action,
            target_path=normalized_path,
            changed_paths=self._extract_changed_paths(response, fallback=normalized_path),
            summary=self._extract_response_summary(response),
            raw_payload=response,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def agent_run_start(
        self,
        prompt: str,
        *,
        workspace: str | None = None,
        tab: str | None = None,
        context_id: str | None = None,
        agent_role: str | None = None,
        stage: str | None = None,
    ) -> RpAgentRunStartResult:
        capability_error = self._capability_error("agent_run", operation="start")
        if capability_error is not None:
            return RpAgentRunStartResult(ok=False, command=self.command, path=self.command[0], error=capability_error)
        if not prompt.strip():
            raise ValueError("agent_run_start requires a non-empty prompt")
        payload: dict[str, Any] = {"op": "start", "message": prompt, "detach": True}
        if workspace is not None:
            payload["workspace"] = workspace
        if tab is not None:
            payload["tab"] = tab
        if context_id is not None:
            payload["context_id"] = context_id
        if agent_role is not None:
            payload["agent_role"] = agent_role
        if stage is not None:
            payload["stage"] = stage

        invocation = self._invoke_tool("agent_run", payload, context="agent_run_start")
        if not invocation.ok:
            return RpAgentRunStartResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        response = self._load_json_payload(invocation, context="agent_run_start")
        if not isinstance(response, dict):
            return RpAgentRunStartResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                error=self._malformed_response_error(
                    invocation,
                    context="agent_run_start",
                    message="agent_run_start did not return a JSON object",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        session_id = self._optional_string(response.get("session_id"))
        if session_id is None:
            return RpAgentRunStartResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                error=self._malformed_response_error(
                    invocation,
                    context="agent_run_start",
                    message="agent_run_start did not include a non-empty session_id",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        return RpAgentRunStartResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            session_id=session_id,
            status=self._optional_string(response.get("status")),
            workspace=self._optional_string(response.get("workspace")) or workspace,
            tab=self._optional_string(response.get("tab")) or tab,
            context_id=self._optional_string(response.get("context_id")) or context_id,
            raw_payload=response,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def agent_run_poll(
        self,
        session_id: str,
        *,
        workspace: str | None = None,
        tab: str | None = None,
        context_id: str | None = None,
    ) -> RpAgentRunWaitResult:
        capability_error = self._capability_error("agent_run", operation="poll")
        normalized_session_id = session_id.strip()
        if capability_error is not None:
            return RpAgentRunWaitResult(
                ok=False,
                command=self.command,
                path=self.command[0],
                session_id=normalized_session_id,
                error=capability_error,
            )
        if not normalized_session_id:
            raise ValueError("agent_run_poll requires a non-empty session_id")
        payload: dict[str, Any] = {"op": "poll", "session_id": normalized_session_id}
        if workspace is not None:
            payload["workspace"] = workspace
        if tab is not None:
            payload["tab"] = tab
        if context_id is not None:
            payload["context_id"] = context_id
        invocation = self._invoke_tool("agent_run", payload, context="agent_run_poll")
        if not invocation.ok:
            return RpAgentRunWaitResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                session_id=normalized_session_id,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        response = self._load_json_payload(invocation, context="agent_run_poll")
        if not isinstance(response, dict):
            return RpAgentRunWaitResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                session_id=normalized_session_id,
                error=self._malformed_response_error(
                    invocation,
                    context="agent_run_poll",
                    message="agent_run_poll did not return a JSON object",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        status = self._optional_string(response.get("status"))
        if status is None:
            return RpAgentRunWaitResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                session_id=normalized_session_id,
                error=self._malformed_response_error(
                    invocation,
                    context="agent_run_poll",
                    message="agent_run_poll did not include a non-empty status",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        return RpAgentRunWaitResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            session_id=normalized_session_id,
            status=status,
            output=self._extract_output_text(response),
            workspace=self._optional_string(response.get("workspace")) or workspace,
            tab=self._optional_string(response.get("tab")) or tab,
            context_id=self._optional_string(response.get("context_id")) or context_id,
            raw_payload=response,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def agent_run_wait(
        self,
        session_id: str,
        *,
        workspace: str | None = None,
        tab: str | None = None,
        context_id: str | None = None,
    ) -> RpAgentRunWaitResult:
        capability_error = self._capability_error("agent_run", operation="wait")
        normalized_session_id = session_id.strip()
        if capability_error is not None:
            return RpAgentRunWaitResult(
                ok=False,
                command=self.command,
                path=self.command[0],
                session_id=normalized_session_id,
                error=capability_error,
            )
        if not normalized_session_id:
            raise ValueError("agent_run_wait requires a non-empty session_id")
        wait_timeout_seconds = max(1, self.timeout_seconds - 1)
        payload: dict[str, Any] = {
            "op": "wait",
            "session_id": normalized_session_id,
            "timeout": wait_timeout_seconds,
        }
        if workspace is not None:
            payload["workspace"] = workspace
        if tab is not None:
            payload["tab"] = tab
        if context_id is not None:
            payload["context_id"] = context_id

        invocation = self._invoke_tool("agent_run", payload, context="agent_run_wait")
        if not invocation.ok:
            return RpAgentRunWaitResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                session_id=normalized_session_id,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        response = self._load_json_payload(invocation, context="agent_run_wait")
        if not isinstance(response, dict):
            return RpAgentRunWaitResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                session_id=normalized_session_id,
                error=self._malformed_response_error(
                    invocation,
                    context="agent_run_wait",
                    message="agent_run_wait did not return a JSON object",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        status = self._optional_string(response.get("status"))
        if status is None:
            return RpAgentRunWaitResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                session_id=normalized_session_id,
                error=self._malformed_response_error(
                    invocation,
                    context="agent_run_wait",
                    message="agent_run_wait did not include a non-empty status",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        return RpAgentRunWaitResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            session_id=normalized_session_id,
            status=status,
            output=self._extract_output_text(response),
            workspace=self._optional_string(response.get("workspace")) or workspace,
            tab=self._optional_string(response.get("tab")) or tab,
            context_id=self._optional_string(response.get("context_id")) or context_id,
            raw_payload=response,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def agent_run_cancel(
        self,
        session_id: str,
        *,
        workspace: str | None = None,
        tab: str | None = None,
        context_id: str | None = None,
    ) -> RpAgentRunCancelResult:
        capability_error = self._capability_error("agent_run", operation="cancel")
        normalized_session_id = session_id.strip()
        if capability_error is not None:
            return RpAgentRunCancelResult(
                ok=False,
                command=self.command,
                path=self.command[0],
                session_id=normalized_session_id,
                error=capability_error,
            )
        if not normalized_session_id:
            raise ValueError("agent_run_cancel requires a non-empty session_id")
        payload: dict[str, Any] = {"op": "cancel", "session_id": normalized_session_id}
        if workspace is not None:
            payload["workspace"] = workspace
        if tab is not None:
            payload["tab"] = tab
        if context_id is not None:
            payload["context_id"] = context_id
        invocation = self._invoke_tool("agent_run", payload, context="agent_run_cancel")
        if not invocation.ok:
            return RpAgentRunCancelResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                session_id=normalized_session_id,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        response = self._load_json_payload(invocation, context="agent_run_cancel")
        if response is not None and not isinstance(response, dict):
            return RpAgentRunCancelResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                session_id=normalized_session_id,
                error=self._malformed_response_error(
                    invocation,
                    context="agent_run_cancel",
                    message="agent_run_cancel did not return a JSON object",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        mapping = response if isinstance(response, dict) else {}
        return RpAgentRunCancelResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            session_id=normalized_session_id,
            status=self._optional_string(mapping.get("status")) or "cancelled",
            workspace=self._optional_string(mapping.get("workspace")) or workspace,
            tab=self._optional_string(mapping.get("tab")) or tab,
            context_id=self._optional_string(mapping.get("context_id")) or context_id,
            raw_payload=mapping or None,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def agent_log(
        self,
        session_id: str,
        *,
        workspace: str | None = None,
        tab: str | None = None,
        context_id: str | None = None,
    ) -> RpAgentLogResult:
        capability_error = self._capability_error("agent_manage", operation="get_log")
        normalized_session_id = session_id.strip()
        if capability_error is not None:
            return RpAgentLogResult(
                ok=False,
                command=self.command,
                path=self.command[0],
                session_id=normalized_session_id,
                error=capability_error,
            )
        if not normalized_session_id:
            raise ValueError("agent_log requires a non-empty session_id")
        payload: dict[str, Any] = {"op": "get_log", "session_id": normalized_session_id}
        if workspace is not None:
            payload["workspace"] = workspace
        if tab is not None:
            payload["tab"] = tab
        if context_id is not None:
            payload["context_id"] = context_id

        invocation = self._invoke_tool("agent_manage", payload, context="agent_log")
        if not invocation.ok:
            return RpAgentLogResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                session_id=normalized_session_id,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        response = self._load_json_payload(invocation, context="agent_log")
        if response is None:
            transcript = (invocation.stdout or "").strip() or None
            return RpAgentLogResult(
                ok=True,
                command=invocation.command,
                path=invocation.path,
                session_id=normalized_session_id,
                status=None,
                output=transcript,
                log={"transcript": transcript} if transcript is not None else {},
                workspace=workspace,
                tab=tab,
                context_id=context_id,
                raw_payload=None,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        if not isinstance(response, dict):
            transcript = (invocation.stdout or "").strip() or None
            return RpAgentLogResult(
                ok=True,
                command=invocation.command,
                path=invocation.path,
                session_id=normalized_session_id,
                status=None,
                output=transcript,
                log={"transcript": transcript} if transcript is not None else {},
                workspace=workspace,
                tab=tab,
                context_id=context_id,
                raw_payload=None,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        status = self._optional_string(response.get("status"))
        return RpAgentLogResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            session_id=normalized_session_id,
            status=status,
            output=self._extract_output_text(response),
            log=response,
            workspace=self._optional_string(response.get("workspace")) or workspace,
            tab=self._optional_string(response.get("tab")) or tab,
            context_id=self._optional_string(response.get("context_id")) or context_id,
            raw_payload=response,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def agent_manage_list_sessions(
        self,
        *,
        limit: int | None = None,
        state: str | None = None,
        name: str | None = None,
    ) -> RpAgentSessionListResult:
        capability_error = self._capability_error("agent_manage", operation="list_sessions")
        if capability_error is not None:
            return RpAgentSessionListResult(ok=False, command=self.command, path=self.command[0], error=capability_error)
        payload: dict[str, Any] = {"op": "list_sessions"}
        if limit is not None:
            payload["limit"] = limit
        if state is not None:
            payload["state"] = state
        if name is not None:
            payload["name"] = name
        invocation = self._invoke_tool("agent_manage", payload, context="agent_manage_list_sessions")
        if not invocation.ok:
            return RpAgentSessionListResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        response = self._load_json_payload(invocation, context="agent_manage_list_sessions")
        sessions = self._extract_agent_sessions(response)
        return RpAgentSessionListResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            sessions=sessions,
            raw_payload=response,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def agent_manage_resume_session(self, session_id: str, *, model_id: str | None = None) -> RpAgentSessionResumeResult:
        capability_error = self._capability_error("agent_manage", operation="resume_session")
        normalized_session_id = session_id.strip()
        if capability_error is not None:
            return RpAgentSessionResumeResult(
                ok=False,
                command=self.command,
                path=self.command[0],
                session_id=normalized_session_id,
                error=capability_error,
            )
        if not normalized_session_id:
            raise ValueError("agent_manage_resume_session requires a non-empty session_id")
        payload: dict[str, Any] = {"op": "resume_session", "session_id": normalized_session_id}
        if model_id is not None:
            payload["model_id"] = model_id
        invocation = self._invoke_tool("agent_manage", payload, context="agent_manage_resume_session")
        if not invocation.ok:
            return RpAgentSessionResumeResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                session_id=normalized_session_id,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        response = self._load_json_payload(invocation, context="agent_manage_resume_session")
        if response is not None and not isinstance(response, dict):
            return RpAgentSessionResumeResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                session_id=normalized_session_id,
                error=self._malformed_response_error(
                    invocation,
                    context="agent_manage_resume_session",
                    message="agent_manage_resume_session did not return a JSON object",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        mapping = response if isinstance(response, dict) else {}
        return RpAgentSessionResumeResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            session_id=self._optional_string(mapping.get("session_id")) or normalized_session_id,
            status=self._optional_string(mapping.get("status")),
            raw_payload=mapping or None,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def agent_manage_transcript(
        self,
        session_id: str,
        *,
        offset: int | None = None,
        limit: int | None = None,
    ) -> RpAgentTranscriptResult:
        normalized_session_id = session_id.strip()
        if not normalized_session_id:
            raise ValueError("agent_manage_transcript requires a non-empty session_id")

        if self._tool_supports_operation("agent_manage", "get_transcript"):
            payload: dict[str, Any] = {"op": "get_transcript", "session_id": normalized_session_id}
            if offset is not None:
                payload["offset"] = offset
            if limit is not None:
                payload["limit"] = limit
            invocation = self._invoke_tool("agent_manage", payload, context="agent_manage_transcript")
            if not invocation.ok:
                return RpAgentTranscriptResult(
                    ok=False,
                    command=invocation.command,
                    path=invocation.path,
                    session_id=normalized_session_id,
                    error=invocation.error,
                    raw_stdout=invocation.stdout,
                    raw_stderr=invocation.stderr,
                )
            response = self._load_json_payload(invocation, context="agent_manage_transcript")
            if not isinstance(response, dict):
                return RpAgentTranscriptResult(
                    ok=False,
                    command=invocation.command,
                    path=invocation.path,
                    session_id=normalized_session_id,
                    error=self._malformed_response_error(
                        invocation,
                        context="agent_manage_transcript",
                        message="agent_manage_transcript did not return a JSON object",
                    ),
                    raw_stdout=invocation.stdout,
                    raw_stderr=invocation.stderr,
                )
            raw_events = response.get("events")
            events = tuple(item for item in raw_events if isinstance(item, dict)) if isinstance(raw_events, list) else ()
            return RpAgentTranscriptResult(
                ok=True,
                command=invocation.command,
                path=invocation.path,
                session_id=normalized_session_id,
                status=self._optional_string(response.get("status")),
                transcript=self._optional_string(response.get("transcript")) or self._extract_output_text(response),
                events=events,
                handoff_summary=self._optional_string(response.get("handoff_summary"))
                or self._optional_string(response.get("summary")),
                source_operation="get_transcript",
                raw_payload=response,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )

        log_result = self.agent_log(normalized_session_id)
        if not log_result.ok:
            return RpAgentTranscriptResult(
                ok=False,
                command=log_result.command,
                path=log_result.path,
                session_id=log_result.session_id,
                error=log_result.error,
                raw_payload=log_result.raw_payload,
                raw_stdout=log_result.raw_stdout,
                raw_stderr=log_result.raw_stderr,
            )
        transcript = log_result.output
        events = ()
        raw_payload = log_result.raw_payload
        if isinstance(raw_payload, dict):
            raw_events = raw_payload.get("events")
            if isinstance(raw_events, list):
                events = tuple(item for item in raw_events if isinstance(item, dict))
        return RpAgentTranscriptResult(
            ok=True,
            command=log_result.command,
            path=log_result.path,
            session_id=log_result.session_id,
            status=log_result.status,
            transcript=transcript,
            events=events,
            source_operation="get_log",
            raw_payload=raw_payload,
            raw_stdout=log_result.raw_stdout,
            raw_stderr=log_result.raw_stderr,
        )

    def agent_manage_extract_handoff(
        self,
        session_id: str,
        *,
        output_path: str | None = None,
        inline: bool | None = None,
    ) -> RpAgentHandoffResult:
        capability_error = self._capability_error("agent_manage", operation="extract_handoff")
        normalized_session_id = session_id.strip()
        if capability_error is not None:
            return RpAgentHandoffResult(
                ok=False,
                command=self.command,
                path=self.command[0],
                session_id=normalized_session_id,
                error=capability_error,
            )
        if not normalized_session_id:
            raise ValueError("agent_manage_extract_handoff requires a non-empty session_id")
        payload: dict[str, Any] = {"op": "extract_handoff", "session_id": normalized_session_id}
        if output_path is not None:
            payload["output_path"] = output_path
        if inline is not None:
            payload["inline"] = inline
        invocation = self._invoke_tool("agent_manage", payload, context="agent_manage_extract_handoff")
        if not invocation.ok:
            return RpAgentHandoffResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                session_id=normalized_session_id,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        response = self._load_json_payload(invocation, context="agent_manage_extract_handoff")
        handoff_xml = (invocation.stdout or "").strip() or None
        resolved_output_path = output_path
        raw_payload: dict[str, Any] | None = None
        if isinstance(response, dict):
            raw_payload = response
            handoff_xml = self._optional_string(response.get("handoff_xml")) or self._extract_output_text(response) or handoff_xml
            resolved_output_path = self._optional_string(response.get("output_path")) or output_path
        elif response is not None:
            return RpAgentHandoffResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                session_id=normalized_session_id,
                error=self._malformed_response_error(
                    invocation,
                    context="agent_manage_extract_handoff",
                    message="agent_manage_extract_handoff did not return valid JSON or XML",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        return RpAgentHandoffResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            session_id=normalized_session_id,
            status=self._optional_string(raw_payload.get("status")) if isinstance(raw_payload, dict) else None,
            handoff_xml=handoff_xml,
            handoff_summary=(
                self._optional_string(raw_payload.get("handoff_summary"))
                or self._optional_string(raw_payload.get("summary"))
                if isinstance(raw_payload, dict)
                else None
            ),
            output_path=resolved_output_path,
            raw_payload=raw_payload,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def _bind_context(self, payload: Mapping[str, Any], *, context: str) -> RpBindContextResult:
        capability_error = self._capability_error("bind_context", operation=str(payload.get("op", "")).strip() or None)
        if capability_error is not None:
            return RpBindContextResult(ok=False, command=self.command, path=self.command[0], error=capability_error)
        invocation = self._invoke_tool("bind_context", payload, context=context)
        if not invocation.ok:
            return RpBindContextResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        response = self._load_json_payload(invocation, context=context)
        if response is not None and not isinstance(response, dict):
            return RpBindContextResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                error=self._malformed_response_error(
                    invocation,
                    context=context,
                    message=f"{context} did not return a JSON object",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        mapping = response if isinstance(response, dict) else {}
        return RpBindContextResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            workspace=self._optional_string(self._resolve_nested_value(mapping, ("workspace", "name")))
            or self._optional_string(mapping.get("workspace"))
            or self._optional_string(self._resolve_nested_value(mapping, ("current_workspace", "name"))),
            workspace_id=self._optional_string(self._resolve_nested_value(mapping, ("workspace", "id")))
            or self._optional_string(self._resolve_nested_value(mapping, ("current_workspace", "id")))
            or self._optional_string(mapping.get("workspace_id")),
            window_id=self._optional_int(mapping.get("window_id"))
            or self._optional_int(self._resolve_nested_value(mapping, ("binding", "window_id")))
            or self._optional_int(self._resolve_nested_value(mapping, ("current_binding", "window_id"))),
            tab=self._optional_string(self._resolve_nested_value(mapping, ("tab", "name")))
            or self._optional_string(mapping.get("tab"))
            or self._optional_string(self._resolve_nested_value(mapping, ("binding", "tab_name"))),
            tab_id=self._optional_string(self._resolve_nested_value(mapping, ("tab", "id")))
            or self._optional_string(mapping.get("tab_id"))
            or self._optional_string(self._resolve_nested_value(mapping, ("binding", "tab_id"))),
            context_id=self._optional_string(mapping.get("context_id"))
            or self._optional_string(self._resolve_nested_value(mapping, ("tab", "context_id")))
            or self._optional_string(self._resolve_nested_value(mapping, ("binding", "context_id")))
            or self._optional_string(self._resolve_nested_value(mapping, ("current_binding", "context_id"))),
            working_dirs=self._extract_string_list(mapping, keys=("working_dirs", "repo_paths", "repoPaths")),
            windows=tuple(window for window in self._extract_windows(mapping) if isinstance(window, dict)),
            raw_payload=mapping or None,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def _context_builder_call(
        self,
        *,
        instructions: str | None,
        response_type: str,
        export_response: bool,
        flow: Literal["preview", "apply"],
    ) -> RpContextBuilderResult:
        capability_error = self._capability_error("context_builder")
        if capability_error is not None:
            return RpContextBuilderResult(
                ok=False,
                command=self.command,
                path=self.command[0],
                flow=flow,
                response_type=response_type,
                error=capability_error,
            )
        if not self._tool_property_supports_value("context_builder", "response_type", response_type):
            return RpContextBuilderResult(
                ok=False,
                command=self.command,
                path=self.command[0],
                flow=flow,
                response_type=response_type,
                error=RpBridgeError(
                    code="TOOL_UNAVAILABLE",
                    message=f"RP bridge tool 'context_builder' does not support response_type {response_type!r}",
                    retriable=False,
                    detail={"tool": "context_builder", "response_type": response_type},
                ),
            )
        payload: dict[str, Any] = {"response_type": response_type}
        normalized_instructions = instructions.strip() if isinstance(instructions, str) else None
        if normalized_instructions:
            payload["instructions"] = normalized_instructions
        if export_response:
            payload["export_response"] = True
        invocation = self._invoke_tool("context_builder", payload, context=f"context_builder_{flow}")
        if not invocation.ok:
            return RpContextBuilderResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                flow=flow,
                response_type=response_type,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        response = self._load_json_payload(invocation, context=f"context_builder_{flow}")
        if response is not None and not isinstance(response, dict):
            return RpContextBuilderResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                flow=flow,
                response_type=response_type,
                error=self._malformed_response_error(
                    invocation,
                    context=f"context_builder_{flow}",
                    message=f"context_builder_{flow} did not return a JSON object",
                ),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        mapping = response if isinstance(response, dict) else {}
        return RpContextBuilderResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            flow=flow,
            response_type=self._optional_string(mapping.get("response_type")) or response_type,
            context_id=self._optional_string(mapping.get("context_id")),
            workspace=self._optional_string(mapping.get("workspace")),
            selected_paths=self._extract_selected_paths(mapping),
            response_text=self._extract_output_text(mapping)
            or self._optional_string(mapping.get("response"))
            or (invocation.stdout or "").strip()
            or None,
            export_path=self._optional_string(mapping.get("oracle_export_path"))
            or self._optional_string(mapping.get("export_path")),
            raw_payload=mapping or None,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def _capability_error(self, tool: str, *, operation: str | None = None) -> RpBridgeError | None:
        mode = self._detect_invocation_mode()
        if mode is _ToolInvocationMode.UNAVAILABLE:
            return self._invocation_detection_error or RpBridgeError(
                code="BRIDGE_TOOL_INVOCATION_UNSUPPORTED",
                message="RP bridge does not expose a supported MCP tool invocation surface",
                retriable=False,
            )
        tool_info = self._tool_info(tool)
        if tool_info is None:
            return RpBridgeError(
                code="TOOL_UNAVAILABLE",
                message=f"RP bridge tool {tool!r} is not available in this runtime",
                retriable=False,
                detail={"tool": tool},
            )
        if operation is None:
            return None
        supported_operations = self._tool_operations(tool_info)
        if supported_operations and operation not in supported_operations:
            return RpBridgeError(
                code="TOOL_UNAVAILABLE",
                message=f"RP bridge tool {tool!r} does not support operation {operation!r}",
                retriable=False,
                detail={"tool": tool, "operation": operation},
            )
        return None

    def _tool_info(self, tool: str) -> RpToolInfo | None:
        self._detect_invocation_mode()
        tools = self._detected_tools or ()
        for item in tools:
            if item.name == tool:
                return item
        return None

    def _tool_supports_operation(self, tool: str, operation: str) -> bool:
        tool_info = self._tool_info(tool)
        if tool_info is None:
            return False
        operations = self._tool_operations(tool_info)
        return operation in operations

    def _tool_operations(self, tool: RpToolInfo) -> set[str]:
        operations: set[str] = set()
        for key in ("op", "action"):
            operations.update(self._tool_property_enum_values(tool, key))
        return operations

    def _tool_property_supports_value(self, tool_name: str, property_name: str, value: str) -> bool:
        tool_info = self._tool_info(tool_name)
        if tool_info is None:
            return False
        supported = self._tool_property_enum_values(tool_info, property_name)
        return not supported or value in supported

    def _tool_property_enum_values(self, tool: RpToolInfo, property_name: str) -> set[str]:
        metadata = tool.metadata or {}
        input_schema = metadata.get("inputSchema")
        if not isinstance(input_schema, dict):
            return set()
        properties = input_schema.get("properties")
        if not isinstance(properties, dict):
            return set()
        raw_property = properties.get(property_name)
        if not isinstance(raw_property, dict):
            return set()
        raw_enum = raw_property.get("enum")
        if not isinstance(raw_enum, list):
            return set()
        values: set[str] = set()
        for item in raw_enum:
            if isinstance(item, str) and item.strip():
                values.add(item.strip())
        return values

    def _detect_invocation_mode(self) -> _ToolInvocationMode:
        if self._invocation_mode is not None:
            return self._invocation_mode

        help_invocation = self._execute_command((*self.command, "--help"))
        if not help_invocation.ok:
            self._invocation_mode = _ToolInvocationMode.UNAVAILABLE
            self._invocation_detection_error = help_invocation.error
            return self._invocation_mode

        help_text = "\n".join(
            part for part in ((help_invocation.stdout or ""), (help_invocation.stderr or "")) if part
        ).lower()
        has_markers = "-c" in help_text and "-j" in help_text and "--tools-schema" in help_text
        if not has_markers:
            self._invocation_mode = _ToolInvocationMode.UNAVAILABLE
            self._invocation_detection_error = RpBridgeError(
                code="BRIDGE_TOOL_INVOCATION_UNSUPPORTED",
                message="RP bridge does not advertise MCP tool invocation flags (-c/-j/--tools-schema)",
                retriable=False,
            )
            return self._invocation_mode

        tools_invocation = self._execute_command((*self.command, "--tools-schema", "--raw-json"))
        self._tool_schema_command = tools_invocation.command
        if not tools_invocation.ok:
            self._invocation_mode = _ToolInvocationMode.UNAVAILABLE
            tools_error = tools_invocation.error
            if tools_error is None:
                self._invocation_detection_error = RpBridgeError(
                    code="BRIDGE_TOOL_INVOCATION_UNSUPPORTED",
                    message="RP bridge tools schema probe failed",
                    retriable=False,
                )
            elif tools_error.code in {"TIMEOUT", "NOT_INSTALLED", "COMMAND_UNAVAILABLE"}:
                self._invocation_detection_error = tools_error
            else:
                self._invocation_detection_error = RpBridgeError(
                    code="BRIDGE_TOOL_INVOCATION_UNSUPPORTED",
                    message="RP bridge tools schema probe failed",
                    retriable=False,
                    detail={"probe_error": tools_error.code},
                )
            return self._invocation_mode

        tools_payload = self._load_json_payload(tools_invocation, context="tools schema")
        if not isinstance(tools_payload, (dict, list)):
            self._invocation_mode = _ToolInvocationMode.UNAVAILABLE
            self._invocation_detection_error = RpBridgeError(
                code="BRIDGE_TOOL_INVOCATION_UNSUPPORTED",
                message="RP bridge tools schema probe did not return valid JSON",
                retriable=False,
                detail={"stdout": (tools_invocation.stdout or "").strip()[:400]},
            )
            return self._invocation_mode

        try:
            self._detected_tools = self._parse_tools_schema_payload(tools_payload)
        except ValueError as exc:
            self._invocation_mode = _ToolInvocationMode.UNAVAILABLE
            self._invocation_detection_error = RpBridgeError(
                code="BRIDGE_TOOL_INVOCATION_UNSUPPORTED",
                message=f"RP bridge tools schema probe could not parse tool inventory: {exc}",
                retriable=False,
            )
            return self._invocation_mode

        self._invocation_mode = _ToolInvocationMode.COMMAND_MODE_RAW_JSON
        self._invocation_detection_error = None
        return self._invocation_mode

    def _invoke_tool(
        self,
        tool: str,
        arguments: Mapping[str, Any] | None,
        *,
        context: str,
    ) -> _RpInvocation:
        mode = self._detect_invocation_mode()
        if mode is _ToolInvocationMode.UNAVAILABLE:
            return _RpInvocation(
                command=self.command,
                path=self.command[0],
                ok=False,
                error=self._invocation_detection_error
                or RpBridgeError(
                    code="BRIDGE_TOOL_INVOCATION_UNSUPPORTED",
                    message="RP bridge does not expose a supported MCP tool invocation surface",
                    retriable=False,
                ),
            )
        return self._invoke_tool_with_mode(mode, tool, arguments, context=context)

    def _invoke_tool_with_mode(
        self,
        mode: _ToolInvocationMode,
        tool: str,
        arguments: Mapping[str, Any] | None,
        *,
        context: str,
    ) -> _RpInvocation:
        del context
        if mode is not _ToolInvocationMode.COMMAND_MODE_RAW_JSON:
            return _RpInvocation(
                command=self.command,
                path=self.command[0],
                ok=False,
                error=RpBridgeError(
                    code="BRIDGE_TOOL_INVOCATION_UNSUPPORTED",
                    message="RP bridge does not expose a supported MCP tool invocation surface",
                    retriable=False,
                ),
            )

        command = [*self.command, "-c", tool, "-j", json.dumps(dict(arguments or {}), ensure_ascii=False), "--raw-json"]
        invocation = self._execute_command(tuple(command), tool=tool)
        return invocation

    def _execute_command(
        self,
        command: tuple[str, ...],
        *,
        stdin_payload: str | None = None,
        tool: str | None = None,
    ) -> _RpInvocation:
        try:
            completed = subprocess.run(
                list(command),
                capture_output=True,
                text=True,
                input=stdin_payload,
                check=False,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError:
            return _RpInvocation(
                command=command,
                path=self.command[0],
                ok=False,
                error=RpBridgeError(
                    code="NOT_INSTALLED",
                    message=f"RP bridge command {self.command[0]!r} was not found",
                    retriable=False,
                ),
            )
        except subprocess.TimeoutExpired:
            return _RpInvocation(
                command=command,
                path=self.command[0],
                ok=False,
                error=RpBridgeError(
                    code="TIMEOUT",
                    message=f"RP bridge command {self.command[0]!r} exceeded the bridge timeout",
                    retriable=True,
                    detail={"timeout_seconds": self.timeout_seconds},
                ),
            )
        except OSError as exc:
            return _RpInvocation(
                command=command,
                path=self.command[0],
                ok=False,
                error=RpBridgeError(
                    code="COMMAND_UNAVAILABLE",
                    message=f"RP bridge command {self.command[0]!r} could not be executed: {exc}",
                    retriable=False,
                ),
            )

        if completed.returncode != 0:
            stderr_text = (completed.stderr or "").lower()
            if tool is not None and any(
                marker in stderr_text
                for marker in (
                    "unknown tool",
                    "tool not found",
                    "no such tool",
                    "unsupported tool",
                    "unknown command",
                    "unknown mcp tool",
                )
            ):
                return _RpInvocation(
                    command=command,
                    path=self.command[0],
                    ok=False,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                    error=RpBridgeError(
                        code="TOOL_UNAVAILABLE",
                        message=f"RP bridge tool {tool!r} is not available in this runtime",
                        retriable=False,
                        detail={"returncode": completed.returncode, "tool": tool},
                    ),
                )
            return _RpInvocation(
                command=command,
                path=self.command[0],
                ok=False,
                stdout=completed.stdout,
                stderr=completed.stderr,
                error=RpBridgeError(
                    code="COMMAND_FAILED",
                    message=f"RP bridge command exited with status {completed.returncode}",
                    retriable=False,
                    detail={"returncode": completed.returncode},
                ),
            )

        return _RpInvocation(
            command=command,
            path=self.command[0],
            ok=True,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def _load_json_payload(
        self,
        invocation: _RpInvocation,
        *,
        context: str,
    ) -> dict[str, Any] | list[Any] | None:
        del context
        stdout = (invocation.stdout or "").strip()
        if not stdout:
            return None
        payload = self._extract_embedded_json(stdout)
        if not isinstance(payload, (dict, list)):
            return None
        return payload

    def _extract_embedded_json(self, raw_text: str) -> dict[str, Any] | list[Any] | None:
        stripped = raw_text.strip()
        if not stripped:
            return None
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, (dict, list)):
            return parsed

        decoder = json.JSONDecoder()
        for index, char in enumerate(stripped):
            if char not in "[{":
                continue
            fragment = stripped[index:]
            try:
                parsed_value, _ = decoder.raw_decode(fragment)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed_value, (dict, list)):
                return parsed_value
        return None

    def _parse_tools_schema_payload(self, payload: dict[str, Any] | list[Any]) -> tuple[RpToolInfo, ...]:
        if isinstance(payload, list):
            return self._parse_tools_payload(payload)

        if not isinstance(payload, dict):
            raise ValueError("tools schema payload is not a JSON object")

        raw_tools = payload.get("tools")
        if isinstance(raw_tools, list):
            return self._parse_tools_payload(raw_tools)
        if isinstance(raw_tools, dict):
            return self._parse_tool_mapping(raw_tools)

        raw_tool_schemas = payload.get("tool_schemas")
        if isinstance(raw_tool_schemas, list):
            return self._parse_tools_payload(raw_tool_schemas)
        if isinstance(raw_tool_schemas, dict):
            return self._parse_tool_mapping(raw_tool_schemas)

        if payload and all(isinstance(name, str) and isinstance(schema, dict) for name, schema in payload.items()):
            return self._parse_tool_mapping(payload)

        raise ValueError("tools schema did not include a parseable tools inventory")

    def _parse_tool_mapping(self, mapping: Mapping[str, Any]) -> tuple[RpToolInfo, ...]:
        tools: list[RpToolInfo] = []
        for name, raw_schema in mapping.items():
            normalized_name = name.strip() if isinstance(name, str) else ""
            if not normalized_name:
                continue
            metadata: dict[str, Any] = {}
            description: str | None = None
            if isinstance(raw_schema, dict):
                raw_description = raw_schema.get("description")
                if isinstance(raw_description, str) and raw_description.strip():
                    description = raw_description.strip()
                metadata = dict(raw_schema)
            elif raw_schema is not None:
                metadata = {"schema": raw_schema}
            tools.append(RpToolInfo(name=normalized_name, description=description, metadata=metadata))
        if not tools:
            raise ValueError("tools schema mapping did not include any named tools")
        return tuple(tools)

    def _parse_tools_payload(self, payload: dict[str, Any] | list[Any]) -> tuple[RpToolInfo, ...]:
        raw_tools: Any
        if isinstance(payload, dict):
            raw_tools = payload.get("tools")
        else:
            raw_tools = payload
        if not isinstance(raw_tools, list):
            raise ValueError("tool list probe did not include a tools array")

        tools: list[RpToolInfo] = []
        for item in raw_tools:
            if isinstance(item, str) and item.strip():
                tools.append(RpToolInfo(name=item.strip()))
                continue
            if not isinstance(item, dict):
                raise ValueError("tool list entries must be strings or objects")
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("tool list entry is missing a non-empty name")
            description = item.get("description")
            metadata = {key: value for key, value in item.items() if key not in {"name", "description"}}
            tools.append(
                RpToolInfo(
                    name=name.strip(),
                    description=description.strip() if isinstance(description, str) and description.strip() else None,
                    metadata=metadata,
                )
            )
        return tuple(tools)

    def _extract_workspaces(self, payload: dict[str, Any] | list[Any] | None) -> tuple[RpWorkspaceInfo, ...]:
        if payload is None:
            return ()
        raw_items: list[Any]
        if isinstance(payload, list):
            raw_items = payload
        elif isinstance(payload, dict):
            for key in ("workspaces", "items", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    raw_items = value
                    break
            else:
                raw_items = [payload] if any(key in payload for key in ("workspace", "id", "name", "repo_paths", "repoPaths")) else []
        else:
            raw_items = []
        items: list[RpWorkspaceInfo] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            workspace_mapping = raw_item.get("workspace") if isinstance(raw_item.get("workspace"), dict) else raw_item
            if not isinstance(workspace_mapping, dict):
                continue
            repo_paths = self._extract_string_list(workspace_mapping, keys=("repo_paths", "repoPaths", "paths", "folders"))
            window_ids = self._extract_int_list(workspace_mapping, keys=("window_ids", "windowIds", "showing_window_ids"))
            items.append(
                RpWorkspaceInfo(
                    workspace_id=self._optional_string(workspace_mapping.get("id"))
                    or self._optional_string(workspace_mapping.get("workspace_id")),
                    name=self._optional_string(workspace_mapping.get("name"))
                    or self._optional_string(workspace_mapping.get("workspace")),
                    repo_paths=repo_paths,
                    window_ids=window_ids,
                    is_hidden=self._optional_bool(workspace_mapping.get("is_hidden"))
                    if self._optional_bool(workspace_mapping.get("is_hidden")) is not None
                    else self._optional_bool(workspace_mapping.get("hidden")),
                    raw_payload=dict(raw_item),
                )
            )
        return tuple(items)

    def _extract_windows(self, payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        for key in ("windows", "items", "results"):
            raw_windows = payload.get(key)
            if isinstance(raw_windows, list):
                return tuple(item for item in raw_windows if isinstance(item, dict))
        current_window = payload.get("window")
        if isinstance(current_window, dict):
            return (current_window,)
        return ()

    def _extract_agent_sessions(self, payload: dict[str, Any] | list[Any] | None) -> tuple[RpAgentSessionInfo, ...]:
        if payload is None:
            return ()
        raw_items: list[Any]
        if isinstance(payload, list):
            raw_items = payload
        elif isinstance(payload, dict):
            for key in ("sessions", "items", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    raw_items = value
                    break
            else:
                raw_items = [payload] if any(key in payload for key in ("session_id", "status", "session_name")) else []
        else:
            raw_items = []
        sessions: list[RpAgentSessionInfo] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            sessions.append(
                RpAgentSessionInfo(
                    session_id=self._optional_string(raw_item.get("session_id")) or self._optional_string(raw_item.get("id")),
                    session_name=self._optional_string(raw_item.get("session_name"))
                    or self._optional_string(raw_item.get("name")),
                    status=self._optional_string(raw_item.get("status")) or self._optional_string(raw_item.get("state")),
                    model_id=self._optional_string(raw_item.get("model_id")),
                    raw_payload=dict(raw_item),
                )
            )
        return tuple(sessions)

    def _extract_selected_paths(self, payload: dict[str, Any]) -> tuple[str, ...]:
        raw_paths = payload.get("selected_paths")
        if raw_paths is None:
            raw_paths = payload.get("selection")
        if raw_paths is None:
            raw_paths = payload.get("paths")
        if not isinstance(raw_paths, list):
            return ()
        return tuple(path.strip() for path in raw_paths if isinstance(path, str) and path.strip())

    def _extract_file_search_matches(self, payload: dict[str, Any] | list[Any] | None) -> tuple[RpFileSearchMatch, ...]:
        if payload is None:
            return ()
        raw_matches: list[Any]
        if isinstance(payload, list):
            raw_matches = payload
        elif isinstance(payload, dict):
            candidate = payload.get("matches")
            raw_matches = candidate if isinstance(candidate, list) else []
        else:
            raw_matches = []

        matches: list[RpFileSearchMatch] = []
        for raw_match in raw_matches:
            if isinstance(raw_match, str) and raw_match.strip():
                matches.append(RpFileSearchMatch(path=raw_match.strip()))
                continue
            if not isinstance(raw_match, dict):
                continue
            path = self._optional_string(raw_match.get("path")) or self._optional_string(raw_match.get("file"))
            if path is None:
                continue
            line = self._optional_int(raw_match.get("line")) or self._optional_int(raw_match.get("line_number"))
            snippet = (
                self._optional_string(raw_match.get("snippet"))
                or self._optional_string(raw_match.get("line_text"))
                or self._optional_string(raw_match.get("text"))
            )
            matches.append(RpFileSearchMatch(path=path, line=line, snippet=snippet, raw_payload=dict(raw_match)))
        return tuple(matches)

    def _extract_changed_paths(
        self,
        payload: dict[str, Any] | list[Any] | None,
        *,
        fallback: str,
    ) -> tuple[str, ...]:
        if isinstance(payload, dict):
            for key in ("changed_paths", "paths", "files", "applied_paths"):
                raw = payload.get(key)
                if isinstance(raw, list):
                    values = tuple(item.strip() for item in raw if isinstance(item, str) and item.strip())
                    if values:
                        return values
            for key in ("path", "new_path"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return (value.strip(),)
        if isinstance(payload, list):
            values = tuple(item.strip() for item in payload if isinstance(item, str) and item.strip())
            if values:
                return values
        return (fallback,)

    def _extract_response_summary(self, payload: dict[str, Any] | list[Any] | None) -> str | None:
        if isinstance(payload, dict):
            for key in ("summary", "message", "status", "result"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            output_text = self._extract_output_text(payload)
            if output_text is not None:
                return output_text
        return None

    def _extract_string_list(self, payload: dict[str, Any], *, keys: Sequence[str]) -> tuple[str, ...]:
        for key in keys:
            raw = payload.get(key)
            if not isinstance(raw, list):
                continue
            values = [value.strip() for value in raw if isinstance(value, str) and value.strip()]
            if values:
                return tuple(values)
        return ()

    def _extract_int_list(self, payload: dict[str, Any], *, keys: Sequence[str]) -> tuple[int, ...]:
        for key in keys:
            raw = payload.get(key)
            if not isinstance(raw, list):
                continue
            values = [value for value in raw if isinstance(value, int)]
            if values:
                return tuple(values)
        return ()

    def _extract_output_text(self, payload: dict[str, Any]) -> str | None:
        for key in ("output", "content", "response"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    def _resolve_nested_value(self, payload: Mapping[str, Any], path: Sequence[str]) -> object | None:
        current: object = payload
        for key in path:
            if not isinstance(current, Mapping):
                return None
            current = current.get(key)
        return current

    def _malformed_response_error(
        self,
        invocation: _RpInvocation,
        *,
        context: str,
        message: str | None = None,
    ) -> RpBridgeError:
        return RpBridgeError(
            code="MALFORMED_RESPONSE",
            message=message or f"RP bridge {context} did not return valid JSON",
            retriable=False,
            detail={"stdout": (invocation.stdout or "").strip()[:400]},
        )

    def _optional_string(self, value: object) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None

    def _optional_int(self, value: object) -> int | None:
        return value if isinstance(value, int) else None

    def _optional_bool(self, value: object) -> bool | None:
        return value if isinstance(value, bool) else None


__all__ = [
    "RpAgentLogResult",
    "RpAgentHandoffResult",
    "RpAgentRunCancelResult",
    "RpAgentSessionListResult",
    "RpAgentSessionResumeResult",
    "RpAgentRunStartResult",
    "RpAgentRunWaitResult",
    "RpAgentTranscriptResult",
    "RpAskOracleResult",
    "RpApplyEditsResult",
    "RpBindContextResult",
    "RpBridgeError",
    "RpBridgeProbeResult",
    "RpCliBridgeClient",
    "RpContextBuilderResult",
    "RpFileSearchMatch",
    "RpFileSearchResult",
    "RpFileActionResult",
    "RpManageSelectionResult",
    "RpReadFileResult",
    "RpToolInfo",
    "RpToolListResult",
    "RpWorkspaceInfo",
    "RpWorkspaceListResult",
    "RpWorkspaceResolveResult",
    "RpWorkspaceContextResult",
]
