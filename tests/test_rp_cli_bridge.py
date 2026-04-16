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


def test_rp_cli_bridge_workspace_context_snapshot_success(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="context-oracle-ok")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    result = client.workspace_context_snapshot(include=["prompt", "selection", "tokens"])

    assert result.ok is True
    assert result.prompt == "# Prompt"
    assert result.tokens == {"selection": 12, "files": 8}
    assert result.sections is not None
    assert "selection" in result.sections


def test_rp_cli_bridge_context_builder_and_oracle_success(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="context-oracle-ok")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    preview = client.context_builder_preview("<task>preview</task>")
    apply = client.context_builder_apply("<task>apply</task>", response_type="plan", export_response=True)
    oracle = client.ask_oracle("Review this", mode="review", export_response=True)

    assert preview.ok is True
    assert preview.flow == "preview"
    assert preview.response_type == "clarify"
    assert preview.response_text == "context-builder preview"
    assert apply.ok is True
    assert apply.flow == "apply"
    assert apply.response_type == "plan"
    assert apply.export_path == ".ai/runs/run-1/context-builder-plan.md"
    assert oracle.ok is True
    assert oracle.mode == "review"
    assert oracle.chat_id == "rp-chat-7"
    assert oracle.export_path == ".ai/runs/run-1/oracle-review.md"


def test_rp_cli_bridge_manage_workspaces_and_bind_context_success(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="workspace-bind-ok")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    list_result = client.manage_workspaces_list(include_hidden=True)
    resolve_result = client.manage_workspaces_resolve("workspace-alpha")
    bind_result = client.bind_context_bind(window_id=11)

    assert list_result.ok is True
    assert [workspace.name for workspace in list_result.workspaces] == ["workspace-alpha", "workspace-beta"]
    assert resolve_result.ok is True
    assert resolve_result.workspace_id == "workspace-1"
    assert resolve_result.window_ids == (11,)
    assert bind_result.ok is True
    assert bind_result.workspace == "workspace-alpha"
    assert bind_result.window_id == 11
    assert bind_result.tab == "implement-tab"
    assert bind_result.context_id == "ctx-456"


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


def test_rp_cli_bridge_agent_recovery_surfaces_success(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="agent-recovery")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    poll = client.agent_run_poll("agent-session-123")
    cancel = client.agent_run_cancel("agent-session-123")
    sessions = client.agent_manage_list_sessions(limit=5, state="waiting_for_input")
    resume = client.agent_manage_resume_session("agent-session-123")
    transcript = client.agent_manage_transcript("agent-session-123")
    handoff = client.agent_manage_extract_handoff("agent-session-123", output_path=str(tmp_path / "handoff.xml"), inline=False)

    assert poll.ok is True
    assert poll.status == "running"
    assert cancel.ok is True
    assert cancel.status == "cancelled"
    assert sessions.ok is True
    assert sessions.sessions[0].session_id == "agent-session-123"
    assert sessions.sessions[0].status == "waiting_for_input"
    assert resume.ok is True
    assert resume.session_id == "agent-session-123"
    assert transcript.ok is True
    assert transcript.transcript == "<transcript><item>hello</item></transcript>"
    assert transcript.source_operation == "get_log"
    assert handoff.ok is True
    assert handoff.output_path == str(tmp_path / "handoff.xml")


def test_rp_cli_bridge_agent_run_wait_reports_malformed_payload(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="agent-malformed")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    result = client.agent_run_wait("agent-session-123")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "MALFORMED_RESPONSE"


