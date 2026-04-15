"""Compiler utilities for host-specific outputs."""

from aiwf.compilers.base import CompilerSpec
from aiwf.compilers.claude import CLAUDE_COMPILER_SPEC, compile_claude

COMPILER_SPECS: dict[str, CompilerSpec] = {
    "claude": CLAUDE_COMPILER_SPEC,
}

__all__ = ["COMPILER_SPECS", "CLAUDE_COMPILER_SPEC", "CompilerSpec", "compile_claude"]
