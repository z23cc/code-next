"""Custom exception hierarchy for aiwf."""

from __future__ import annotations

from enum import Enum
from pathlib import Path


class ErrorCode(str, Enum):
    """Stable machine-readable workflow error taxonomy."""

    GATE_FAILURE = "GATE_FAILURE"
    ADAPTER_TIMEOUT = "ADAPTER_TIMEOUT"
    ADAPTER_UNAVAILABLE = "ADAPTER_UNAVAILABLE"
    ADAPTER_FAILURE = "ADAPTER_FAILURE"
    BRIDGE_AGENT_FAILURE = "BRIDGE_AGENT_FAILURE"
    MISSING_ARTIFACT = "MISSING_ARTIFACT"
    INVALID_ARTIFACT = "INVALID_ARTIFACT"
    STATE_VIOLATION = "STATE_VIOLATION"
    LOAD_FAILURE = "LOAD_FAILURE"
    UNKNOWN = "UNKNOWN"


class AiwfError(Exception):
    """Base exception for all aiwf-specific failures."""

    default_error_code = ErrorCode.UNKNOWN

    def __init__(
        self,
        message: str,
        *,
        path: str | Path | None = None,
        stage: str | None = None,
        error_code: ErrorCode | str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.path = str(path) if path is not None else None
        self.stage = stage
        self.error_code = ErrorCode(error_code) if error_code is not None else self.default_error_code

    def __str__(self) -> str:
        details = [self.message]
        if self.path:
            details.append(f"path={self.path}")
        if self.stage:
            details.append(f"stage={self.stage}")
        return " | ".join(details)


class LoadError(AiwfError):
    """Raised when `.ai/` source files cannot be loaded or validated."""

    default_error_code = ErrorCode.LOAD_FAILURE


class StateError(AiwfError):
    """Raised when run state cannot be created, loaded, or transitioned."""

    default_error_code = ErrorCode.STATE_VIOLATION


class ArtifactError(AiwfError):
    """Raised for artifact persistence failures."""

    default_error_code = ErrorCode.INVALID_ARTIFACT


class GateError(AiwfError):
    """Raised for gate execution failures."""

    default_error_code = ErrorCode.GATE_FAILURE


class AdapterError(AiwfError):
    """Raised for adapter failures."""

    default_error_code = ErrorCode.ADAPTER_FAILURE
