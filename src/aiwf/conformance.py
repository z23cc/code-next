"""Executable provider conformance checks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

_RP_PROTOCOL_NAME = "aiwf-rp-native"
_RP_PROTOCOL_VERSION = 1
_RP_PROTOCOL_PROBE_ARGUMENT = "--aiwf-protocol-version"
RpConformanceScope = Literal["reference-stub", "real-runtime-untrusted", "real-runtime-certified"]


def run_rp_conformance(
    command: Sequence[str],
    *,
    repo_root: str | Path = ".",
    certify_real_runtime: bool = False,
) -> dict[str, Any]:
    """Run RP native protocol conformance checks against an external command."""
    resolved_root = Path(repo_root)
    command_list = [str(part) for part in command]
    checks: list[dict[str, Any]] = []

    probe_result = _run_command([*command_list, _RP_PROTOCOL_PROBE_ARGUMENT], cwd=resolved_root)
    probe_payload = _load_payload(probe_result.get("stdout", ""))
    checks.append(_validate_probe(probe_result, probe_payload))
    if not checks[-1]["ok"]:
        return _build_report(
            command_list,
            resolved_root,
            checks,
            certify_real_runtime=certify_real_runtime,
        )

    for name, request_type, stage in (
        ("plan", "plan", "plan"),
        ("execute", "execute", "implement"),
        ("review", "review", "review"),
    ):
        request = _build_request(request_type=request_type, stage=stage, prompt=f"Conformance {name} prompt")
        result = _run_command(command_list, cwd=resolved_root, runtime_input=json.dumps(request, ensure_ascii=False))
        payload = _load_payload(result.get("stdout", ""))
        checks.append(_validate_ok_response(name, result, payload))

    invalid_request = {
        "protocol": _RP_PROTOCOL_NAME,
        "version": _RP_PROTOCOL_VERSION,
        "request_type": "plan",
        "stage": "plan",
        "context": {"adapter": "rp", "mode": "auto"},
        "options": {"timeout_seconds": 30},
        "metadata": {},
    }
    invalid_result = _run_command(
        command_list,
        cwd=resolved_root,
        runtime_input=json.dumps(invalid_request, ensure_ascii=False),
    )
    invalid_payload = _load_payload(invalid_result.get("stdout", ""))
    checks.append(
        _validate_error_response(
            "invalid-request",
            invalid_result,
            invalid_payload,
            expected_code="INVALID_REQUEST",
            detail_key=None,
        )
    )

    unsupported_request = _build_request(request_type="plan", stage="plan", prompt="Unsupported version")
    unsupported_request["version"] = 9999
    unsupported_result = _run_command(
        command_list,
        cwd=resolved_root,
        runtime_input=json.dumps(unsupported_request, ensure_ascii=False),
    )
    unsupported_payload = _load_payload(unsupported_result.get("stdout", ""))
    checks.append(
        _validate_error_response(
            "unsupported-version",
            unsupported_result,
            unsupported_payload,
            expected_code="UNSUPPORTED_VERSION",
            detail_key="supported_version",
        )
    )

    legacy_result = _run_command(command_list, cwd=resolved_root, runtime_input="Legacy raw conformance input")
    checks.append(_validate_legacy_response(legacy_result))
    return _build_report(
        command_list,
        resolved_root,
        checks,
        certify_real_runtime=certify_real_runtime,
    )


def render_rp_conformance_report(report: Mapping[str, Any]) -> str:
    """Render a concise human-readable conformance report."""
    lines = [
        f"provider_command={' '.join(str(part) for part in report.get('provider_command', []))}",
        f"repo_root={report.get('repo_root')}",
    ]
    scope = str(report.get("scope", "")).strip()
    scope_reason = str(report.get("scope_reason", "")).strip()
    if scope:
        lines.append(f"scope={scope}" + (f" scope_reason={scope_reason}" if scope_reason else ""))
    for check in report.get("checks", []):
        if not isinstance(check, Mapping):
            continue
        status = "PASS" if check.get("ok") else "FAIL"
        detail = str(check.get("detail", "")).strip()
        lines.append(f"{status} {check.get('name')}: {detail}" if detail else f"{status} {check.get('name')}")
    return "\n".join(lines)


def _build_request(*, request_type: str, stage: str, prompt: str) -> dict[str, Any]:
    return {
        "protocol": _RP_PROTOCOL_NAME,
        "version": _RP_PROTOCOL_VERSION,
        "request_type": request_type,
        "stage": stage,
        "prompt": prompt,
        "context": {
            "adapter": "rp",
            "mode": "auto",
            "task_slug": "rp-conformance",
            "run_id": "conformance-run",
        },
        "options": {"timeout_seconds": 30},
        "metadata": {},
    }


def _run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    runtime_input: str | None = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            input=runtime_input,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "detail": str(exc),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": getattr(exc, "stdout", "") or "",
            "stderr": getattr(exc, "stderr", "") or "",
            "detail": str(exc),
        }
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "detail": "",
    }


def _load_payload(raw_output: str) -> dict[str, Any] | None:
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


def _validate_probe(result: Mapping[str, Any], payload: dict[str, Any] | None) -> dict[str, Any]:
    if not result.get("ok"):
        return _failed_check("probe", f"command failed: {_result_summary(result)}")
    if payload is None:
        return _failed_check("probe", "probe did not return a valid aiwf-rp-native payload")
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, list):
        return _failed_check("probe", "probe payload is missing list capabilities")
    return {"name": "probe", "ok": True, "detail": f"version={payload['version']} capabilities={len(capabilities)}"}


def _validate_ok_response(name: str, result: Mapping[str, Any], payload: dict[str, Any] | None) -> dict[str, Any]:
    if not result.get("ok"):
        return _failed_check(name, f"command failed: {_result_summary(result)}")
    if payload is None:
        return _failed_check(name, "response did not return a valid aiwf-rp-native payload")
    if payload.get("status") != "ok":
        return _failed_check(name, f"expected status=ok, got {payload.get('status')!r}")
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return _failed_check(name, "response content must be a non-empty string")
    return {"name": name, "ok": True, "detail": f"content_length={len(content)}"}


def _validate_error_response(
    name: str,
    result: Mapping[str, Any],
    payload: dict[str, Any] | None,
    *,
    expected_code: str,
    detail_key: str | None,
) -> dict[str, Any]:
    if not result.get("ok"):
        return _failed_check(name, f"command failed: {_result_summary(result)}")
    if payload is None:
        return _failed_check(name, "response did not return a valid aiwf-rp-native payload")
    if payload.get("status") != "error":
        return _failed_check(name, f"expected status=error, got {payload.get('status')!r}")
    error = payload.get("error")
    if not isinstance(error, dict):
        return _failed_check(name, "response is missing structured error payload")
    if error.get("code") != expected_code:
        return _failed_check(name, f"expected error code {expected_code}, got {error.get('code')!r}")
    if detail_key is not None:
        detail = error.get("detail")
        if not isinstance(detail, dict) or detail_key not in detail:
            return _failed_check(name, f"response error.detail is missing {detail_key!r}")
    return {"name": name, "ok": True, "detail": f"code={expected_code}"}


def _validate_legacy_response(result: Mapping[str, Any]) -> dict[str, Any]:
    if not result.get("ok"):
        return _failed_check("legacy-raw", f"command failed: {_result_summary(result)}")
    stdout = str(result.get("stdout", "")).strip()
    if not stdout:
        return _failed_check("legacy-raw", "legacy response was empty")
    if _load_payload(stdout) is not None:
        return _failed_check("legacy-raw", "legacy response unexpectedly returned a protocol payload")
    return {"name": "legacy-raw", "ok": True, "detail": f"output={stdout}"}


def _build_report(
    command: list[str],
    repo_root: Path,
    checks: list[dict[str, Any]],
    *,
    certify_real_runtime: bool,
) -> dict[str, Any]:
    ok = all(bool(check.get("ok")) for check in checks)
    scope, scope_reason = _classify_scope(
        command,
        repo_root=repo_root,
        ok=ok,
        certify_real_runtime=certify_real_runtime,
    )
    return {
        "provider_command": command,
        "repo_root": str(repo_root),
        "ok": ok,
        "scope": scope,
        "scope_reason": scope_reason,
        "checks": checks,
    }


def _failed_check(name: str, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": False, "detail": detail}


def _result_summary(result: Mapping[str, Any]) -> str:
    parts = []
    if result.get("detail"):
        parts.append(str(result["detail"]).strip())
    if result.get("returncode") is not None:
        parts.append(f"returncode={result['returncode']}")
    stdout = str(result.get("stdout", "")).strip()
    stderr = str(result.get("stderr", "")).strip()
    if stdout:
        parts.append(f"stdout={stdout}")
    if stderr:
        parts.append(f"stderr={stderr}")
    return " | ".join(parts) if parts else "unknown runtime failure"


def _classify_scope(
    command: Sequence[str],
    *,
    repo_root: Path,
    ok: bool,
    certify_real_runtime: bool,
) -> tuple[RpConformanceScope, str]:
    stub_like, stub_reason = _looks_like_reference_stub(command, repo_root=repo_root)
    if stub_like:
        return "reference-stub", stub_reason
    if ok and certify_real_runtime:
        return (
            "real-runtime-certified",
            (
                "non-stub-like runtime passed conformance and the operator explicitly requested "
                "real-runtime certification for this report"
            ),
        )
    return (
        "real-runtime-untrusted",
        (
            "non-stub-like runtime candidate; conformance results are informative, but aiwf does not "
            "treat this as certification unless the operator explicitly promotes it"
        ),
    )


def _looks_like_reference_stub(command: Sequence[str], *, repo_root: Path) -> tuple[bool, str]:
    resolved_root = repo_root.resolve()
    virtual_env = os.environ.get("VIRTUAL_ENV")
    for part in command:
        lower = str(part).lower()
        if "rp_cli_stub" in lower or "rp-cli-stub" in lower:
            return True, f"command segment {part!r} matches the repo-local rp-cli-stub/reference harness"
        if "fake_rp_runtime" in lower or "fake-rp-runtime" in lower:
            return True, f"command segment {part!r} matches the aiwf fake RP runtime harness"
        candidate = _resolve_command_path(part, repo_root=resolved_root)
        if candidate is None:
            continue
        if _is_relative_to(candidate, resolved_root / "tools" / "rp-cli-stub"):
            return True, f"command path {candidate} is inside tools/rp-cli-stub"
        if candidate.name in {"rp", "rp-cli"} and virtual_env and _is_relative_to(candidate, Path(virtual_env)):
            return True, f"command path {candidate} is inside the current virtual environment ({virtual_env})"
        if candidate.name in {"rp", "rp-cli"} and _is_relative_to(candidate, Path(sys.prefix)):
            return True, f"command path {candidate} is inside the current Python environment ({sys.prefix})"
    return False, "command does not match aiwf reference-stub heuristics"


def _resolve_command_path(part: str, *, repo_root: Path) -> Path | None:
    if not part:
        return None
    candidate = Path(part).expanduser()
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    if any(separator in part for separator in ("/", "\\")) or part.startswith("."):
        return (repo_root / candidate).resolve(strict=False)
    return None


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(other.resolve(strict=False))
    except ValueError:
        return False
    return True
