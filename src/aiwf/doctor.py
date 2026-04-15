"""Repository/operator diagnostics for aiwf workspaces."""

from __future__ import annotations

import shlex
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from aiwf.adapters import ADAPTER_SPECS
from aiwf.adapters.base import HostContract
from aiwf.loader import load_gate_set, load_policy, load_runbook


DoctorStatus = Literal["ok", "warn", "fail"]

_SHELL_OPERATORS = ("&&", "||", "|", ";", ">", "<", "$(", "`")


@dataclass(frozen=True)
class DoctorCheck:
    """A single doctor diagnostic entry."""

    status: DoctorStatus
    category: str
    name: str
    detail: str
    path: str | None = None


@dataclass(frozen=True)
class DoctorReport:
    """Collected doctor diagnostics and summary counts."""

    repo_root: str
    ai_root: str
    checks: list[DoctorCheck]

    @property
    def summary(self) -> dict[str, int]:
        counts = {"ok": 0, "warn": 0, "fail": 0}
        for check in self.checks:
            counts[check.status] += 1
        return counts

    @property
    def ok(self) -> bool:
        return self.summary["fail"] == 0

    def to_json(self) -> dict[str, Any]:
        return {
            "repo_root": self.repo_root,
            "ai_root": self.ai_root,
            "ok": self.ok,
            "summary": self.summary,
            "checks": [asdict(check) for check in self.checks],
        }


def run_doctor(ai_root: str | Path = ".ai", repo_root: str | Path = ".") -> DoctorReport:
    """Build a repository/operator diagnostics report."""
    ai_root_path = Path(ai_root)
    repo_root_path = Path(repo_root)

    checks: list[DoctorCheck] = []
    checks.extend(_check_workspace_structure(ai_root_path))
    checks.extend(_check_ai_sources(ai_root_path))
    checks.extend(_check_gate_commands(ai_root_path))
    checks.extend(_check_host_tools())
    return DoctorReport(
        repo_root=str(repo_root_path),
        ai_root=str(ai_root_path),
        checks=checks,
    )


def render_doctor_report(report: DoctorReport) -> str:
    """Render a human-readable doctor report."""
    lines = [
        f"ai_root={report.ai_root} repo_root={report.repo_root}",
        f"summary ok={report.summary['ok']} warn={report.summary['warn']} fail={report.summary['fail']}",
    ]
    for check in report.checks:
        path_suffix = f" path={check.path}" if check.path else ""
        lines.append(
            f"{check.status.upper()} [{check.category}] {check.name}: {check.detail}{path_suffix}"
        )
    return "\n".join(lines)


def _check_workspace_structure(ai_root: Path) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    if not ai_root.exists():
        return [
            DoctorCheck(
                status="fail",
                category="workspace",
                name="ai_root",
                detail="`.ai` root does not exist",
                path=str(ai_root),
            )
        ]
    if not ai_root.is_dir():
        return [
            DoctorCheck(
                status="fail",
                category="workspace",
                name="ai_root",
                detail="`.ai` root is not a directory",
                path=str(ai_root),
            )
        ]

    required_dirs = {
        "tasks": ai_root / "tasks",
        "runbooks": ai_root / "runbooks",
        "policies": ai_root / "policies",
        "gates": ai_root / "gates",
    }
    for name, path in required_dirs.items():
        if path.exists() and path.is_dir():
            status: DoctorStatus = "ok"
            detail = "present"
        elif path.exists():
            status = "fail"
            detail = "expected directory but found a non-directory path"
        else:
            status = "fail"
            detail = "missing required directory"
        checks.append(DoctorCheck(status=status, category="workspace", name=name, detail=detail, path=str(path)))
    return checks


def _check_ai_sources(ai_root: Path) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []

    runbook_dir = ai_root / "runbooks"
    runbook_files = sorted(runbook_dir.glob("*.md")) if runbook_dir.exists() else []
    if not runbook_files:
        checks.append(
            DoctorCheck(
                status="warn",
                category="sources",
                name="runbooks",
                detail="no runbook files found",
                path=str(runbook_dir),
            )
        )
    for path in runbook_files:
        try:
            runbook = load_runbook(path)
            checks.append(
                DoctorCheck(
                    status="ok",
                    category="sources",
                    name=f"runbook:{runbook.name}",
                    detail="loaded successfully",
                    path=str(path),
                )
            )
        except Exception as exc:
            checks.append(
                DoctorCheck(
                    status="fail",
                    category="sources",
                    name=f"runbook:{path.stem}",
                    detail=str(exc),
                    path=str(path),
                )
            )

    policy_dir = ai_root / "policies"
    policy_files = sorted(policy_dir.glob("*.md")) if policy_dir.exists() else []
    if not policy_files:
        checks.append(
            DoctorCheck(
                status="warn",
                category="sources",
                name="policies",
                detail="no policy files found",
                path=str(policy_dir),
            )
        )
    for path in policy_files:
        try:
            load_policy(path)
            checks.append(
                DoctorCheck(
                    status="ok",
                    category="sources",
                    name=f"policy:{path.stem}",
                    detail="loaded successfully",
                    path=str(path),
                )
            )
        except Exception as exc:
            checks.append(
                DoctorCheck(
                    status="fail",
                    category="sources",
                    name=f"policy:{path.stem}",
                    detail=str(exc),
                    path=str(path),
                )
            )

    return checks


