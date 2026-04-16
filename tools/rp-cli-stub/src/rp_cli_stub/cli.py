from __future__ import annotations

import argparse
import json
import sys
from typing import Any

PROTOCOL = "aiwf-rp-native"
VERSION = 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rp-cli-stub", add_help=True)
    parser.add_argument(
        "--aiwf-protocol-version",
        action="store_true",
        help="Print aiwf-rp-native protocol support JSON and exit.",
    )
    parser.add_argument(
        "--force-error",
        metavar="CODE",
        help="Force a structured protocol error response code for envelope requests.",
    )
    return parser


def _probe_payload() -> dict[str, Any]:
    return {
        "protocol": PROTOCOL,
        "version": VERSION,
        "capabilities": [],
    }


def _error_payload(code: str) -> dict[str, Any]:
    detail: dict[str, Any] = {}
    if code == "UNSUPPORTED_VERSION":
        detail["supported_version"] = VERSION
    return {
        "protocol": PROTOCOL,
        "version": VERSION,
        "status": "error",
        "content": None,
        "error": {
            "code": code,
            "message": f"Forced error: {code}",
            "retriable": False,
            "detail": detail,
        },
        "metadata": {},
        "diagnostics": None,
    }


def _ok_payload(request: dict[str, Any]) -> dict[str, Any]:
    request_type = request.get("request_type", "unknown")
    stage = request.get("stage", "unknown")
    metadata = request.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "protocol": PROTOCOL,
        "version": VERSION,
        "status": "ok",
        "content": f"stub:{request_type}:{stage}",
        "metadata": metadata,
        "diagnostics": None,
    }


def _write_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.aiwf_protocol_version:
        _write_json(_probe_payload())
        return 0

    raw = sys.stdin.read()
    stripped = raw.strip()

    if stripped:
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            if args.force_error:
                _write_json(_error_payload(args.force_error))
                return 0
            _write_json(_ok_payload(payload))
            return 0

    # Legacy fallback: raw text in, raw text out.
    sys.stdout.write(raw)
    return 0
