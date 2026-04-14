"""Load task, runbook, gate, and policy files from `.ai/`."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from aiwf.exceptions import LoadError
from aiwf.models import GateSet, RunbookSpec, TaskSpec


def load_task(path: str | Path) -> TaskSpec:
    """Load a task markdown file into a validated TaskSpec."""
    source_path = Path(path)
    metadata, body = _read_markdown_with_front_matter(source_path, stage="load_task")
    payload = {**metadata, "body": body}
    try:
        return TaskSpec.model_validate(payload)
    except ValidationError as exc:
        raise LoadError("Invalid task spec", path=source_path, stage="load_task") from exc


def load_runbook(path: str | Path) -> RunbookSpec:
    """Load a runbook markdown file into a validated RunbookSpec."""
    source_path = Path(path)
    metadata, body = _read_markdown_with_front_matter(source_path, stage="load_runbook")
    payload = {**metadata, "body": body}
    try:
        return RunbookSpec.model_validate(payload)
    except ValidationError as exc:
        raise LoadError("Invalid runbook spec", path=source_path, stage="load_runbook") from exc


def load_gate_set(path: str | Path) -> GateSet:
    """Load a gate set YAML file into a validated GateSet."""
    source_path = Path(path)
    text = _read_text(source_path, stage="load_gate_set")
    payload = _parse_yaml_mapping(text, source_path, stage="load_gate_set")
    try:
        return GateSet.model_validate(payload)
    except ValidationError as exc:
        raise LoadError("Invalid gate set", path=source_path, stage="load_gate_set") from exc


def load_policy(path: str | Path) -> str:
    """Load a plain-text policy file."""
    return _read_text(Path(path), stage="load_policy").strip()


def _read_text(path: Path, *, stage: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise LoadError("File does not exist", path=path, stage=stage) from exc
    except OSError as exc:
        raise LoadError("Failed to read file", path=path, stage=stage) from exc


def _read_markdown_with_front_matter(path: Path, *, stage: str) -> tuple[dict[str, Any], str]:
    text = _read_text(path, stage=stage)
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not match:
        return {}, text.strip()
    metadata = _parse_yaml_mapping(match.group(1), path, stage=stage)
    return metadata, match.group(2).strip()


def _parse_yaml_mapping(text: str, path: Path, *, stage: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise LoadError("Invalid YAML content", path=path, stage=stage) from exc
    if not isinstance(data, dict):
        raise LoadError("YAML document must be a mapping", path=path, stage=stage)
    return data
