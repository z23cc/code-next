"""Typer CLI for aiwf workflow operations."""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Callable, Literal

import typer
from rich.console import Console

from aiwf import __version__
from aiwf.adapters import (
    ADAPTER_SPECS,
    build_adapter,
    build_adapter_from_contract,
    restore_host_contract,
    restore_rp_bridge_config,
)
from aiwf.adapters.base import HostContract
from aiwf.adapters.rp_bridge_normalize import (
    RpBridgeNormalizationError,
    normalize_implement_capture,
    normalize_review_capture,
)
from aiwf.adapters.rp_cli_bridge import RpBridgeProbeResult, RpCliBridgeClient
from aiwf.artifacts import ArtifactStore
from aiwf.compilers.claude import compile_claude
from aiwf.compilers.codex import compile_codex
from aiwf.compilers.rp import compile_rp
from aiwf.conformance import render_rp_conformance_report, run_rp_conformance
from aiwf.contracts import assess_review_boundary, assess_review_evidence, lint_contract_registry, review_contract_fields
from aiwf.doctor import render_doctor_report, run_doctor
from aiwf.engine import WorkflowEngine
from aiwf.exceptions import AiwfError
from aiwf.models import (
    RpBridgeCaptureArtifact,
    RpBridgeCaptureRecord,
    RpBridgeRunConfig,
    RpBridgeToolCall,
    RunMeta,
    RunStatus,
)
from aiwf.state import RunStateManager

app = typer.Typer(
    invoke_without_command=True,
    help="aiwf workflow CLI.",
)
run_app = typer.Typer(help="Run workflow stages with the configured adapter.")
compile_app = typer.Typer(help="Compile workflow inputs for host-specific outputs.")
contracts_app = typer.Typer(help="Lint and inspect built-in host contracts.")
conformance_app = typer.Typer(
    help="Run RP executable protocol checks; the official product target is the real RepoPrompt app / MCP CLI runtime."
)
rp_app = typer.Typer(help="RepoPrompt bridge utilities.")
bridge_app = typer.Typer(help="RepoPrompt bridge workflow helpers.")
app.add_typer(run_app, name="run")
app.add_typer(compile_app, name="compile")
app.add_typer(contracts_app, name="contracts")
app.add_typer(conformance_app, name="conformance")
app.add_typer(rp_app, name="rp")
rp_app.add_typer(bridge_app, name="bridge")
console = Console()


AdapterName = Literal["claude", "rp", "codex", "stub"]
_ADAPTER_OPTION_HELP = "Host adapter to use (`stub` is internal/test-only)."
_AUTO_OPTION_HELP = (
    "Use adapter auto mode when supported by the selected host contract. For RP, auto is experimental "
    "and intended for a verified real RepoPrompt app / MCP CLI runtime; manual handoff remains the stable path."
)
_BRIDGE_OPTION_HELP = (
    "Enable the experimental RepoPrompt bridge groundwork for RP manual mode. This enriches manual handoff "
    "prompts and metadata only; it does not invoke RepoPrompt MCP/tools yet, and the stable manual path remains supported."
)
_INTERNAL_RUN_FILES = {"run.json", "events.ndjson", "run-diagnostics.json", "run-provenance.json"}
_DIFF_FIELDS = ("workflow", "status", "last_completed_stage", "error_code", "error", "adapter", "mode")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the installed aiwf version.",
        ),
    ] = False,
) -> None:
    """Run the aiwf CLI."""


def _build_engine(
    ai_root: Path,
    repo_root: Path,
    *,
    adapter_name: AdapterName | None = None,
    auto: bool = False,
    host_contract: HostContract | None = None,
    bridge_config: RpBridgeRunConfig | None = None,
) -> WorkflowEngine:
    try:
        if host_contract is None:
            if adapter_name is None:
                raise AiwfError("Adapter name is required when no stored host contract is provided")
            adapter, host_contract = build_adapter(adapter_name, repo_root, auto=auto, bridge_config=bridge_config)
        else:
            run_data = {"rp_bridge": bridge_config.model_dump(mode="json")} if bridge_config is not None else None
            adapter = build_adapter_from_contract(host_contract, repo_root, run_data=run_data)
        return WorkflowEngine(
            adapter,
            ai_root=ai_root,
            repo_root=repo_root,
            host_contract=host_contract,
            adapter_resolver=lambda contract, run_data: build_adapter_from_contract(contract, repo_root, run_data=run_data),
            bridge_config=bridge_config,
        )
    except ValueError as exc:
        raise AiwfError(str(exc)) from exc


def _resolve_run_execution_payload(ai_root: Path, run_id: str) -> tuple[HostContract, RpBridgeRunConfig | None]:
    meta = RunStateManager(ai_root).load_run(run_id)
    try:
        host_contract = restore_host_contract(meta.data)
    except ValueError as exc:
        raise AiwfError(f"Run {run_id} does not include a valid stored host contract") from exc
    try:
        bridge_config = restore_rp_bridge_config(meta.data)
    except ValueError as exc:
        raise AiwfError(f"Run {run_id} does not include valid stored RP bridge metadata") from exc
    return host_contract, bridge_config


def _resolve_run_execution(ai_root: Path, run_id: str) -> HostContract:
    host_contract, _ = _resolve_run_execution_payload(ai_root, run_id)
    return host_contract


def _build_engine_from_stored_run(ai_root: Path, repo_root: Path, run_id: str) -> WorkflowEngine:
    host_contract, bridge_config = _resolve_run_execution_payload(ai_root, run_id)
    return _build_engine(ai_root, repo_root, host_contract=host_contract, bridge_config=bridge_config)


def _resolve_bridge_config(
    adapter_name: AdapterName,
    auto: bool,
    *,
    bridge: bool,
    bridge_mode: str | None,
    bridge_workspace: str | None,
    bridge_tab: str | None,
    bridge_context_id: str | None,
    bridge_agent_role: str | None,
    bridge_timeout: int | None,
    bridge_export_transcript: bool,
) -> RpBridgeRunConfig | None:
    any_bridge_option = any(
        [
            bridge,
            bridge_mode is not None,
            bridge_workspace is not None,
            bridge_tab is not None,
            bridge_context_id is not None,
            bridge_agent_role is not None,
            bridge_timeout is not None,
            bridge_export_transcript,
        ]
    )
    if not any_bridge_option:
        return None
    if adapter_name != "rp":
        raise AiwfError("Bridge is currently only supported with --adapter rp")
    if auto:
        raise AiwfError("Bridge is currently only supported with RP manual mode")

    bridge_contract = ADAPTER_SPECS["rp"].variants["manual"].bridge
    resolved_mode = bridge_mode or bridge_contract.default_mode
    if resolved_mode not in bridge_contract.supported_modes or resolved_mode != "manual-assist":
        raise AiwfError(f"Bridge mode '{resolved_mode}' is not supported in this slice")

    try:
        return RpBridgeRunConfig(
            mode=resolved_mode,
            workspace=bridge_workspace,
            tab=bridge_tab,
            context_id=bridge_context_id,
            agent_role=bridge_agent_role,
            timeout_seconds=bridge_timeout,
            export_transcript=bridge_export_transcript,
        )
    except Exception as exc:
        raise AiwfError(f"Invalid bridge configuration: {exc}") from exc


