from __future__ import annotations

import sys
from pathlib import Path

import pytest

from aiwf.exceptions import GateError
from aiwf.models import GateSet
from aiwf.gates import run_gates


def test_run_gates_passes_all_commands(tmp_path: Path) -> None:
    gate_set = GateSet(
        name="default",
        gates=[
            {
                "name": "first",
                "command": f'{sys.executable} -c "print(\'alpha\')"',
            },
            {
                "name": "second",
                "command": f'{sys.executable} -c "print(\'beta\')"',
            },
        ],
    )

    report = run_gates(gate_set, tmp_path)

    assert report.passed is True
    assert [result.name for result in report.results] == ["first", "second"]
    assert report.results[0].stdout.strip() == "alpha"
    assert report.results[1].stdout.strip() == "beta"


def test_run_gates_records_failures_and_continues(tmp_path: Path) -> None:
    gate_set = GateSet(
        name="default",
        gates=[
            {
                "name": "ok",
                "command": f'{sys.executable} -c "print(\'before\')"',
            },
            {
                "name": "fail",
                "command": f'{sys.executable} -c "import sys; print(\'broken\'); sys.exit(3)"',
            },
            {
                "name": "after",
                "command": f'{sys.executable} -c "print(\'after\')"',
            },
        ],
    )

    report = run_gates(gate_set, tmp_path)

    assert report.passed is False
    assert len(report.results) == 3
    assert report.results[1].passed is False
    assert report.results[1].returncode == 3
    assert report.results[1].stdout.strip() == "broken"
    assert report.results[2].stdout.strip() == "after"


def test_run_gates_marks_timeout_as_failed(tmp_path: Path) -> None:
    gate_set = GateSet(
        name="timeout-suite",
        gates=[
            {
                "name": "slow",
                "command": f'{sys.executable} -c "import time; time.sleep(2)"',
                "timeout_seconds": 1,
            }
        ],
    )

    report = run_gates(gate_set, tmp_path)

    assert report.passed is False
    assert report.results[0].timed_out is True
    assert report.results[0].returncode is None


def test_run_gates_requires_existing_directory(tmp_path: Path) -> None:
    gate_set = GateSet(name="default", gates=[])

    with pytest.raises(GateError) as exc_info:
        run_gates(gate_set, tmp_path / "missing")

    assert "stage=run_gates" in str(exc_info.value)
