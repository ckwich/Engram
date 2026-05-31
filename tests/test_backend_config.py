from __future__ import annotations

import pytest

from core.backend_config import load_backend_config


def test_backend_config_defaults_keep_live_backends_legacy(monkeypatch):
    monkeypatch.delenv("ENGRAM_RETRIEVAL_BACKEND", raising=False)
    monkeypatch.delenv("ENGRAM_GRAPH_BACKEND", raising=False)

    config = load_backend_config()

    assert config.retrieval_backend == "chroma"
    assert config.graph_backend == "json"
    assert config.live_backend_switch_requested is False
    assert config.retrieval_candidate_requested is False
    assert config.graph_candidate_requested is False


def test_backend_config_accepts_optional_candidates_without_promotion(monkeypatch):
    monkeypatch.setenv("ENGRAM_RETRIEVAL_BACKEND", "lancedb")
    monkeypatch.setenv("ENGRAM_GRAPH_BACKEND", "kuzu")

    config = load_backend_config()

    assert config.retrieval_backend == "lancedb"
    assert config.graph_backend == "kuzu"
    assert config.live_backend_switch_requested is True
    assert config.retrieval_candidate_requested is True
    assert config.graph_candidate_requested is True


def test_backend_config_rejects_unknown_backends(monkeypatch):
    monkeypatch.setenv("ENGRAM_RETRIEVAL_BACKEND", "milvus")

    with pytest.raises(ValueError, match="Unsupported ENGRAM_RETRIEVAL_BACKEND"):
        load_backend_config()
