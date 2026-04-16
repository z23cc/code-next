from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

from typer.testing import CliRunner

from aiwf.cli import app
from aiwf.conformance import run_rp_conformance
from tests.test_adapter_rp import _write_fake_rp_runtime


runner = CliRunner()
_STUB_SRC = Path(__file__).resolve().parents[1] / "tools" / "rp-cli-stub" / "src"


def test_run_rp_conformance_passes_against_fake_runtime(tmp_path: Path) -> None:
    runtime_script = _write_fake_rp_runtime(tmp_path)

    report = run_rp_conformance(
        [sys.executable, str(runtime_script), "protocol-conformance"],
        repo_root=tmp_path,
    )

    assert report["ok"] is True
    assert report["scope"] == "reference-stub"
    assert "fake RP runtime harness" in report["scope_reason"]
    assert [check["name"] for check in report["checks"]] == [
        "probe",
        "plan",
        "execute",
        "review",
        "invalid-request",
        "unsupported-version",
        "legacy-raw",
    ]
    assert all(check["ok"] for check in report["checks"])


def test_run_rp_conformance_passes_against_standalone_stub_entrypoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    existing_pythonpath = os.environ.get("PYTHONPATH")
    pythonpath_parts = [str(_STUB_SRC)]
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(pythonpath_parts))

    report = run_rp_conformance(
        [sys.executable, "-m", "rp_cli_stub"],
        repo_root=tmp_path,
    )

    assert report["ok"] is True
    assert report["scope"] == "reference-stub"
    assert "rp-cli-stub" in report["scope_reason"]
    assert [check["name"] for check in report["checks"]] == [
        "probe",
        "plan",
        "execute",
        "review",
        "invalid-request",
        "unsupported-version",
        "legacy-raw",
    ]
    assert all(check["ok"] for check in report["checks"])


def test_run_rp_conformance_defaults_external_like_runtime_to_untrusted_scope(tmp_path: Path) -> None:
    runtime_script = _write_external_like_rp_runtime(tmp_path)

    report = run_rp_conformance(
        [sys.executable, str(runtime_script), "protocol-conformance"],
        repo_root=tmp_path,
    )

    assert report["ok"] is True
    assert report["scope"] == "real-runtime-untrusted"
    assert "non-stub-like runtime candidate" in report["scope_reason"]


def test_cli_conformance_rp_command_emits_json_report(tmp_path: Path) -> None:
    runtime_script = _write_fake_rp_runtime(tmp_path)

    result = runner.invoke(
        app,
        [
            "conformance",
            "rp",
            "--rp-command",
            sys.executable,
            "--rp-arg",
            str(runtime_script),
            "--rp-arg",
            "protocol-conformance",
            "--repo-root",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["scope"] == "reference-stub"
    assert payload["checks"][0]["name"] == "probe"
    assert payload["checks"][-1]["name"] == "legacy-raw"


def test_cli_conformance_rp_command_can_certify_non_stub_runtime(tmp_path: Path) -> None:
    runtime_script = _write_external_like_rp_runtime(tmp_path)

    result = runner.invoke(
        app,
        [
            "conformance",
            "rp",
            "--rp-command",
            sys.executable,
            "--rp-arg",
            str(runtime_script),
            "--rp-arg",
            "protocol-conformance",
            "--repo-root",
            str(tmp_path),
            "--certify-real-runtime",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["scope"] == "real-runtime-certified"
    assert "operator explicitly requested real-runtime certification" in payload["scope_reason"]


def _write_external_like_rp_runtime(tmp_path: Path) -> Path:
    source = _write_fake_rp_runtime(tmp_path)
    external_like = tmp_path / "repoprompt_runtime.py"
    external_like.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    external_like.chmod(external_like.stat().st_mode | stat.S_IXUSR)
    return external_like
