from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from aiwf.adapters import resolve_adapter_contract
from aiwf.cli import app
from aiwf.compilers import COMPILER_SPECS
from aiwf.compilers.claude import compile_claude
from aiwf.compilers.codex import compile_codex
from aiwf.compilers.rp import compile_rp


runner = CliRunner()
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_compile_claude_writes_bundle_projection_install_surface_and_manifest(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".claude" / "compiled"

    compiled = compile_claude(ai_root, output_dir)

    bundle = compiled["bundle_path"].read_text(encoding="utf-8")
    projection = json.loads(compiled["projection_path"].read_text(encoding="utf-8"))
    install_surface = json.loads(compiled["install_surface_path"].read_text(encoding="utf-8"))
    manifest = json.loads(compiled["manifest_path"].read_text(encoding="utf-8"))

    assert "## Claude Host Contract" in bundle
    assert "## Host Bundle / Install Surface" in bundle
    assert ".claude/skills" in bundle
    assert "## Projection Traceability Index" in bundle
    assert "## Policies" in bundle
    assert "## Runbooks" in bundle
    assert "## Gates" in bundle
    assert "## Suggested Commands" in bundle
    assert "uv run aiwf run review --run-id <run_id>" in bundle
    assert "uv run aiwf resume <run_id>" in bundle
    assert "- stored_runtime_key: `host_contract`" in bundle
    assert "- required pre-review artifact: `verify-report.json`" in bundle
    assert "- discover: no description" in bundle
    assert ".ai/policies/repo-policy.md" in bundle

    assert projection["host"]["name"] == "claude_code"
    assert projection["host"]["stored_runtime_key"] == "host_contract"
    assert projection["host"]["default_variant"] == "claude/manual"
    assert projection["host"]["variants"]["manual"] == resolve_adapter_contract("claude", auto=False).to_metadata()
    assert projection["host"]["variants"]["auto"] == resolve_adapter_contract("claude", auto=True).to_metadata()
    assert projection["host"]["variants"]["manual"]["review"]["linked_report_artifact_field"] == "prompt_file"
    assert projection["host"]["variants"]["auto"]["review"]["linked_report_artifact_field"] == "response_file"
    assert projection["workflow_contract"]["review"]["required_run_artifacts"] == ["verify-report.json"]
    assert projection["workflow_contract"]["review"]["report_contract"]["manual"]["expected_report_mode"] == "manual"
    assert projection["workflow_contract"]["resume"]["restores_run_metadata"] == ["host_contract"]
    assert projection["artifacts"]["bundle"] == "claude-bundle.md"
    assert projection["artifacts"]["install_surface"] == "install-surface.json"
    assert projection["install_surface"]["default_output_dir"] == ".claude/compiled"
    assert projection["install_surface"]["external_assets"][0]["path"] == ".claude/skills"

    assert install_surface["install_strategy"] == "use_compiled_output_directory"
    assert install_surface["default_output_dir"] == ".claude/compiled"
    assert [asset["role"] for asset in install_surface["generated_assets"]] == [
        "bundle",
        "projection",
        "install_surface",
        "manifest",
    ]
    assert install_surface["external_assets"][0]["path"] == ".claude/skills"
    assert install_surface["external_assets"][0]["owner"] == "handwritten"
    assert install_surface["external_assets"][0]["managed_by_compiler"] is False

    assert manifest["compiler"]["projection_contract"] == "claude-host-projection-v3"
    assert manifest["files"]["claude_bundle"] == "claude-bundle.md"
    assert manifest["files"]["install_surface"] == "install-surface.json"
    assert manifest["sources"]["runbooks"] == ["default.md"]
    assert manifest["sources"]["gates"] == ["default.yaml"]
    assert manifest["files"]["projection"] == "claude-projection.json"
    assert manifest["hashes"]["install_surface_sha256"]
    assert manifest["drift"]["status"] == "initial"
    assert manifest["drift"]["install_surface_changed"] is False
    assert compiled["drift_status"] == "initial"


def test_compile_codex_writes_bundle_projection_install_surface_and_manifest(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".codex" / "compiled"

    compiled = compile_codex(ai_root, output_dir)

    bundle = compiled["bundle_path"].read_text(encoding="utf-8")
    projection = json.loads(compiled["projection_path"].read_text(encoding="utf-8"))
    install_surface = json.loads(compiled["install_surface_path"].read_text(encoding="utf-8"))
    manifest = json.loads(compiled["manifest_path"].read_text(encoding="utf-8"))

    assert "## Codex Host Contract" in bundle
    assert "## Host Bundle / Install Surface" in bundle
    assert "## Projection Traceability Index" in bundle
    assert "## Policies" in bundle
    assert "## Runbooks" in bundle
    assert "## Gates" in bundle
    assert "## Suggested Commands" in bundle
    assert "uv run aiwf run plan --task .ai/tasks/<task>.md --adapter codex" in bundle
    assert "uv run aiwf run implement --task .ai/tasks/<task>.md --adapter codex" in bundle
    assert "- supported_variants: `codex/manual`" in bundle
    assert "- required pre-review artifact: `verify-report.json`" in bundle

    assert projection["host"]["name"] == "codex"
    assert projection["host"]["stored_runtime_key"] == "host_contract"
    assert projection["host"]["default_variant"] == "codex/manual"
    assert projection["host"]["variants"]["manual"] == resolve_adapter_contract("codex", auto=False).to_metadata()
    assert sorted(projection["host"]["variants"]) == ["manual"]
    assert projection["workflow_contract"]["review"]["required_run_artifacts"] == ["verify-report.json"]
    assert projection["workflow_contract"]["review"]["report_contract"]["manual"]["expected_report_mode"] == "manual"
    assert sorted(projection["workflow_contract"]["review"]["report_contract"]) == ["manual"]
    assert projection["workflow_contract"]["resume"]["restores_run_metadata"] == ["host_contract"]
    assert projection["artifacts"]["bundle"] == "codex-bundle.md"
    assert projection["artifacts"]["install_surface"] == "install-surface.json"
    assert projection["install_surface"]["default_output_dir"] == ".codex/compiled"
    assert projection["install_surface"]["external_assets"] == []

    assert install_surface["install_strategy"] == "use_compiled_output_directory"
    assert install_surface["default_output_dir"] == ".codex/compiled"
    assert install_surface["external_assets"] == []

    assert manifest["compiler"]["projection_contract"] == "codex-host-projection-v2"
    assert manifest["files"]["codex_bundle"] == "codex-bundle.md"
    assert manifest["files"]["install_surface"] == "install-surface.json"
    assert manifest["files"]["projection"] == "codex-projection.json"
    assert manifest["drift"]["status"] == "initial"
    assert manifest["drift"]["install_surface_changed"] is False
    assert compiled["drift_status"] == "initial"


def test_compile_rp_writes_bundle_projection_install_surface_and_manifest(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".rp" / "compiled"

    compiled = compile_rp(ai_root, output_dir)

    bundle = compiled["bundle_path"].read_text(encoding="utf-8")
    projection = json.loads(compiled["projection_path"].read_text(encoding="utf-8"))
    install_surface = json.loads(compiled["install_surface_path"].read_text(encoding="utf-8"))
    manifest = json.loads(compiled["manifest_path"].read_text(encoding="utf-8"))

    assert "## RepoPrompt Host Contract" in bundle
    assert "## Host Bundle / Install Surface" in bundle
    assert "Native variant note:" in bundle
    assert "rp/manual`, `rp/auto" in bundle
    assert "uv run aiwf run implement --task .ai/tasks/<task>.md --adapter rp" in bundle
    assert "rp, rp-cli" in bundle
    assert "aiwf-rp-native/v1" in bundle

    assert projection["host"]["name"] == "repoprompt"
    assert projection["host"]["stored_runtime_key"] == "host_contract"
    assert projection["host"]["default_variant"] == "rp/manual"
    assert projection["host"]["variants"]["manual"] == resolve_adapter_contract("rp", auto=False).to_metadata()
    assert projection["host"]["variants"]["auto"] == resolve_adapter_contract("rp", auto=True).to_metadata()
    assert projection["host"]["variants"]["auto"]["native_runtime"]["protocol_version"] == 1
    assert projection["workflow_contract"]["plan"]["auto_entrypoint"] == (
        "uv run aiwf run plan --task .ai/tasks/<task>.md --adapter rp --auto"
    )
    assert projection["workflow_contract"]["implement"]["manual_handoff_artifact"] == "rp-agent-implement-prompt.md"
    assert projection["workflow_contract"]["implement"]["auto_stage_output_artifact"] == "rp-agent-implement-response.md"
    assert projection["workflow_contract"]["implement"]["auto_entrypoint"] == (
        "uv run aiwf run implement --task .ai/tasks/<task>.md --adapter rp --auto"
    )
    assert projection["workflow_contract"]["review"]["report_contract"]["auto"]["expected_report_mode"] == "auto"
    assert projection["artifacts"]["bundle"] == "rp-bundle.md"
    assert projection["artifacts"]["install_surface"] == "install-surface.json"
    assert projection["install_surface"]["default_output_dir"] == ".rp/compiled"
    assert projection["install_surface"]["external_assets"] == []

    assert install_surface["install_strategy"] == "use_compiled_output_directory"
    assert install_surface["default_output_dir"] == ".rp/compiled"
    assert install_surface["external_assets"] == []

    assert manifest["compiler"]["projection_contract"] == "rp-host-projection-v2"
    assert manifest["files"]["rp_bundle"] == "rp-bundle.md"
    assert manifest["files"]["install_surface"] == "install-surface.json"
    assert manifest["files"]["projection"] == "rp-projection.json"
    assert manifest["drift"]["status"] == "initial"
    assert manifest["drift"]["install_surface_changed"] is False
    assert compiled["drift_status"] == "initial"


def test_compiler_registry_exposes_host_specs_backed_by_adapter_contracts() -> None:
    claude_spec = COMPILER_SPECS["claude"]
    codex_spec = COMPILER_SPECS["codex"]
    rp_spec = COMPILER_SPECS["rp"]

    assert claude_spec.projection_name == "claude-host-projection"
    assert claude_spec.variants["manual"] == resolve_adapter_contract("claude", auto=False)
    assert claude_spec.variants["auto"] == resolve_adapter_contract("claude", auto=True)

    assert codex_spec.projection_name == "codex-host-projection"
    assert codex_spec.variants["manual"] == resolve_adapter_contract("codex", auto=False)
    assert sorted(codex_spec.variants) == ["manual"]

    assert rp_spec.projection_name == "rp-host-projection"
    assert rp_spec.variants["manual"] == resolve_adapter_contract("rp", auto=False)
    assert rp_spec.variants["auto"] == resolve_adapter_contract("rp", auto=True)


def test_compile_claude_projection_matches_compat_fixture(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".claude" / "compiled"

    compiled = compile_claude(ai_root, output_dir)
    projection = json.loads(compiled["projection_path"].read_text(encoding="utf-8"))
    expected = json.loads((FIXTURES_DIR / "claude_projection_compat.json").read_text(encoding="utf-8"))

    assert _auto_capable_projection_compat_view(projection) == expected


def test_compile_codex_projection_matches_compat_fixture(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".codex" / "compiled"

    compiled = compile_codex(ai_root, output_dir)
    projection = json.loads(compiled["projection_path"].read_text(encoding="utf-8"))
    expected = json.loads((FIXTURES_DIR / "codex_projection_compat.json").read_text(encoding="utf-8"))

    assert _manual_projection_compat_view(projection) == expected


def test_compile_rp_projection_matches_compat_fixture(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".rp" / "compiled"

    compiled = compile_rp(ai_root, output_dir)
    projection = json.loads(compiled["projection_path"].read_text(encoding="utf-8"))
    expected = json.loads((FIXTURES_DIR / "rp_projection_compat.json").read_text(encoding="utf-8"))

    assert _auto_capable_projection_compat_view(projection) == expected


def test_compile_cross_host_projection_surface_matches_common_contract_structure(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    claude_output_dir = tmp_path / ".claude" / "compiled"
    codex_output_dir = tmp_path / ".codex" / "compiled"
    rp_output_dir = tmp_path / ".rp" / "compiled"

    claude_compiled = compile_claude(ai_root, claude_output_dir)
    codex_compiled = compile_codex(ai_root, codex_output_dir)
    rp_compiled = compile_rp(ai_root, rp_output_dir)
    claude_projection = json.loads(claude_compiled["projection_path"].read_text(encoding="utf-8"))
    codex_projection = json.loads(codex_compiled["projection_path"].read_text(encoding="utf-8"))
    rp_projection = json.loads(rp_compiled["projection_path"].read_text(encoding="utf-8"))

    common_view = _common_projection_contract_view(claude_projection)
    assert common_view == _common_projection_contract_view(codex_projection)
    assert common_view == _common_projection_contract_view(rp_projection)


def test_compile_claude_projection_exposes_required_contract_paths(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".claude" / "compiled"

    compiled = compile_claude(ai_root, output_dir)
    projection = json.loads(compiled["projection_path"].read_text(encoding="utf-8"))
    actual_paths = _flatten_mapping_paths(projection)

    assert {
        "schema_version",
        "projection_name",
        "host.name",
        "host.display_name",
        "host.stored_runtime_key",
        "host.default_variant",
        "host.variants.manual.adapter",
        "host.variants.manual.mode",
        "host.variants.manual.capabilities.supports_auto_execution",
        "host.variants.manual.capabilities.requires_explicit_review_handoff",
        "host.variants.manual.review.required_run_artifacts",
        "host.variants.manual.review.required_report_string_fields",
        "host.variants.manual.review.required_report_list_fields",
        "host.variants.manual.review.expected_report_mode",
        "host.variants.manual.review.linked_report_artifact_field",
        "host.variants.auto.adapter",
        "host.variants.auto.mode",
        "host.variants.auto.capabilities.supports_auto_execution",
        "host.variants.auto.capabilities.requires_explicit_review_handoff",
        "host.variants.auto.review.required_run_artifacts",
        "host.variants.auto.review.required_report_string_fields",
        "host.variants.auto.review.required_report_list_fields",
        "host.variants.auto.review.expected_report_mode",
        "host.variants.auto.review.linked_report_artifact_field",
        "artifacts.bundle",
        "artifacts.install_surface",
        "artifacts.manifest",
        "install_surface.install_strategy",
        "install_surface.default_output_dir",
        "install_surface.resolved_output_dir",
        "commands.plan",
        "commands.implement",
        "commands.review",
        "commands.resume",
        "workflow_contract.plan.entrypoint",
        "workflow_contract.plan.primary_artifacts",
        "workflow_contract.implement.entrypoint",
        "workflow_contract.implement.manual_handoff_artifact",
        "workflow_contract.implement.resume_boundary",
        "workflow_contract.review.entrypoint",
        "workflow_contract.review.requires_status",
        "workflow_contract.review.required_run_artifacts",
        "workflow_contract.review.report_contract.manual.expected_report_mode",
        "workflow_contract.review.report_contract.manual.linked_report_artifact_field",
        "workflow_contract.review.report_contract.auto.expected_report_mode",
        "workflow_contract.review.report_contract.auto.linked_report_artifact_field",
        "workflow_contract.resume.entrypoint",
        "workflow_contract.resume.restores_run_metadata",
        "projection_inputs",
        "projection_hashes.bundle_sha256",
    } <= actual_paths


def test_compile_codex_projection_exposes_required_contract_paths(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".codex" / "compiled"

    compiled = compile_codex(ai_root, output_dir)
    projection = json.loads(compiled["projection_path"].read_text(encoding="utf-8"))
    actual_paths = _flatten_mapping_paths(projection)

    assert {
        "schema_version",
        "projection_name",
        "host.name",
        "host.display_name",
        "host.stored_runtime_key",
        "host.default_variant",
        "host.variants.manual.adapter",
        "host.variants.manual.mode",
        "host.variants.manual.capabilities.supports_auto_execution",
        "host.variants.manual.capabilities.requires_explicit_review_handoff",
        "host.variants.manual.review.required_run_artifacts",
        "host.variants.manual.review.required_report_string_fields",
        "host.variants.manual.review.required_report_list_fields",
        "host.variants.manual.review.expected_report_mode",
        "host.variants.manual.review.linked_report_artifact_field",
        "artifacts.bundle",
        "artifacts.install_surface",
        "artifacts.manifest",
        "install_surface.install_strategy",
        "install_surface.default_output_dir",
        "install_surface.resolved_output_dir",
        "commands.plan",
        "commands.implement",
        "commands.review",
        "commands.resume",
        "workflow_contract.plan.entrypoint",
        "workflow_contract.plan.primary_artifacts",
        "workflow_contract.implement.entrypoint",
        "workflow_contract.implement.manual_handoff_artifact",
        "workflow_contract.implement.resume_boundary",
        "workflow_contract.review.entrypoint",
        "workflow_contract.review.requires_status",
        "workflow_contract.review.required_run_artifacts",
        "workflow_contract.review.report_contract.manual.expected_report_mode",
        "workflow_contract.review.report_contract.manual.linked_report_artifact_field",
        "workflow_contract.resume.entrypoint",
        "workflow_contract.resume.restores_run_metadata",
        "projection_inputs",
        "projection_hashes.bundle_sha256",
    } <= actual_paths


def test_compile_rp_projection_exposes_required_contract_paths(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".rp" / "compiled"

    compiled = compile_rp(ai_root, output_dir)
    projection = json.loads(compiled["projection_path"].read_text(encoding="utf-8"))
    actual_paths = _flatten_mapping_paths(projection)

    assert {
        "schema_version",
        "projection_name",
        "host.name",
        "host.display_name",
        "host.stored_runtime_key",
        "host.default_variant",
        "host.variants.manual.adapter",
        "host.variants.manual.mode",
        "host.variants.manual.native_runtime.protocol_version",
        "host.variants.auto.adapter",
        "host.variants.auto.mode",
        "host.variants.auto.native_runtime.protocol_version",
        "artifacts.bundle",
        "artifacts.install_surface",
        "artifacts.manifest",
        "install_surface.install_strategy",
        "install_surface.default_output_dir",
        "install_surface.resolved_output_dir",
        "commands.plan",
        "commands.implement",
        "commands.review",
        "commands.resume",
        "workflow_contract.plan.entrypoint",
        "workflow_contract.plan.auto_entrypoint",
        "workflow_contract.plan.primary_artifacts",
        "workflow_contract.implement.entrypoint",
        "workflow_contract.implement.manual_handoff_artifact",
        "workflow_contract.implement.auto_stage_output_artifact",
        "workflow_contract.implement.auto_entrypoint",
        "workflow_contract.implement.resume_boundary",
        "workflow_contract.review.entrypoint",
        "workflow_contract.review.requires_status",
        "workflow_contract.review.required_run_artifacts",
        "workflow_contract.review.report_contract.manual.expected_report_mode",
        "workflow_contract.review.report_contract.auto.expected_report_mode",
        "workflow_contract.resume.entrypoint",
        "workflow_contract.resume.restores_run_metadata",
        "projection_inputs",
        "projection_hashes.bundle_sha256",
    } <= actual_paths


def test_compile_claude_tracks_manifest_drift_against_previous_projection(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".claude" / "compiled"

    compile_claude(ai_root, output_dir)
    second = compile_claude(ai_root, output_dir)
    clean_manifest = json.loads(second["manifest_path"].read_text(encoding="utf-8"))

    assert second["drift_status"] == "clean"
    assert clean_manifest["drift"]["status"] == "clean"
    assert clean_manifest["drift"]["source_changes"]["changed"] == []
    assert clean_manifest["drift"]["bundle_changed"] is False
    assert clean_manifest["drift"]["install_surface_changed"] is False

    (ai_root / "policies" / "repo-policy.md").write_text(
        "# Policy\n\nKeep artifacts readable and traceable.\n",
        encoding="utf-8",
    )

    third = compile_claude(ai_root, output_dir)
    changed_manifest = json.loads(third["manifest_path"].read_text(encoding="utf-8"))

    assert third["drift_status"] == "changed"
    assert changed_manifest["drift"]["status"] == "changed"
    assert changed_manifest["drift"]["source_changes"]["changed"] == [".ai/policies/repo-policy.md"]
    assert changed_manifest["drift"]["bundle_changed"] is True
    assert changed_manifest["drift"]["projection_changed"] is True
    assert changed_manifest["drift"]["install_surface_changed"] is False


def test_compile_codex_tracks_manifest_drift_against_previous_projection(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".codex" / "compiled"

    compile_codex(ai_root, output_dir)
    second = compile_codex(ai_root, output_dir)
    clean_manifest = json.loads(second["manifest_path"].read_text(encoding="utf-8"))

    assert second["drift_status"] == "clean"
    assert clean_manifest["drift"]["status"] == "clean"
    assert clean_manifest["drift"]["source_changes"]["changed"] == []
    assert clean_manifest["drift"]["bundle_changed"] is False
    assert clean_manifest["drift"]["install_surface_changed"] is False

    (ai_root / "gates" / "default.yaml").write_text(
        "\n".join(
            [
                "name: default",
                "description: compile test gates",
                "gates:",
                "  - name: lint",
                "    command: 'ruff check src/ tests/'",
                "    timeout_seconds: 180",
            ]
        ),
        encoding="utf-8",
    )

    third = compile_codex(ai_root, output_dir)
    changed_manifest = json.loads(third["manifest_path"].read_text(encoding="utf-8"))

    assert third["drift_status"] == "changed"
    assert changed_manifest["drift"]["status"] == "changed"
    assert changed_manifest["drift"]["source_changes"]["changed"] == [".ai/gates/default.yaml"]
    assert changed_manifest["drift"]["bundle_changed"] is True
    assert changed_manifest["drift"]["projection_changed"] is True
    assert changed_manifest["drift"]["install_surface_changed"] is False


def test_compile_rp_tracks_manifest_drift_against_previous_projection(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".rp" / "compiled"

    compile_rp(ai_root, output_dir)
    second = compile_rp(ai_root, output_dir)
    clean_manifest = json.loads(second["manifest_path"].read_text(encoding="utf-8"))

    assert second["drift_status"] == "clean"
    assert clean_manifest["drift"]["status"] == "clean"
    assert clean_manifest["drift"]["install_surface_changed"] is False

    (ai_root / "runbooks" / "default.md").write_text(
        "\n".join(
            [
                "---",
                "name: default",
                "description: compile test runbook",
                "stages:",
                "  - name: discover",
                "  - name: plan",
                "  - name: implement",
                "---",
                "",
                "# Default Runbook",
            ]
        ),
        encoding="utf-8",
    )

    third = compile_rp(ai_root, output_dir)
    changed_manifest = json.loads(third["manifest_path"].read_text(encoding="utf-8"))

    assert third["drift_status"] == "changed"
    assert changed_manifest["drift"]["status"] == "changed"
    assert changed_manifest["drift"]["source_changes"]["changed"] == [".ai/runbooks/default.md"]
    assert changed_manifest["drift"]["bundle_changed"] is True
    assert changed_manifest["drift"]["projection_changed"] is True
    assert changed_manifest["drift"]["install_surface_changed"] is False


def test_compile_claude_treats_older_manifest_without_hashes_as_initial(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".claude" / "compiled"
    output_dir.mkdir(parents=True)
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T00:00:00+00:00",
                "source_index": [
                    {
                        "kind": "policy",
                        "logical_name": "repo-policy",
                        "source_path": ".ai/policies/repo-policy.md",
                        "sha256": "legacy-hash",
                    }
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    compiled = compile_claude(ai_root, output_dir)
    manifest = json.loads(compiled["manifest_path"].read_text(encoding="utf-8"))

    assert compiled["drift_status"] == "initial"
    assert manifest["drift"]["status"] == "initial"
    assert manifest["drift"]["notes"] == ["Previous manifest did not include compatible output hashes."]


def test_compile_codex_treats_older_manifest_without_hashes_as_initial(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".codex" / "compiled"
    output_dir.mkdir(parents=True)
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T00:00:00+00:00",
                "source_index": [
                    {
                        "kind": "policy",
                        "logical_name": "repo-policy",
                        "source_path": ".ai/policies/repo-policy.md",
                        "sha256": "legacy-hash",
                    }
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    compiled = compile_codex(ai_root, output_dir)
    manifest = json.loads(compiled["manifest_path"].read_text(encoding="utf-8"))

    assert compiled["drift_status"] == "initial"
    assert manifest["drift"]["status"] == "initial"
    assert manifest["drift"]["notes"] == ["Previous manifest did not include compatible output hashes."]


def test_compile_claude_cli_command_succeeds(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".claude" / "compiled"

    result = runner.invoke(
        app,
        [
            "compile",
            "claude",
            "--ai-root",
            str(ai_root),
            "--output",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    assert "compile completed" in result.stdout
    assert "projection=" in result.stdout
    assert "install=" in result.stdout
    assert "drift=initial" in result.stdout
    assert (output_dir / "claude-bundle.md").exists()
    assert (output_dir / "claude-projection.json").exists()
    assert (output_dir / "install-surface.json").exists()
    assert (output_dir / "manifest.json").exists()


def test_compile_codex_cli_command_succeeds(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".codex" / "compiled"

    result = runner.invoke(
        app,
        [
            "compile",
            "codex",
            "--ai-root",
            str(ai_root),
            "--output",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    assert "compile completed" in result.stdout
    assert "projection=" in result.stdout
    assert "install=" in result.stdout
    assert "drift=initial" in result.stdout
    assert (output_dir / "codex-bundle.md").exists()
    assert (output_dir / "codex-projection.json").exists()
    assert (output_dir / "install-surface.json").exists()
    assert (output_dir / "manifest.json").exists()


def test_compile_rp_cli_command_succeeds(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".rp" / "compiled"

    result = runner.invoke(
        app,
        [
            "compile",
            "rp",
            "--ai-root",
            str(ai_root),
            "--output",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    assert "compile completed" in result.stdout
    assert "projection=" in result.stdout
    assert "install=" in result.stdout
    assert "drift=initial" in result.stdout
    assert (output_dir / "rp-bundle.md").exists()
    assert (output_dir / "rp-projection.json").exists()
    assert (output_dir / "install-surface.json").exists()
    assert (output_dir / "manifest.json").exists()


def test_compile_claude_install_surface_explicitly_marks_skills_as_handwritten(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".claude" / "compiled"

    compiled = compile_claude(ai_root, output_dir)
    install_surface = json.loads(compiled["install_surface_path"].read_text(encoding="utf-8"))

    assert install_surface["external_assets"] == [
        {
            "path": ".claude/skills",
            "owner": "handwritten",
            "managed_by_compiler": False,
            "rationale": (
                "Claude skill prompts remain handwritten source assets; compile only owns generated "
                "bundle artifacts under .claude/compiled."
            ),
        }
    ]


def _create_ai_sources(tmp_path: Path) -> Path:
    ai_root = tmp_path / ".ai"
    (ai_root / "runbooks").mkdir(parents=True)
    (ai_root / "policies").mkdir()
    (ai_root / "gates").mkdir()

    (ai_root / "runbooks" / "default.md").write_text(
        "\n".join(
            [
                "---",
                "name: default",
                "description: compile test runbook",
                "stages:",
                "  - name: discover",
                "  - name: plan",
                "---",
                "",
                "# Default Runbook",
            ]
        ),
        encoding="utf-8",
    )
    (ai_root / "policies" / "repo-policy.md").write_text(
        "# Policy\n\nKeep artifacts readable.\n",
        encoding="utf-8",
    )
    (ai_root / "gates" / "default.yaml").write_text(
        "\n".join(
            [
                "name: default",
                "description: compile test gates",
                "gates:",
                "  - name: lint",
                "    command: 'ruff check src/ tests/'",
                "    timeout_seconds: 120",
            ]
        ),
        encoding="utf-8",
    )
    return ai_root


def _auto_capable_projection_compat_view(projection: dict[str, object]) -> dict[str, object]:
    host = projection["host"]
    workflow_contract = projection["workflow_contract"]
    projection_inputs = projection["projection_inputs"]
    projection_hashes = projection["projection_hashes"]
    install_surface = projection["install_surface"]

    assert isinstance(host, dict)
    assert isinstance(workflow_contract, dict)
    assert isinstance(projection_inputs, list)
    assert isinstance(projection_hashes, dict)
    assert isinstance(install_surface, dict)

    return {
        "schema_version": projection["schema_version"],
        "projection_name": projection["projection_name"],
        "host": {
            "name": host["name"],
            "display_name": host["display_name"],
            "stored_runtime_key": host["stored_runtime_key"],
            "default_variant": host["default_variant"],
            "variants": {
                "manual": host["variants"]["manual"],
                "auto": host["variants"]["auto"],
            },
        },
        "artifacts": projection["artifacts"],
        "install_surface": _install_surface_summary(install_surface),
        "commands": projection["commands"],
        "workflow_contract": workflow_contract,
        "projection_inputs": _projection_input_summary(projection_inputs),
        "projection_hash_keys": sorted(projection_hashes),
    }


def _manual_projection_compat_view(projection: dict[str, object]) -> dict[str, object]:
    host = projection["host"]
    workflow_contract = projection["workflow_contract"]
    projection_inputs = projection["projection_inputs"]
    projection_hashes = projection["projection_hashes"]
    install_surface = projection["install_surface"]

    assert isinstance(host, dict)
    assert isinstance(workflow_contract, dict)
    assert isinstance(projection_inputs, list)
    assert isinstance(projection_hashes, dict)
    assert isinstance(install_surface, dict)

    return {
        "schema_version": projection["schema_version"],
        "projection_name": projection["projection_name"],
        "host": {
            "name": host["name"],
            "display_name": host["display_name"],
            "stored_runtime_key": host["stored_runtime_key"],
            "default_variant": host["default_variant"],
            "variants": {
                "manual": host["variants"]["manual"],
            },
        },
        "artifacts": projection["artifacts"],
        "install_surface": _install_surface_summary(install_surface),
        "commands": projection["commands"],
        "workflow_contract": workflow_contract,
        "projection_inputs": _projection_input_summary(projection_inputs),
        "projection_hash_keys": sorted(projection_hashes),
    }


def _common_projection_contract_view(projection: dict[str, object]) -> dict[str, object]:
    host = projection["host"]
    artifacts = projection["artifacts"]
    commands = projection["commands"]
    workflow_contract = projection["workflow_contract"]
    projection_inputs = projection["projection_inputs"]
    projection_hashes = projection["projection_hashes"]
    install_surface = projection["install_surface"]

    assert isinstance(host, dict)
    assert isinstance(artifacts, dict)
    assert isinstance(commands, dict)
    assert isinstance(workflow_contract, dict)
    assert isinstance(projection_inputs, list)
    assert isinstance(projection_hashes, dict)
    assert isinstance(install_surface, dict)

    manual_variant = _require_mapping(_require_mapping(host, "variants"), "manual")
    manual_capabilities = _require_mapping(manual_variant, "capabilities")
    manual_variant_review = _require_mapping(manual_variant, "review")
    manual_review_contract = _require_mapping(_require_mapping(workflow_contract, "review"), "report_contract")
    manual_review = _require_mapping(manual_review_contract, "manual")

    return {
        "schema_version": projection["schema_version"],
        "host": {
            "stored_runtime_key": host["stored_runtime_key"],
            "default_variant_suffix": str(host["default_variant"]).split("/", maxsplit=1)[-1],
            "manual_variant": {
                "mode": manual_variant["mode"],
                "capability_keys": sorted(manual_capabilities),
                "review": {
                    "required_run_artifacts": manual_variant_review["required_run_artifacts"],
                    "required_report_string_fields": manual_variant_review["required_report_string_fields"],
                    "required_report_list_fields": manual_variant_review["required_report_list_fields"],
                    "expected_report_mode": manual_variant_review["expected_report_mode"],
                    "linked_report_artifact_field": manual_variant_review["linked_report_artifact_field"],
                },
            },
        },
        "artifacts": {
            "keys": sorted(artifacts),
            "manifest": artifacts["manifest"],
        },
        "install_surface": {
            "install_strategy": install_surface["install_strategy"],
            "generated_asset_roles": [asset["role"] for asset in install_surface["generated_assets"]],
        },
        "commands": {
            "keys": sorted(commands),
            "review": commands["review"],
            "resume": commands["resume"],
        },
        "workflow_contract": {
            "keys": sorted(workflow_contract),
            "plan": {
                "has_entrypoint": "entrypoint" in _require_mapping(workflow_contract, "plan"),
                "primary_artifacts": _require_mapping(workflow_contract, "plan")["primary_artifacts"],
            },
            "implement": {
                "has_entrypoint": "entrypoint" in _require_mapping(workflow_contract, "implement"),
                "has_manual_handoff_artifact": "manual_handoff_artifact" in _require_mapping(
                    workflow_contract, "implement"
                ),
                "has_resume_boundary": "resume_boundary" in _require_mapping(workflow_contract, "implement"),
            },
            "review": {
                "requires_status": _require_mapping(workflow_contract, "review")["requires_status"],
                "required_run_artifacts": _require_mapping(workflow_contract, "review")["required_run_artifacts"],
                "manual_report_contract": {
                    "required_run_artifacts": manual_review["required_run_artifacts"],
                    "required_report_string_fields": manual_review["required_report_string_fields"],
                    "required_report_list_fields": manual_review["required_report_list_fields"],
                    "expected_report_mode": manual_review["expected_report_mode"],
                    "linked_report_artifact_field": manual_review["linked_report_artifact_field"],
                },
            },
            "resume": {
                "restores_run_metadata": _require_mapping(workflow_contract, "resume")["restores_run_metadata"],
            },
        },
        "projection_inputs": _projection_input_summary(projection_inputs),
        "projection_hash_keys": sorted(projection_hashes),
    }


def _install_surface_summary(install_surface: dict[str, object]) -> dict[str, object]:
    generated_assets = install_surface["generated_assets"]
    external_assets = install_surface["external_assets"]
    assert isinstance(generated_assets, list)
    assert isinstance(external_assets, list)
    return {
        "install_strategy": install_surface["install_strategy"],
        "default_output_dir": install_surface["default_output_dir"],
        "generated_asset_roles": [
            asset["role"]
            for asset in generated_assets
            if isinstance(asset, dict) and isinstance(asset.get("role"), str)
        ],
        "external_assets": external_assets,
    }


def _projection_input_summary(projection_inputs: list[object]) -> dict[str, object]:
    return {
        "count": len(projection_inputs),
        "entry_keys": sorted(
            {
                key
                for entry in projection_inputs
                if isinstance(entry, dict)
                for key in entry
            }
        ),
        "kind_counts": {
            "gate": sum(1 for entry in projection_inputs if isinstance(entry, dict) and entry.get("kind") == "gate"),
            "policy": sum(1 for entry in projection_inputs if isinstance(entry, dict) and entry.get("kind") == "policy"),
            "runbook": sum(
                1 for entry in projection_inputs if isinstance(entry, dict) and entry.get("kind") == "runbook"
            ),
        },
    }


def _require_mapping(payload: dict[str, object], key: str) -> dict[str, Any]:
    value = payload[key]
    assert isinstance(value, dict)
    return value


def _flatten_mapping_paths(payload: dict[str, object], prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for key, value in payload.items():
        current = f"{prefix}.{key}" if prefix else key
        paths.add(current)
        if isinstance(value, dict):
            paths.update(_flatten_mapping_paths(value, prefix=current))
    return paths
