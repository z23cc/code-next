"""Typer CLI for aiwf workflow operations."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Callable, Literal

import typer
from rich.console import Console

from aiwf import __version__
from aiwf.adapters.base import RunnerAdapter
from aiwf.adapters.claude_code import ClaudeCodeAdapter
from aiwf.adapters.stub import StubRunnerAdapter
from aiwf.compilers.claude import compile_claude
from aiwf.engine import WorkflowEngine
from aiwf.exceptions import AiwfError
from aiwf.state import RunStateManager

app = typer.Typer(
    invoke_without_command=True,
    help="aiwf workflow CLI.",
)
run_app = typer.Typer(help="Run workflow stages with the configured adapter.")
compile_app = typer.Typer(help="Compile workflow inputs for host-specific outputs.")
app.add_typer(run_app, name="run")
app.add_typer(compile_app, name="compile")
console = Console()


AdapterName = Literal["claude", "stub"]


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
    auto: bool = False,
) -> WorkflowEngine:
    adapter: RunnerAdapter
    if adapter_name == "stub":
        adapter = StubRunnerAdapter()
    elif adapter_name == "claude":
        adapter = ClaudeCodeAdapter(repo_root=repo_root, auto=auto)
    else:
        raise ValueError(f"Unknown adapter: {adapter_name}")
    return WorkflowEngine(
        adapter,
        ai_root=ai_root,
        repo_root=repo_root,
        adapter_name=adapter_name,
        adapter_auto=auto if adapter_name == "claude" else False,
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
    adapter: Annotated[AdapterName, typer.Option("--adapter")] = "claude",
    auto: Annotated[bool, typer.Option("--auto", help="Use the Claude CLI for subprocess execution.")] = False,
) -> None:
    """Run the plan workflow."""
    engine = _build_engine(ai_root, repo_root, adapter_name=adapter, auto=auto)
    _execute_command("plan", ai_root, lambda: engine.run_plan(task))


@run_app.command("implement")
def run_implement(
    task: Annotated[Path, typer.Option("--task", exists=True, dir_okay=False, readable=True)],
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path("."),
    adapter: Annotated[AdapterName, typer.Option("--adapter")] = "claude",
    auto: Annotated[bool, typer.Option("--auto", help="Use the Claude CLI for subprocess execution.")] = False,
) -> None:
    """Run the implement workflow."""
    engine = _build_engine(ai_root, repo_root, adapter_name=adapter, auto=auto)
    _execute_command("implement", ai_root, lambda: engine.run_implement(task))


@run_app.command("review")
def run_review(
    task: Annotated[Path, typer.Option("--task", exists=True, dir_okay=False, readable=True)],
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path("."),
    adapter: Annotated[AdapterName, typer.Option("--adapter")] = "claude",
    auto: Annotated[bool, typer.Option("--auto", help="Use the Claude CLI for subprocess execution.")] = False,
) -> None:
    """Run the review workflow."""
    engine = _build_engine(ai_root, repo_root, adapter_name=adapter, auto=auto)
    _execute_command("review", ai_root, lambda: engine.run_review(task))


@app.command("resume")
def resume(
    run_id: str,
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    repo_root: Annotated[Path, typer.Option("--repo-root")] = Path("."),
    adapter: Annotated[AdapterName | None, typer.Option("--adapter")] = None,
    auto: Annotated[bool, typer.Option("--auto", help="Use the Claude CLI for subprocess execution.")] = False,
) -> None:
    """Resume a failed, blocked, or needs-review workflow run."""
    stored_meta = RunStateManager(ai_root).load_run(run_id)
    stored_adapter = str(stored_meta.data.get("adapter", "claude"))
    resolved_adapter: AdapterName = adapter or ("claude" if stored_adapter == "claude" else "stub")
    engine = _build_engine(ai_root, repo_root, adapter_name=resolved_adapter, auto=auto)
    _execute_command("resume", ai_root, lambda: engine.resume(run_id))


@compile_app.command("claude")
def compile_claude_command(
    ai_root: Annotated[Path, typer.Option("--ai-root")] = Path(".ai"),
    output: Annotated[Path, typer.Option("--output")] = Path(".claude/compiled"),
) -> None:
    """Compile `.ai/` sources into a Claude-friendly bundle."""
    try:
        result = compile_claude(ai_root, output)
    except AiwfError as exc:
        console.print(f"[red]compile failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(
        "[green]compile completed[/green] "
        f"bundle={result['bundle_path']} manifest={result['manifest_path']}"
    )
