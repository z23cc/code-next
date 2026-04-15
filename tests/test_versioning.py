from __future__ import annotations

import io
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aiwf import __version__
from aiwf.cli import app
from aiwf.release import ReleaseValidationError, build_release_manifest, main as release_main


runner = CliRunner()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _write_test_project(root: Path, *, version: str = "1.2.3") -> None:
    (root / "src" / "aiwf").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "aiwf"',
                f'version = "{version}"',
                'readme = "README.md"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "src" / "aiwf" / "__init__.py").write_text(
        f'__version__ = "{version}"\n',
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        "\n".join(
            [
                "# Changelog",
                "",
                "## Unreleased",
                "",
                f"## {version}",
                "",
                "### Added",
                "- Example release.",
                "",
                "## 1.2.2",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_wheel(path: Path, *, name: str, version: str) -> None:
    dist_info = f"{name.replace('-', '_')}-{version}.dist-info"
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{dist_info}/METADATA", metadata)


def _write_sdist(path: Path, *, name: str, version: str) -> None:
    pkg_info = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    package_dir = f"{name}-{version}"
    with tarfile.open(path, "w:gz") as archive:
        data = pkg_info.encode("utf-8")
        info = tarfile.TarInfo(name=f"{package_dir}/PKG-INFO")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))


def test_package_version_matches_pyproject() -> None:
    pyproject_path = _project_root() / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert pyproject["project"]["version"] == __version__


def test_cli_version_reports_package_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_release_manifest_matches_repository_metadata() -> None:
    manifest = build_release_manifest(_project_root())

    assert manifest["project"]["name"] == "aiwf"
    assert manifest["project"]["version"] == __version__
    assert manifest["project"]["tag"] == f"v{__version__}"
    assert manifest["changelog"]["latest_released_version"] == __version__
    assert manifest["changelog"]["path"] == "CHANGELOG.md"


def test_release_manifest_requires_current_version_heading_in_changelog(tmp_path: Path) -> None:
    _write_test_project(tmp_path, version="1.2.3")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## Unreleased\n\n## 1.2.2\n",
        encoding="utf-8",
    )

    with pytest.raises(ReleaseValidationError, match="release heading for version 1.2.3"):
        build_release_manifest(tmp_path)


def test_release_manifest_rejects_mismatched_expected_tag(tmp_path: Path) -> None:
    _write_test_project(tmp_path, version="1.2.3")

    with pytest.raises(ReleaseValidationError, match="Tag v9.9.9 does not match package version 1.2.3"):
        build_release_manifest(tmp_path, expected_tag="v9.9.9")


def test_release_main_returns_nonzero_for_validation_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_test_project(tmp_path, version="1.2.3")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## 1.2.2\n", encoding="utf-8")

    exit_code = release_main(["verify", "--project-root", str(tmp_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "release metadata error:" in captured.err
    assert "## Unreleased" in captured.err


def test_release_manifest_collects_built_artifact_metadata(tmp_path: Path) -> None:
    _write_test_project(tmp_path, version="1.2.3")
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _write_wheel(dist_dir / "aiwf-1.2.3-py3-none-any.whl", name="aiwf", version="1.2.3")
    _write_sdist(dist_dir / "aiwf-1.2.3.tar.gz", name="aiwf", version="1.2.3")

    manifest = build_release_manifest(tmp_path, dist_dir=dist_dir, expected_tag="v1.2.3")

    assert manifest["project"]["version"] == "1.2.3"
    assert [artifact["type"] for artifact in manifest["artifacts"]] == ["sdist", "wheel"]
    assert {artifact["package_version"] for artifact in manifest["artifacts"]} == {"1.2.3"}
    assert all(len(artifact["sha256"]) == 64 for artifact in manifest["artifacts"])