def _check_gate_commands(ai_root: Path) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    gate_dir = ai_root / "gates"
    gate_files = sorted(gate_dir.glob("*.yaml")) if gate_dir.exists() else []
    if not gate_files:
        return [
            DoctorCheck(
                status="warn",
                category="gates",
                name="gate_sets",
                detail="no gate files found",
                path=str(gate_dir),
            )
        ]

    for path in gate_files:
        try:
            gate_set = load_gate_set(path)
        except Exception as exc:
            checks.append(
                DoctorCheck(
                    status="fail",
                    category="gates",
                    name=f"gate_set:{path.stem}",
                    detail=str(exc),
                    path=str(path),
                )
            )
            continue

        checks.append(
            DoctorCheck(
                status="ok",
                category="gates",
                name=f"gate_set:{gate_set.name}",
                detail=f"loaded {len(gate_set.gates)} gate(s)",
                path=str(path),
            )
        )
        for gate in gate_set.gates:
            status, detail = _check_shell_command(gate.command)
            checks.append(
                DoctorCheck(
                    status=status,
                    category="gate_command",
                    name=f"{gate_set.name}:{gate.name}",
                    detail=detail,
                    path=str(path),
                )
            )
    return checks


def _check_host_tools() -> list[DoctorCheck]:
    checks = [
        DoctorCheck(
            status="ok",
            category="tool",
            name="python",
            detail=f"using interpreter {sys.executable}",
            path=sys.executable,
        )
    ]
    checks.append(_tool_check("uv", required=False, reason="recommended for local aiwf commands"))
    checks.append(_tool_check("git", required=False, reason="useful for repo-aware workflows"))
    checks.append(_tool_check("claude", required=False, reason="needed for Claude adapter workflows"))
    checks.append(_check_native_runtime("rp", ADAPTER_SPECS["rp"].resolve_contract()))
    return checks


def _check_native_runtime(adapter_name: str, contract: HostContract) -> DoctorCheck:
    native_runtime = contract.native_runtime
    if not native_runtime.enabled:
        return DoctorCheck(
            status="ok",
            category="tool",
            name=adapter_name,
            detail="manual-only contract; no native runtime scaffold declared",
        )

    for command in native_runtime.command_candidates:
        resolved = shutil.which(command)
        if resolved:
            return DoctorCheck(
                status="ok",
                category="tool",
                name=adapter_name,
                detail=(
                    f"native-ready via {command} at {resolved}; "
                    "manual handoff remains available until the native bridge is enabled"
                ),
                path=resolved,
            )

    candidates = ", ".join(native_runtime.command_candidates)
    hint = native_runtime.install_hint or f"Install one of: {candidates}."
    return DoctorCheck(
        status="warn",
        category="tool",
        name=adapter_name,
        detail=(
            "manual-only fallback active; native runtime contract is declared but no compatible "
            f"RepoPrompt runtime was found on PATH ({candidates}). {hint}"
        ),
    )


def _tool_check(command: str, *, required: bool, reason: str) -> DoctorCheck:
    resolved = shutil.which(command)
    if resolved:
        return DoctorCheck(
            status="ok",
            category="tool",
            name=command,
            detail=f"available at {resolved}",
            path=resolved,
        )
    return DoctorCheck(
        status="fail" if required else "warn",
        category="tool",
        name=command,
        detail=f"not found on PATH ({reason})",
    )


def _check_shell_command(command: str) -> tuple[DoctorStatus, str]:
    stripped = command.strip()
    if not stripped:
        return "fail", "gate command is empty"
    if any(operator in stripped for operator in _SHELL_OPERATORS):
        return "warn", "shell expression is complex; static executable resolution skipped"

    try:
        argv = shlex.split(stripped)
    except ValueError as exc:
        return "fail", f"unable to parse shell command: {exc}"
    if not argv:
        return "fail", "gate command is empty after parsing"

    command_index = 0
    while command_index < len(argv) and "=" in argv[command_index] and not argv[command_index].startswith(("/", ".", "~")):
        command_index += 1
    if command_index >= len(argv):
        return "warn", "shell environment assignment detected without a resolvable executable"

    executable = _resolve_command_executable(argv[command_index])
    if executable is None:
        return "fail", f"executable {argv[command_index]!r} not found on PATH"
    return "ok", f"resolved executable {argv[command_index]!r} -> {executable}"


def _resolve_command_executable(token: str) -> str | None:
    if "=" in token and not token.startswith(("/", ".", "~")):
        return None
    return shutil.which(token)


__all__ = [
    "DoctorCheck",
    "DoctorReport",
    "render_doctor_report",
    "run_doctor",
]
