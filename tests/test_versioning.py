from __future__ import annotations

import tomllib
from pathlib import Path

from typer.testing import CliRunner

from aiwf import __version__
from aiwf.cli import app


runner = CliRunner()


def test_package_version_matches_pyproject() -> None:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert pyproject["project"]["version"] == __version__


def test_cli_version_reports_package_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == __version__
