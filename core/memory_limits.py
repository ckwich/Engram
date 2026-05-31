"""Shared limits for reviewed memory writes and daemon requests."""
from __future__ import annotations

MAX_DIRECT_MEMORY_CHARS = 15_000
DEFAULT_DAEMON_MAX_CONTENT_LENGTH = 16 * 1024 * 1024
DAEMON_MAX_CONTENT_LENGTH_ENV = "ENGRAM_DAEMON_MAX_CONTENT_LENGTH"


def direct_memory_too_long_message(chars: int) -> str:
    return (
        f"Content is {chars:,} chars - exceeds the "
        f"{MAX_DIRECT_MEMORY_CHARS:,} char direct memory limit. "
        "Use source intake, document intake, or artifact storage for larger material."
    )
