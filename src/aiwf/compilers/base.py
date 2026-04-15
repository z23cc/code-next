"""Shared compiler helpers for host-specific workflow projections."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiwf.adapters.base import HostContract, HostMode
from aiwf.exceptions import LoadError
from aiwf.loader import load_gate_set, load_runbook
from aiwf.models import utc_now


BundleBuilder = Callable[["CompileContext"], str]
ProjectionBuilder = Callable[["CompileContext", str, dict[str, object]], dict[str, object]]


@dataclass(frozen=True)
class CompileContext:
    """Normalized compile inputs shared across concrete compilers."""

    ai_root: Path
    output_dir: Path
    runbook_files: list[Path]
    policy_files: list[Path]
    gate_files: list[Path]
    source_index: list[dict[str, object]]

    @property
    def traceability(self) -> dict[str, str]:
        return {str(entry["source_path"]): str(entry["sha256"]) for entry in self.source_index}


@dataclass(frozen=True)
class ExternalAssetPolicy:
    """Ownership policy for host assets outside the generated compile bundle."""

    path: str
    owner: str
    managed_by_compiler: bool
    rationale: str

    def to_metadata(self) -> dict[str, object]:
        return {
            "path": self.path,
            "owner": self.owner,
            "managed_by_compiler": self.managed_by_compiler,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class CompilerSpec:
    """Declarative compiler registry entry for a host projection."""

    key: str
    projection_name: str
    variant_namespace: str
    compiler_name: str
    projection_contract: str
    host_name: str
    host_display_name: str
    stored_runtime_key: str
    default_variant: HostMode
    default_output_dir: str
    bundle_filename: str
    projection_filename: str
    install_surface_filename: str
    bundle_manifest_key: str
    variants: Mapping[HostMode, HostContract]
    bundle_builder: BundleBuilder
    projection_builder: ProjectionBuilder
    external_asset_policies: tuple[ExternalAssetPolicy, ...] = ()


def compile_host_projection(spec: CompilerSpec, ai_root: str | Path, output_dir: str | Path) -> dict[str, Path | str]:
    """Compile `.ai/` sources into a host projection described by `spec`."""
    ai_root_path = Path(ai_root)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    runbook_dir = ai_root_path / "runbooks"
    policy_dir = ai_root_path / "policies"
    gate_dir = ai_root_path / "gates"
    _require_directory(runbook_dir, stage=spec.compiler_name)
    _require_directory(policy_dir, stage=spec.compiler_name)
    _require_directory(gate_dir, stage=spec.compiler_name)

    runbook_files = sorted(runbook_dir.glob("*.md"))
    policy_files = sorted(policy_dir.glob("*.md"))
    gate_files = sorted(gate_dir.glob("*.yaml"))
    if not runbook_files:
        raise LoadError("No runbook files found", path=runbook_dir, stage=spec.compiler_name)
    if not policy_files:
        raise LoadError("No policy files found", path=policy_dir, stage=spec.compiler_name)
    if not gate_files:
        raise LoadError("No gate files found", path=gate_dir, stage=spec.compiler_name)

    source_index = build_source_index(ai_root_path, runbook_files, policy_files, gate_files)
    context = CompileContext(
        ai_root=ai_root_path,
        output_dir=output_path,
        runbook_files=runbook_files,
        policy_files=policy_files,
        gate_files=gate_files,
        source_index=source_index,
    )

    compiled_markdown = spec.bundle_builder(context)
    bundle_sha256 = sha256_text(compiled_markdown)

    install_surface = build_install_surface_document(spec=spec, output_dir=output_path)
    install_surface_text = json.dumps(install_surface, indent=2, ensure_ascii=False) + "\n"
    install_surface_sha256 = sha256_text(install_surface_text)

    projection = spec.projection_builder(context, bundle_sha256, install_surface)
    projection_text = json.dumps(projection, indent=2, ensure_ascii=False) + "\n"
    projection_sha256 = sha256_text(projection_text)

    manifest_path = output_path / "manifest.json"
    previous_manifest = load_existing_manifest(manifest_path, stage=spec.compiler_name)
    drift = build_drift_report(
        previous_manifest,
        source_index,
        bundle_sha256,
        projection_sha256,
        install_surface_sha256,
    )

    manifest = {
        "schema_version": 2,
        "generated_at": utc_now().isoformat(),
        "compiler": {
            "name": spec.compiler_name,
            "host": spec.host_name,
            "projection_contract": spec.projection_contract,
        },
        "ai_root": str(ai_root_path),
        "output_dir": str(output_path),
        "files": {
            spec.bundle_manifest_key: spec.bundle_filename,
            "projection": spec.projection_filename,
            "install_surface": spec.install_surface_filename,
            "manifest": "manifest.json",
        },
        "sources": {
            "runbooks": [path.name for path in runbook_files],
            "policies": [path.name for path in policy_files],
            "gates": [path.name for path in gate_files],
        },
        "source_index": source_index,
        "hashes": {
            "bundle_sha256": bundle_sha256,
            "projection_sha256": projection_sha256,
            "install_surface_sha256": install_surface_sha256,
        },
        "drift": drift,
    }

    bundle_path = output_path / spec.bundle_filename
    projection_path = output_path / spec.projection_filename
    install_surface_path = output_path / spec.install_surface_filename
    bundle_path.write_text(compiled_markdown, encoding="utf-8")
    projection_path.write_text(projection_text, encoding="utf-8")
    install_surface_path.write_text(install_surface_text, encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "bundle_path": bundle_path,
        "projection_path": projection_path,
        "install_surface_path": install_surface_path,
        "manifest_path": manifest_path,
        "drift_status": str(drift["status"]),
    }


def build_projection_document(
    *,
    spec: CompilerSpec,
    source_ai_root: Path,
    source_index: list[dict[str, object]],
    bundle_sha256: str,
    install_surface: Mapping[str, object],
    artifacts: Mapping[str, str],
    commands: Mapping[str, str],
    workflow_contract: Mapping[str, object],
) -> dict[str, object]:
    """Build a shared host projection document from compiler and contract metadata."""
    return {
        "schema_version": 2,
        "projection_name": spec.projection_name,
        "source_ai_root": str(source_ai_root),
        "host": {
            "name": spec.host_name,
            "display_name": spec.host_display_name,
            "stored_runtime_key": spec.stored_runtime_key,
            "default_variant": f"{spec.variant_namespace}/{spec.default_variant}",
            "variants": {mode: contract.to_metadata() for mode, contract in spec.variants.items()},
        },
        "artifacts": dict(artifacts),
        "install_surface": dict(install_surface),
        "commands": dict(commands),
        "workflow_contract": dict(workflow_contract),
        "projection_inputs": source_index,
        "projection_hashes": {
            "bundle_sha256": bundle_sha256,
        },
    }


def build_source_index(
    ai_root: Path,
    runbook_files: list[Path],
    policy_files: list[Path],
    gate_files: list[Path],
) -> list[dict[str, object]]:
    """Build source fingerprints used by manifests and projections."""
    entries: list[dict[str, object]] = []

    for policy_file in policy_files:
        entries.append(
            source_entry(
                ai_root,
                policy_file,
                kind="policy",
                logical_name=policy_file.stem,
            )
        )
    for runbook_file in runbook_files:
        runbook = load_runbook(runbook_file)
        entries.append(
            source_entry(
                ai_root,
                runbook_file,
                kind="runbook",
                logical_name=runbook.name,
            )
        )
    for gate_file in gate_files:
        gate_set = load_gate_set(gate_file)
        entries.append(
            source_entry(
                ai_root,
                gate_file,
                kind="gate",
                logical_name=gate_set.name,
            )
        )

    return sorted(entries, key=lambda entry: (str(entry["kind"]), str(entry["source_path"])))


def source_entry(ai_root: Path, path: Path, *, kind: str, logical_name: str) -> dict[str, object]:
    """Build a single fingerprinted source entry."""
    content = path.read_text(encoding="utf-8")
    return {
        "kind": kind,
        "logical_name": logical_name,
        "source_path": relative_source_path(ai_root, path),
        "sha256": sha256_text(content),
    }


def build_drift_report(
    previous_manifest: dict[str, Any] | None,
    source_index: list[dict[str, object]],
    bundle_sha256: str,
    projection_sha256: str,
    install_surface_sha256: str,
) -> dict[str, object]:
    """Compare the current projection against a previous manifest baseline."""
    if not previous_manifest:
        return {
            "status": "initial",
            "baseline_generated_at": None,
            "source_changes": {"added": [], "removed": [], "changed": [], "unchanged_count": len(source_index)},
            "bundle_changed": False,
            "projection_changed": False,
            "install_surface_changed": False,
        }

    previous_index = previous_manifest.get("source_index")
    if not isinstance(previous_index, list):
        return {
            "status": "initial",
            "baseline_generated_at": previous_manifest.get("generated_at"),
            "source_changes": {"added": [], "removed": [], "changed": [], "unchanged_count": len(source_index)},
            "bundle_changed": False,
            "projection_changed": False,
            "install_surface_changed": False,
            "notes": ["Previous manifest did not include compatible source fingerprints."],
        }

    previous_map = fingerprint_map(previous_index)
    current_map = fingerprint_map(source_index)

    added = sorted(set(current_map) - set(previous_map))
    removed = sorted(set(previous_map) - set(current_map))
    changed = sorted(path for path in current_map.keys() & previous_map.keys() if current_map[path] != previous_map[path])
    unchanged_count = len(current_map.keys() & previous_map.keys()) - len(changed)

    previous_hashes = previous_manifest.get("hashes")
    if not isinstance(previous_hashes, dict):
        return {
            "status": "initial",
            "baseline_generated_at": previous_manifest.get("generated_at"),
            "source_changes": {
                "added": added,
                "removed": removed,
                "changed": changed,
                "unchanged_count": unchanged_count,
            },
            "bundle_changed": False,
            "projection_changed": False,
            "install_surface_changed": False,
            "notes": ["Previous manifest did not include compatible output hashes."],
        }

    previous_bundle_sha256 = previous_hashes.get("bundle_sha256")
    previous_projection_sha256 = previous_hashes.get("projection_sha256")
    previous_install_surface_sha256 = previous_hashes.get("install_surface_sha256")

    bundle_changed = bool(previous_bundle_sha256 and previous_bundle_sha256 != bundle_sha256)
    projection_changed = bool(previous_projection_sha256 and previous_projection_sha256 != projection_sha256)
    install_surface_changed = bool(
        previous_install_surface_sha256 and previous_install_surface_sha256 != install_surface_sha256
    )
    status = (
        "changed"
        if added or removed or changed or bundle_changed or projection_changed or install_surface_changed
        else "clean"
    )

    return {
        "status": status,
        "baseline_generated_at": previous_manifest.get("generated_at"),
        "source_changes": {
            "added": added,
            "removed": removed,
            "changed": changed,
            "unchanged_count": unchanged_count,
        },
        "bundle_changed": bundle_changed,
        "projection_changed": projection_changed,
        "install_surface_changed": install_surface_changed,
    }


def build_install_surface_document(*, spec: CompilerSpec, output_dir: Path) -> dict[str, object]:
    """Build a minimal installable host-bundle descriptor for compiled outputs."""
    return {
        "schema_version": 1,
        "host": {
            "key": spec.key,
            "name": spec.host_name,
            "display_name": spec.host_display_name,
        },
        "install_strategy": "use_compiled_output_directory",
        "default_output_dir": spec.default_output_dir,
        "resolved_output_dir": str(output_dir),
        "generated_assets": [
            {
                "role": "bundle",
                "relative_path": spec.bundle_filename,
                "managed_by_compiler": True,
            },
            {
                "role": "projection",
                "relative_path": spec.projection_filename,
                "managed_by_compiler": True,
            },
            {
                "role": "install_surface",
                "relative_path": spec.install_surface_filename,
                "managed_by_compiler": True,
            },
            {
                "role": "manifest",
                "relative_path": "manifest.json",
                "managed_by_compiler": True,
            },
        ],
        "external_assets": [policy.to_metadata() for policy in spec.external_asset_policies],
    }


def render_install_surface_markdown(install_surface: Mapping[str, object]) -> list[str]:
    """Render a concise markdown section describing the generated host bundle/install surface."""
    lines = [
        "## Host Bundle / Install Surface",
        f"- install_strategy: `{install_surface.get('install_strategy', '-')}`",
        f"- default_output_dir: `{install_surface.get('default_output_dir', '-')}`",
        f"- resolved_output_dir: `{install_surface.get('resolved_output_dir', '-')}`",
    ]
    generated_assets = install_surface.get("generated_assets")
    if isinstance(generated_assets, list) and generated_assets:
        lines.append("- generated assets:")
        for asset in generated_assets:
            if not isinstance(asset, Mapping):
                continue
            role = asset.get("role", "-")
            relative_path = asset.get("relative_path", "-")
            lines.append(f"  - {role}: `{relative_path}`")
    external_assets = install_surface.get("external_assets")
    if isinstance(external_assets, list) and external_assets:
        lines.append("- external assets (not compiler-managed):")
        for asset in external_assets:
            if not isinstance(asset, Mapping):
                continue
            path = asset.get("path", "-")
            owner = asset.get("owner", "-")
            rationale = asset.get("rationale", "-")
            lines.append(f"  - `{path}` owner={owner} — {rationale}")
    else:
        lines.append("- external assets (not compiler-managed): none")
    lines.append("")
    return lines


def fingerprint_map(entries: list[dict[str, object]] | list[Any]) -> dict[str, str]:
    """Reduce a source index into a source_path -> sha256 mapping."""
    mapping: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source_path = entry.get("source_path")
        sha256 = entry.get("sha256")
        if isinstance(source_path, str) and isinstance(sha256, str):
            mapping[source_path] = sha256
    return mapping


def load_existing_manifest(path: Path, *, stage: str) -> dict[str, Any] | None:
    """Load a previous manifest when available and compatible."""
    if not path.exists() or not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LoadError("Failed to read existing manifest", path=path, stage=stage) from exc
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def relative_source_path(ai_root: Path, source_path: Path) -> str:
    """Return a stable source path rooted at the repo when possible."""
    try:
        return str(source_path.relative_to(ai_root.parent))
    except ValueError:
        return str(source_path)


def sha256_text(content: str) -> str:
    """Return the sha256 fingerprint for UTF-8 text content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def require_directory(path: Path, *, stage: str) -> None:
    """Validate that a required compiler input directory exists."""
    if not path.exists():
        raise LoadError("Required compile source directory does not exist", path=path, stage=stage)
    if not path.is_dir():
        raise LoadError("Compile source path is not a directory", path=path, stage=stage)


_require_directory = require_directory
