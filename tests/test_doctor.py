from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from aiwf.cli import app
from aiwf.adapters.rp_cli_bridge import RpBridgeError, RpBridgeProbeResult, RpToolInfo, RpWorkspaceListResult
from aiwf.doctor import render_doctor_report, run_doctor


runner = CliRunner()

EXPECTED_BRIDGE_TOOLS = [
    "manage_workspaces",
    "bind_context",
    "manage_selection",
    "workspace_context",
    "context_builder",
    "ask_oracle",
    "agent_run",
    "agent_manage",
    "read_file",
    "file_search",
]


def test_run_doctor_reports_ok_for_valid_workspace(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command='python -c "print(\'ok\')"')
    _mock_which(
        monkeypatch,
        {
            "python": "/usr/bin/python",
            "uv": "/usr/bin/uv",
            "git": "/usr/bin/git",
            "rp": "/usr/bin/rp",
        },
    )
    _mock_protocol_probe(monkeypatch, {"/usr/bin/rp": 1})

    report = run_doctor(ai_root=ai_root, repo_root=repo_root)

    assert report.ok is True
    assert report.summary["fail"] == 0
    assert any(check.name == "runbook:default" and check.status == "ok" for check in report.checks)
    assert any(check.name == "policy:repo-policy" and check.status == "ok" for check in report.checks)
    assert any(check.name == "default:lint" and check.status == "ok" for check in report.checks)
    rp_check = next(check for check in report.checks if check.name == "rp")
    assert rp_check.protocol_supported is True
    assert rp_check.protocol_version == 1
    assert rp_check.runtime_detection == "non-stub-like"
    assert "outside aiwf test-harness" in (rp_check.runtime_detection_reason or "")
    rendered = render_doctor_report(report)
    assert "summary ok=" in rendered
    assert "OK [workspace] tasks" in rendered


