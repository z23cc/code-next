from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from aiwf.cli import app
from aiwf.compilers.claude import compile_claude


runner = CliRunner()


def test_compile_claude_writes_bundle_and_manifest(tmp_path: Path) -> None:
    ai_root = _create_ai_sources(tmp_path)
    output_dir = tmp_path / ".claude" / "compiled"

    compiled = compile_claude(ai_root, output_dir)

    bundle = compiled["bundle_path"].read_text(encoding="utf-8")
    manifest = json.loads(compiled["manifest_path"].read_text(encoding="utf-8"))

    assert "## Policies" in bundle
    assert "## Runbooks" in bundle
    assert "## Gates" in bundle
    assert "## Suggested Commands" in bundle
    assert "uv run aiwf run review --run-id <run_id>" in bundle
    assert "uv run aiwf resume <run_id>" in bundle
    assert "- discover: no description" in bundle
    assert manifest["sources"]["runbooks"] == ["default.md"]
    assert manifest["sources"]["gates"] == ["default.yaml"]


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
    assert (output_dir / "claude-bundle.md").exists()
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
