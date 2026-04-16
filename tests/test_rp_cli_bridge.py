from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

from aiwf.adapters.rp_cli_bridge import RpCliBridgeClient


def test_rp_cli_bridge_list_tools_success_and_probe_available(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="ok")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    result = client.list_tools()
    probe = client.probe_available()

    assert result.ok is True
    assert [tool.name for tool in result.tools] == ["file_search", "manage_selection", "workspace_context"]
    assert result.tools[0].description == "Search files"
    assert probe.available is True
    assert [tool.name for tool in probe.tools] == ["file_search", "manage_selection", "workspace_context"]


def test_rp_cli_bridge_workspace_context_success(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="ok")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    result = client.workspace_context("workspace-alpha")

    assert result.ok is True
    assert result.workspace == "workspace-alpha"
    assert result.context_id == "ctx-123"
    assert result.selected_paths == ("src/example.py", ".ai/runs/sample/context-pack.md")


def test_rp_cli_bridge_manage_selection_success(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="ok")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    result = client.manage_selection_add(
        [".ai/runs/run-1/context-pack.md", ".ai/runs/run-1/exec-plan.md"],
        workspace="workspace-alpha",
        context_id="ctx-123",
        tab="implement-tab",
    )

    assert result.ok is True
    assert result.workspace == "workspace-alpha"
    assert result.context_id == "ctx-123"
    assert result.added_paths == (".ai/runs/run-1/context-pack.md", ".ai/runs/run-1/exec-plan.md")
    assert result.selected_paths == (".ai/runs/run-1/context-pack.md", ".ai/runs/run-1/exec-plan.md")


def test_rp_cli_bridge_reports_missing_binary() -> None:
    client = RpCliBridgeClient(("/path/does/not/exist/rp-cli",), timeout_seconds=1)

    result = client.list_tools()

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "NOT_INSTALLED"
    assert result.error.retriable is False


def test_rp_cli_bridge_reports_timeout(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="timeout")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=1)

    result = client.list_tools()

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "TIMEOUT"
    assert result.error.retriable is True


def test_rp_cli_bridge_reports_malformed_json(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="malformed")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    result = client.list_tools()

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "MALFORMED_RESPONSE"
    assert result.error.retriable is False


def test_rp_cli_bridge_reports_nonzero_exit(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="fail")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    result = client.list_tools()

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "COMMAND_FAILED"
    assert result.error.detail["returncode"] == 9


def test_rp_cli_bridge_manage_selection_reports_nonzero_exit(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="manage-fail")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    result = client.manage_selection_add([".ai/runs/run-1/context-pack.md"])

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "COMMAND_FAILED"
    assert result.error.detail["returncode"] == 7


def _write_fake_rp_bridge_cli(tmp_path: Path, *, mode: str) -> Path:
    script_path = tmp_path / f"fake-rp-bridge-{mode}.py"
    script_path.write_text(
        (
            f"#!{sys.executable}\n"
            "import json\n"
            "import sys\n"
            "import time\n"
            "\n"
            f"MODE = {mode!r}\n"
            "\n"
            "if '--list-tools' in sys.argv:\n"
            "    if MODE == 'timeout':\n"
            "        time.sleep(10)\n"
            "    if MODE == 'malformed':\n"
            "        sys.stdout.write('not-json\\n')\n"
            "        raise SystemExit(0)\n"
            "    if MODE == 'fail':\n"
            "        sys.stderr.write('tool listing failed\\n')\n"
            "        raise SystemExit(9)\n"
            "    sys.stdout.write(json.dumps({'tools': [{'name': 'file_search', 'description': 'Search files'}, {'name': 'manage_selection'}, {'name': 'workspace_context'}]}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if '--workspace-context' in sys.argv:\n"
            "    workspace = None\n"
            "    if len(sys.argv) >= 3:\n"
            "        workspace = sys.argv[-1]\n"
            "    sys.stdout.write(json.dumps({'workspace': workspace, 'context_id': 'ctx-123', 'selection': ['src/example.py', '.ai/runs/sample/context-pack.md']}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if '--manage-selection' in sys.argv:\n"
            "    if MODE == 'manage-fail':\n"
            "        sys.stderr.write('manage selection failed\\n')\n"
            "        raise SystemExit(7)\n"
            "    payload = json.loads(sys.argv[-1])\n"
            "    paths = payload.get('paths', [])\n"
            "    sys.stdout.write(json.dumps({'workspace': payload.get('workspace'), 'context_id': payload.get('context_id'), 'selected_paths': paths, 'added_paths': paths}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "sys.stderr.write('unsupported invocation\\n')\n"
            "raise SystemExit(2)\n"
        ),
        encoding="utf-8",
    )
    script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR)
    return script_path
