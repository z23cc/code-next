"""Compiler utilities for host-specific outputs."""

from aiwf.compilers.base import CompilerSpec
from aiwf.compilers.claude import CLAUDE_COMPILER_SPEC, compile_claude
from aiwf.compilers.codex import CODEX_COMPILER_SPEC, compile_codex
from aiwf.compilers.rp import RP_COMPILER_SPEC, compile_rp

COMPILER_SPECS: dict[str, CompilerSpec] = {
    "claude": CLAUDE_COMPILER_SPEC,
    "codex": CODEX_COMPILER_SPEC,
    "rp": RP_COMPILER_SPEC,
}

__all__ = [
    "COMPILER_SPECS",
    "CLAUDE_COMPILER_SPEC",
    "CODEX_COMPILER_SPEC",
    "RP_COMPILER_SPEC",
    "CompilerSpec",
    "compile_claude",
    "compile_codex",
    "compile_rp",
]