def _build_engine_or_exit(action: str, builder: Callable[[], WorkflowEngine]) -> WorkflowEngine:
    try:
        return builder()
    except AiwfError as exc:
        console.print(f"[red]{action} failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc


def _execute_command(action: str, ai_root: Path, func: Callable[[], str]) -> None:
    try:
        run_id = func()
    except AiwfError as exc:
        console.print(f"[red]{action} failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    final_status = RunStateManager(ai_root).load_run(run_id).status.value
    if final_status == "failed":
        console.print(f"[red]{action} finished with failed status[/red] run_id={run_id}")
        _print_run_guidance(ai_root, run_id)
        raise typer.Exit(code=1)
    if final_status == "passed":
        console.print(f"[green]{action} completed[/green] run_id={run_id}")
        return
    console.print(f"[yellow]{action} stopped[/yellow] run_id={run_id} status={final_status}")
    _print_run_guidance(ai_root, run_id)


def _load_run_surface(ai_root: Path, run_id: str, artifact_name: str) -> dict[str, Any]:
    run_dir = ai_root / "runs" / run_id
    try:
        artifact = ArtifactStore(run_dir).read_artifact(artifact_name)
    except Exception as exc:
        raise AiwfError(f"Unable to read {artifact_name} for run {run_id}: {exc}") from exc
    if not isinstance(artifact, dict):
        raise AiwfError(f"{artifact_name} for run {run_id} is not a JSON object")
    return artifact


def _load_optional_run_surface(ai_root: Path, run_id: str, artifact_name: str) -> dict[str, Any] | None:
    try:
        return _load_run_surface(ai_root, run_id, artifact_name)
    except AiwfError:
        return None


def _artifact_path(ai_root: Path, run_id: str, artifact_name: str) -> Path:
    return ai_root / "runs" / run_id / artifact_name


def _resolve_bridge_capture_run(ai_root: Path, run_id: str) -> tuple[RunMeta, HostContract, RpBridgeRunConfig]:
    state_manager = RunStateManager(ai_root)
    meta = state_manager.load_run(run_id)
    workflow = str(meta.data.get("workflow", "")).strip()
    if workflow != "implement":
        raise AiwfError(f"Bridge capture only supports implement workflow runs; run {run_id} is {workflow or '-'}")

    host_contract, bridge_config = _resolve_run_execution_payload(ai_root, run_id)
    if host_contract.adapter != "rp" or host_contract.mode != "manual":
        raise AiwfError(f"Run {run_id} does not use the rp/manual bridge handoff path")
    if bridge_config is None or bridge_config.mode != "manual-assist":
        raise AiwfError(f"Run {run_id} is not bridge-enabled with manual-assist mode")
    return meta, host_contract, bridge_config


def _build_bridge_capture_client(host_contract: HostContract, bridge_config: RpBridgeRunConfig) -> RpCliBridgeClient:
    timeout_seconds = bridge_config.timeout_seconds or 5
    client = RpCliBridgeClient.from_command_candidates(
        host_contract.bridge.command_candidates,
        timeout_seconds=timeout_seconds,
    )
    if client is not None:
        return client

    candidates = ", ".join(candidate for candidate in host_contract.bridge.command_candidates if candidate) or "-"
    install_hint = host_contract.bridge.install_hint or "Install a RepoPrompt bridge command candidate and try again."
    raise AiwfError(f"No RP bridge command candidate was found on PATH ({candidates}). {install_hint}")


def _bridge_tool_call_from_read_result(result: object, *, step: str, tool: str = "read_file") -> RpBridgeToolCall:
    ok = bool(getattr(result, "ok", False))
    error = getattr(result, "error", None)
    summary = f"Captured RepoPrompt source via {tool}" if ok else str(getattr(error, "message", "RP bridge call failed"))
    return RpBridgeToolCall(
        step=step,
        tool=tool,
        ok=ok,
        command=list(getattr(result, "command", ()) or ()),
        summary=summary,
        error_code=getattr(error, "code", None),
        error_message=getattr(error, "message", None),
        detail=dict(getattr(error, "detail", {}) or {}),
    )


def _load_bridge_capture_artifact(store: ArtifactStore) -> RpBridgeCaptureArtifact:
    capture_path = store.run_dir / "rp-bridge-capture.json"
    if not capture_path.exists():
        return RpBridgeCaptureArtifact()
    artifact = store.read_artifact("rp-bridge-capture.json")
    if not isinstance(artifact, dict):
        raise AiwfError(f"Stored bridge capture artifact for run {store.run_id} is invalid")
    try:
        return RpBridgeCaptureArtifact.model_validate(artifact)
    except Exception as exc:
        raise AiwfError(f"Stored bridge capture artifact for run {store.run_id} is invalid: {exc}") from exc


def _upsert_bridge_capture_record(store: ArtifactStore, record: RpBridgeCaptureRecord) -> None:
    capture_artifact = _load_bridge_capture_artifact(store)
    captures = [existing for existing in capture_artifact.captures if existing.stage != record.stage]
    captures.append(record)
    captures.sort(key=lambda item: item.stage)
    store.write_json_artifact(
        "rp-bridge-capture.json",
        RpBridgeCaptureArtifact(version=capture_artifact.version, captures=captures),
    )


def _refresh_run_surfaces(ai_root: Path, repo_root: Path, run_id: str) -> None:
    engine = _build_engine_from_stored_run(ai_root, repo_root, run_id)
    meta = RunStateManager(ai_root).load_run(run_id)
    workflow = str(meta.data.get("workflow", "")).strip() or "implement"
    store = ArtifactStore(Path(meta.run_dir), state_manager=engine.state_manager)
    engine._write_runtime_surfaces(store, workflow=workflow)  # noqa: SLF001 - shared CLI/runtime integration seam


def _capture_bridge_stage(
    ai_root: Path,
    repo_root: Path,
    *,
    run_id: str,
    stage: Literal["implement", "review"],
    source: str,
) -> dict[str, str]:
    meta, host_contract, bridge_config = _resolve_bridge_capture_run(ai_root, run_id)
    if meta.status is not RunStatus.blocked or meta.last_completed_stage != stage:
        raise AiwfError(
            f"Run {run_id} is not currently blocked at {stage}; current status={meta.status.value} "
            f"last_completed_stage={meta.last_completed_stage or '-'}"
        )

    client = _build_bridge_capture_client(host_contract, bridge_config)
    store = ArtifactStore(Path(meta.run_dir), state_manager=RunStateManager(ai_root))
    read_result = client.read_file(
        source,
        workspace=bridge_config.workspace,
        tab=bridge_config.tab,
        context_id=bridge_config.context_id,
    )
    calls = [_bridge_tool_call_from_read_result(read_result, step=f"capture_{stage}")]
    record_workspace = getattr(read_result, "workspace", None) or bridge_config.workspace
    record_context_id = getattr(read_result, "context_id", None) or bridge_config.context_id

    def refuse(summary: str) -> None:
        _upsert_bridge_capture_record(
            store,
            RpBridgeCaptureRecord(
                stage=stage,
                source=source,
                status="refused",
                workspace=record_workspace,
                context_id=record_context_id,
                summary=summary,
                calls=calls,
            ),
        )
        _refresh_run_surfaces(ai_root, repo_root, run_id)

    if not read_result.ok or read_result.content is None:
        message = read_result.error.message if read_result.error is not None else "RP bridge read_file failed"
        refuse(message)
        raise AiwfError(f"Bridge capture failed for run {run_id} at {stage}: {message}")

    response_artifact_name = "rp-agent-implement-response.md" if stage == "implement" else "rp-agent-review-response.md"
    try:
        if stage == "implement":
            normalized_response = normalize_implement_capture(read_result.content)
            store.write_text_artifact(response_artifact_name, normalized_response)
            summary = f"Captured RepoPrompt implement response into {response_artifact_name}"
            review_report_artifact = None
        else:
            existing_review_report = store.read_artifact("review-report.json")
            if not isinstance(existing_review_report, dict):
                raise AiwfError(f"Stored review-report.json for run {run_id} is invalid")
            linked_field = host_contract.review.linked_report_artifact_field
            linked_artifact_name = None
            if linked_field is not None:
                raw_linked_name = existing_review_report.get(linked_field)
                if isinstance(raw_linked_name, str) and raw_linked_name.strip():
                    linked_artifact_name = raw_linked_name.strip()
            normalized_review_report = normalize_review_capture(
                read_result.content,
                contract=host_contract.review,
                linked_artifact_name=linked_artifact_name,
                response_artifact_name=response_artifact_name,
                existing_report=existing_review_report,
            )
            store.write_text_artifact(response_artifact_name, read_result.content.strip() + "\n")
            store.write_review_report(normalized_review_report)
            summary = f"Captured RepoPrompt review response into {response_artifact_name} and normalized review-report.json"
            review_report_artifact = "review-report.json"
    except (AiwfError, RpBridgeNormalizationError) as exc:
        refuse(str(exc))
        raise AiwfError(f"Bridge capture refused for run {run_id} at {stage}: {exc}") from exc

    _upsert_bridge_capture_record(
        store,
        RpBridgeCaptureRecord(
            stage=stage,
            source=source,
            status="captured",
            workspace=record_workspace,
            context_id=record_context_id,
            response_artifact=response_artifact_name,
            review_report_artifact=review_report_artifact,
            summary=summary,
            calls=calls,
        ),
    )
    _refresh_run_surfaces(ai_root, repo_root, run_id)
    return {
        "response_artifact": response_artifact_name,
        "capture_artifact": "rp-bridge-capture.json",
        "review_report_artifact": review_report_artifact or "",
    }


def _print_run_guidance(ai_root: Path, run_id: str) -> None:
    try:
        diagnostics = _load_run_surface(ai_root, run_id, "run-diagnostics.json")
    except AiwfError:
        console.print(f"[yellow]inspect hint:[/yellow] uv run aiwf inspect {run_id} --ai-root {ai_root}")
        return

    status_reason = str(diagnostics.get("status_reason", "")).strip()
    if status_reason:
        console.print(f"reason={status_reason}")
    error_code = diagnostics.get("error_code")
    if isinstance(error_code, str) and error_code.strip():
        console.print(f"error_code={error_code}")

    next_actions = diagnostics.get("next_actions")
    if isinstance(next_actions, list):
        for action in next_actions[:2]:
            if isinstance(action, str) and action.strip():
                console.print(f"next={action.strip()}")

    console.print(f"diagnostics={_artifact_path(ai_root, run_id, 'run-diagnostics.json')}")
    console.print(f"provenance={_artifact_path(ai_root, run_id, 'run-provenance.json')}")
    console.print(f"inspect=uv run aiwf inspect {run_id} --ai-root {ai_root}")


def _list_run_artifact_names(ai_root: Path, run_id: str) -> set[str]:
    run_dir = ai_root / "runs" / run_id
    try:
        return {path.name for path in run_dir.iterdir() if path.is_file()}
    except OSError as exc:
        raise AiwfError(f"Unable to inspect artifacts for run {run_id}: {exc}") from exc


def _format_csv(values: tuple[str, ...] | list[str] | set[str]) -> str:
    flattened = sorted(value for value in values if value)
    return ",".join(flattened) if flattened else "-"


@dataclass(frozen=True)
class _RunRecord:
    run_id: str
    run_dir: Path
    status: RunStatus
    workflow: str
    adapter: str
    created_at: datetime
    updated_at: datetime
    last_completed_stage: str | None


def _extract_run_workflow(meta: RunMeta) -> str:
    workflow = str(meta.data.get("workflow", "")).strip()
    return workflow or "-"


def _extract_run_adapter(meta: RunMeta) -> str:
    host_contract = meta.data.get("host_contract")
    if isinstance(host_contract, Mapping):
        adapter = str(host_contract.get("adapter", "")).strip()
        if adapter:
            return adapter
    return "-"


def _enumerate_runs(ai_root: Path) -> list[_RunRecord]:
    runs_dir = ai_root / "runs"
    if not runs_dir.exists():
        return []
    if not runs_dir.is_dir():
        raise AiwfError("Run root is not a directory", path=runs_dir, stage="list_runs")

    state_manager = RunStateManager(ai_root)
    records: list[_RunRecord] = []
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name
        try:
            meta = state_manager.load_run(run_id)
        except AiwfError as exc:
            raise AiwfError(f"Unable to load run metadata for {run_id}", path=run_dir, stage="list_runs") from exc
        records.append(
            _RunRecord(
                run_id=meta.run_id,
                run_dir=run_dir,
                status=meta.status,
                workflow=_extract_run_workflow(meta),
                adapter=_extract_run_adapter(meta),
                created_at=meta.created_at,
                updated_at=meta.updated_at,
                last_completed_stage=meta.last_completed_stage,
            )
        )

    records.sort(key=lambda entry: (entry.created_at, entry.run_id), reverse=True)
    return records


def _parse_status_filter(raw: str | None, *, default: tuple[RunStatus, ...] = ()) -> set[RunStatus]:
    if raw is None:
        return set(default)
    tokens = [token.strip() for token in raw.split(",") if token.strip()]
    if not tokens:
        return set(default)

    statuses: set[RunStatus] = set()
    for token in tokens:
        try:
            statuses.add(RunStatus(token))
        except ValueError as exc:
            allowed = ", ".join(status.value for status in RunStatus)
            raise AiwfError(f"Unknown run status '{token}'. Allowed values: {allowed}") from exc
    return statuses


def _parse_value_filter(raw: str | None) -> set[str]:
    if raw is None:
        return set()
    return {token.strip() for token in raw.split(",") if token.strip()}


def _filter_run_records(
    records: list[_RunRecord],
    *,
    statuses: set[RunStatus],
    workflows: set[str],
    adapters: set[str],
) -> list[_RunRecord]:
    filtered = records
    if statuses:
        filtered = [record for record in filtered if record.status in statuses]
    if workflows:
        filtered = [record for record in filtered if record.workflow in workflows]
    if adapters:
        filtered = [record for record in filtered if record.adapter in adapters]
    return filtered


def _serialize_run_record(record: _RunRecord) -> dict[str, Any]:
    return {
        "run_id": record.run_id,
        "status": record.status.value,
        "workflow": record.workflow,
        "adapter": record.adapter,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "last_completed_stage": record.last_completed_stage,
    }


def _parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _extract_run_mode(meta: RunMeta) -> str | None:
    host_contract = meta.data.get("host_contract")
    if isinstance(host_contract, Mapping):
        mode = str(host_contract.get("mode", "")).strip()
        if mode:
            return mode
    return None


def _run_field_values(meta: RunMeta) -> dict[str, Any]:
    return {
        "workflow": _extract_run_workflow(meta),
        "status": meta.status.value,
        "last_completed_stage": meta.last_completed_stage,
        "error_code": meta.error_code.value if meta.error_code is not None else None,
        "error": meta.error,
        "adapter": _extract_run_adapter(meta),
        "mode": _extract_run_mode(meta),
    }


def _stored_diagnostics_field_values(diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    host = diagnostics.get("host")
    return {
        "workflow": diagnostics.get("workflow"),
        "status": diagnostics.get("status"),
        "last_completed_stage": diagnostics.get("last_completed_stage"),
        "error_code": diagnostics.get("error_code"),
        "error": diagnostics.get("error"),
        "adapter": host.get("adapter") if isinstance(host, Mapping) else None,
        "mode": host.get("mode") if isinstance(host, Mapping) else None,
    }


def _build_field_changes(
    from_values: Mapping[str, Any],
    to_values: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    changes: dict[str, dict[str, Any]] = {}
    for field in _DIFF_FIELDS:
        from_value = from_values.get(field)
        to_value = to_values.get(field)
        if from_value != to_value:
            changes[field] = {"from": from_value, "to": to_value}
    return changes


def _provenance_artifact_map(provenance: object) -> dict[str, dict[str, Any]]:
    artifact_map: dict[str, dict[str, Any]] = {}
    if not isinstance(provenance, Mapping):
        return artifact_map
    artifact_index = provenance.get("artifact_index")
    if not isinstance(artifact_index, list):
        return artifact_map
    for artifact in artifact_index:
        if not isinstance(artifact, Mapping):
            continue
        name = str(artifact.get("name", "")).strip()
        if not name:
            continue
        artifact_map[name] = {
            "name": name,
            "path": artifact.get("path"),
            "stage": artifact.get("stage"),
            "category": artifact.get("category"),
        }
    return artifact_map


def _collect_live_artifacts(ai_root: Path, run_id: str, provenance: object) -> dict[str, dict[str, Any]]:
    run_dir = ai_root / "runs" / run_id
    artifact_refs = _provenance_artifact_map(provenance)
    try:
        paths = sorted(path for path in run_dir.iterdir() if path.is_file() and path.name not in _INTERNAL_RUN_FILES)
    except OSError as exc:
        raise AiwfError(f"Unable to inspect artifacts for run {run_id}: {exc}") from exc

    artifacts: dict[str, dict[str, Any]] = {}
    for path in paths:
        try:
            stats = path.stat()
        except OSError as exc:
            raise AiwfError(f"Unable to inspect artifact {path.name} for run {run_id}: {exc}") from exc
        artifact_ref = artifact_refs.get(path.name, {})
        artifacts[path.name] = {
            "name": path.name,
            "path": str(path),
            "size_bytes": stats.st_size,
            "modified_at": datetime.fromtimestamp(stats.st_mtime, tz=timezone.utc).isoformat(),
            "stage": artifact_ref.get("stage"),
            "category": artifact_ref.get("category"),
        }
    return artifacts


def _baseline_artifact_names(diagnostics: Mapping[str, Any], provenance: object) -> set[str]:
    artifact_names = {
        name
        for name in _provenance_artifact_map(provenance)
        if name and name not in _INTERNAL_RUN_FILES
    }
    if artifact_names:
        return artifact_names

    key_artifacts = diagnostics.get("key_artifacts")
    if not isinstance(key_artifacts, list):
        return set()
    names: set[str] = set()
    for artifact in key_artifacts:
        if not isinstance(artifact, Mapping):
            continue
        name = str(artifact.get("name", "")).strip()
        if name and name not in _INTERNAL_RUN_FILES:
            names.add(name)
    return names


def _removed_artifact_entry(ai_root: Path, run_id: str, artifact_name: str, provenance: object) -> dict[str, Any]:
    artifact_ref = _provenance_artifact_map(provenance).get(artifact_name, {})
    return {
        "name": artifact_name,
        "path": artifact_ref.get("path") or str(_artifact_path(ai_root, run_id, artifact_name)),
        "stage": artifact_ref.get("stage"),
        "category": artifact_ref.get("category"),
        "size_bytes": None,
        "modified_at": None,
    }


def _build_current_diff(ai_root: Path, run_id: str, diagnostics: Mapping[str, Any], provenance: object) -> dict[str, Any]:
    state_manager = RunStateManager(ai_root)
    meta = state_manager.load_run(run_id)
    live_artifacts = _collect_live_artifacts(ai_root, run_id, provenance)
    live_artifact_names = set(live_artifacts)
    baseline_artifact_names = _baseline_artifact_names(diagnostics, provenance)
    baseline_generated_at = _parse_iso_datetime(diagnostics.get("generated_at"))

    modified: list[dict[str, Any]] = []
    if baseline_generated_at is not None:
        for artifact_name in sorted(live_artifact_names & baseline_artifact_names):
            modified_at = _parse_iso_datetime(live_artifacts[artifact_name].get("modified_at"))
            if modified_at is not None and modified_at > baseline_generated_at:
                modified.append(dict(live_artifacts[artifact_name]))

    added = [dict(live_artifacts[name]) for name in sorted(live_artifact_names - baseline_artifact_names)]
    removed = [_removed_artifact_entry(ai_root, run_id, name, provenance) for name in sorted(baseline_artifact_names - live_artifact_names)]
    field_changes = _build_field_changes(_stored_diagnostics_field_values(diagnostics), _run_field_values(meta))

    return {
        "mode": "current",
        "from_label": "stored",
        "to_label": "current",
        "baseline_generated_at": diagnostics.get("generated_at"),
        "field_changes": field_changes,
        "artifact_changes": {
            "added": added,
            "removed": removed,
            "modified": modified,
        },
        "has_changes": bool(field_changes or added or removed or modified),
    }


def _build_run_to_run_diff(ai_root: Path, run_id: str, other_run_id: str, provenance: object) -> dict[str, Any]:
    state_manager = RunStateManager(ai_root)
    subject_meta = state_manager.load_run(run_id)
    other_meta = state_manager.load_run(other_run_id)
    try:
        other_payload = _build_inspection_payload(ai_root, other_run_id)
    except AiwfError as exc:
        raise AiwfError(f"Cannot diff against run {other_run_id}: {exc}") from exc
    other_provenance = other_payload.get("provenance")

    subject_artifacts = _collect_live_artifacts(ai_root, run_id, provenance)
    other_artifacts = _collect_live_artifacts(ai_root, other_run_id, other_provenance)
    subject_names = set(subject_artifacts)
    other_names = set(other_artifacts)

    added = [dict(other_artifacts[name]) for name in sorted(other_names - subject_names)]
    removed = [dict(subject_artifacts[name]) for name in sorted(subject_names - other_names)]
    field_changes = _build_field_changes(_run_field_values(subject_meta), _run_field_values(other_meta))

    return {
        "mode": "run_to_run",
        "from_label": run_id,
        "to_label": other_run_id,
        "compare_run_id": other_run_id,
        "field_changes": field_changes,
        "artifact_changes": {
            "added": added,
            "removed": removed,
            "modified": [],
        },
        "has_changes": bool(field_changes or added or removed),
    }


def _build_inspection_payload(
    ai_root: Path,
    run_id: str,
    *,
    diff: bool = False,
    diff_run: str | None = None,
    bridge_probe: bool = False,
) -> dict[str, Any]:
    meta = RunStateManager(ai_root).load_run(run_id)
    diagnostics = _load_run_surface(ai_root, run_id, "run-diagnostics.json")
    provenance = _load_optional_run_surface(ai_root, run_id, "run-provenance.json")
    review_report = _load_optional_run_surface(ai_root, run_id, "review-report.json")
    bridge_seeding = _load_optional_run_surface(ai_root, run_id, "rp-bridge-seeding.json")
    bridge_capture = _load_optional_run_surface(ai_root, run_id, "rp-bridge-capture.json")

    payload: dict[str, Any] = {
        "ok": True,
        "run_id": run_id,
        "diagnostics": diagnostics,
        "provenance": provenance,
        "review_report": review_report,
        "bridge_seeding": bridge_seeding,
        "bridge_capture": bridge_capture,
        "rp_bridge": meta.data.get("rp_bridge") if "rp_bridge" in meta.data else None,
        "artifacts": {
            "diagnostics": str(_artifact_path(ai_root, run_id, "run-diagnostics.json")),
            "provenance": str(_artifact_path(ai_root, run_id, "run-provenance.json")),
            "review_report": str(_artifact_path(ai_root, run_id, "review-report.json")) if review_report is not None else None,
            "bridge_seeding": str(_artifact_path(ai_root, run_id, "rp-bridge-seeding.json")) if bridge_seeding is not None else None,
            "bridge_capture": str(_artifact_path(ai_root, run_id, "rp-bridge-capture.json")) if bridge_capture is not None else None,
        },
    }

    try:
        resolved_contract = _resolve_run_execution(ai_root, run_id)
    except AiwfError as exc:
        payload["host_contract"] = None
        payload["host_contract_warning"] = str(exc)
        payload["review_contract"] = None
        payload["review_boundary"] = None
        payload["review_evidence"] = None
    else:
        artifact_names = _list_run_artifact_names(ai_root, run_id)
        review_contract = resolved_contract.review
        review_boundary = assess_review_boundary(resolved_contract, available_artifact_names=artifact_names)
        review_evidence = assess_review_evidence(
            resolved_contract,
            review_report if isinstance(review_report, Mapping) else None,
            available_artifact_names=artifact_names,
        )

        payload["host_contract"] = resolved_contract.to_metadata()
        payload["review_contract"] = {
            "required_run_artifacts": list(review_contract.required_run_artifacts),
            "required_report_fields": list(review_contract_fields(review_contract)),
            "expected_mode": review_contract.expected_report_mode,
            "linked_field": review_contract.linked_report_artifact_field,
        }
        payload["review_boundary"] = {
            "ready": review_boundary.ready,
            "missing_required_artifacts": list(review_boundary.missing_required_artifacts),
        }
        payload["review_evidence"] = {
            "status": review_evidence.status,
            "mode": review_evidence.mode,
            "missing_report_fields": list(review_evidence.missing_report_fields),
            "missing_linked_artifacts": list(review_evidence.missing_linked_artifacts),
            "linked_artifacts": list(review_evidence.linked_artifacts),
            "mode_mismatch": review_evidence.mode_mismatch,
        }
        if bridge_probe:
            payload["bridge_probe"] = _build_bridge_probe_payload(resolved_contract, meta.data)
    if diff_run is not None:
        payload["diff"] = _build_run_to_run_diff(ai_root, run_id, diff_run, provenance)
    elif diff:
        payload["diff"] = _build_current_diff(ai_root, run_id, diagnostics, provenance)
    elif bridge_probe and "bridge_probe" not in payload:
        payload["bridge_probe"] = {
            "available": False,
            "path": None,
            "command": [],
            "tools": [],
            "error": {
                "code": "BRIDGE_PROBE_UNAVAILABLE",
                "message": "Bridge probe could not be run because the stored host contract was unavailable.",
                "retriable": False,
                "detail": {},
            },
        }
    return payload


def _bridge_probe_payload_from_result(result: RpBridgeProbeResult) -> dict[str, Any]:
    return {
        "available": result.available,
        "path": result.path,
        "command": list(result.command),
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "metadata": tool.metadata,
            }
            for tool in result.tools
        ],
        "error": (
            {
                "code": result.error.code,
                "message": result.error.message,
                "retriable": result.error.retriable,
                "detail": result.error.detail,
            }
            if result.error is not None
            else None
        ),
    }


def _build_bridge_probe_payload(contract: HostContract, run_data: Mapping[str, Any]) -> dict[str, Any]:
    if contract.adapter != "rp" or not contract.bridge.enabled:
        return {
            "available": False,
            "path": None,
            "command": [],
            "tools": [],
            "error": {
                "code": "BRIDGE_UNAVAILABLE",
                "message": "Run host contract does not expose an RP bridge probe target.",
                "retriable": False,
                "detail": {},
            },
        }
    client = RpCliBridgeClient.from_command_candidates(contract.bridge.command_candidates, timeout_seconds=5)
    if client is None:
        candidates = [candidate for candidate in contract.bridge.command_candidates if candidate]
        return {
            "available": False,
            "path": None,
            "command": candidates,
            "tools": [],
            "error": {
                "code": "NOT_INSTALLED",
                "message": (
                    "No RP bridge command candidate was found on PATH for this run "
                    f"({', '.join(candidates) if candidates else '-'})"
                ),
                "retriable": False,
                "detail": {},
            },
        }
    del run_data
    return _bridge_probe_payload_from_result(client.probe_available())


def _format_diff_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _print_diff_artifact(kind: str, artifact: Mapping[str, Any]) -> None:
    name = str(artifact.get("name", "")).strip() or "-"
    stage = artifact.get("stage")
    category = artifact.get("category")
    stage_label = stage.strip() if isinstance(stage, str) and stage.strip() else "-"
    category_label = category.strip() if isinstance(category, str) and category.strip() else "-"
    details = [f"[{stage_label}/{category_label}] {name}"]
    size_bytes = artifact.get("size_bytes")
    if isinstance(size_bytes, int):
        details.append(f"size_bytes={size_bytes}")
    modified_at = artifact.get("modified_at")
    if isinstance(modified_at, str) and modified_at.strip():
        details.append(f"modified_at={modified_at}")
    console.print(f"- {kind} {' '.join(details)}")


def _print_inspection_diff(payload: Mapping[str, Any]) -> None:
    diff = payload.get("diff")
    if not isinstance(diff, Mapping):
        return

    mode = str(diff.get("mode", "")).strip()
    if mode == "run_to_run":
        console.print(f"diff=run_to_run compare_run={diff.get('to_label') or '-'}")
    else:
        console.print(f"diff={'changes_detected' if diff.get('has_changes') else 'no_changes'} baseline_generated_at={diff.get('baseline_generated_at') or '-'}")

    field_changes = diff.get("field_changes")
    if isinstance(field_changes, Mapping) and field_changes:
        console.print("diff_field_changes:")
        for field in _DIFF_FIELDS:
            change = field_changes.get(field)
            if not isinstance(change, Mapping):
                continue
            console.print(
                f"- {field}: {_format_diff_value(change.get('from'))} -> {_format_diff_value(change.get('to'))}"
            )

    artifact_changes = diff.get("artifact_changes")
    if not isinstance(artifact_changes, Mapping):
        return

    added = artifact_changes.get("added")
    removed = artifact_changes.get("removed")
    modified = artifact_changes.get("modified")
    if any(isinstance(items, list) and items for items in (added, removed, modified)):
        console.print("diff_artifact_changes:")
    if isinstance(added, list):
        for artifact in added:
            if isinstance(artifact, Mapping):
                _print_diff_artifact("added", artifact)
    if isinstance(removed, list):
        for artifact in removed:
            if isinstance(artifact, Mapping):
                _print_diff_artifact("removed", artifact)
    if isinstance(modified, list):
        for artifact in modified:
            if isinstance(artifact, Mapping):
                _print_diff_artifact("modified", artifact)


def _print_inspection(
    ai_root: Path,
    run_id: str,
    *,
    verbose: bool = False,
    diff: bool = False,
    diff_run: str | None = None,
    bridge_probe: bool = False,
) -> None:
    payload = _build_inspection_payload(ai_root, run_id, diff=diff, diff_run=diff_run, bridge_probe=bridge_probe)
    diagnostics = payload["diagnostics"]
    provenance = payload["provenance"]

    workflow = str(diagnostics.get("workflow", "")).strip()
    status = str(diagnostics.get("status", "")).strip()
    last_completed_stage = diagnostics.get("last_completed_stage")
    console.print(
        f"run_id={run_id} workflow={workflow} status={status} "
        f"last_completed_stage={last_completed_stage or '-'}"
    )

    status_reason = str(diagnostics.get("status_reason", "")).strip()
    if status_reason:
        console.print(f"reason={status_reason}")
    error_code = diagnostics.get("error_code")
    if isinstance(error_code, str) and error_code.strip():
        console.print(f"error_code={error_code}")

    resolved_contract = payload.get("host_contract")
    if isinstance(resolved_contract, dict):
        capabilities = resolved_contract.get("capabilities")
        console.print(
            "host_contract="
            f"adapter={resolved_contract.get('adapter', '-')} "
            f"mode={resolved_contract.get('mode', '-')} "
            "supports_auto_execution="
            f"{capabilities.get('supports_auto_execution') if isinstance(capabilities, dict) else '-'} "
            "requires_explicit_review_handoff="
            f"{capabilities.get('requires_explicit_review_handoff') if isinstance(capabilities, dict) else '-'}"
        )
        review_contract = payload.get("review_contract")
        if isinstance(review_contract, dict):
            console.print(
                "review_contract="
                f"required_run_artifacts={_format_csv(review_contract.get('required_run_artifacts', []))} "
                f"required_report_fields={_format_csv(review_contract.get('required_report_fields', []))} "
                f"expected_mode={review_contract.get('expected_mode') or '-'} "
                f"linked_field={review_contract.get('linked_field') or '-'}"
            )

        review_boundary = payload.get("review_boundary")
        if isinstance(review_boundary, dict):
            console.print(
                "review_boundary="
                f"{'ready' if review_boundary.get('ready') else 'waiting'} "
                f"missing_required_artifacts={_format_csv(review_boundary.get('missing_required_artifacts', []))}"
            )

        review_evidence = payload.get("review_evidence")
        if isinstance(review_evidence, dict):
            console.print(
                "review_evidence="
                f"{review_evidence.get('status') or '-'} "
                f"mode={review_evidence.get('mode') or '-'} "
                f"missing_report_fields={_format_csv(review_evidence.get('missing_report_fields', []))} "
                f"missing_linked_artifacts={_format_csv(review_evidence.get('missing_linked_artifacts', []))}"
            )
            if review_evidence.get("mode_mismatch"):
                console.print(f"review_evidence_mode_mismatch={review_evidence['mode_mismatch']}")
            linked_artifacts = review_evidence.get("linked_artifacts")
            if isinstance(linked_artifacts, list) and linked_artifacts:
                console.print(f"review_linked_artifacts={_format_csv(linked_artifacts)}")
    else:
        warning = payload.get("host_contract_warning")
        if warning:
            console.print(f"host_contract_warning={warning}")
        host = diagnostics.get("host")
        if isinstance(host, dict):
            adapter = str(host.get("adapter", "")).strip()
            mode = str(host.get("mode", "")).strip()
            supports_auto = host.get("supports_auto_execution")
            explicit_review = host.get("requires_explicit_review_handoff")
            console.print(
                "host="
                f"adapter={adapter or '-'} "
                f"mode={mode or '-'} "
                f"supports_auto_execution={supports_auto} "
                f"requires_explicit_review_handoff={explicit_review}"
            )

    rp_bridge = payload.get("rp_bridge")
    if isinstance(rp_bridge, Mapping):
        console.print(
            "bridge="
            f"mode={rp_bridge.get('mode') or '-'} "
            f"workspace={rp_bridge.get('workspace') or '-'} "
            f"tab={rp_bridge.get('tab') or '-'} "
            f"context_id={rp_bridge.get('context_id') or '-'} "
            f"agent_role={rp_bridge.get('agent_role') or '-'}"
        )
    diagnostics_bridge = diagnostics.get("bridge")
    if isinstance(diagnostics_bridge, Mapping):
        summary = str(diagnostics_bridge.get("summary", "")).strip()
        if summary:
            console.print(f"bridge_summary={summary}")
        handoff_artifacts = diagnostics_bridge.get("handoff_artifacts")
        if isinstance(handoff_artifacts, list) and handoff_artifacts:
            console.print(f"bridge_handoff_artifacts={_format_csv(handoff_artifacts)}")
        seeding_artifact = diagnostics_bridge.get("seeding_artifact")
        seeding_status = diagnostics_bridge.get("seeding_status")
        seeding_summary = diagnostics_bridge.get("seeding_summary")
        if isinstance(seeding_artifact, str) and seeding_artifact.strip():
            console.print(f"bridge_seeding_artifact={seeding_artifact}")
        if isinstance(seeding_status, str) and seeding_status.strip():
            console.print(f"bridge_seeding_status={seeding_status}")
        if isinstance(seeding_summary, str) and seeding_summary.strip():
            console.print(f"bridge_seeding_summary={seeding_summary}")
    bridge_probe_payload = payload.get("bridge_probe")
    if isinstance(bridge_probe_payload, Mapping):
        if bridge_probe_payload.get("available"):
            console.print(f"bridge_probe=available path={bridge_probe_payload.get('path') or '-'}")
            tools = bridge_probe_payload.get("tools")
            if isinstance(tools, list):
                tool_names = [
                    str(tool.get("name", "")).strip()
                    for tool in tools
                    if isinstance(tool, Mapping) and str(tool.get("name", "")).strip()
                ]
                console.print(f"bridge_probe_tools={_format_csv(tool_names)}")
        else:
            error = bridge_probe_payload.get("error")
            if isinstance(error, Mapping):
                console.print(
                    "bridge_probe="
                    f"{error.get('code') or 'UNKNOWN'}:{error.get('message') or 'bridge probe failed'}"
                )
    bridge_capture = payload.get("bridge_capture")
    if isinstance(bridge_capture, Mapping):
        captures = bridge_capture.get("captures")
        if isinstance(captures, list) and captures:
            capture_labels: list[str] = []
            for capture in captures:
                if not isinstance(capture, Mapping):
                    continue
                stage_name = str(capture.get("stage", "")).strip()
                status_name = str(capture.get("status", "")).strip()
                if stage_name and status_name:
                    capture_labels.append(f"{stage_name}:{status_name}")
            if capture_labels:
                console.print(f"bridge_capture_status={_format_csv(capture_labels)}")

    _print_inspection_diff(payload)

    next_actions = diagnostics.get("next_actions")
    if isinstance(next_actions, list) and next_actions:
        console.print("next_actions:")
        for action in next_actions:
            if isinstance(action, str) and action.strip():
                console.print(f"- {action.strip()}")

    if isinstance(provenance, dict):
        gate_evidence = provenance.get("gate_evidence")
        if isinstance(gate_evidence, dict):
            report = gate_evidence.get("report")
            gate_set = gate_evidence.get("gate_set")
            passed = gate_evidence.get("passed")
            if isinstance(report, dict) and isinstance(report.get("path"), str):
                console.print(
                    f"gate_evidence=gate_set={gate_set or '-'} passed={passed} report={report['path']}"
                )

        review_evidence_ref = provenance.get("review_evidence")
        if isinstance(review_evidence_ref, dict):
            report = review_evidence_ref.get("report")
            mode_value = review_evidence_ref.get("mode")
            linked_artifacts = review_evidence_ref.get("linked_artifacts")
            if isinstance(report, dict) and isinstance(report.get("path"), str) and verbose:
                console.print(f"review_report={report['path']} mode={mode_value or '-'}")
            if isinstance(linked_artifacts, list) and linked_artifacts and verbose:
                console.print("review_links:")
                for artifact in linked_artifacts:
                    if isinstance(artifact, dict) and isinstance(artifact.get("path"), str):
                        console.print(f"- {artifact['path']}")

        artifact_index = provenance.get("artifact_index")
        if verbose and isinstance(artifact_index, list) and artifact_index:
            console.print("artifacts:")
            for artifact in artifact_index:
                if not isinstance(artifact, dict):
                    continue
                name = str(artifact.get("name", "")).strip()
                raw_stage = artifact.get("stage")
                stage_label = raw_stage.strip() if isinstance(raw_stage, str) and raw_stage.strip() else "-"
                category = str(artifact.get("category", "")).strip() or "-"
                path = str(artifact.get("path", "")).strip()
                if name and path:
                    console.print(f"- [{stage_label}/{category}] {name} -> {path}")
    else:
        console.print(
            f"provenance_warning=Unable to read run-provenance.json for run {run_id}: artifact unavailable or invalid"
        )

    artifacts = payload["artifacts"]
    console.print(f"diagnostics={artifacts['diagnostics']}")
    console.print(f"provenance={artifacts['provenance']}")
    if artifacts.get("bridge_seeding"):
        console.print(f"bridge_seeding={artifacts['bridge_seeding']}")
    if artifacts.get("bridge_capture"):
        console.print(f"bridge_capture={artifacts['bridge_capture']}")


@run_app.command("plan")
def run_plan(
    task: Annotated[Path, typer.Option("--task", exists=True, dir_okay=False, readable=True)],
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path("."),
    adapter: Annotated[AdapterName, typer.Option("--adapter", help=_ADAPTER_OPTION_HELP)] = "claude",
    auto: Annotated[bool, typer.Option("--auto", help=_AUTO_OPTION_HELP)] = False,
    bridge: Annotated[bool, typer.Option("--bridge", help=_BRIDGE_OPTION_HELP)] = False,
    bridge_mode: Annotated[str | None, typer.Option("--bridge-mode", help="Experimental RP bridge mode override. Only manual-assist is supported in this slice.")] = None,
    bridge_workspace: Annotated[str | None, typer.Option("--bridge-workspace", help="RepoPrompt workspace identifier for bridge groundwork.")] = None,
    bridge_tab: Annotated[str | None, typer.Option("--bridge-tab", help="RepoPrompt tab/window identifier for bridge groundwork.")] = None,
    bridge_context_id: Annotated[str | None, typer.Option("--bridge-context-id", help="Pre-bound RepoPrompt context id for bridge groundwork.")] = None,
    bridge_agent_role: Annotated[str | None, typer.Option("--bridge-agent-role", help="Operator-defined RepoPrompt agent role label.")] = None,
    bridge_timeout: Annotated[int | None, typer.Option("--bridge-timeout", help="Reserved bridge timeout hint for future slices.")] = None,
    bridge_export_transcript: Annotated[bool, typer.Option("--bridge-export-transcript", help="Reserved bridge transcript-export hint for future slices.")] = False,
) -> None:
    """Run the plan workflow."""
    engine = _build_engine_or_exit(
        "plan",
        lambda: _build_engine(
            ai_root,
            repo_root,
            adapter_name=adapter,
            auto=auto,
            bridge_config=_resolve_bridge_config(
                adapter,
                auto,
                bridge=bridge,
                bridge_mode=bridge_mode,
                bridge_workspace=bridge_workspace,
                bridge_tab=bridge_tab,
                bridge_context_id=bridge_context_id,
                bridge_agent_role=bridge_agent_role,
                bridge_timeout=bridge_timeout,
                bridge_export_transcript=bridge_export_transcript,
            ),
        ),
    )
    _execute_command("plan", ai_root, lambda: engine.run_plan(task))


@run_app.command("implement")
def run_implement(
    task: Annotated[Path, typer.Option("--task", exists=True, dir_okay=False, readable=True)],
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path("."),
    adapter: Annotated[AdapterName, typer.Option("--adapter", help=_ADAPTER_OPTION_HELP)] = "claude",
    auto: Annotated[bool, typer.Option("--auto", help=_AUTO_OPTION_HELP)] = False,
    bridge: Annotated[bool, typer.Option("--bridge", help=_BRIDGE_OPTION_HELP)] = False,
    bridge_mode: Annotated[str | None, typer.Option("--bridge-mode", help="Experimental RP bridge mode override. Only manual-assist is supported in this slice.")] = None,
    bridge_workspace: Annotated[str | None, typer.Option("--bridge-workspace", help="RepoPrompt workspace identifier for bridge groundwork.")] = None,
    bridge_tab: Annotated[str | None, typer.Option("--bridge-tab", help="RepoPrompt tab/window identifier for bridge groundwork.")] = None,
    bridge_context_id: Annotated[str | None, typer.Option("--bridge-context-id", help="Pre-bound RepoPrompt context id for bridge groundwork.")] = None,
    bridge_agent_role: Annotated[str | None, typer.Option("--bridge-agent-role", help="Operator-defined RepoPrompt agent role label.")] = None,
    bridge_timeout: Annotated[int | None, typer.Option("--bridge-timeout", help="Reserved bridge timeout hint for future slices.")] = None,
    bridge_export_transcript: Annotated[bool, typer.Option("--bridge-export-transcript", help="Reserved bridge transcript-export hint for future slices.")] = False,
) -> None:
    """Run the implement workflow."""
    engine = _build_engine_or_exit(
        "implement",
        lambda: _build_engine(
            ai_root,
            repo_root,
            adapter_name=adapter,
            auto=auto,
            bridge_config=_resolve_bridge_config(
                adapter,
                auto,
                bridge=bridge,
                bridge_mode=bridge_mode,
                bridge_workspace=bridge_workspace,
                bridge_tab=bridge_tab,
                bridge_context_id=bridge_context_id,
                bridge_agent_role=bridge_agent_role,
                bridge_timeout=bridge_timeout,
                bridge_export_transcript=bridge_export_transcript,
            ),
        ),
    )
    _execute_command("implement", ai_root, lambda: engine.run_implement(task))


@run_app.command("review")
def run_review(
    run_id: Annotated[str, typer.Option("--run-id", help="Existing run to review.")],
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path("."),
) -> None:
    """Run review against an existing run using its stored host contract."""
    engine = _build_engine_or_exit(
        "review",
        lambda: _build_engine_from_stored_run(ai_root, repo_root, run_id),
    )
    _execute_command("review", ai_root, lambda: engine.run_review(run_id))


@app.command("resume")
def resume(
    run_id: str,
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path("."),
) -> None:
    """Resume a failed, blocked, or needs-review workflow run with its stored host contract."""
    engine = _build_engine_or_exit(
        "resume",
        lambda: _build_engine_from_stored_run(ai_root, repo_root, run_id),
    )
    _execute_command("resume", ai_root, lambda: engine.resume(run_id))


@bridge_app.command("capture")
def rp_bridge_capture(
    run_id: str,
    stage: Annotated[
        Literal["implement", "review"],
        typer.Option("--stage", help="Bridge stage whose RepoPrompt-side output should be captured."),
    ],
    source: Annotated[
        str,
        typer.Option("--source", help="RepoPrompt-side source identifier/path consumed through bridge read_file."),
    ],
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path("."),
) -> None:
    """Capture RepoPrompt-side manual-assist output back into aiwf artifacts."""
    try:
        result = _capture_bridge_stage(ai_root, repo_root, run_id=run_id, stage=stage, source=source)
    except AiwfError as exc:
        console.print(f"[red]rp bridge capture failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        "[green]rp bridge capture completed[/green] "
        f"run_id={run_id} stage={stage} response={result['response_artifact']} capture={result['capture_artifact']}"
    )
    if result["review_report_artifact"]:
        console.print(f"review_report={result['review_report_artifact']}")


@app.command("inspect")
def inspect_run(
    run_id: str,
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    verbose: Annotated[bool, typer.Option("--verbose", help="Show artifact index and detailed provenance links.")] = False,
    diff: Annotated[bool, typer.Option("--diff", help="Show delta versus the current live run metadata/artifact state.")] = False,
    diff_run: Annotated[str | None, typer.Option("--diff-run", help="Compare this run to another run's status/artifact metadata.")] = None,
    bridge_probe: Annotated[
        bool,
        typer.Option("--bridge-probe", help="Run a read-only RP bridge tool probe for this run's stored bridge command candidates."),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Render inspect output as JSON.")] = False,
) -> None:
    """Inspect diagnostics and provenance for an existing run."""
    try:
        if diff and diff_run is not None:
            raise AiwfError("Cannot use --diff and --diff-run together")
        if json_output:
            typer.echo(
                json.dumps(
                    _build_inspection_payload(ai_root, run_id, diff=diff, diff_run=diff_run, bridge_probe=bridge_probe),
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            _print_inspection(ai_root, run_id, verbose=verbose, diff=diff, diff_run=diff_run, bridge_probe=bridge_probe)
    except AiwfError as exc:
        if json_output:
            typer.echo(json.dumps({"ok": False, "run_id": run_id, "error": str(exc)}, indent=2, ensure_ascii=False))
        else:
            console.print(f"[red]inspect failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command("list")
def list_runs(
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    status: Annotated[
        str | None,
        typer.Option("--status", help="Comma-separated status filter.")
    ] = None,
    workflow: Annotated[
        str | None,
        typer.Option("--workflow", help="Comma-separated workflow filter.")
    ] = None,
    adapter: Annotated[
        str | None,
        typer.Option("--adapter", help="Comma-separated adapter filter.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, help="Maximum number of runs to show.")] = 20,
    json_output: Annotated[bool, typer.Option("--json", help="Render run list as JSON.")] = False,
) -> None:
    """List workflow runs from `.ai/runs/` with optional filters."""
    try:
        records = _enumerate_runs(ai_root)
        filtered = _filter_run_records(
            records,
            statuses=_parse_status_filter(status),
            workflows=_parse_value_filter(workflow),
            adapters=_parse_value_filter(adapter),
        )
        filtered = filtered[:limit]
        payload = [_serialize_run_record(record) for record in filtered]
        if json_output:
            typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))
            return
        if not payload:
            typer.echo("No runs found.")
            return
        typer.echo("run_id\tstatus\tworkflow\tadapter\tcreated_at\tlast_completed_stage")
        for record in payload:
            typer.echo(
                "\t".join(
                    [
                        str(record["run_id"]),
                        str(record["status"]),
                        str(record["workflow"]),
                        str(record["adapter"]),
                        str(record["created_at"]),
                        str(record["last_completed_stage"] or "-"),
                    ]
                )
            )
    except AiwfError as exc:
        if json_output:
            typer.echo(json.dumps({"ok": False, "error": str(exc)}, indent=2, ensure_ascii=False))
        else:
            console.print(f"[red]list failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command("clean")
def clean_runs(
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    keep: Annotated[int, typer.Option("--keep", min=0, help="Keep N most recent runs per workflow.")] = 10,
    status: Annotated[
        str | None,
        typer.Option(
            "--status",
            help="Comma-separated statuses eligible for cleanup. Defaults to passed,canceled.",
        ),
    ] = None,
    workflow: Annotated[
        str | None,
        typer.Option("--workflow", help="Comma-separated workflow filter.")
    ] = None,
    adapter: Annotated[
        str | None,
        typer.Option("--adapter", help="Comma-separated adapter filter.")
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview runs that would be deleted.")] = False,
) -> None:
    """Delete old run directories using safe defaults."""
    try:
        records = _enumerate_runs(ai_root)
        filtered = _filter_run_records(
            records,
            statuses=_parse_status_filter(status, default=(RunStatus.passed, RunStatus.canceled)),
            workflows=_parse_value_filter(workflow),
            adapters=_parse_value_filter(adapter),
        )

        grouped: dict[str, list[_RunRecord]] = {}
        for record in filtered:
            grouped.setdefault(record.workflow, []).append(record)

        deletable: list[_RunRecord] = []
        for workflow_records in grouped.values():
            workflow_records.sort(key=lambda entry: (entry.created_at, entry.run_id), reverse=True)
            deletable.extend(workflow_records[keep:])

        deletable.sort(key=lambda entry: (entry.created_at, entry.run_id), reverse=True)

        if not deletable:
            console.print("No runs matched cleanup criteria.")
            return

        action_prefix = "Would delete" if dry_run else "Deleting"
        console.print(f"{action_prefix} {len(deletable)} run(s).")
        for record in deletable:
            console.print(
                f"- {record.run_id} status={record.status.value} workflow={record.workflow} "
                f"adapter={record.adapter}"
            )

        if dry_run:
            return

        for record in deletable:
            try:
                shutil.rmtree(record.run_dir)
            except OSError as exc:
                raise AiwfError("Failed to delete run directory", path=record.run_dir, stage="clean_runs") from exc

        console.print(f"Deleted {len(deletable)} run(s).")
    except AiwfError as exc:
        console.print(f"[red]clean failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc


@contracts_app.command("lint")
def contract_lint() -> None:
    """Lint built-in adapter host/review contracts."""
    results = lint_contract_registry(ADAPTER_SPECS)
    failed = False
    for result in results:
        status = "[green]ok[/green]" if result.ok else "[red]fail[/red]"
        console.print(f"{status} {result.subject}")
        if result.ok:
            continue
        failed = True
        for issue in result.issues:
            console.print(f"  - {issue.code}: {issue.message}")
    if failed:
        raise typer.Exit(code=1)
    console.print(f"[green]contract lint completed[/green] contracts={len(results)} adapters={len(ADAPTER_SPECS)}")


@conformance_app.command("rp")
def conformance_rp_command(
    rp_command: Annotated[
        str,
        typer.Option(
            "--rp-command",
            help=(
                "Executable to validate as an RP runtime. The official target is the real RepoPrompt app / MCP CLI "
                "runtime; `rp-cli-stub` is reference/test-only."
            ),
        ),
    ],
    rp_arg: Annotated[
        list[str] | None,
        typer.Option("--rp-arg", help="Additional arguments passed to the RP provider command."),
    ] = None,
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json", help="Render the conformance report as JSON.")] = False,
) -> None:
    """Run RP native protocol conformance checks against a specific runtime command."""
    report = run_rp_conformance([rp_command, *(rp_arg or [])], repo_root=repo_root)
    if json_output:
        typer.echo(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        typer.echo(render_rp_conformance_report(report))
    if not report["ok"]:
        raise typer.Exit(code=1)


@app.command("doctor")
def doctor_command(
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path("."),
    json_output: Annotated[bool, typer.Option("--json", help="Render doctor output as JSON.")] = False,
) -> None:
    """Inspect workspace structure, gate commands, and host/tool availability."""
    report = run_doctor(ai_root=ai_root, repo_root=repo_root)
    if json_output:
        typer.echo(json.dumps(report.to_json(), indent=2, ensure_ascii=False))
    else:
        console.print(render_doctor_report(report), markup=False)
    if not report.ok:
        raise typer.Exit(code=1)


@compile_app.command("claude")
def compile_claude_command(
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    output: Annotated[Path, typer.Option("--output")] = Path(".claude/compiled"),
) -> None:
    """Compile `.ai/` sources into a Claude host projection and drift manifest."""
    try:
        result = compile_claude(ai_root, output)
    except AiwfError as exc:
        console.print(f"[red]compile failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(
        "[green]compile completed[/green] "
        f"bundle={result['bundle_path']} projection={result['projection_path']} install={result['install_surface_path']} "
        f"manifest={result['manifest_path']} drift={result['drift_status']}"
    )


@compile_app.command("codex")
def compile_codex_command(
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    output: Annotated[Path, typer.Option("--output")] = Path(".codex/compiled"),
) -> None:
    """Compile `.ai/` sources into a Codex host projection and drift manifest."""
    try:
        result = compile_codex(ai_root, output)
    except AiwfError as exc:
        console.print(f"[red]compile failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(
        "[green]compile completed[/green] "
        f"bundle={result['bundle_path']} projection={result['projection_path']} install={result['install_surface_path']} "
        f"manifest={result['manifest_path']} drift={result['drift_status']}"
    )


@compile_app.command("rp")
def compile_rp_command(
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    output: Annotated[Path, typer.Option("--output")] = Path(".rp/compiled"),
) -> None:
    """Compile `.ai/` sources into a RepoPrompt host projection and drift manifest."""
    try:
        result = compile_rp(ai_root, output)
    except AiwfError as exc:
        console.print(f"[red]compile failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(
        "[green]compile completed[/green] "
        f"bundle={result['bundle_path']} projection={result['projection_path']} install={result['install_surface_path']} "
        f"manifest={result['manifest_path']} drift={result['drift_status']}"
    )
