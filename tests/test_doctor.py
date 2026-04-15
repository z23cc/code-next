from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from aiwf.cli import app
from aiwf.doctor import render_doctor_report, run_doctor


runner = CliRunner()


def test_run_doctor_reports_ok_for_valid_workspace(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command='python -c "print(\'ok\')"')
    _mock_which(
        monkeypatch,
        {
            "python": "/usr/bin/python",
            "uv": "/usr/bin/uv",
            "git": "/usr/bin/git",
        },
    )

    report = run_doctor(ai_root=ai_root, repo_root=repo_root)

    assert report.ok is True
    assert report.summary["fail"] == 0
    assert any(check.name == "runbook:default" and check.status == "ok" for check in report.checks)
    assert any(check.name == "policy:repo-policy" and check.status == "ok" for check in report.checks)
    assert any(check.name == "default:lint" and check.status == "ok" for check in report.checks)
    rendered = render_doctor_report(report)
    assert "summary ok=" in rendered
    assert "OK [workspace] tasks" in rendered


def test_run_doctor_reports_fail_for_missing_structure_and_gate_command(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    ai_root = repo_root / ".ai"
    (ai_root / "runbooks").mkdir(parents=True)
    (ai_root / "policies").mkdir()
    (ai_root / "gates").mkdir()
    (ai_root / "runbooks" / "default.md").write_text(
        "\n".join(
            [
                "---",
                "name: default",
                "stages:",
                "  - name: discover",
                "---",
                "",
                "# Runbook",
            ]
        ),
        encoding="utf-8",
    )
    (ai_root / "policies" / "repo-policy.md").write_text("# Policy\n", encoding="utf-8")
    (ai_root / "gates" / "default.yaml").write_text(
        "\n".join(
            [
                "name: default",
                "gates:",
                "  - name: lint",
                "    command: missing-command --flag",
                "    timeout_seconds: 10",
            ]
        ),
        encoding="utf-8",
    )
    _mock_which(monkeypatch, {"python": "/usr/bin/python"})

    report = run_doctor(ai_root=ai_root, repo_root=repo_root)

    assert report.ok is False
    assert report.summary["fail"] >= 2
    assert any(check.name == "tasks" and check.status == "fail" for check in report.checks)
    assert any(check.name == "default:lint" and check.status == "fail" for check in report.checks)


def test_cli_doctor_human_output_succeeds(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command='python -c "print(\'ok\')"')
    _mock_which(
        monkeypatch,
        {
            "python": "/usr/bin/python",
            "uv": "/usr/bin/uv",
            "git": "/usr/bin/git",
        },
    )

    result = runner.invoke(
        app,
        [
            "doctor",
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
        ],
    )

    assert result.exit_code == 0
    assert "summary ok=" in result.stdout
    assert "OK [gate_command] default:lint" in result.stdout


def test_cli_doctor_json_output_reports_failures(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command="missing-command --flag")
    _mock_which(monkeypatch, {"python": "/usr/bin/python"})

    result = runner.invoke(
        app,
        [
            "doctor",
            "--ai-root",
            str(ai_root),
            "--repo-root",
            str(repo_root),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["summary"]["fail"] >= 1
    assert any(
        check["name"] == "default:lint" and check["status"] == "fail"
        for check in payload["checks"]
    )


def _create_workspace(tmp_path: Path, *, gate_command: str) -> tuple[Path, Path]:
    repo_root = tmp_path / "repo"
    ai_root = repo_root / ".ai"
    (ai_root / "tasks").mkdir(parents=True)
    (ai_root / "runbooks").mkdir()
    (ai_root / "policies").mkdir()
    (ai_root / "gates").mkdir()
    (ai_root / "tasks" / "sample.md").write_text("# Task\n", encoding="utf-8")
    (ai_root / "runbooks" / "default.md").write_text(
        "\n".join(
            [
                "---",
                "name: default",
                "stages:",
                "  - name: discover",
                "---",
                "",
                "# Runbook",
            ]
        ),
        encoding="utf-8",
    )
    (ai_root / "policies" / "repo-policy.md").write_text("# Policy\n", encoding="utf-8")
    escaped_command = gate_command.replace("'", "''")
    (ai_root / "gates" / "default.yaml").write_text(
        "\n".join(
            [
                "name: default",
                "gates:",
                "  - name: lint",
                f"    command: '{escaped_command}'",
                "    timeout_seconds: 10",
            ]
        ),
        encoding="utf-8",
    )
    return repo_root, ai_root


def _mock_which(monkeypatch, mapping: dict[str, str]) -> None:
    def fake_which(command: str) -> str | None:
        return mapping.get(command)

    monkeypatch.setattr("aiwf.doctor.shutil.which", fake_which)
