"""Claude compiler for host-aware `.ai/` workflow projections."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from aiwf.exceptions import LoadError
from aiwf.loader import load_gate_set, load_policy, load_runbook
from aiwf.models import utc_now


def compile_claude(ai_root: str | Path, output_dir: str | Path) -> dict[str, Path | str]:
    """Compile `.ai/` sources into a Claude host projection with drift metadata."""
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

    source_index = _build_source_index(ai_root_path, runbook_files, policy_files, gate_files)
    compiled_markdown = _build_compiled_markdown(ai_root_path, runbook_files, policy_files, gate_files, source_index)
    bundle_sha256 = _sha256_text(compiled_markdown)

    projection = _build_projection(ai_root_path, source_index, bundle_sha256)
    projection_text = json.dumps(projection, indent=2, ensure_ascii=False) + "\n"
    projection_sha256 = _sha256_text(projection_text)

    manifest_path = output_path / "manifest.json"
    previous_manifest = _load_existing_manifest(manifest_path)
    drift = _build_drift_report(previous_manifest, source_index, bundle_sha256, projection_sha256)

    manifest = {
        "schema_version": 2,
        "generated_at": utc_now().isoformat(),
        "compiler": {
            "name": "aiwf.compile.claude",
            "host": "claude_code",
            "projection_contract": "claude-host-projection-v1",
        },
        "ai_root": str(ai_root_path),
        "output_dir": str(output_path),
        "files": {
            "claude_bundle": "claude-bundle.md",
            "projection": "claude-projection.json",
            "manifest": "manifest.json",
        },
        "sources": {
            "runbooks": [path.name for path in runbook_files],
            "policies": [path.name for path in policy_files],
            "gates": [path.name for path in gate_files],
        },
        "source_index": source_index,
        "hashes": {
            "bundle_sha256": bundle_sha256,
            "projection_sha256": projection_sha256,
        },
        "drift": drift,
    }

    bundle_path = output_path / "claude-bundle.md"
    projection_path = output_path / "claude-projection.json"
    bundle_path.write_text(compiled_markdown, encoding="utf-8")
    projection_path.write_text(projection_text, encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "bundle_path": bundle_path,
        "projection_path": projection_path,
        "manifest_path": manifest_path,
        "drift_status": drift["status"],
    }


def _build_compiled_markdown(
    ai_root: Path,
    runbook_files: list[Path],
    policy_files: list[Path],
    gate_files: list[Path],
    source_index: list[dict[str, object]],
) -> str:
    traceability = {str(entry["source_path"]): str(entry["sha256"]) for entry in source_index}
    sections: list[str] = [
        "# Claude Workflow Bundle",
        "",
        f"- source_ai_root: {ai_root}",
        "- intended_host: Claude Code",
        "- host_projection: `claude-projection.json`",
        "- drift_manifest: `manifest.json`",
        "",
        "## Claude Host Contract",
        "- adapter: `claude`",
        "- manual_handoff: supported",
        "- auto_subprocess: supported",
        "- review_mode: existing run + `verify-report.json` driven",
        "- resume_mode: restores stored `adapter` and `auto` settings from run metadata",
        "",
        "## Suggested Commands",
        "```bash",
        "uv run aiwf run plan --task .ai/tasks/<task>.md --adapter claude",
        "uv run aiwf run implement --task .ai/tasks/<task>.md --adapter claude",
        "uv run aiwf run review --run-id <run_id>",
        "uv run aiwf resume <run_id>",
        "```",
        "",
        "## Projection Traceability Index",
        "| kind | logical_name | source | sha256 |",
        "| --- | --- | --- | --- |",
    ]
    sections.extend(
        [
            f"| {entry['kind']} | {entry['logical_name']} | `{entry['source_path']}` | `{entry['sha256']}` |"
            for entry in source_index
        ]
    )

    sections.extend(["", "## Policies"])
    for policy_file in policy_files:
        policy_text = load_policy(policy_file)
        source_path = _relative_source_path(ai_root, policy_file)
        sections.extend(
            [
                "",
                f"### {policy_file.stem}",
                f"- source: `{source_path}`",
                f"- sha256: `{traceability[source_path]}`",
                "",
                policy_text or "_Empty policy file._",
            ]
        )

    sections.extend(["", "## Runbooks"])
    for runbook_file in runbook_files:
        runbook = load_runbook(runbook_file)
        source_path = _relative_source_path(ai_root, runbook_file)
        sections.extend(
            [
                "",
                f"### {runbook.name}",
                f"- source: `{source_path}`",
                f"- sha256: `{traceability[source_path]}`",
                "",
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
        source_path = _relative_source_path(ai_root, gate_file)
        sections.extend(
            [
                "",
                f"### {gate_set.name}",
                f"- source: `{source_path}`",
                f"- sha256: `{traceability[source_path]}`",
                "",
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


def _build_projection(
    ai_root: Path,
    source_index: list[dict[str, object]],
    bundle_sha256: str,
) -> dict[str, object]:
    commands = {
        "plan": "uv run aiwf run plan --task .ai/tasks/<task>.md --adapter claude",
        "implement": "uv run aiwf run implement --task .ai/tasks/<task>.md --adapter claude",
        "review": "uv run aiwf run review --run-id <run_id>",
        "resume": "uv run aiwf resume <run_id>",
    }
    return {
        "schema_version": 2,
        "projection_name": "claude-host-projection",
        "source_ai_root": str(ai_root),
        "host": {
            "name": "claude_code",
            "display_name": "Claude Code",
            "adapter": "claude",
            "manual_handoff": True,
            "auto_subprocess": True,
        },
        "artifacts": {
            "bundle": "claude-bundle.md",
            "manifest": "manifest.json",
        },
        "commands": commands,
        "workflow_contract": {
            "plan": {
                "entrypoint": commands["plan"],
                "primary_artifacts": ["context-pack.md", "exec-plan.md"],
            },
            "implement": {
                "entrypoint": commands["implement"],
                "manual_handoff_artifact": "claude-implement-prompt.md",
                "resume_boundary": "Use `uv run aiwf resume <run_id>` after manual implement handoff.",
            },
            "review": {
                "entrypoint": commands["review"],
                "requires_status": "needs_review",
                "requires_artifact": "verify-report.json",
                "manual_handoff_artifact": "claude-review-prompt.md",
            },
            "resume": {
                "entrypoint": commands["resume"],
                "restores_run_metadata": ["adapter", "auto"],
            },
        },
        "projection_inputs": source_index,
        "projection_hashes": {
            "bundle_sha256": bundle_sha256,
        },
    }


def _build_source_index(
    ai_root: Path,
    runbook_files: list[Path],
    policy_files: list[Path],
    gate_files: list[Path],
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []

    for policy_file in policy_files:
        entries.append(
            _source_entry(
                ai_root,
                policy_file,
                kind="policy",
                logical_name=policy_file.stem,
            )
        )
    for runbook_file in runbook_files:
        runbook = load_runbook(runbook_file)
        entries.append(
            _source_entry(
                ai_root,
                runbook_file,
                kind="runbook",
                logical_name=runbook.name,
            )
        )
    for gate_file in gate_files:
        gate_set = load_gate_set(gate_file)
        entries.append(
            _source_entry(
                ai_root,
                gate_file,
                kind="gate",
                logical_name=gate_set.name,
            )
        )

    return sorted(entries, key=lambda entry: (str(entry["kind"]), str(entry["source_path"])))


def _source_entry(ai_root: Path, path: Path, *, kind: str, logical_name: str) -> dict[str, object]:
    content = path.read_text(encoding="utf-8")
    return {
        "kind": kind,
        "logical_name": logical_name,
        "source_path": _relative_source_path(ai_root, path),
        "sha256": _sha256_text(content),
    }


def _build_drift_report(
    previous_manifest: dict[str, Any] | None,
    source_index: list[dict[str, object]],
    bundle_sha256: str,
    projection_sha256: str,
) -> dict[str, object]:
    if not previous_manifest:
        return {
            "status": "initial",
            "baseline_generated_at": None,
            "source_changes": {"added": [], "removed": [], "changed": [], "unchanged_count": len(source_index)},
            "bundle_changed": False,
            "projection_changed": False,
        }

    previous_index = previous_manifest.get("source_index")
    if not isinstance(previous_index, list):
        return {
            "status": "initial",
            "baseline_generated_at": previous_manifest.get("generated_at"),
            "source_changes": {"added": [], "removed": [], "changed": [], "unchanged_count": len(source_index)},
            "bundle_changed": False,
            "projection_changed": False,
            "notes": ["Previous manifest did not include compatible source fingerprints."],
        }

    previous_map = _fingerprint_map(previous_index)
    current_map = _fingerprint_map(source_index)

    added = sorted(set(current_map) - set(previous_map))
    removed = sorted(set(previous_map) - set(current_map))
    changed = sorted(path for path in current_map.keys() & previous_map.keys() if current_map[path] != previous_map[path])
    unchanged_count = len(current_map.keys() & previous_map.keys()) - len(changed)

    previous_hashes = previous_manifest.get("hashes")
    if not isinstance(previous_hashes, dict):
        return {
            "status": "initial",
            "baseline_generated_at": previous_manifest.get("generated_at"),
            "source_changes": {
                "added": added,
                "removed": removed,
                "changed": changed,
                "unchanged_count": unchanged_count,
            },
            "bundle_changed": False,
            "projection_changed": False,
            "notes": ["Previous manifest did not include compatible output hashes."],
        }

    previous_bundle_sha256 = previous_hashes.get("bundle_sha256")
    previous_projection_sha256 = previous_hashes.get("projection_sha256")

    bundle_changed = bool(previous_bundle_sha256 and previous_bundle_sha256 != bundle_sha256)
    projection_changed = bool(previous_projection_sha256 and previous_projection_sha256 != projection_sha256)
    status = "changed" if added or removed or changed or bundle_changed or projection_changed else "clean"

    return {
        "status": status,
        "baseline_generated_at": previous_manifest.get("generated_at"),
        "source_changes": {
            "added": added,
            "removed": removed,
            "changed": changed,
            "unchanged_count": unchanged_count,
        },
        "bundle_changed": bundle_changed,
        "projection_changed": projection_changed,
    }


def _fingerprint_map(entries: list[dict[str, object]] | list[Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source_path = entry.get("source_path")
        sha256 = entry.get("sha256")
        if isinstance(source_path, str) and isinstance(sha256, str):
            mapping[source_path] = sha256
    return mapping


def _load_existing_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LoadError("Failed to read existing manifest", path=path, stage="compile_claude") from exc
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _relative_source_path(ai_root: Path, source_path: Path) -> str:
    try:
        return str(source_path.relative_to(ai_root.parent))
    except ValueError:
        return str(source_path)


def _sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _require_directory(path: Path, *, stage: str) -> None:
    if not path.exists():
        raise LoadError("Required compile source directory does not exist", path=path, stage=stage)
    if not path.is_dir():
        raise LoadError("Compile source path is not a directory", path=path, stage=stage)
