from __future__ import annotations

import json
import subprocess
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
            "rp": "/usr/bin/rp",
        },
    )
    _mock_protocol_probe(monkeypatch, {"/usr/bin/rp": 1})

    report = run_doctor(ai_root=ai_root, repo_root=repo_root)

    assert report.ok is True
    assert report.summary["fail"] == 0
    assert any(check.name == "runbook:default" and check.status == "ok" for check in report.checks)
    assert any(check.name == "policy:repo-policy" and check.status == "ok" for check in report.checks)
    assert any(check.name == "default:lint" and check.status == "ok" for check in report.checks)
    rp_check = next(check for check in report.checks if check.name == "rp")
    assert rp_check.protocol_supported is True
    assert rp_check.protocol_version == 1
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


def test_run_doctor_reports_rp_manual_only_when_runtime_missing(tmp_path: Path, monkeypatch) -> None:
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

    rp_check = next(check for check in report.checks if check.name == "rp")
    assert rp_check.status == "warn"
    assert "manual-only fallback active" in rp_check.detail
    assert "rp, rp-cli" in rp_check.detail
    assert "protocol v1" in rp_check.detail
    assert rp_check.protocol_supported is False
    assert rp_check.protocol_version is None


def test_run_doctor_reports_rp_native_ready_when_runtime_found(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command='python -c "print(\'ok\')"')
    _mock_which(
        monkeypatch,
        {
            "python": "/usr/bin/python",
            "uv": "/usr/bin/uv",
            "git": "/usr/bin/git",
            "rp-cli": "/usr/local/bin/rp-cli",
        },
    )
    _mock_protocol_probe(monkeypatch, {"/usr/local/bin/rp-cli": 1})

    report = run_doctor(ai_root=ai_root, repo_root=repo_root)

    rp_check = next(check for check in report.checks if check.name == "rp")
    assert rp_check.status == "ok"
    assert rp_check.path == "/usr/local/bin/rp-cli"
    assert "native-ready via rp-cli" in rp_check.detail
    assert "protocol aiwf-rp-native v1 detected" in rp_check.detail
    assert rp_check.protocol_supported is True
    assert rp_check.protocol_version == 1
    payload = report.to_json()
    rp_payload = next(check for check in payload["checks"] if check["name"] == "rp")
    assert rp_payload["protocol_supported"] is True
    assert rp_payload["protocol_version"] == 1


def test_run_doctor_warns_when_rp_runtime_lacks_protocol_support(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command="python -c \"print('ok')\"")
    _mock_which(
        monkeypatch,
        {
            "python": "/usr/bin/python",
            "uv": "/usr/bin/uv",
            "git": "/usr/bin/git",
            "rp": "/usr/bin/rp",
        },
    )
    _mock_protocol_probe(monkeypatch, unsupported_paths={"/usr/bin/rp"})

    report = run_doctor(ai_root=ai_root, repo_root=repo_root)

    rp_check = next(check for check in report.checks if check.name == "rp")
    assert rp_check.status == "warn"
    assert "protocol negotiation support was not detected" in rp_check.detail
    assert "protocol v1" in rp_check.detail
    assert rp_check.protocol_supported is False
    assert rp_check.protocol_version is None


def test_run_doctor_warns_when_rp_runtime_protocol_version_mismatches(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command="python -c \"print('ok')\"")
    _mock_which(
        monkeypatch,
        {
            "python": "/usr/bin/python",
            "uv": "/usr/bin/uv",
            "git": "/usr/bin/git",
            "rp": "/usr/bin/rp",
        },
    )
    _mock_protocol_probe(monkeypatch, {"/usr/bin/rp": 2})

    report = run_doctor(ai_root=ai_root, repo_root=repo_root)

    rp_check = next(check for check in report.checks if check.name == "rp")
    assert rp_check.status == "warn"
    assert "aiwf-rp-native v2" in rp_check.detail
    assert "advertises v1" in rp_check.detail
    assert rp_check.protocol_supported is True
    assert rp_check.protocol_version == 2


def test_cli_doctor_human_output_succeeds(tmp_path: Path, monkeypatch) -> None:
    repo_root, ai_root = _create_workspace(tmp_path, gate_command='python -c "print(\'ok\')"')
    _mock_which(
        monkeypatch,
        {
            "python": "/usr/bin/python",
            "uv": "/usr/bin/uv",
            "git": "/usr/bin/git",
            "rp": "/usr/bin/rp",
        },
    )
    _mock_protocol_probe(monkeypatch, {"/usr/bin/rp": 1})

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


def _mock_protocol_probe(
    monkeypatch,
    version_by_path: dict[str, int] | None = None,
    *,
    unsupported_paths: set[str] | None = None,
) -> None:
    version_by_path = version_by_path or {}
    unsupported_paths = unsupported_paths or set()

    def fake_run(args: list[str], capture_output: bool, text: bool, check: bool, timeout: int) -> subprocess.CompletedProcess[str]:
        assert capture_output is True
        assert text is True
        assert check is False
        assert timeout == 10
        command_path = args[0]
        if command_path in version_by_path:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps({"protocol": "aiwf-rp-native", "version": version_by_path[command_path]}),
                stderr="",
            )
        if command_path in unsupported_paths:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unsupported")
        raise AssertionError(f"Unexpected protocol probe for {command_path}")

    monkeypatch.setattr("aiwf.doctor.subprocess.run", fake_run)
