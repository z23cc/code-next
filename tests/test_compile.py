from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from aiwf.adapters import resolve_adapter_contract
from aiwf.cli import app
from aiwf.compilers import COMPILER_SPECS
from aiwf.compilers.claude import compile_claude


runner = CliRunner()
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_compile_claude_writes_bundle_projection_and_manifest(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".claude" / "compiled"

    compiled = compile_claude(ai_root, output_dir)

    bundle = compiled["bundle_path"].read_text(encoding="utf-8")
    projection = json.loads(compiled["projection_path"].read_text(encoding="utf-8"))
    manifest = json.loads(compiled["manifest_path"].read_text(encoding="utf-8"))

    assert "## Claude Host Contract" in bundle
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
    assert manifest["compiler"]["projection_contract"] == "claude-host-projection-v2"
    assert manifest["files"]["claude_bundle"] == "claude-bundle.md"
    assert manifest["sources"]["runbooks"] == ["default.md"]
    assert manifest["sources"]["gates"] == ["default.yaml"]
    assert manifest["files"]["projection"] == "claude-projection.json"
    assert manifest["drift"]["status"] == "initial"
    assert compiled["drift_status"] == "initial"


def test_compiler_registry_exposes_claude_spec_backed_by_adapter_contracts() -> None:
    spec = COMPILER_SPECS["claude"]

    assert spec is COMPILER_SPECS["claude"]
    assert spec.projection_name == "claude-host-projection"
    assert spec.variants["manual"] == resolve_adapter_contract("claude", auto=False)
    assert spec.variants["auto"] == resolve_adapter_contract("claude", auto=True)


def test_compile_claude_projection_matches_compat_fixture(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".claude" / "compiled"

    compiled = compile_claude(ai_root, output_dir)
    projection = json.loads(compiled["projection_path"].read_text(encoding="utf-8"))
    expected = json.loads((FIXTURES_DIR / "claude_projection_compat.json").read_text(encoding="utf-8"))

    assert _projection_compat_view(projection) == expected


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
        "artifacts.manifest",
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
    assert "drift=initial" in result.stdout
    assert (output_dir / "claude-bundle.md").exists()
    assert (output_dir / "claude-projection.json").exists()
    assert (output_dir / "manifest.json").exists()


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


def _projection_compat_view(projection: dict[str, object]) -> dict[str, object]:
    host = projection["host"]
    workflow_contract = projection["workflow_contract"]
    projection_inputs = projection["projection_inputs"]
    projection_hashes = projection["projection_hashes"]

    assert isinstance(host, dict)
    assert isinstance(workflow_contract, dict)
    assert isinstance(projection_inputs, list)
    assert isinstance(projection_hashes, dict)

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
        "commands": projection["commands"],
        "workflow_contract": workflow_contract,
        "projection_inputs": {
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
                "policy": sum(
                    1 for entry in projection_inputs if isinstance(entry, dict) and entry.get("kind") == "policy"
                ),
                "runbook": sum(
                    1 for entry in projection_inputs if isinstance(entry, dict) and entry.get("kind") == "runbook"
                ),
            },
        },
        "projection_hash_keys": sorted(projection_hashes),
    }


def _flatten_mapping_paths(payload: dict[str, object], prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for key, value in payload.items():
        current = f"{prefix}.{key}" if prefix else key
        paths.add(current)
        if isinstance(value, dict):
            paths.update(_flatten_mapping_paths(value, current))
    return paths