def test_rp_cli_bridge_agent_transcript_uses_get_transcript_when_available(tmp_path: Path) -> None:
    script_path = _write_fake_rp_bridge_cli(tmp_path, mode="agent-transcript-op")
    client = RpCliBridgeClient((str(script_path),), timeout_seconds=2)

    result = client.agent_manage_transcript("agent-session-123", offset=2, limit=10)

    assert result.ok is True
    assert result.source_operation == "get_transcript"
    assert result.status == "completed"
    assert result.transcript == "# transcript from op"
    assert result.handoff_summary == "handoff summary"
    payload = json.loads(result.command[result.command.index("-j") + 1])
    assert payload == {"op": "get_transcript", "session_id": "agent-session-123", "offset": 2, "limit": 10}


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
            "from pathlib import Path\n"
            "\n"
            f"MODE = {mode!r}\n"
            "agent_manage_ops = ['get_log', 'list_sessions', 'resume_session', 'extract_handoff']\n"
            "if MODE == 'agent-transcript-op':\n"
            "    agent_manage_ops.append('get_transcript')\n"
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
            "    sys.stdout.write(json.dumps({'tools': [{'name': 'manage_workspaces', 'inputSchema': {'properties': {'action': {'enum': ['list', 'list_tabs', 'select_tab']}}}}, {'name': 'bind_context', 'inputSchema': {'properties': {'op': {'enum': ['list', 'status', 'bind']}}}}, {'name': 'manage_selection'}, {'name': 'workspace_context', 'inputSchema': {'properties': {'op': {'enum': ['snapshot', 'export', 'list_presets', 'select_preset']}}}}, {'name': 'context_builder', 'inputSchema': {'properties': {'response_type': {'enum': ['clarify', 'plan', 'question', 'review']}}}}, {'name': 'ask_oracle', 'inputSchema': {'properties': {'mode': {'enum': ['chat', 'plan', 'review']}}}}, {'name': 'agent_run', 'inputSchema': {'properties': {'op': {'enum': ['start', 'poll', 'wait', 'cancel']}}}}, {'name': 'agent_manage', 'inputSchema': {'properties': {'op': {'enum': agent_manage_ops}}}}, {'name': 'read_file'}, {'name': 'file_search', 'description': 'Search files'}]}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "tool, payload = _tool_and_payload(sys.argv)\n"
            "if tool is None:\n"
            "    sys.stderr.write('unsupported invocation\\n')\n"
            "    raise SystemExit(2)\n"
            "\n"
            "if tool == 'manage_workspaces':\n"
            "    if MODE == 'workspace-bind-ok' and payload.get('action') == 'list':\n"
            "        sys.stdout.write(json.dumps({'workspaces': [{'id': 'workspace-1', 'name': 'workspace-alpha', 'repo_paths': ['/tmp/repo-alpha'], 'window_ids': [11], 'is_hidden': False}, {'id': 'workspace-2', 'name': 'workspace-beta', 'repo_paths': ['/tmp/repo-beta'], 'window_ids': [12], 'is_hidden': True}]}))\n"
            "        sys.stdout.write('\\n')\n"
            "        raise SystemExit(0)\n"
            "    sys.stdout.write(json.dumps({'workspaces': []}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if tool == 'bind_context':\n"
            "    if MODE == 'workspace-bind-ok':\n"
            "        sys.stdout.write(json.dumps({'workspace': 'workspace-alpha', 'workspace_id': 'workspace-1', 'window_id': payload.get('window_id', 11), 'tab': 'implement-tab', 'tab_id': 'tab-1', 'context_id': 'ctx-456', 'windows': [{'window_id': 11, 'tabs': [{'id': 'tab-1', 'name': 'implement-tab', 'context_id': 'ctx-456'}]}]}))\n"
            "        sys.stdout.write('\\n')\n"
            "        raise SystemExit(0)\n"
            "    sys.stdout.write(json.dumps({'context_id': 'ctx-123'}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
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
            "    if MODE == 'context-oracle-ok' and payload.get('op') == 'snapshot':\n"
            "        sys.stdout.write(json.dumps({'context_id': 'ctx-123', 'prompt': '# Prompt', 'selection': {'paths': ['src/example.py']}, 'tokens': {'selection': 12, 'files': 8}}))\n"
            "        sys.stdout.write('\\n')\n"
            "        raise SystemExit(0)\n"
            "    sys.stdout.write(json.dumps({'workspace': payload.get('workspace'), 'context_id': 'ctx-123', 'selection': ['src/example.py', '.ai/runs/sample/context-pack.md']}))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if tool == 'context_builder':\n"
            "    response_type = payload.get('response_type', 'clarify')\n"
            "    response_text = 'context-builder preview' if response_type == 'clarify' else 'context-builder applied'\n"
            "    result = {'response_type': response_type, 'context_id': 'ctx-123', 'selected_paths': ['src/example.py'], 'response': response_text}\n"
            "    if payload.get('export_response'):\n"
            "        result['export_path'] = '.ai/runs/run-1/context-builder-plan.md'\n"
            "    sys.stdout.write(json.dumps(result))\n"
            "    sys.stdout.write('\\n')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "if tool == 'ask_oracle':\n"
            "    result = {'mode': payload.get('mode', 'chat'), 'chat_id': 'rp-chat-7', 'response': 'oracle response'}\n"
            "    if payload.get('export_response'):\n"
            "        result['oracle_export_path'] = '.ai/runs/run-1/oracle-review.md'\n"
            "    sys.stdout.write(json.dumps(result))\n"
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
            "    if op == 'poll':\n"
            "        sys.stdout.write(json.dumps({'session_id': payload.get('session_id'), 'status': 'running', 'workspace': payload.get('workspace'), 'tab': payload.get('tab'), 'context_id': payload.get('context_id')}))\n"
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
            "    if op == 'cancel':\n"
            "        sys.stdout.write(json.dumps({'session_id': payload.get('session_id'), 'status': 'cancelled'}))\n"
            "        sys.stdout.write('\\n')\n"
            "        raise SystemExit(0)\n"
            "\n"
            "if tool == 'agent_manage':\n"
            "    if MODE == 'agent-recovery' and payload.get('op') == 'list_sessions':\n"
            "        sys.stdout.write(json.dumps({'sessions': [{'session_id': 'agent-session-123', 'status': 'waiting_for_input', 'session_name': 'Auth work'}]}))\n"
            "        sys.stdout.write('\\n')\n"
            "        raise SystemExit(0)\n"
            "    if MODE == 'agent-recovery' and payload.get('op') == 'resume_session':\n"
            "        sys.stdout.write(json.dumps({'session_id': payload.get('session_id'), 'status': 'waiting_for_input'}))\n"
            "        sys.stdout.write('\\n')\n"
            "        raise SystemExit(0)\n"
            "    if MODE == 'agent-recovery' and payload.get('op') == 'extract_handoff':\n"
            "        output_path = payload.get('output_path')\n"
            "        Path(output_path).write_text('<forked_session />\\n', encoding='utf-8')\n"
            "        sys.stdout.write(json.dumps({'session_id': payload.get('session_id'), 'output_path': output_path}))\n"
            "        sys.stdout.write('\\n')\n"
            "        raise SystemExit(0)\n"
            "    if MODE == 'agent-recovery' and payload.get('op') == 'get_log':\n"
            "        sys.stdout.write('<transcript><item>hello</item></transcript>\\n')\n"
            "        raise SystemExit(0)\n"
            "    if MODE == 'agent-transcript-op' and payload.get('op') == 'get_transcript':\n"
            "        sys.stdout.write(json.dumps({'session_id': payload.get('session_id'), 'status': 'completed', 'transcript': '# transcript from op\\n', 'events': [{'kind': 'agent_log'}], 'handoff_summary': 'handoff summary'}))\n"
            "        sys.stdout.write('\\n')\n"
            "        raise SystemExit(0)\n"
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
