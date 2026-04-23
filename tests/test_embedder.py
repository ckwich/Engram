from __future__ import annotations

import re

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
