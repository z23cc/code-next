"""Typer CLI for aiwf workflow operations."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Callable, Literal

import typer
from rich.console import Console

from aiwf import __version__
from aiwf.adapters.base import RunnerAdapter
from aiwf.adapters.stub import StubRunnerAdapter
from aiwf.engine import WorkflowEngine
from aiwf.exceptions import AiwfError
from aiwf.state import RunStateManager

app = typer.Typer(
    invoke_without_command=True,
    help="aiwf workflow CLI."
)
run_app = typer.Typer(help="Run workflow stages with the built-in stub adapter.")
app.add_typer(run_app, name="run")
console = Console()


AdapterName = Literal["stub"]


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
    adapter_name: AdapterName,
) -> WorkflowEngine:
    adapter: RunnerAdapter
    if adapter_name == "stub":
        adapter = StubRunnerAdapter()
    else:
        raise ValueError(f"Unknown adapter: {adapter_name}")
    return WorkflowEngine(
        adapter,
        ai_root=ai_root,
        repo_root=repo_root,
        adapter_name=adapter_name,
        adapter_auto=False,
    )


def _execute_command(action: str, ai_root: Path, func: Callable[[], str]) -> None:
    try:
        run_id = func()
    except AiwfError as exc:
        console.print(f"[red]{action} failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    final_status = RunStateManager(ai_root).load_run(run_id).status.value
    if final_status == "failed":
        console.print(f"[red]{action} finished with failed status[/red] run_id={run_id}")
        raise typer.Exit(code=1)
    console.print(f"[green]{action} completed[/green] run_id={run_id}")


@run_app.command("plan")
def run_plan(
    task: Annotated[Path, typer.Option("--task", exists=True, dir_okay=False, readable=True)],
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path("."),
    adapter: Annotated[AdapterName, typer.Option("--adapter")] = "stub",
) -> None:
    """Run the plan workflow."""
    engine = _build_engine(ai_root, repo_root, adapter_name=adapter)
    _execute_command("plan", ai_root, lambda: engine.run_plan(task))


@run_app.command("implement")
def run_implement(
    task: Annotated[Path, typer.Option("--task", exists=True, dir_okay=False, readable=True)],
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path("."),
    adapter: Annotated[AdapterName, typer.Option("--adapter")] = "stub",
) -> None:
    """Run the implement workflow."""
    engine = _build_engine(ai_root, repo_root, adapter_name=adapter)
    _execute_command("implement", ai_root, lambda: engine.run_implement(task))


@run_app.command("review")
def run_review(
    task: Annotated[Path, typer.Option("--task", exists=True, dir_okay=False, readable=True)],
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path("."),
    adapter: Annotated[AdapterName, typer.Option("--adapter")] = "stub",
) -> None:
    """Run the review workflow."""
    engine = _build_engine(ai_root, repo_root, adapter_name=adapter)
    _execute_command("review", ai_root, lambda: engine.run_review(task))


@app.command("resume")
def resume(
    run_id: str,
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path("."),
    adapter: Annotated[AdapterName | None, typer.Option("--adapter")] = None,
) -> None:
    """Resume a failed, blocked, or needs-review workflow run."""
    stored_meta = RunStateManager(ai_root).load_run(run_id)
    stored_adapter = str(stored_meta.data.get("adapter", "stub"))
    resolved_adapter = adapter or ("stub" if stored_adapter == "stub" else "stub")
    engine = _build_engine(ai_root, repo_root, adapter_name=resolved_adapter)
    _execute_command("resume", ai_root, lambda: engine.resume(run_id))
