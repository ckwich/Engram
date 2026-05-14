from __future__ import annotations

import re
import logging
import sys
import types

import pytest

from core.embedder import Embedder, MODEL_NOT_LOADED_MESSAGE


def test_embed_requires_model_load():
    embedder = Embedder()

    with pytest.raises(RuntimeError, match=re.escape(MODEL_NOT_LOADED_MESSAGE)):
        embedder.embed("hello")


def test_embed_batch_requires_model_load():
    embedder = Embedder()

    with pytest.raises(RuntimeError, match=re.escape(MODEL_NOT_LOADED_MESSAGE)):
        embedder.embed_batch(["hello"])


def test_model_load_suppresses_dependency_chatter(monkeypatch, capsys):
    class FakeSentenceTransformer:
        def __init__(self, *_args, **_kwargs):
            print("dependency stdout noise")
            print("dependency stderr noise", file=sys.stderr)

        def encode(self, *_args, **_kwargs):
            return []

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )

    embedder = Embedder()
    embedder._load()

    captured = capsys.readouterr()
    assert "dependency stdout noise" not in captured.out
    assert "dependency stderr noise" not in captured.err
    assert "[Engram] Loading embedding model" in captured.err
    assert "[Engram] Model loaded." in captured.err


def test_model_load_suppresses_transformers_warning_logs(monkeypatch, caplog):
    class FakeSentenceTransformer:
        def __init__(self, *_args, **_kwargs):
            logging.getLogger("transformers.utils.loading_report").warning("dependency log noise")

        def encode(self, *_args, **_kwargs):
            return []

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )

    embedder = Embedder()
    with caplog.at_level(logging.WARNING):
        embedder._load()

    assert "dependency log noise" not in caplog.text
