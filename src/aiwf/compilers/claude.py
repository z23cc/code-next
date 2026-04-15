"""Claude compiler for merged `.ai/` workflow inputs."""

from __future__ import annotations

import json
from pathlib import Path

from aiwf.exceptions import LoadError
from aiwf.loader import load_gate_set, load_policy, load_runbook
from aiwf.models import utc_now


def compile_claude(ai_root: str | Path, output_dir: str | Path) -> dict[str, Path]:
    """Compile `.ai/` sources into Claude-friendly merged artifacts."""
    ai_root_path = Path(ai_root)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    runbook_dir = ai_root_path / "runbooks"
    policy_dir = ai_root_path / "policies"
    gate_dir = ai_root_path / "gates"
    _require_directory(runbook_dir, stage="compile_claude")
    _require_directory(policy_dir, stage="compile_claude")
    _require_directory(gate_dir, stage="compile_claude")

    runbook_files = sorted(runbook_dir.glob("*.md"))
    policy_files = sorted(policy_dir.glob("*.md"))
    gate_files = sorted(gate_dir.glob("*.yaml"))
    if not runbook_files:
        raise LoadError("No runbook files found", path=runbook_dir, stage="compile_claude")
    if not policy_files:
        raise LoadError("No policy files found", path=policy_dir, stage="compile_claude")
    if not gate_files:
        raise LoadError("No gate files found", path=gate_dir, stage="compile_claude")

    compiled_markdown = _build_compiled_markdown(ai_root_path, runbook_files, policy_files, gate_files)
    manifest = {
        "generated_at": utc_now().isoformat(),
        "ai_root": str(ai_root_path),
        "output_dir": str(output_path),
        "files": {
            "claude_bundle": "claude-bundle.md",
            "manifest": "manifest.json",
        },
        "sources": {
            "runbooks": [path.name for path in runbook_files],
            "policies": [path.name for path in policy_files],
            "gates": [path.name for path in gate_files],
        },
    }

    bundle_path = output_path / "claude-bundle.md"
    manifest_path = output_path / "manifest.json"
    bundle_path.write_text(compiled_markdown, encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"bundle_path": bundle_path, "manifest_path": manifest_path}


def _build_compiled_markdown(
    ai_root: Path,
    runbook_files: list[Path],
    policy_files: list[Path],
    gate_files: list[Path],
) -> str:
    sections: list[str] = [
        "# Claude Workflow Bundle",
        "",
        f"- source_ai_root: {ai_root}",
        "- generated_from: runbooks + policies + gates",
        "- intended_use: `aiwf compile claude` output for Claude Code workflows",
        "",
        "## Suggested Commands",
        "```bash",
        "uv run aiwf run plan --task .ai/tasks/<task>.md --adapter claude",
        "uv run aiwf run implement --task .ai/tasks/<task>.md --adapter claude",
        "uv run aiwf run review --run-id <run_id>",
        "uv run aiwf resume <run_id>",
        "```",
    ]

    sections.extend(["", "## Policies"])
    for policy_file in policy_files:
        policy_text = load_policy(policy_file)
        sections.extend(
            [
                "",
                f"### {policy_file.stem}",
                policy_text or "_Empty policy file._",
            ]
        )

    sections.extend(["", "## Runbooks"])
    for runbook_file in runbook_files:
        runbook = load_runbook(runbook_file)
        sections.extend(
            [
                "",
                f"### {runbook.name}",
                runbook.description or "_No description provided._",
                "",
                "Stages:",
                *[f"- {stage.name}: {stage.description or 'no description'}" for stage in runbook.stages],
                "",
                runbook.body or "_No body content provided._",
            ]
        )

    sections.extend(["", "## Gates"])
    for gate_file in gate_files:
        gate_set = load_gate_set(gate_file)
        sections.extend(
            [
                "",
                f"### {gate_set.name}",
                gate_set.description or "_No description provided._",
                "",
                *[
                    f"- {gate.name}: `{gate.command}` (timeout={gate.timeout_seconds}s)"
                    for gate in gate_set.gates
                ],
            ]
        )

    sections.append("")
    return "\n".join(sections)


def _require_directory(path: Path, *, stage: str) -> None:
    if not path.exists():
        raise LoadError("Required compile source directory does not exist", path=path, stage=stage)
    if not path.is_dir():
        raise LoadError("Compile source path is not a directory", path=path, stage=stage)
