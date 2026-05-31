from __future__ import annotations

import asyncio

import server
import server_daemon_client
from core.mcp.tool_registry import build_memory_protocol_sections, validate_protocol_sections
from core.memory_os.schema import (
    MEMORY_SCOPES,
    MEMORY_TYPES,
    RETENTION_POLICIES,
    SYNC_POLICIES,
    TRUST_STATES,
)


def test_full_memory_protocol_advertises_memory_taxonomy():
    payload = asyncio.run(server.memory_protocol())

    assert payload["memory_taxonomy"] == {
        "memory_types": list(MEMORY_TYPES),
        "memory_scopes": list(MEMORY_SCOPES),
        "trust_states": list(TRUST_STATES),
        "retention_policies": list(RETENTION_POLICIES),
        "sync_policies": list(SYNC_POLICIES),
    }
    assert validate_protocol_sections(payload) == []


def test_thin_memory_protocol_advertises_memory_taxonomy():
    payload = server_daemon_client.memory_protocol()

    assert payload["memory_taxonomy"] == build_memory_protocol_sections(thin_client=True)["memory_taxonomy"]
    assert payload["memory_taxonomy"]["memory_types"] == list(MEMORY_TYPES)
    assert payload["memory_taxonomy"]["memory_scopes"] == list(MEMORY_SCOPES)
    assert payload["memory_taxonomy"]["trust_states"] == list(TRUST_STATES)
    assert payload["memory_taxonomy"]["retention_policies"] == list(RETENTION_POLICIES)
    assert payload["memory_taxonomy"]["sync_policies"] == list(SYNC_POLICIES)
    assert validate_protocol_sections(payload, thin_client=True) == []
