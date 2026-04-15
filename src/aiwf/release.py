"""Release metadata validation helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Any


VERSION_HEADING_RE = re.compile(r"^##\s+([0-9]+\.[0-9]+\.[0-9]+)\s*$", re.MULTILINE)
UNRELEASED_HEADING_RE = re.compile(r"^##\s+Unreleased\s*$", re.MULTILINE)
VERSION_ASSIGNMENT_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']\s*$', re.MULTILINE)


class ReleaseValidationError(ValueError):
    """Raised when release metadata or build artifacts are inconsistent."""


def normalize_distribution_name(name: str) -> str:
    """Return a normalized distribution name for comparisons."""
    return re.sub(r"[-_.]+", "-", name).lower()


def read_pyproject_metadata(project_root: Path) -> dict[str, str]:
    """Load the project name and version from ``pyproject.toml``."""
    pyproject_path = project_root / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    name = project.get("name")
    version = project.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise ReleaseValidationError(f"Missing project name/version in {pyproject_path}")
    return {"name": name, "version": version}


def read_package_version(project_root: Path) -> str:
    """Extract ``__version__`` from ``src/aiwf/__init__.py``."""
    init_path = project_root / "src" / "aiwf" / "__init__.py"
    init_text = init_path.read_text(encoding="utf-8")
    match = VERSION_ASSIGNMENT_RE.search(init_text)
    if match is None:
        raise ReleaseValidationError(f"Could not find __version__ assignment in {init_path}")
    return match.group(1)


def released_versions(changelog_text: str) -> list[str]:
    """Return released semantic versions found in ``CHANGELOG.md``."""
    return VERSION_HEADING_RE.findall(changelog_text)


def validate_changelog(project_root: Path, version: str) -> dict[str, Any]:
    """Ensure the changelog is present and anchored to the current package version."""
    changelog_path = project_root / "CHANGELOG.md"
    changelog_text = changelog_path.read_text(encoding="utf-8")

    unreleased_match = UNRELEASED_HEADING_RE.search(changelog_text)
    if unreleased_match is None:
        raise ReleaseValidationError("CHANGELOG.md must keep a '## Unreleased' section")

    versions = released_versions(changelog_text)
    if not versions:
        raise ReleaseValidationError("CHANGELOG.md does not contain any released version headings")
    if version not in versions:
        raise ReleaseValidationError(
            f"CHANGELOG.md does not contain a release heading for version {version}"
        )
    if versions[0] != version:
        raise ReleaseValidationError(
            f"CHANGELOG.md latest released version is {versions[0]}, expected {version}"
        )

    first_release_heading = VERSION_HEADING_RE.search(changelog_text)
    assert first_release_heading is not None
    if unreleased_match.start() > first_release_heading.start():
        raise ReleaseValidationError("CHANGELOG.md must place '## Unreleased' before released versions")

    return {
        "path": str(changelog_path.relative_to(project_root)),
        "has_unreleased": True,
        "latest_released_version": versions[0],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_package_metadata(raw_text: str) -> tuple[str, str]:
    parsed = Parser().parsestr(raw_text)
    name = parsed.get("Name")
    version = parsed.get("Version")
    if not name or not version:
        raise ReleaseValidationError("Built artifact metadata is missing Name or Version headers")
    return name, version


def read_wheel_metadata(path: Path) -> dict[str, str]:
    """Read package metadata from a built wheel."""
    with zipfile.ZipFile(path) as archive:
        metadata_members = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_members) != 1:
            raise ReleaseValidationError(
                f"Expected exactly one wheel METADATA file in {path.name}, found {len(metadata_members)}"
            )
        metadata_name = metadata_members[0]
        raw_metadata = archive.read(metadata_name).decode("utf-8")
    name, version = _parse_package_metadata(raw_metadata)
    return {"metadata_path": metadata_name, "name": name, "version": version}


def read_sdist_metadata(path: Path) -> dict[str, str]:
    """Read package metadata from a built source distribution."""
    with tarfile.open(path, mode="r:gz") as archive:
        members = [member for member in archive.getmembers() if member.name.endswith("/PKG-INFO")]
        if not members:
            raise ReleaseValidationError(f"Expected a PKG-INFO file in {path.name}")
        primary_member = min(members, key=lambda member: (member.name.count("/"), len(member.name)))
        pkg_info = archive.extractfile(primary_member)
        if pkg_info is None:
            raise ReleaseValidationError(f"Could not read PKG-INFO from {path.name}")
        raw_metadata = pkg_info.read().decode("utf-8")
    name, version = _parse_package_metadata(raw_metadata)
    return {"metadata_path": primary_member.name, "name": name, "version": version}


def collect_distribution_artifacts(
    dist_dir: Path,
    *,
    project_name: str,
    version: str,
) -> list[dict[str, Any]]:
    """Validate built wheel/sdist artifacts and return release metadata for them."""
    if not dist_dir.is_dir():
        raise ReleaseValidationError(f"Distribution directory does not exist: {dist_dir}")

    filename_base = project_name.replace("-", "_")
    sdists = sorted(dist_dir.glob(f"{filename_base}-{version}.tar.gz"))
    wheels = sorted(dist_dir.glob(f"{filename_base}-{version}-*.whl"))

    if len(sdists) != 1:
        raise ReleaseValidationError(
            f"Expected exactly one sdist for {project_name} {version} in {dist_dir}, found {len(sdists)}"
        )
    if len(wheels) != 1:
        raise ReleaseValidationError(
            f"Expected exactly one wheel for {project_name} {version} in {dist_dir}, found {len(wheels)}"
        )

    artifacts: list[dict[str, Any]] = []
    for kind, path, metadata_loader in (
        ("sdist", sdists[0], read_sdist_metadata),
        ("wheel", wheels[0], read_wheel_metadata),
    ):
        metadata = metadata_loader(path)
        if normalize_distribution_name(metadata["name"]) != normalize_distribution_name(project_name):
            raise ReleaseValidationError(
                f"{path.name} package name {metadata['name']} does not match {project_name}"
            )
        if metadata["version"] != version:
            raise ReleaseValidationError(
                f"{path.name} package version {metadata['version']} does not match {version}"
            )
        artifacts.append(
            {
                "type": kind,
                "filename": path.name,
                "path": str(path.relative_to(dist_dir.parent)),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
                "metadata_path": metadata["metadata_path"],
                "package_name": metadata["name"],
                "package_version": metadata["version"],
            }
        )

    return artifacts


def build_release_manifest(
    project_root: Path,
    *,
    dist_dir: Path | None = None,
    expected_tag: str | None = None,
) -> dict[str, Any]:
    """Build validated release metadata for the current project state."""
    project = read_pyproject_metadata(project_root)
    package_version = read_package_version(project_root)
    if project["version"] != package_version:
        raise ReleaseValidationError(
            f"pyproject version {project['version']} does not match package version {package_version}"
        )

    expected_version_tag = f"v{project['version']}"
    if expected_tag is not None and expected_tag != expected_version_tag:
        raise ReleaseValidationError(
            f"Tag {expected_tag} does not match package version {project['version']}"
        )

    manifest: dict[str, Any] = {
        "project": {
            "name": project["name"],
            "version": project["version"],
            "tag": expected_version_tag,
        },
        "changelog": validate_changelog(project_root, project["version"]),
    }

    if dist_dir is not None:
        manifest["artifacts"] = collect_distribution_artifacts(
            dist_dir,
            project_name=project["name"],
            version=project["version"],
        )

    return manifest


def write_release_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Persist release metadata as formatted JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for release metadata validation."""
    parser = argparse.ArgumentParser(description="Validate aiwf release metadata and built artifacts.")
    parser.add_argument(
        "command",
        nargs="?",
        default="verify",
        choices=["verify"],
        help="Validation action to run.",
    )
    parser.add_argument("--project-root", default=".", help="Repository root to validate.")
    parser.add_argument("--dist", help="Distribution directory to validate.")
    parser.add_argument("--expect-tag", help="Release tag expected for this version, e.g. v1.2.3.")
    parser.add_argument(
        "--write-manifest",
        help="Optional path to write validated release metadata JSON.",
    )
    args = parser.parse_args(argv)

    try:
        manifest = build_release_manifest(
            Path(args.project_root).resolve(),
            dist_dir=Path(args.dist).resolve() if args.dist else None,
            expected_tag=args.expect_tag,
        )
    except ReleaseValidationError as exc:
        print(f"release metadata error: {exc}", file=sys.stderr)
        return 1
    if args.write_manifest:
        write_release_manifest(Path(args.write_manifest).resolve(), manifest)

    artifact_count = len(manifest.get("artifacts", []))
    print(
        f"release metadata OK: {manifest['project']['name']} {manifest['project']['version']} "
        f"({artifact_count} artifacts checked)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
