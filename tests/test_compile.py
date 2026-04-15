from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from aiwf.cli import app
from aiwf.compilers.claude import compile_claude


runner = CliRunner()


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
    assert "- discover: no description" in bundle
    assert ".ai/policies/repo-policy.md" in bundle
    assert projection["host"]["name"] == "claude_code"
    assert projection["workflow_contract"]["review"]["requires_artifact"] == "verify-report.json"
    assert projection["artifacts"]["bundle"] == "claude-bundle.md"
    assert manifest["sources"]["runbooks"] == ["default.md"]
    assert manifest["sources"]["gates"] == ["default.yaml"]
    assert manifest["files"]["projection"] == "claude-projection.json"
    assert manifest["drift"]["status"] == "initial"
    assert compiled["drift_status"] == "initial"


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
