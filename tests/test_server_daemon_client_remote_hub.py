import importlib
import asyncio
import sys

from core.hub_client_config import (
    build_hub_headers,
    describe_hub_mode,
    read_hub_client_config,
    validate_hub_client_config,
)
from core.engramd_client import EngramDaemonClientError


def test_remote_hub_client_config_does_not_import_storage_modules(monkeypatch):
    monkeypatch.setenv("ENGRAM_HUB_URL", "http://engram-hub.tailnet-name.ts.net:8767")
    monkeypatch.setenv("ENGRAM_HUB_ACCESS_TOKEN", "x" * 40)
    exact_before = set(sys.modules)

    importlib.import_module("server_daemon_client")

    forbidden = {
        "core.memory_manager",
        "chromadb",
        "lancedb",
        "kuzu",
        "core.document_extractors",
    }
    assert forbidden.isdisjoint(set(sys.modules) - exact_before)


def test_hub_client_config_validates_token_without_echoing_secret(monkeypatch):
    token = "x" * 40
    monkeypatch.setenv("ENGRAM_HUB_URL", "http://engram-hub.tailnet-name.ts.net:8767")
    monkeypatch.setenv("ENGRAM_HUB_ACCESS_TOKEN", token)

    config = read_hub_client_config()
    validation = validate_hub_client_config(config)
    headers = build_hub_headers(config)
    description = describe_hub_mode(config)

    assert validation["status"] == "ready"
    assert headers == {"Authorization": f"Bearer {token}"}
    assert description["mode"] == "hub"
    assert token not in str(validation)
    assert token not in str(description)


def test_hub_client_config_fails_closed_without_token(monkeypatch):
    monkeypatch.setenv("ENGRAM_HUB_URL", "http://engram-hub.tailnet-name.ts.net:8767")
    monkeypatch.delenv("ENGRAM_HUB_ACCESS_TOKEN", raising=False)

    config = read_hub_client_config()
    validation = validate_hub_client_config(config)

    assert validation["status"] == "policy_denied"
    assert validation["error"]["code"] == "hub_access_token_too_short"


def test_hub_client_config_rejects_credential_or_query_urls_without_echoing_them(monkeypatch):
    monkeypatch.setenv(
        "ENGRAM_HUB_URL",
        "https://secret-token@engram-hub.tailnet-name.ts.net:8767?token=also-secret",
    )
    monkeypatch.setenv("ENGRAM_HUB_ACCESS_TOKEN", "x" * 40)

    config = read_hub_client_config()
    validation = validate_hub_client_config(config)
    description = describe_hub_mode(config)

    assert validation["status"] == "policy_denied"
    assert validation["error"]["code"] == "hub_url_must_not_include_credentials"
    assert description["hub_url"] is None
    assert "secret-token" not in str(validation)
    assert "also-secret" not in str(validation)
    assert "secret-token" not in str(description)
    assert "also-secret" not in str(description)


def test_hub_client_config_rejects_cleartext_public_http_without_opt_in(monkeypatch):
    monkeypatch.setenv("ENGRAM_HUB_URL", "http://example.com:8767")
    monkeypatch.setenv("ENGRAM_HUB_ACCESS_TOKEN", "x" * 40)
    monkeypatch.delenv("ENGRAM_HUB_INSECURE_HTTP_OK", raising=False)

    config = read_hub_client_config()
    validation = validate_hub_client_config(config)

    assert validation["status"] == "policy_denied"
    assert validation["error"]["code"] == "hub_url_insecure_http_requires_opt_in"


def test_daemon_client_targets_remote_hub_with_bearer_header(monkeypatch):
    import server_daemon_client

    captured = {}
    token = "x" * 40

    class FakeClient:
        def __init__(self, base_url, *, timeout, headers=None):
            captured["base_url"] = base_url
            captured["timeout"] = timeout
            captured["headers"] = headers or {}

    monkeypatch.setenv("ENGRAM_HUB_URL", "http://engram-hub.tailnet-name.ts.net:8767/")
    monkeypatch.setenv("ENGRAM_HUB_ACCESS_TOKEN", token)
    monkeypatch.setattr(server_daemon_client, "EngramDaemonClient", FakeClient)

    server_daemon_client._daemon_client()

    assert captured["base_url"] == "http://engram-hub.tailnet-name.ts.net:8767"
    assert captured["headers"] == {"Authorization": f"Bearer {token}"}


def test_daemon_status_fails_closed_when_hub_token_missing(monkeypatch):
    import server_daemon_client

    monkeypatch.setenv("ENGRAM_HUB_URL", "http://engram-hub.tailnet-name.ts.net:8767")
    monkeypatch.delenv("ENGRAM_HUB_ACCESS_TOKEN", raising=False)

    status = asyncio.run(server_daemon_client.daemon_status())

    assert status["mode"] == "hub"
    assert status["reachable"] is False
    assert status["error"]["code"] == "hub_access_token_too_short"


def test_memory_protocol_reports_invalid_hub_config_without_secrets(monkeypatch):
    import server_daemon_client

    monkeypatch.setenv("ENGRAM_HUB_URL", "http://engram-hub.tailnet-name.ts.net:8767")
    monkeypatch.setenv("ENGRAM_HUB_ACCESS_TOKEN", "too-short")

    protocol = server_daemon_client.memory_protocol()

    assert protocol["daemon"]["hub_mode"]["mode"] == "hub"
    assert protocol["daemon"]["hub_mode"]["status"] == "policy_denied"
    assert protocol["error"]["code"] == "hub_access_token_too_short"
    assert "too-short" not in str(protocol)


def test_remote_hub_tool_errors_use_hub_unreachable_code(monkeypatch):
    import server_daemon_client

    token = "x" * 40

    class FailingClient:
        def __init__(self, base_url, *, timeout, headers=None):
            self.base_url = base_url
            self.timeout = timeout
            self.headers = headers or {}

        def search_memories(self, payload):
            raise EngramDaemonClientError("connection refused")

        def retrieve_chunk(self, payload):
            raise EngramDaemonClientError("connection refused")

        def store_memory(self, payload):
            raise EngramDaemonClientError("connection refused")

    monkeypatch.setenv("ENGRAM_HUB_URL", "http://engram-hub.tailnet-name.ts.net:8767")
    monkeypatch.setenv("ENGRAM_HUB_ACCESS_TOKEN", token)
    monkeypatch.setattr(server_daemon_client, "EngramDaemonClient", FailingClient)

    search = asyncio.run(server_daemon_client.search_memories("hub outage"))
    chunk = asyncio.run(server_daemon_client.retrieve_chunk("missing", 0))
    stored = asyncio.run(server_daemon_client.store_memory("key", "body"))

    assert search["error"]["code"] == "hub_unreachable"
    assert chunk["error"]["code"] == "hub_unreachable"
    assert "hub_unreachable" in stored