def test_run_doctor_reports_fail_for_missing_structure_and_gate_command(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    ai_root = repo_root / ".ai"
    (ai_root / "runbooks").mkdir(parents=True)
    (ai_root / "policies").mkdir()
    (ai_root / "gates").mkdir()
    (ai_root / "runbooks" / "default.md").write_text(
        "\n".join(
            [
                "---",
                "name: default",
                "stages:",
                "  - name: discover",
                "---",
                "",
                "# Runbook",
            ]
        ),
        encoding="utf-8",
    )
    (ai_root / "policies" / "repo-policy.md").write_text("# Policy\n", encoding="utf-8")
    (ai_root / "gates" / "default.yaml").write_text(
        "\n".join(
            [
                "name: default",
                "gates:",
                "  - name: lint",
                "    command: missing-command --flag",
                "    timeout_seconds: 10",
            ]
        ),
        encoding="utf-8",
    )
    _mock_which(monkeypatch, {"python": "/usr/bin/python"})

    report = run_doctor(ai_root=ai_root, repo_root=repo_root)

    assert report.ok is False
    assert report.summary["fail"] >= 2
    assert any(check.name == "tasks" and check.status == "fail" for check in report.checks)
    assert any(check.name == "default:lint" and check.status == "fail" for check in report.checks)


def test_run_doctor_reports_rp_manual_only_when_runtime_missing(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command='python -c "print(\'ok\')"')
    _mock_which(
        monkeypatch,
        {
            "python": "/usr/bin/python",
            "uv": "/usr/bin/uv",
            "git": "/usr/bin/git",
        },
    )

    report = run_doctor(ai_root=ai_root, repo_root=repo_root)

    rp_check = next(check for check in report.checks if check.name == "rp")
    assert rp_check.status == "warn"
    assert "stable manual handoff path active" in rp_check.detail
    assert "rp, rp-cli" in rp_check.detail
    assert "experimental auto/native" in rp_check.detail
    assert "protocol v1" in rp_check.detail
    assert rp_check.protocol_supported is False
    assert rp_check.protocol_version is None


def test_run_doctor_reports_rp_bridge_groundwork_when_candidate_missing(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command='python -c "print(\'ok\')"')
    _mock_which(
        monkeypatch,
        {
            "python": "/usr/bin/python",
            "uv": "/usr/bin/uv",
            "git": "/usr/bin/git",
        },
    )

    report = run_doctor(ai_root=ai_root, repo_root=repo_root)

    bridge_check = next(check for check in report.checks if check.name == "rp-bridge")
    assert bridge_check.status == "warn"
    assert "groundwork-only" in bridge_check.detail
    assert "stable manual handoff path remains active" in bridge_check.detail
    assert bridge_check.protocol_supported is None
    assert bridge_check.protocol_version is None


def test_run_doctor_reports_rp_native_ready_when_runtime_found(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command='python -c "print(\'ok\')"')
    _mock_which(
        monkeypatch,
        {
            "python": "/usr/bin/python",
            "uv": "/usr/bin/uv",
            "git": "/usr/bin/git",
            "rp-cli": "/usr/local/bin/rp-cli",
        },
    )
    _mock_protocol_probe(monkeypatch, {"/usr/local/bin/rp-cli": 1})

    report = run_doctor(ai_root=ai_root, repo_root=repo_root)

    rp_check = next(check for check in report.checks if check.name == "rp")
    assert rp_check.status == "ok"
    assert rp_check.path == "/usr/local/bin/rp-cli"
    assert "experimental RP auto runtime detected via rp-cli" in rp_check.detail
    assert "protocol aiwf-rp-native v1 detected" in rp_check.detail
    assert "heuristic classifies this binary as non-stub-like" in rp_check.detail
    assert rp_check.protocol_supported is True
    assert rp_check.protocol_version == 1
    assert rp_check.runtime_detection == "non-stub-like"
    assert "outside aiwf test-harness" in (rp_check.runtime_detection_reason or "")
    payload = report.to_json()
    rp_payload = next(check for check in payload["checks"] if check["name"] == "rp")
    assert rp_payload["protocol_supported"] is True
    assert rp_payload["protocol_version"] == 1
    assert rp_payload["runtime_detection"] == "non-stub-like"


def test_run_doctor_reports_rp_bridge_candidate_when_runtime_found(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command="python -c \"print('ok')\"")
    _mock_which(
        monkeypatch,
        {
            "python": "/usr/bin/python",
            "uv": "/usr/bin/uv",
            "git": "/usr/bin/git",
            "rp-cli": "/usr/local/bin/rp-cli",
        },
    )
    _mock_protocol_probe(monkeypatch, {"/usr/local/bin/rp-cli": 1})
    _mock_bridge_probe(monkeypatch, {"/usr/local/bin/rp-cli": ["file_search", "manage_selection"]})

    report = run_doctor(ai_root=ai_root, repo_root=repo_root)

    bridge_check = next(check for check in report.checks if check.name == "rp-bridge")
    assert bridge_check.status == "ok"
    assert bridge_check.path == "/usr/local/bin/rp-cli"
    assert "experimental RP bridge candidate detected via rp-cli" in bridge_check.detail
    assert (
        "read-only bridge probe reports the CLI supports MCP tool invocation; "
        "inventoried tools: file_search, manage_selection"
    ) in bridge_check.detail
    assert "heuristic classifies this binary as non-stub-like" in bridge_check.detail
    assert bridge_check.protocol_supported is None
    assert bridge_check.protocol_version is None
    assert bridge_check.bridge_tools_detected == ["file_search", "manage_selection"]
    assert bridge_check.runtime_detection == "non-stub-like"


def test_run_doctor_reports_bridge_readiness_hints_from_tool_operations(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command='python -c "print(\'ok\')"')
    _mock_which(
        monkeypatch,
        {
            "python": "/usr/bin/python",
            "uv": "/usr/bin/uv",
            "git": "/usr/bin/git",
            "rp-cli": "/usr/local/bin/rp-cli",
        },
    )
    _mock_protocol_probe(monkeypatch, {"/usr/local/bin/rp-cli": 1})

    def fake_probe(command_path: str) -> RpBridgeProbeResult:
        assert command_path == "/usr/local/bin/rp-cli"
        return RpBridgeProbeResult(
            available=True,
            command=(command_path,),
            path=command_path,
            tools=(
                RpToolInfo(
                    name="manage_workspaces",
                    metadata={"inputSchema": {"properties": {"action": {"enum": ["list"]}}}},
                ),
                RpToolInfo(
                    name="bind_context",
                    metadata={"inputSchema": {"properties": {"op": {"enum": ["status", "bind"]}}}},
                ),
                RpToolInfo(
                    name="agent_manage",
                    metadata={
                        "inputSchema": {
                            "properties": {"op": {"enum": ["resume_session", "get_transcript", "extract_handoff"]}}
                        }
                    },
                ),
            ),
            error=None,
        )

    def fake_workspace_list(self, *, include_hidden: bool = False) -> RpWorkspaceListResult:
        del include_hidden
        return RpWorkspaceListResult(ok=True, command=("/usr/local/bin/rp-cli",), path="/usr/local/bin/rp-cli", workspaces=())

    monkeypatch.setattr("aiwf.doctor._probe_bridge_runtime", fake_probe)
    monkeypatch.setattr("aiwf.doctor.RpCliBridgeClient.manage_workspaces_list", fake_workspace_list)

    report = run_doctor(ai_root=ai_root, repo_root=repo_root)

    bridge_check = next(check for check in report.checks if check.name == "rp-bridge")
    assert bridge_check.status == "ok"
    assert "Readiness hints:" in bridge_check.detail
    assert "workspace-resolution=ready" in bridge_check.detail
    assert "bind-context=ready" in bridge_check.detail
    assert "session-recovery=ready" in bridge_check.detail
    assert "transcript=ready" in bridge_check.detail


def test_run_doctor_warns_when_bridge_probe_fails(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command='python -c "print(\'ok\')"')
    _mock_which(
        monkeypatch,
        {
            "python": "/usr/bin/python",
            "uv": "/usr/bin/uv",
            "git": "/usr/bin/git",
            "rp-cli": "/usr/local/bin/rp-cli",
        },
    )
    _mock_protocol_probe(monkeypatch, {"/usr/local/bin/rp-cli": 1})
    _mock_bridge_probe_error(monkeypatch, "/usr/local/bin/rp-cli", code="MALFORMED_RESPONSE", message="tool list probe returned invalid JSON")

    report = run_doctor(ai_root=ai_root, repo_root=repo_root)

    bridge_check = next(check for check in report.checks if check.name == "rp-bridge")
    assert bridge_check.status == "warn"
    assert "read-only bridge probe failed" in bridge_check.detail
    assert "tool list probe returned invalid JSON" in bridge_check.detail
    assert "Heuristic classification: non-stub-like" in bridge_check.detail
    assert bridge_check.bridge_probe_error == "tool list probe returned invalid JSON"
    assert bridge_check.runtime_detection == "non-stub-like"


def test_run_doctor_json_surfaces_bridge_tool_probe_info_with_fake_cli(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command='python -c "print(\'ok\')"')
    fake_cli = _write_fake_rp_bridge_cli(tmp_path)
    _mock_which(
        monkeypatch,
        {
            "python": "/usr/bin/python",
            "uv": "/usr/bin/uv",
            "git": "/usr/bin/git",
            "rp-cli": str(fake_cli),
        },
    )
    _mock_protocol_probe(monkeypatch, {str(fake_cli): 1})

    result = runner.invoke(
        app,
        [
            "doctor",
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    bridge_check = next(check for check in payload["checks"] if check["name"] == "rp-bridge")
    assert bridge_check["status"] == "ok"
    assert bridge_check["bridge_tools_detected"] == EXPECTED_BRIDGE_TOOLS
    assert bridge_check["bridge_probe_error"] is None
    assert bridge_check["runtime_detection"] == "stub-like"
    assert "fake RP runtime/bridge harness" in bridge_check["runtime_detection_reason"]


def test_run_doctor_warns_when_rp_runtime_lacks_protocol_support(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command="python -c \"print('ok')\"")
    _mock_which(
        monkeypatch,
        {
            "python": "/usr/bin/python",
            "uv": "/usr/bin/uv",
            "git": "/usr/bin/git",
            "rp": "/usr/bin/rp",
        },
    )
    _mock_protocol_probe(monkeypatch, unsupported_paths={"/usr/bin/rp"})

    report = run_doctor(ai_root=ai_root, repo_root=repo_root)

    rp_check = next(check for check in report.checks if check.name == "rp")
    assert rp_check.status == "warn"
    assert "protocol negotiation support was not detected" in rp_check.detail
    assert "treat RP auto/native as unavailable" in rp_check.detail
    assert "protocol v1" in rp_check.detail
    assert "Heuristic classification: non-stub-like" in rp_check.detail
    assert rp_check.protocol_supported is False
    assert rp_check.protocol_version is None
    assert rp_check.runtime_detection == "non-stub-like"


def test_run_doctor_warns_when_rp_runtime_protocol_version_mismatches(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command="python -c \"print('ok')\"")
    _mock_which(
        monkeypatch,
        {
            "python": "/usr/bin/python",
            "uv": "/usr/bin/uv",
            "git": "/usr/bin/git",
            "rp": "/usr/bin/rp",
        },
    )
    _mock_protocol_probe(monkeypatch, {"/usr/bin/rp": 2})

    report = run_doctor(ai_root=ai_root, repo_root=repo_root)

    rp_check = next(check for check in report.checks if check.name == "rp")
    assert rp_check.status == "warn"
    assert "aiwf-rp-native v2" in rp_check.detail
    assert "advertises v1" in rp_check.detail
    assert "heuristic classifies this binary as non-stub-like" in rp_check.detail
    assert rp_check.protocol_supported is True
    assert rp_check.protocol_version == 2
    assert rp_check.runtime_detection == "non-stub-like"


def test_run_doctor_labels_virtualenv_runtime_as_stub_like(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command="python -c \"print('ok')\"")
    fake_venv = tmp_path / ".venv"
    fake_runtime = fake_venv / "bin" / "rp-cli"
    fake_runtime.parent.mkdir(parents=True)
    fake_runtime.write_text("#!/bin/sh\n", encoding="utf-8")
    _mock_which(
        monkeypatch,
        {
            "python": "/usr/bin/python",
            "uv": "/usr/bin/uv",
            "git": "/usr/bin/git",
            "rp-cli": str(fake_runtime),
        },
    )
    monkeypatch.setenv("VIRTUAL_ENV", str(fake_venv))
    _mock_protocol_probe(monkeypatch, {str(fake_runtime): 1})

    report = run_doctor(ai_root=ai_root, repo_root=repo_root)

    rp_check = next(check for check in report.checks if check.name == "rp")
    assert rp_check.status == "ok"
    assert rp_check.runtime_detection == "stub-like"
    assert str(fake_venv) in (rp_check.runtime_detection_reason or "")
    assert "heuristic classifies this binary as stub-like" in rp_check.detail
    assert "reference-stub evidence" in rp_check.detail


def test_cli_doctor_human_output_succeeds(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command='python -c "print(\'ok\')"')
    _mock_which(
        monkeypatch,
        {
            "python": "/usr/bin/python",
            "uv": "/usr/bin/uv",
            "git": "/usr/bin/git",
            "rp": "/usr/bin/rp",
        },
    )
    _mock_protocol_probe(monkeypatch, {"/usr/bin/rp": 1})

    result = runner.invoke(
        app,
        [
            "doctor",
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert result.exit_code == 0
    assert "summary ok=" in result.stdout
    assert "OK [gate_command] default:lint" in result.stdout


def test_cli_doctor_json_output_reports_failures(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command="missing-command --flag")
    _mock_which(monkeypatch, {"python": "/usr/bin/python"})

    result = runner.invoke(
        app,
        [
            "doctor",
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["summary"]["fail"] >= 1
    assert any(
        check["name"] == "default:lint" and check["status"] == "fail"
        for check in payload["checks"]
    )


def _create_workspace(tmp_path: Path, *, gate_command: str) -> tuple[Path, Path]:
    repo_root = tmp_path / "repo"
    ai_root = repo_root / ".ai"
    (ai_root / "tasks").mkdir(parents=True)
    (ai_root / "runbooks").mkdir()
    (ai_root / "policies").mkdir()
    (ai_root / "gates").mkdir()
    (ai_root / "tasks" / "sample.md").write_text("# Task\n", encoding="utf-8")
    (ai_root / "runbooks" / "default.md").write_text(
        "\n".join(
            [
                "---",
                "name: default",
                "stages:",
                "  - name: discover",
                "---",
                "",
                "# Runbook",
            ]
        ),
        encoding="utf-8",
    )
    (ai_root / "policies" / "repo-policy.md").write_text("# Policy\n", encoding="utf-8")
    escaped_command = gate_command.replace("'", "''")
    (ai_root / "gates" / "default.yaml").write_text(
        "\n".join(
            [
                "name: default",
                "gates:",
                "  - name: lint",
                f"    command: '{escaped_command}'",
                "    timeout_seconds: 10",
            ]
        ),
        encoding="utf-8",
    )
    return repo_root, ai_root


def _mock_which(monkeypatch, mapping: dict[str, str]) -> None:
    def fake_which(command: str) -> str | None:
        return mapping.get(command)

    monkeypatch.setattr("aiwf.doctor.shutil.which", fake_which)


def _mock_protocol_probe(
    monkeypatch,
    version_by_path: dict[str, int] | None = None,
    *,
    unsupported_paths: set[str] | None = None,
) -> None:
    version_by_path = version_by_path or {}
    unsupported_paths = unsupported_paths or set()

    def fake_probe(command_path: str) -> tuple[bool, int | None]:
        if command_path in version_by_path:
            return True, version_by_path[command_path]
        if command_path in unsupported_paths:
            return False, None
        raise AssertionError(f"Unexpected protocol probe for {command_path}")

    monkeypatch.setattr("aiwf.doctor._probe_native_runtime_protocol", fake_probe)


def _mock_bridge_probe(monkeypatch, tools_by_path: dict[str, list[str]]) -> None:
    def fake_probe(command_path: str) -> RpBridgeProbeResult:
        tools = tuple(RpToolInfo(name=name) for name in tools_by_path.get(command_path, []))
        return RpBridgeProbeResult(
            available=True,
            command=(command_path,),
            path=command_path,
            tools=tools,
            error=None,
        )

    monkeypatch.setattr("aiwf.doctor._probe_bridge_runtime", fake_probe)


def _mock_bridge_probe_error(monkeypatch, command_path: str, *, code: str, message: str) -> None:
    def fake_probe(resolved_command_path: str) -> RpBridgeProbeResult:
        assert resolved_command_path == command_path
        return RpBridgeProbeResult(
            available=False,
            command=(resolved_command_path,),
            path=resolved_command_path,
            tools=(),
            error=RpBridgeError(code=code, message=message, retriable=False),
        )

    monkeypatch.setattr("aiwf.doctor._probe_bridge_runtime", fake_probe)


def _write_fake_rp_bridge_cli(tmp_path: Path) -> Path:
    script_path = tmp_path / "fake-rp-bridge-doctor.py"
    script_path.write_text(
        (
            f"#!{sys.executable}\n"
            "import json\n"
            "import sys\n"
            "\n"
            "def _tool_and_payload(argv):\n"
            "    if '-c' not in argv:\n"
            "        return None, {}\n"
            "    idx = argv.index('-c')\n"
            "    if idx + 1 >= len(argv):\n"
            "        return None, {}\n"
            "    tool = argv[idx + 1]\n"
            "    payload = {}\n"
            "    if '-j' in argv:\n"
            "        jidx = argv.index('-j')\n"
            "        if jidx + 1 < len(argv):\n"
            "            payload = json.loads(argv[jidx + 1])\n"
            "    return tool, payload\n"
            "\n"
            "if '--help' in sys.argv:\n"
            "    sys.stdout.write('usage: rp-cli -c TOOL -j JSON --raw-json --tools-schema\\n')\n"
            "    sys.stdout.write('tool mode with -c and -j and --raw-json\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if '--tools-schema' in sys.argv:\n"
            "    sys.stdout.write(json.dumps({'tools': [{'name': 'manage_workspaces'}, {'name': 'bind_context'}, {'name': 'manage_selection'}, {'name': 'workspace_context'}, {'name': 'context_builder'}, {'name': 'ask_oracle'}, {'name': 'agent_run'}, {'name': 'agent_manage'}, {'name': 'read_file'}, {'name': 'file_search'}]}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "tool, payload = _tool_and_payload(sys.argv)\n"
            "if tool is None:\n"
            "    sys.stderr.write('unsupported invocation\\n')\n"
            "    raise SystemExit(2)\n"
            "\n"
            "if tool == 'file_search':\n"
            "    sys.stdout.write(json.dumps({'count': 0, 'matches': []}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "sys.stderr.write('unknown tool ' + str(tool) + '\\n')\n"
            "raise SystemExit(3)\n"
        ),
        encoding="utf-8",
    )
    script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR)
    return script_path
