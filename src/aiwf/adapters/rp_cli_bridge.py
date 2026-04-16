"""Read-only bridge probing for RepoPrompt CLI surfaces."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True)
class RpBridgeError:
    """Structured bridge probe failure."""

    code: str
    message: str
    retriable: bool
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RpToolInfo:
    """A single read-only-discovered RepoPrompt tool."""

    name: str
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RpToolListResult:
    """Typed result of a read-only `--list-tools` probe."""

    ok: bool
    command: tuple[str, ...]
    path: str
    tools: tuple[RpToolInfo, ...] = ()
    error: RpBridgeError | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None


@dataclass(frozen=True)
class RpWorkspaceContextResult:
    """Typed result of a read-only workspace-context probe."""

    ok: bool
    command: tuple[str, ...]
    path: str
    workspace: str | None = None
    context_id: str | None = None
    selected_paths: tuple[str, ...] = ()
    error: RpBridgeError | None = None
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


@dataclass(frozen=True)
class _RpReadOnlyInvocation:
    command: tuple[str, ...]
    path: str
    ok: bool
    stdout: str | None = None
    stderr: str | None = None
    error: RpBridgeError | None = None


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
    """Safe read-only client for probing RepoPrompt CLI surfaces."""

    def __init__(self, command: Sequence[str], *, timeout_seconds: int = 5) -> None:
        resolved_command = tuple(str(part).strip() for part in command if str(part).strip())
        if not resolved_command:
            raise ValueError("RpCliBridgeClient requires a non-empty command")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")
        self.command = resolved_command
        self.timeout_seconds = timeout_seconds

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
        invocation = self._run_read_only("--list-tools")
        if not invocation.ok:
            return RpToolListResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        payload = self._load_json_payload(invocation, context="tool list")
        if payload is None:
            return RpToolListResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                error=self._malformed_response_error(invocation, context="tool list"),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        try:
            tools = self._parse_tools_payload(payload)
        except ValueError as exc:
            return RpToolListResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                error=self._malformed_response_error(invocation, context="tool list", message=str(exc)),
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        return RpToolListResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            tools=tools,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def workspace_context(self, workspace: str | None = None) -> RpWorkspaceContextResult:
        args = ["--workspace-context"]
        if workspace is not None:
            args.append(workspace)
        invocation = self._run_read_only(*args)
        if not invocation.ok:
            return RpWorkspaceContextResult(
                ok=False,
                command=invocation.command,
                path=invocation.path,
                error=invocation.error,
                raw_stdout=invocation.stdout,
                raw_stderr=invocation.stderr,
            )
        payload = self._load_json_payload(invocation, context="workspace context")
        if not isinstance(payload, dict):
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
        selected_paths = self._extract_selected_paths(payload)
        return RpWorkspaceContextResult(
            ok=True,
            command=invocation.command,
            path=invocation.path,
            workspace=self._optional_string(payload.get("workspace")),
            context_id=self._optional_string(payload.get("context_id")),
            selected_paths=selected_paths,
            raw_stdout=invocation.stdout,
            raw_stderr=invocation.stderr,
        )

    def _run_read_only(self, *arguments: str) -> _RpReadOnlyInvocation:
        command = (*self.command, *arguments)
        try:
            completed = subprocess.run(
                list(command),
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError:
            return _RpReadOnlyInvocation(
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
            return _RpReadOnlyInvocation(
                command=command,
                path=self.command[0],
                ok=False,
                error=RpBridgeError(
                    code="TIMEOUT",
                    message=f"RP bridge command {self.command[0]!r} exceeded the read-only probe timeout",
                    retriable=True,
                    detail={"timeout_seconds": self.timeout_seconds},
                ),
            )
        except OSError as exc:
            return _RpReadOnlyInvocation(
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
            return _RpReadOnlyInvocation(
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

        return _RpReadOnlyInvocation(
            command=command,
            path=self.command[0],
            ok=True,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def _load_json_payload(
        self,
        invocation: _RpReadOnlyInvocation,
        *,
        context: str,
    ) -> dict[str, Any] | list[Any] | None:
        stdout = (invocation.stdout or "").strip()
        if not stdout:
            return None
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, (dict, list)):
            return None
        return payload

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

    def _extract_selected_paths(self, payload: dict[str, Any]) -> tuple[str, ...]:
        raw_paths = payload.get("selected_paths")
        if raw_paths is None:
            raw_paths = payload.get("selection")
        if raw_paths is None:
            raw_paths = payload.get("paths")
        if not isinstance(raw_paths, list):
            return ()
        selected_paths = [
            path.strip()
            for path in raw_paths
            if isinstance(path, str) and path.strip()
        ]
        return tuple(selected_paths)

    def _malformed_response_error(
        self,
        invocation: _RpReadOnlyInvocation,
        *,
        context: str,
        message: str | None = None,
    ) -> RpBridgeError:
        return RpBridgeError(
            code="MALFORMED_RESPONSE",
            message=message or f"RP bridge {context} probe did not return valid JSON",
            retriable=False,
            detail={"stdout": (invocation.stdout or "").strip()[:400]},
        )

    def _optional_string(self, value: object) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = [
    "RpBridgeError",
    "RpBridgeProbeResult",
    "RpCliBridgeClient",
    "RpToolInfo",
    "RpToolListResult",
    "RpWorkspaceContextResult",
]
