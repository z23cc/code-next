"""Custom exception hierarchy for aiwf."""

from __future__ import annotations

from pathlib import Path


class AiwfError(Exception):
    """Base exception for all aiwf-specific failures."""

    def __init__(
        self,
        message: str,
        *,
        path: str | Path | None = None,
        stage: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.path = str(path) if path is not None else None
        self.stage = stage

    def __str__(self) -> str:
        details = [self.message]
        if self.path:
            details.append(f"path={self.path}")
        if self.stage:
            details.append(f"stage={self.stage}")
        return " | ".join(details)


class LoadError(AiwfError):
    """Raised when `.ai/` source files cannot be loaded or validated."""


class StateError(AiwfError):
    """Raised when run state cannot be created, loaded, or transitioned."""


class ArtifactError(AiwfError):
    """Raised for artifact persistence failures."""


class GateError(AiwfError):
    """Raised for gate execution failures."""


class AdapterError(AiwfError):
    """Raised for adapter failures."""
