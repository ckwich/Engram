import hashlib

import pytest

from core.memory_os.content_store import ContentAddressedStore


def test_store_returns_sha256_artifact_id_and_reads_exact_bytes(tmp_path):
    store = ContentAddressedStore(tmp_path / "objects")
    data = b"source bytes"

    artifact_id = store.put_bytes(data)

    assert artifact_id == f"sha256:{hashlib.sha256(data).hexdigest()}"
    assert store.read_bytes(artifact_id) == data


def test_duplicate_bytes_return_same_artifact_id(tmp_path):
    store = ContentAddressedStore(tmp_path / "objects")
    data = b"same document"

    first = store.put_bytes(data, suffix=".bin")
    second = store.put_bytes(data, suffix=".bin")

    assert first == second
    assert store.path_for(first).read_bytes() == data


def test_artifact_paths_remain_under_configured_root(tmp_path):
    root = tmp_path / "objects"
    store = ContentAddressedStore(root)
    artifact_id = store.put_bytes(b"portable evidence", suffix=".json")

    artifact_path = store.path_for(artifact_id).resolve()

    assert artifact_path.is_relative_to(root.resolve())
    assert artifact_path.name.endswith(".json")


def test_unsafe_artifact_ids_and_suffixes_are_rejected(tmp_path):
    store = ContentAddressedStore(tmp_path / "objects")

    with pytest.raises(ValueError, match="unsafe suffix"):
        store.put_bytes(b"bad", suffix="../bad")

    with pytest.raises(ValueError, match="invalid artifact id"):
        store.path_for("sha256:../bad")
