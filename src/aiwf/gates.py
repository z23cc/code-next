"""Gate execution helpers."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from aiwf.exceptions import GateError
from aiwf.models import GateResult, GateSet, VerifyReport, utc_now


def run_gates(gate_set: GateSet, cwd: str | Path, timeout: int | None = None) -> VerifyReport:
    """Run each gate command sequentially and return an aggregated report."""
    working_dir = Path(cwd)
    if not working_dir.exists():
        raise GateError("Gate working directory does not exist", path=working_dir, stage="run_gates")
    if not working_dir.is_dir():
        raise GateError("Gate working directory is not a directory", path=working_dir, stage="run_gates")

    started_at = utc_now()
    results: list[GateResult] = []

    for gate in gate_set.gates:
        gate_timeout = gate.timeout_seconds if timeout is None else min(gate.timeout_seconds, timeout)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                gate.command,
                shell=True,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=gate_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            results.append(
                GateResult(
                    name=gate.name,
                    command=gate.command,
                    passed=False,
                    returncode=None,
                    stdout=_coerce_timeout_output(exc.stdout),
                    stderr=_coerce_timeout_output(exc.stderr),
                    timed_out=True,
                    duration_seconds=time.monotonic() - started,
                )
            )
            continue
        except OSError as exc:
            results.append(
                GateResult(
                    name=gate.name,
                    command=gate.command,
                    passed=False,
                    returncode=None,
                    stderr=str(exc),
                    timed_out=False,
                    duration_seconds=time.monotonic() - started,
                )
            )
            continue

        results.append(
            GateResult(
                name=gate.name,
                command=gate.command,
                passed=completed.returncode == 0,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                timed_out=False,
                duration_seconds=time.monotonic() - started,
            )
        )

    return VerifyReport(
        gate_set=gate_set.name,
        cwd=str(working_dir),
        # An empty gate set is treated as passing because there are no deterministic checks to fail.
        passed=all(result.passed for result in results),
        started_at=started_at,
        finished_at=utc_now(),
        results=results,
    )


def _coerce_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
