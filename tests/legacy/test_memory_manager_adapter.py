from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_import_probe(source: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_adapter_imports_legacy_memory_manager_lazily():
    probe = _run_import_probe(
        "import sys\n"
        "import core.legacy.memory_manager_adapter\n"
        "print('core.memory_manager' in sys.modules)\n"
    )

    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "False"


def test_adapter_exports_bounded_direct_mode_surface():
    import core.legacy.memory_manager_adapter as adapter

    expected = {
        "get_memory_manager",
        "search_memories_legacy",
        "retrieve_memory_legacy",
        "retrieve_chunk_legacy",
        "store_memory_legacy",
        "delete_memory_legacy",
        "is_duplicate_memory_error",
        "is_chroma_availability_error",
        "get_config_value",
        "memory_manager",
    }

    exported = set(getattr(adapter, "__all__"))

    assert expected.issubset(exported)
    assert "DuplicateMemoryError" not in exported
    assert "_config" not in exported


def test_adapter_wrappers_resolve_legacy_manager_only_when_called(monkeypatch):
    import core.legacy.memory_manager_adapter as adapter

    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    class FakeManager:
        def search_memories(self, *args, **kwargs):
            calls.append(("search_memories", args, kwargs))
            return [{"key": "legacy"}]

        def retrieve_memory(self, *args, **kwargs):
            calls.append(("retrieve_memory", args, kwargs))
            return {"key": args[0]}

        def retrieve_chunk(self, *args, **kwargs):
            calls.append(("retrieve_chunk", args, kwargs))
            return {"chunk_id": args[1]}

        def store_memory(self, *args, **kwargs):
            calls.append(("store_memory", args, kwargs))
            return {"stored": True}

        def delete_memory(self, *args, **kwargs):
            calls.append(("delete_memory", args, kwargs))
            return True

    fake_module = types.SimpleNamespace(
        memory_manager=FakeManager(),
        DuplicateMemoryError=RuntimeError,
        _config={"dedup_threshold": 0.91},
        is_chroma_availability_error=lambda error: str(error) == "chroma",
    )
    monkeypatch.setattr(adapter, "_load_memory_manager_module", lambda: fake_module)

    assert adapter.search_memories_legacy("query", limit=2) == [{"key": "legacy"}]
    assert adapter.retrieve_memory_legacy("legacy") == {"key": "legacy"}
    assert adapter.retrieve_chunk_legacy("legacy", 0) == {"chunk_id": 0}
    assert adapter.store_memory_legacy("legacy", "body") == {"stored": True}
    assert adapter.delete_memory_legacy("legacy") is True
    assert adapter.get_config_value("dedup_threshold", 0.92) == 0.91
    assert adapter.is_chroma_availability_error(RuntimeError("chroma")) is True

    assert [call[0] for call in calls] == [
        "search_memories",
        "retrieve_memory",
        "retrieve_chunk",
        "store_memory",
        "delete_memory",
    ]


def test_memory_os_imports_do_not_import_legacy_memory_manager():
    probe = _run_import_probe(
        "import sys\n"
        "import core.memory_os.runtime\n"
        "import core.memory_os.document_promotion\n"
        "print('core.memory_manager' in sys.modules)\n"
    )

    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "False"

