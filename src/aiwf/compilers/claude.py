"""Claude compiler for host-aware `.ai/` workflow projections."""

from __future__ import annotations

from pathlib import Path

from aiwf.adapters import resolve_adapter_contract
from aiwf.compilers.base import CompileContext, CompilerSpec, build_projection_document, compile_host_projection
from aiwf.loader import load_gate_set, load_policy, load_runbook


CLAUDE_COMMANDS = {
    "plan": "uv run aiwf run plan --task .ai/tasks/<task>.md --adapter claude",
    "implement": "uv run aiwf run implement --task .ai/tasks/<task>.md --adapter claude",
    "review": "uv run aiwf run review --run-id <run_id>",
    "resume": "uv run aiwf resume <run_id>",
}


def compile_claude(ai_root: str | Path, output_dir: str | Path) -> dict[str, Path | str]:
    """Compile `.ai/` sources into a Claude host projection with drift metadata."""
    return compile_host_projection(CLAUDE_COMPILER_SPEC, ai_root, output_dir)


def _build_compiled_markdown(context: CompileContext) -> str:
    manual_contract = CLAUDE_COMPILER_SPEC.variants["manual"]
    auto_contract = CLAUDE_COMPILER_SPEC.variants["auto"]
    sections: list[str] = [
        "# Claude Workflow Bundle",
        "",
        f"- source_ai_root: {context.ai_root}",
        "- intended_host: Claude Code",
        f"- host_projection: `{CLAUDE_COMPILER_SPEC.projection_filename}`",
        "- drift_manifest: `manifest.json`",
        "",
        "## Claude Host Contract",
        f"- stored_runtime_key: `{CLAUDE_COMPILER_SPEC.stored_runtime_key}`",
        f"- default_variant: `{CLAUDE_COMPILER_SPEC.variant_namespace}/{CLAUDE_COMPILER_SPEC.default_variant}`",
        "- supported_variants: `claude/manual`, `claude/auto`",
        f"- resume_mode: restores stored `{CLAUDE_COMPILER_SPEC.stored_runtime_key}` from run metadata",
        "",
        "## Claude Review Evidence Contract",
        "- review entrypoint targets an existing run at `needs_review`",
        f"- required pre-review artifact: `{manual_contract.review.required_run_artifacts[0]}`",
        f"- manual review report fields: {_format_review_fields(manual_contract)}",
        f"- auto review report fields: {_format_review_fields(auto_contract)}",
        "- linked review evidence artifact must exist before finalization",
        "",
        "## Suggested Commands",
        "```bash",
        CLAUDE_COMMANDS["plan"],
        CLAUDE_COMMANDS["implement"],
        CLAUDE_COMMANDS["review"],
        CLAUDE_COMMANDS["resume"],
        "```",
        "",
        "## Projection Traceability Index",
        "| kind | logical_name | source | sha256 |",
        "| --- | --- | --- | --- |",
    ]
    sections.extend(
        [
            f"| {entry['kind']} | {entry['logical_name']} | `{entry['source_path']}` | `{entry['sha256']}` |"
            for entry in context.source_index
        ]
    )

    sections.extend(["", "## Policies"])
    for policy_file in context.policy_files:
        policy_text = load_policy(policy_file)
        source_path = _source_path(context, policy_file)
        sections.extend(
            [
                "",
                f"### {policy_file.stem}",
                f"- source: `{source_path}`",
                f"- sha256: `{context.traceability[source_path]}`",
                "",
                policy_text or "_Empty policy file._",
            ]
        )

    sections.extend(["", "## Runbooks"])
    for runbook_file in context.runbook_files:
        runbook = load_runbook(runbook_file)
        source_path = _source_path(context, runbook_file)
        sections.extend(
            [
                "",
                f"### {runbook.name}",
                f"- source: `{source_path}`",
                f"- sha256: `{context.traceability[source_path]}`",
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
    for gate_file in context.gate_files:
        gate_set = load_gate_set(gate_file)
        source_path = _source_path(context, gate_file)
        sections.extend(
            [
                "",
                f"### {gate_set.name}",
                f"- source: `{source_path}`",
                f"- sha256: `{context.traceability[source_path]}`",
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


def _build_projection(context: CompileContext, bundle_sha256: str) -> dict[str, object]:
    manual_contract = CLAUDE_COMPILER_SPEC.variants["manual"]
    auto_contract = CLAUDE_COMPILER_SPEC.variants["auto"]
    return build_projection_document(
        spec=CLAUDE_COMPILER_SPEC,
        source_ai_root=context.ai_root,
        source_index=context.source_index,
        bundle_sha256=bundle_sha256,
        artifacts={
            "bundle": CLAUDE_COMPILER_SPEC.bundle_filename,
            "manifest": "manifest.json",
        },
        commands=CLAUDE_COMMANDS,
        workflow_contract={
            "plan": {
                "entrypoint": CLAUDE_COMMANDS["plan"],
                "primary_artifacts": ["context-pack.md", "exec-plan.md"],
            },
            "implement": {
                "entrypoint": CLAUDE_COMMANDS["implement"],
                "manual_handoff_artifact": "claude-implement-prompt.md",
                "resume_boundary": "Use `uv run aiwf resume <run_id>` after manual implement handoff.",
            },
            "review": {
                "entrypoint": CLAUDE_COMMANDS["review"],
                "requires_status": "needs_review",
                "required_run_artifacts": list(manual_contract.review.required_run_artifacts),
                "report_contract": {
                    "manual": manual_contract.review.to_metadata(),
                    "auto": auto_contract.review.to_metadata(),
                },
            },
            "resume": {
                "entrypoint": CLAUDE_COMMANDS["resume"],
                "restores_run_metadata": [CLAUDE_COMPILER_SPEC.stored_runtime_key],
            },
        },
    )


def _source_path(context: CompileContext, source_path: Path) -> str:
    try:
        return str(source_path.relative_to(context.ai_root.parent))
    except ValueError:
        return str(source_path)


def _format_review_fields(contract) -> str:
    ordered_fields: list[str] = []
    if "summary" in contract.review.required_report_string_fields:
        ordered_fields.append("summary")
    if "issues" in contract.review.required_report_list_fields:
        ordered_fields.append("issues")
    ordered_fields.extend(
        field_name for field_name in contract.review.required_report_string_fields if field_name != "summary"
    )
    ordered_fields.extend(
        field_name for field_name in contract.review.required_report_list_fields if field_name != "issues"
    )
    return ", ".join(f"`{field_name}`" for field_name in ordered_fields)


CLAUDE_COMPILER_SPEC = CompilerSpec(
    key="claude",
    projection_name="claude-host-projection",
    variant_namespace="claude",
    compiler_name="aiwf.compile.claude",
    projection_contract="claude-host-projection-v2",
    host_name="claude_code",
    host_display_name="Claude Code",
    stored_runtime_key="host_contract",
    default_variant="manual",
    bundle_filename="claude-bundle.md",
    projection_filename="claude-projection.json",
    bundle_manifest_key="claude_bundle",
    variants={
        "manual": resolve_adapter_contract("claude", auto=False),
        "auto": resolve_adapter_contract("claude", auto=True),
    },
    bundle_builder=_build_compiled_markdown,
    projection_builder=_build_projection,
)
