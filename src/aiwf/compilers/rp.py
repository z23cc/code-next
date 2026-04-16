"""RepoPrompt compiler for host-aware `.ai/` workflow projections."""

from __future__ import annotations

from pathlib import Path

from aiwf.adapters import resolve_adapter_contract
from aiwf.compilers.base import (
    CompileContext,
    CompilerSpec,
    build_install_surface_document,
    build_projection_document,
    compile_host_projection,
    render_install_surface_markdown,
)
from aiwf.loader import load_gate_set, load_policy, load_runbook


RP_COMMANDS = {
    "plan": "uv run aiwf run plan --task .ai/tasks/<task>.md --adapter rp",
    "implement": "uv run aiwf run implement --task .ai/tasks/<task>.md --adapter rp",
    "review": "uv run aiwf run review --run-id <run_id>",
    "resume": "uv run aiwf resume <run_id>",
}


def compile_rp(ai_root: str | Path, output_dir: str | Path) -> dict[str, Path | str]:
    """Compile `.ai/` sources into a RepoPrompt host projection with drift metadata."""
    return compile_host_projection(RP_COMPILER_SPEC, ai_root, output_dir)


def _build_compiled_markdown(context: CompileContext) -> str:
    manual_contract = RP_COMPILER_SPEC.variants["manual"]
    auto_contract = RP_COMPILER_SPEC.variants["auto"]
    install_surface = build_install_surface_document(spec=RP_COMPILER_SPEC, output_dir=context.output_dir)
    native_runtime = auto_contract.native_runtime
    bridge_contract = manual_contract.bridge
    sections: list[str] = [
        "# RepoPrompt Workflow Bundle",
        "",
        f"- source_ai_root: {context.ai_root}",
        "- intended_host: RepoPrompt",
        f"- host_projection: `{RP_COMPILER_SPEC.projection_filename}`",
        "- drift_manifest: `manifest.json`",
        f"- install_surface: `{RP_COMPILER_SPEC.install_surface_filename}`",
        "",
        "## RepoPrompt Host Contract",
        f"- stored_runtime_key: `{RP_COMPILER_SPEC.stored_runtime_key}`",
        f"- default_variant: `{RP_COMPILER_SPEC.variant_namespace}/{RP_COMPILER_SPEC.default_variant}`",
        "- supported_variants: `rp/manual` (stable), `rp/auto` (experimental)",
        "- official_runtime_target: real RepoPrompt app / MCP CLI runtime",
        (
            f"- native_runtime_candidates: `{', '.join(native_runtime.command_candidates)}` "
            "(must resolve to the real RepoPrompt runtime; `rp-cli-stub` is test-only)"
        ),
        (
            f"- bridge_capability: `{bridge_contract.default_mode} "
            "(groundwork only — does not invoke RepoPrompt MCP/tools yet)`"
        ),
        (
            f"- native_protocol: `aiwf-rp-native/v{native_runtime.protocol_version}` "
            "(experimental auto/native surface; verify against the real RepoPrompt runtime)"
            if native_runtime.protocol_version is not None
            else "- native_protocol: `_legacy text fallback only_`"
        ),
        f"- resume_mode: restores stored `{RP_COMPILER_SPEC.stored_runtime_key}` from run metadata",
        "",
        "## RepoPrompt Review Evidence Contract",
        "- review entrypoint targets an existing run at `needs_review`",
        f"- required pre-review artifact: `{manual_contract.review.required_run_artifacts[0]}`",
        f"- manual review report fields: {_format_review_fields(manual_contract)}",
        f"- auto review report fields: {_format_review_fields(auto_contract)}",
        "- linked review evidence artifact must exist before finalization",
        "",
        "## Suggested Commands",
        "```bash",
        RP_COMMANDS["plan"],
        RP_COMMANDS["implement"],
        RP_COMMANDS["review"],
        RP_COMMANDS["resume"],
        "```",
        "",
        "Experimental auto variant note:",
        "- Use `--auto` only when PATH resolves to the real RepoPrompt app / MCP CLI runtime.",
        "- `rp-cli-stub` is an internal/reference harness and not an official RP product target.",
        "",
        *render_install_surface_markdown(install_surface),
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


def _build_projection(
    context: CompileContext,
    bundle_sha256: str,
    install_surface: dict[str, object],
) -> dict[str, object]:
    manual_contract = RP_COMPILER_SPEC.variants["manual"]
    auto_contract = RP_COMPILER_SPEC.variants["auto"]
    return build_projection_document(
        spec=RP_COMPILER_SPEC,
        source_ai_root=context.ai_root,
        source_index=context.source_index,
        bundle_sha256=bundle_sha256,
        install_surface=install_surface,
        artifacts={
            "bundle": RP_COMPILER_SPEC.bundle_filename,
            "install_surface": RP_COMPILER_SPEC.install_surface_filename,
            "manifest": "manifest.json",
        },
        commands=RP_COMMANDS,
        workflow_contract={
            "plan": {
                "entrypoint": RP_COMMANDS["plan"],
                "primary_artifacts": ["context-pack.md", "exec-plan.md"],
                "auto_entrypoint": f"{RP_COMMANDS['plan']} --auto",
            },
            "implement": {
                "entrypoint": RP_COMMANDS["implement"],
                "manual_handoff_artifact": "rp-agent-implement-prompt.md",
                "bridge_seeding_artifact": "rp-bridge-seeding.json",
                "auto_stage_output_artifact": "rp-agent-implement-response.md",
                "resume_boundary": (
                    "Use `uv run aiwf resume <run_id>` after manual RepoPrompt implement handoff. "
                    "This manual handoff flow is the stable/default RP path."
                ),
                "auto_entrypoint": f"{RP_COMMANDS['implement']} --auto",
            },
            "review": {
                "entrypoint": RP_COMMANDS["review"],
                "requires_status": "needs_review",
                "required_run_artifacts": list(manual_contract.review.required_run_artifacts),
                "report_contract": {
                    "manual": manual_contract.review.to_metadata(),
                    "auto": auto_contract.review.to_metadata(),
                },
            },
            "resume": {
                "entrypoint": RP_COMMANDS["resume"],
                "restores_run_metadata": [RP_COMPILER_SPEC.stored_runtime_key],
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


RP_COMPILER_SPEC = CompilerSpec(
    key="rp",
    projection_name="rp-host-projection",
    variant_namespace="rp",
    compiler_name="aiwf.compile.rp",
    projection_contract="rp-host-projection-v4",
    host_name="repoprompt",
    host_display_name="RepoPrompt",
    stored_runtime_key="host_contract",
    default_variant="manual",
    default_output_dir=".rp/compiled",
    bundle_filename="rp-bundle.md",
    projection_filename="rp-projection.json",
    install_surface_filename="install-surface.json",
    bundle_manifest_key="rp_bundle",
    variants={
        "manual": resolve_adapter_contract("rp", auto=False),
        "auto": resolve_adapter_contract("rp", auto=True),
    },
    bundle_builder=_build_compiled_markdown,
    projection_builder=_build_projection,
)
