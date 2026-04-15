"""Typer CLI for aiwf workflow operations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Callable, Literal

import typer
from rich.console import Console

from aiwf import __version__
from aiwf.adapters import ADAPTER_SPECS, build_adapter, build_adapter_from_contract, restore_host_contract
from aiwf.adapters.base import HostContract
from aiwf.artifacts import ArtifactStore
from aiwf.compilers.claude import compile_claude
from aiwf.compilers.codex import compile_codex
from aiwf.contracts import assess_review_boundary, assess_review_evidence, lint_contract_registry, review_contract_fields
from aiwf.doctor import render_doctor_report, run_doctor
from aiwf.engine import WorkflowEngine
from aiwf.exceptions import AiwfError
from aiwf.state import RunStateManager

app = typer.Typer(
    invoke_without_command=True,
    help="aiwf workflow CLI.",
)
run_app = typer.Typer(help="Run workflow stages with the configured adapter.")
compile_app = typer.Typer(help="Compile workflow inputs for host-specific outputs.")
contracts_app = typer.Typer(help="Lint and inspect built-in host contracts.")
app.add_typer(run_app, name="run")
app.add_typer(compile_app, name="compile")
app.add_typer(contracts_app, name="contracts")
console = Console()


AdapterName = Literal["claude", "rp", "codex", "stub"]


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
) -> WorkflowEngine:
    try:
        if host_contract is None:
            if adapter_name is None:
                raise AiwfError("Adapter name is required when no stored host contract is provided")
            adapter, host_contract = build_adapter(adapter_name, repo_root, auto=auto)
        else:
            adapter = build_adapter_from_contract(host_contract, repo_root)
        return WorkflowEngine(
            adapter,
            ai_root=ai_root,
            repo_root=repo_root,
            host_contract=host_contract,
            adapter_resolver=lambda contract: build_adapter_from_contract(contract, repo_root),
        )
    except ValueError as exc:
        raise AiwfError(str(exc)) from exc


def _resolve_run_execution(ai_root: Path, run_id: str) -> HostContract:
    meta = RunStateManager(ai_root).load_run(run_id)
    try:
        return restore_host_contract(meta.data)
    except ValueError as exc:
        raise AiwfError(f"Run {run_id} does not include a valid stored host contract") from exc


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


def _print_run_guidance(ai_root: Path, run_id: str) -> None:
    try:
        diagnostics = _load_run_surface(ai_root, run_id, "run-diagnostics.json")
    except AiwfError:
        console.print(f"[yellow]inspect hint:[/yellow] uv run aiwf inspect {run_id} --ai-root {ai_root}")
        return

    status_reason = str(diagnostics.get("status_reason", "")).strip()
    if status_reason:
        console.print(f"reason={status_reason}")

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


def _build_inspection_payload(ai_root: Path, run_id: str) -> dict[str, Any]:
    diagnostics = _load_run_surface(ai_root, run_id, "run-diagnostics.json")
    provenance = _load_optional_run_surface(ai_root, run_id, "run-provenance.json")
    review_report = _load_optional_run_surface(ai_root, run_id, "review-report.json")

    payload: dict[str, Any] = {
        "ok": True,
        "run_id": run_id,
        "diagnostics": diagnostics,
        "provenance": provenance,
        "review_report": review_report,
        "artifacts": {
            "diagnostics": str(_artifact_path(ai_root, run_id, "run-diagnostics.json")),
            "provenance": str(_artifact_path(ai_root, run_id, "run-provenance.json")),
            "review_report": str(_artifact_path(ai_root, run_id, "review-report.json")) if review_report is not None else None,
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
        return payload

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
    return payload


def _print_inspection(ai_root: Path, run_id: str, *, verbose: bool = False) -> None:
    payload = _build_inspection_payload(ai_root, run_id)
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


@run_app.command("plan")
def run_plan(
    task: Annotated[Path, typer.Option("--task", exists=True, dir_okay=False, readable=True)],
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path("."),
    adapter: Annotated[AdapterName, typer.Option("--adapter")] = "claude",
    auto: Annotated[
        bool, typer.Option("--auto", help="Use adapter auto mode when supported by the selected host contract.")
    ] = False,
) -> None:
    """Run the plan workflow."""
    engine = _build_engine_or_exit("plan", lambda: _build_engine(ai_root, repo_root, adapter_name=adapter, auto=auto))
    _execute_command("plan", ai_root, lambda: engine.run_plan(task))


@run_app.command("implement")
def run_implement(
    task: Annotated[Path, typer.Option("--task", exists=True, dir_okay=False, readable=True)],
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path("."),
    adapter: Annotated[AdapterName, typer.Option("--adapter")] = "claude",
    auto: Annotated[
        bool, typer.Option("--auto", help="Use adapter auto mode when supported by the selected host contract.")
    ] = False,
) -> None:
    """Run the implement workflow."""
    engine = _build_engine_or_exit(
        "implement",
        lambda: _build_engine(ai_root, repo_root, adapter_name=adapter, auto=auto),
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
        lambda: _build_engine(ai_root, repo_root, host_contract=_resolve_run_execution(ai_root, run_id)),
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
        lambda: _build_engine(ai_root, repo_root, host_contract=_resolve_run_execution(ai_root, run_id)),
    )
    _execute_command("resume", ai_root, lambda: engine.resume(run_id))


@app.command("inspect")
def inspect_run(
    run_id: str,
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    verbose: Annotated[bool, typer.Option("--verbose", help="Show artifact index and detailed provenance links.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Render inspect output as JSON.")] = False,
) -> None:
    """Inspect diagnostics and provenance for an existing run."""
    try:
        if json_output:
            typer.echo(json.dumps(_build_inspection_payload(ai_root, run_id), indent=2, ensure_ascii=False))
        else:
            _print_inspection(ai_root, run_id, verbose=verbose)
    except AiwfError as exc:
        if json_output:
            typer.echo(json.dumps({"ok": False, "run_id": run_id, "error": str(exc)}, indent=2, ensure_ascii=False))
        else:
            console.print(f"[red]inspect failed:[/red] {exc}")
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
        f"bundle={result['bundle_path']} projection={result['projection_path']} "
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
        f"bundle={result['bundle_path']} projection={result['projection_path']} "
        f"manifest={result['manifest_path']} drift={result['drift_status']}"
    )
