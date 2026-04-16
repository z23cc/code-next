from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

from aiwf.adapters.rp_cli_bridge import RpCliBridgeClient


EXPECTED_MANIFEST_TOOLS = [
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


def test_rp_cli_bridge_list_tools_success_and_probe_available(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="ok")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    result = client.list_tools()
    probe = client.probe_available()

    assert result.ok is True
    assert [tool.name for tool in result.tools] == EXPECTED_MANIFEST_TOOLS
    assert probe.available is True
    assert [tool.name for tool in probe.tools] == EXPECTED_MANIFEST_TOOLS


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


def test_rp_cli_bridge_read_file_success(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="read-ok")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    result = client.read_file("implement-response.md", workspace="workspace-alpha", context_id="ctx-123", tab="tab-7")

    assert result.ok is True
    assert result.source == "implement-response.md"
    assert result.content == "# Implemented from RepoPrompt\n"
    assert result.workspace == "workspace-alpha"
    assert result.context_id == "ctx-123"


def test_rp_cli_bridge_agent_run_surfaces_success(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="agent-complete")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    start = client.agent_run_start(
        "Implement the change",
        workspace="workspace-alpha",
        tab="tab-7",
        context_id="ctx-123",
        agent_role="engineer",
        stage="implement",
    )
    wait = client.agent_run_wait(start.session_id or "", workspace="workspace-alpha", tab="tab-7", context_id="ctx-123")
    log = client.agent_log(start.session_id or "", workspace="workspace-alpha", tab="tab-7", context_id="ctx-123")

    assert start.ok is True
    assert start.session_id == "agent-session-123"
    start_payload = json.loads(start.command[start.command.index("-j") + 1])
    assert start_payload["op"] == "start"
    assert start_payload["message"] == "Implement the change"
    assert start_payload["detach"] is True
    assert wait.ok is True
    wait_payload = json.loads(wait.command[wait.command.index("-j") + 1])
    assert wait_payload["op"] == "wait"
    assert wait_payload["session_id"] == "agent-session-123"
    assert wait_payload["timeout"] == 1
    assert wait.status == "completed"
    assert wait.output == "# Managed agent output\n"
    assert log.ok is True
    assert log.session_id == "agent-session-123"
    assert log.status == "completed"
    assert log.output == "# Managed agent output\n"
    assert log.log["events"][0]["kind"] == "agent_wait"


def test_rp_cli_bridge_agent_run_wait_reports_malformed_payload(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="agent-malformed")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    result = client.agent_run_wait("agent-session-123")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "MALFORMED_RESPONSE"


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
    assert result.error.code == "BRIDGE_TOOL_INVOCATION_UNSUPPORTED"
    assert result.error.retriable is False


def test_rp_cli_bridge_reports_nonzero_exit(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="fail")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    result = client.workspace_context("workspace-alpha")

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


def test_rp_cli_bridge_manage_selection_reports_tool_unavailable(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="manage-tool-missing")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    result = client.manage_selection_add([".ai/runs/run-1/context-pack.md"])

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "TOOL_UNAVAILABLE"
    assert result.error.detail["tool"] == "manage_selection"


def test_rp_cli_bridge_read_file_reports_malformed_payload(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="read-malformed")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    result = client.read_file("review-response.json")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "MALFORMED_RESPONSE"


def test_rp_cli_bridge_reports_unsupported_invocation_mode(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="unsupported-help")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    result = client.list_tools()

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "BRIDGE_TOOL_INVOCATION_UNSUPPORTED"


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
            "    if MODE == 'unsupported-help':\n"
            "        sys.stdout.write('usage: rp-cli [legacy-flags]\\n')\n"
            "        raise SystemExit(0)\n"
            "    sys.stdout.write('usage: rp-cli -c TOOL -j JSON --raw-json --tools-schema\\n')\n"
            "    sys.stdout.write('tool mode with -c and -j and --raw-json\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if '--tools-schema' in sys.argv:\n"
            "    if MODE == 'timeout':\n"
            "        time.sleep(10)\n"
            "    if MODE == 'malformed':\n"
            "        sys.stdout.write('not-json\\n')\n"
            "        raise SystemExit(0)\n"
            "    sys.stdout.write(json.dumps({'tools': [{'name': 'manage_workspaces'}, {'name': 'bind_context'}, {'name': 'manage_selection'}, {'name': 'workspace_context'}, {'name': 'context_builder'}, {'name': 'ask_oracle'}, {'name': 'agent_run'}, {'name': 'agent_manage'}, {'name': 'read_file'}, {'name': 'file_search', 'description': 'Search files'}]}))\n"
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
            "if tool == 'workspace_context':\n"
            "    if MODE == 'fail':\n"
            "        sys.stderr.write('workspace context failed\\n')\n"
            "        raise SystemExit(9)\n"
            "    sys.stdout.write(json.dumps({'workspace': payload.get('workspace'), 'context_id': 'ctx-123', 'selection': ['src/example.py', '.ai/runs/sample/context-pack.md']}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if tool == 'manage_selection':\n"
            "    if MODE == 'manage-fail':\n"
            "        sys.stderr.write('manage selection failed\\n')\n"
            "        raise SystemExit(7)\n"
            "    if MODE == 'manage-tool-missing':\n"
            "        sys.stderr.write('unknown tool manage_selection\\n')\n"
            "        raise SystemExit(6)\n"
            "    paths = payload.get('paths', [])\n"
            "    sys.stdout.write(json.dumps({'workspace': payload.get('workspace'), 'context_id': payload.get('context_id'), 'selected_paths': paths, 'added_paths': paths}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if tool == 'read_file':\n"
            "    if MODE == 'read-malformed':\n"
            "        sys.stdout.write(json.dumps({'workspace': payload.get('workspace'), 'context_id': payload.get('context_id'), 'body': 'missing content'}))\n"
            "        sys.stdout.write('\\n')\n"
            "        raise SystemExit(0)\n"
            "    source = payload.get('source')\n"
            "    content = '# Implemented from RepoPrompt\\n' if source == 'implement-response.md' else '{\"summary\": \"Looks good\", \"issues\": []}'\n"
            "    sys.stdout.write(json.dumps({'workspace': payload.get('workspace'), 'context_id': payload.get('context_id'), 'content': content}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if tool == 'agent_run':\n"
            "    op = payload.get('op')\n"
            "    if op == 'start':\n"
            "        sys.stdout.write(json.dumps({'session_id': 'agent-session-123', 'status': 'started', 'workspace': payload.get('workspace'), 'tab': payload.get('tab'), 'context_id': payload.get('context_id')}))\n"
            "        sys.stdout.write('\\n')\n"
            "        raise SystemExit(0)\n"
            "    if op == 'wait':\n"
            "        if MODE == 'agent-malformed':\n"
            "            sys.stdout.write(json.dumps({'session_id': payload.get('session_id')}))\n"
            "            sys.stdout.write('\\n')\n"
            "            raise SystemExit(0)\n"
            "        sys.stdout.write(json.dumps({'session_id': payload.get('session_id'), 'status': 'completed', 'output': '# Managed agent output\\n', 'workspace': payload.get('workspace'), 'tab': payload.get('tab'), 'context_id': payload.get('context_id')}))\n"
            "        sys.stdout.write('\\n')\n"
            "        raise SystemExit(0)\n"
            "\n"
            "if tool == 'agent_manage':\n"
            "    sys.stdout.write(json.dumps({'session_id': payload.get('session_id'), 'status': 'completed', 'output': '# Managed agent output\\n', 'events': [{'kind': 'agent_wait'}], 'workspace': payload.get('workspace'), 'tab': payload.get('tab'), 'context_id': payload.get('context_id')}))\n"
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
