from __future__ import annotations

from core.webui_gateway import WebUIDataGateway


def test_webui_gateway_applies_document_promotion_through_daemon_when_configured():
    calls = []

    class FakeClient:
        def __init__(self, url):
            self.url = url

        def apply_document_promotion_transaction(self, payload):
            calls.append((self.url, payload))
            return {"status": "ok", "owner": "daemon"}

    def fail_runtime():
        raise AssertionError("daemon mode should not open a direct runtime")

    gateway = WebUIDataGateway(
        memory_manager=object(),
        daemon_url_provider=lambda: "http://127.0.0.1:8765",
        memory_os_runtime_provider=fail_runtime,
        daemon_client_factory=FakeClient,
    )
    payload = {
        "document_promotion_transaction": {"transaction_id": "txn:test"},
        "accept": True,
        "approved_by": "agent-review",
    }

    result = gateway.apply_document_promotion(payload)

    assert result == {"status": "ok", "owner": "daemon"}
    assert calls == [("http://127.0.0.1:8765", payload)]


def test_webui_gateway_applies_document_promotion_through_direct_runtime_without_daemon():
    calls = []

    class FakeRuntime:
        def apply_document_promotion_transaction(self, transaction, **kwargs):
            calls.append((transaction, kwargs))
            return {"status": "ok", "owner": "direct"}

    gateway = WebUIDataGateway(
        memory_manager=object(),
        daemon_url_provider=lambda: "",
        memory_os_runtime_provider=FakeRuntime,
    )

    result = gateway.apply_document_promotion(
        {
            "document_promotion_transaction": {"transaction_id": "txn:test"},
            "accept": True,
            "approved_by": "agent-review",
            "selected_operation_indexes": [0],
        }
    )

    assert result == {"status": "ok", "owner": "direct"}
    assert calls == [
        (
            {"transaction_id": "txn:test"},
            {
                "accept": True,
                "approved_by": "agent-review",
                "selected_operation_indexes": [0],
            },
        )
    ]


def test_webui_gateway_normalizes_memory_write_lists():
    calls = []

    class FakeMemoryManager:
        def store_memory(self, **kwargs):
            calls.append(kwargs)
            return {"status": "stored"}

    gateway = WebUIDataGateway(memory_manager=FakeMemoryManager())

    result = gateway.create_memory(
        {
            "key": "k",
            "content": "body",
            "tags": "alpha, beta",
            "related_to": "one, two",
            "force": True,
        }
    )

    assert result == {"status": "stored"}
    assert calls == [
        {
            "key": "k",
            "content": "body",
            "tags": ["alpha", "beta"],
            "title": None,
            "related_to": ["one", "two"],
            "force": True,
        }
    ]
