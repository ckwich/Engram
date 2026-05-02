from __future__ import annotations


def test_usage_summary_api_returns_rollup(isolated_usage_meter, monkeypatch):
    import webui

    monkeypatch.setattr(webui, "usage_meter", isolated_usage_meter.usage_meter)
    isolated_usage_meter.usage_meter.record_tool_call(
        tool="context_pack",
        input_payload={"query": "agent memory"},
        output_payload={"chunks": [{"key": "k", "chunk_id": 0, "text": "body"}]},
        status="ok",
        duration_ms=3,
    )

    client = webui.app.test_client()
    response = client.get("/api/usage/summary?days=7")

    assert response.status_code == 200
    assert response.get_json()["total_calls"] == 1


def test_usage_calls_api_returns_recent_records(isolated_usage_meter, monkeypatch):
    import webui

    monkeypatch.setattr(webui, "usage_meter", isolated_usage_meter.usage_meter)
    isolated_usage_meter.usage_meter.record_tool_call(
        tool="search_memories",
        input_payload={"query": "q"},
        output_payload=[{"key": "k", "snippet": "s"}],
        status="ok",
        duration_ms=1,
    )

    client = webui.app.test_client()
    response = client.get("/api/usage/calls?limit=10")

    assert response.status_code == 200
    assert response.get_json()["calls"][0]["tool"] == "search_memories"


def test_retrieval_eval_api_returns_report(monkeypatch):
    import webui

    def fake_run_retrieval_eval(manager):
        return {"summary": {"passed": True, "scenario_count": 1}, "error": None}

    monkeypatch.setattr(webui, "run_retrieval_eval", fake_run_retrieval_eval)

    client = webui.app.test_client()
    response = client.get("/api/eval/retrieval")

    assert response.status_code == 200
    assert response.get_json()["summary"]["passed"] is True


def test_review_preview_apis_are_no_write(tmp_path):
    import webui

    source = tmp_path / "source.md"
    source.write_text("# Source\n\nDecision: Keep previews dry.", encoding="utf-8")

    client = webui.app.test_client()
    chunk_response = client.post(
        "/api/chunk-preview",
        json={"content": "# Source\n\nBody", "title": "Source"},
    )
    connector_response = client.post(
        "/api/source-connectors/preview",
        json={
            "connector_type": "local_path",
            "target": str(source),
            "include_globs": ["*.md"],
            "max_files": 5,
        },
    )

    assert chunk_response.status_code == 200
    assert chunk_response.get_json()["receipt"]["write_performed"] is False
    assert connector_response.status_code == 200
    assert connector_response.get_json()["write_performed"] is False
