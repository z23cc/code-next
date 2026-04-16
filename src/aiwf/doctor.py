"""Repository/operator diagnostics for aiwf workspaces."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from aiwf.adapters import ADAPTER_SPECS
from aiwf.adapters.rp_cli_bridge import RpBridgeProbeResult, RpCliBridgeClient
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
    protocol_supported: bool | None = None
    protocol_version: int | None = None
    bridge_tools_detected: list[str] | None = None
    bridge_probe_error: str | None = None
    runtime_detection: Literal["stub-like", "non-stub-like"] | None = None
    runtime_detection_reason: str | None = None


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
        detection_suffix = (
            f" runtime_detection={check.runtime_detection}"
            if check.runtime_detection is not None
            else ""
        )
        lines.append(
            f"{check.status.upper()} [{check.category}] {check.name}: {check.detail}{path_suffix}{detection_suffix}"
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
    rp_contract = ADAPTER_SPECS["rp"].resolve_contract()
    checks.append(_check_native_runtime("rp", rp_contract))
    bridge_check = _check_bridge_runtime("rp", rp_contract)
    if bridge_check is not None:
        checks.append(bridge_check)
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
            detection, detection_reason = _classify_runtime_detection(resolved)
            protocol_supported, detected_version = _probe_native_runtime_protocol(resolved)
            declared_version = native_runtime.protocol_version
            if protocol_supported:
                detection_detail = _runtime_detection_detail(
                    detection,
                    detection_reason,
                    stub_warning="treat this as reference-stub evidence, not product validation",
                    non_stub_warning=(
                        "treat this as a real-runtime candidate only; run conformance and the runtime "
                        "validation guide before calling it certified"
                    ),
                )
                if declared_version is not None and detected_version != declared_version:
                    return DoctorCheck(
                        status="warn",
                        category="tool",
                        name=adapter_name,
                        detail=(
                            f"RP runtime found via {command} at {resolved}; protocol probe reported "
                            f"aiwf-rp-native v{detected_version}, but aiwf currently advertises v{declared_version}. "
                            f"{detection_detail}. Manual handoff remains the stable supported path if negotiation "
                            "cannot agree on a version."
                        ),
                        path=resolved,
                        protocol_supported=True,
                        protocol_version=detected_version,
                        runtime_detection=detection,
                        runtime_detection_reason=detection_reason,
                    )
                return DoctorCheck(
                    status="ok",
                    category="tool",
                    name=adapter_name,
                    detail=(
                        f"experimental RP auto runtime detected via {command} at {resolved}; protocol "
                        f"aiwf-rp-native v{detected_version} detected; {detection_detail}. Manual handoff remains "
                        "the stable supported path."
                    ),
                    path=resolved,
                    protocol_supported=True,
                    protocol_version=detected_version,
                    runtime_detection=detection,
                    runtime_detection_reason=detection_reason,
                )
            return DoctorCheck(
                status="warn",
                category="tool",
                name=adapter_name,
                detail=(
                    f"RP runtime found via {command} at {resolved}, but protocol negotiation support "
                    f"was not detected; treat RP auto/native as unavailable and use the stable manual handoff path"
                    + (
                        f" (aiwf advertises protocol v{declared_version})."
                        if declared_version is not None
                        else "."
                    )
                    + f" Heuristic classification: {detection} ({detection_reason})."
                ),
                path=resolved,
                protocol_supported=False,
                runtime_detection=detection,
                runtime_detection_reason=detection_reason,
            )

    candidates = ", ".join(native_runtime.command_candidates)
    hint = native_runtime.install_hint or f"Install one of: {candidates}."
    return DoctorCheck(
        status="warn",
        category="tool",
        name=adapter_name,
        detail=(
            "stable manual handoff path active; no RepoPrompt runtime compatible with RP experimental "
            f"auto/native was found on PATH ({candidates}). "
            + (
                f"aiwf advertises protocol v{native_runtime.protocol_version}. "
                if native_runtime.protocol_version is not None
                else ""
            )
            + hint
        ),
        protocol_supported=False,
    )


def _check_bridge_runtime(adapter_name: str, contract: HostContract) -> DoctorCheck | None:
    bridge = contract.bridge
    if not bridge.enabled:
        return None

    bridge_name = f"{adapter_name}-bridge"
    for command in bridge.command_candidates:
        resolved = shutil.which(command)
        if resolved:
            detection, detection_reason = _classify_runtime_detection(resolved)
            probe_result = _probe_bridge_runtime(resolved)
            if probe_result.available:
                tools_detected = [tool.name for tool in probe_result.tools]
                tool_detail = ", ".join(tools_detected) if tools_detected else "no tools reported"
                return DoctorCheck(
                    status="ok",
                    category="tool",
                    name=bridge_name,
                    detail=(
                        f"experimental RP bridge candidate detected via {command} at {resolved}; read-only bridge probe "
                        f"detected tools: {tool_detail}. "
                        + _runtime_detection_detail(
                            detection,
                            detection_reason,
                            stub_warning=(
                                "treat this as stub-like bridge evidence, not proof of a product RepoPrompt runtime"
                            ),
                            non_stub_warning=(
                                "this is a non-stub-like bridge candidate, but aiwf still treats bridge probing as "
                                "read-only reconnaissance rather than provider certification"
                            ),
                        )
                        + ". Manual handoff remains the stable supported path."
                    ),
                    path=resolved,
                    bridge_tools_detected=tools_detected,
                    runtime_detection=detection,
                    runtime_detection_reason=detection_reason,
                )
            return DoctorCheck(
                status="warn",
                category="tool",
                name=bridge_name,
                detail=(
                    f"experimental RP bridge candidate detected via {command} at {resolved}, but the read-only bridge "
                    f"probe failed: {probe_result.error.message if probe_result.error is not None else 'unknown probe failure'}. "
                    f"Heuristic classification: {detection} ({detection_reason}). This does not imply aiwf "
                    "provider/runtime support, and manual handoff remains the stable supported path."
                ),
                path=resolved,
                bridge_probe_error=probe_result.error.message if probe_result.error is not None else "unknown probe failure",
                runtime_detection=detection,
                runtime_detection_reason=detection_reason,
            )

    candidates = ", ".join(bridge.command_candidates) or "-"
    detail = (
        f"RP bridge candidate not found on PATH ({candidates}); bridge is groundwork-only and the stable manual handoff path remains active."
    )
    if bridge.install_hint:
        detail = f"{detail} {bridge.install_hint}"
    return DoctorCheck(
        status="warn",
        category="tool",
        name=bridge_name,
        detail=detail,
    )


def _probe_bridge_runtime(command_path: str) -> RpBridgeProbeResult:
    client = RpCliBridgeClient((command_path,), timeout_seconds=5)
    return client.probe_available()


def _probe_native_runtime_protocol(command_path: str) -> tuple[bool, int | None]:
    try:
        completed = subprocess.run(
            [command_path, "--aiwf-protocol-version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, None
    if completed.returncode != 0:
        return False, None
    try:
        payload = json.loads(completed.stdout.strip())
    except json.JSONDecodeError:
        return False, None
    if not isinstance(payload, dict):
        return False, None
    version = payload.get("version")
    if payload.get("protocol") != "aiwf-rp-native":
        return False, None
    if not isinstance(version, int) or isinstance(version, bool) or version <= 0:
        return False, None
    return True, version


def _classify_runtime_detection(command_path: str) -> tuple[Literal["stub-like", "non-stub-like"], str]:
    candidate = Path(command_path).expanduser().resolve(strict=False)
    lower_path = str(candidate).lower()
    repo_root = Path(__file__).resolve().parents[2]
    if "rp-cli-stub" in lower_path or "rp_cli_stub" in lower_path:
        return "stub-like", "path matches the repo-local rp-cli-stub/reference harness"
    if "fake_rp_" in candidate.name.lower() or "fake-rp-" in candidate.name.lower():
        return "stub-like", "file name matches the aiwf fake RP runtime/bridge harness naming"
    if _is_relative_to(candidate, repo_root / "tools" / "rp-cli-stub"):
        return "stub-like", "path is inside tools/rp-cli-stub"
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env and _is_relative_to(candidate, Path(virtual_env)):
        return "stub-like", f"path is inside the current virtual environment ({virtual_env})"
    if candidate.name in {"rp", "rp-cli"} and _is_relative_to(candidate, Path(sys.prefix)):
        return "stub-like", f"path is inside the current Python environment ({sys.prefix})"
    return "non-stub-like", "path is outside aiwf test-harness and current Python-environment heuristics"


def _runtime_detection_detail(
    detection: Literal["stub-like", "non-stub-like"],
    reason: str,
    *,
    stub_warning: str,
    non_stub_warning: str,
) -> str:
    if detection == "stub-like":
        return f"heuristic classifies this binary as stub-like ({reason}); {stub_warning}"
    return f"heuristic classifies this binary as non-stub-like ({reason}); {non_stub_warning}"


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


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(other.resolve(strict=False))
    except ValueError:
        return False
    return True


__all__ = [
    "DoctorCheck",
    "DoctorReport",
    "render_doctor_report",
    "run_doctor",
]
