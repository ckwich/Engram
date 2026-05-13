# Engram Backend Promotion Single-Owner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make LanceDB and Kuzu promotion work evidence-led behind a daemon-first single-owner boundary, while preserving Chroma/JSON as the default live backends until gates pass.

**Architecture:** Keep `server.py` as the full direct/daemon-capable MCP entrypoint, and add a thin daemon-client entrypoint for multi-session Codex use that does not import `core.memory_manager`, ChromaDB, or sentence-transformers. Backend candidates stay optional and config-gated; readiness tools prove dependency, corpus, persistence, daemon ownership, and promotion blockers before any live switch.

**Tech Stack:** Python 3.10+, FastMCP, local `engramd`, JSON ledger/migration store, Chroma live retrieval, JSON graph live storage, optional LanceDB/Kuzu adapters, pytest.

---

## File Map

- Create `server_daemon_client.py`: thin MCP daemon-client entrypoint for ordinary multi-session agents.
- Create `core/backend_config.py`: environment-backed backend selection policy with safe defaults.
- Create `core/retrieval_backend_eval.py`: no-write golden retrieval comparison helpers for candidate vector indexes.
- Create `core/graph_backend_eval.py`: no-write Kuzu parity helpers and document/book graph relationship readiness checks.
- Create `requirements-core.txt`, `requirements-dashboard.txt`, and `requirements-backend-spike.txt`: install profiles.
- Modify `core/lancedb_vector_index.py`: reopen existing tables before search/stats/delete/upsert.
- Modify `core/retrieval_backend_status.py` and `core/graph_backend_status.py`: report config, daemon gate, real parity gate, and promotion status accurately.
- Modify `server.py`: expose backend config/eval gates through accurate MCP docstrings.
- Modify `engramd.py`: expose daemon-owned backend status and optional eval commands where safe.
- Modify `AGENTS.md`, `README.md`, `plan.md`, and backend docs: record current truth and operator flow.
- Add/modify tests under `tests/`: thin client import guard, backend config, LanceDB reopen, retrieval comparison, Kuzu parity, status shape, and graph relationship taxonomy.

---

### Task 1: Thin Daemon Client Entry Point

**Files:**
- Create: `server_daemon_client.py`
- Test: `tests/test_server_daemon_client_entrypoint.py`

- [ ] **Step 1: Write failing import-boundary test**

```python
def test_thin_daemon_client_imports_without_storage_dependencies(monkeypatch):
    import builtins
    import importlib

    blocked = {"chromadb", "sentence_transformers", "torch"}
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in blocked:
            raise ImportError(f"blocked storage dependency: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    module = importlib.import_module("server_daemon_client")

    assert module.PRODUCT_NAME == "Engram"
    assert module._daemon_url() == "http://127.0.0.1:8765"
```

- [ ] **Step 2: Run test and verify red**

Run: `.\venv\Scripts\python.exe -m pytest tests\test_server_daemon_client_entrypoint.py -q`

Expected: fail because `server_daemon_client.py` does not exist.

- [ ] **Step 3: Implement thin entrypoint**

Expose `memory_protocol`, `daemon_status`, `search_memories`, `retrieve_chunk`, `retrieve_chunks`, `retrieve_memory`, `store_memory`/`write_memory`, `check_duplicate`, source draft lifecycle tools, metadata repair/update, delete, and document disassembly by delegating to `EngramDaemonClient`.

- [ ] **Step 4: Verify green**

Run: `.\venv\Scripts\python.exe -m pytest tests\test_server_daemon_client_entrypoint.py tests\test_server_daemon_client.py -q`

- [ ] **Step 5: Commit**

Commit message: `feat: add thin daemon MCP entrypoint`

### Task 2: Optional Dependency Profiles And Backend Config

**Files:**
- Create: `requirements-core.txt`
- Create: `requirements-dashboard.txt`
- Create: `requirements-backend-spike.txt`
- Create: `core/backend_config.py`
- Test: `tests/test_backend_config.py`

- [ ] **Step 1: Write failing config tests**

```python
from core.backend_config import load_backend_config


def test_backend_config_defaults_keep_live_backends_legacy(monkeypatch):
    monkeypatch.delenv("ENGRAM_RETRIEVAL_BACKEND", raising=False)
    monkeypatch.delenv("ENGRAM_GRAPH_BACKEND", raising=False)

    config = load_backend_config()

    assert config.retrieval_backend == "chroma"
    assert config.graph_backend == "json"
    assert config.live_backend_switch_requested is False


def test_backend_config_accepts_optional_candidates_without_promotion(monkeypatch):
    monkeypatch.setenv("ENGRAM_RETRIEVAL_BACKEND", "lancedb")
    monkeypatch.setenv("ENGRAM_GRAPH_BACKEND", "kuzu")

    config = load_backend_config()

    assert config.retrieval_backend == "lancedb"
    assert config.graph_backend == "kuzu"
    assert config.live_backend_switch_requested is True
```

- [ ] **Step 2: Run test and verify red**

Run: `.\venv\Scripts\python.exe -m pytest tests\test_backend_config.py -q`

Expected: fail because `core.backend_config` does not exist.

- [ ] **Step 3: Implement config and profiles**

Defaults remain `chroma` and `json`. Accepted candidates are `lancedb` and `kuzu`; unknown values raise `ValueError`. Profiles keep LanceDB/Kuzu out of base install.

- [ ] **Step 4: Verify green**

Run: `.\venv\Scripts\python.exe -m pytest tests\test_backend_config.py -q`

- [ ] **Step 5: Commit**

Commit message: `feat: add backend config and optional profiles`

### Task 3: LanceDB Reopen And Golden Retrieval Gate

**Files:**
- Modify: `core/lancedb_vector_index.py`
- Create: `core/retrieval_backend_eval.py`
- Modify: `core/retrieval_backend_status.py`
- Test: `tests/test_lancedb_vector_index.py`
- Test: `tests/test_retrieval_backend_eval.py`
- Test: `tests/test_retrieval_backend_status.py`

- [ ] **Step 1: Write failing reopen test**

```python
def test_lancedb_vector_index_reopens_existing_table_before_search(tmp_path):
    fake_db = FakeLanceDB()
    first = LanceDBVectorIndex(tmp_path / "lance", connect=lambda uri: fake_db)
    first.rebuild([VectorIndexDocument("alpha-0", "alpha", 0, "Alpha notes", [1.0])])

    reopened = LanceDBVectorIndex(tmp_path / "lance", connect=lambda uri: fake_db)
    results = reopened.search(VectorIndexQuery("alpha", [1.0], limit=5))

    assert [result.document_id for result in results] == ["alpha-0"]
```

- [ ] **Step 2: Run test and verify red**

Run: `.\venv\Scripts\python.exe -m pytest tests\test_lancedb_vector_index.py::test_lancedb_vector_index_reopens_existing_table_before_search -q`

Expected: fail because fresh adapters currently do not load existing tables.

- [ ] **Step 3: Implement table loading**

Load existing table lazily with `open_table`, `__getitem__`, or `table_names` where available. Search, stats, delete, and upsert must call the loader before assuming the table is empty.

- [ ] **Step 4: Add retrieval comparison helper tests**

Compare two `VectorIndex` adapters on golden queries. Report overlap, missing expected ids, top-k ids, and pass/fail without writing live retrieval.

- [ ] **Step 5: Verify green**

Run: `.\venv\Scripts\python.exe -m pytest tests\test_lancedb_vector_index.py tests\test_retrieval_backend_eval.py tests\test_retrieval_backend_status.py -q`

- [ ] **Step 6: Commit**

Commit message: `feat: add LanceDB reopen and retrieval parity gate`

### Task 4: Kuzu Parity And Graph Relationship Readiness

**Files:**
- Create: `core/graph_backend_eval.py`
- Modify: `core/graph_backend_status.py`
- Test: `tests/test_graph_backend_eval.py`
- Test: `tests/test_graph_backend_status.py`

- [ ] **Step 1: Write failing Kuzu parity tests**

```python
def test_graph_backend_parity_reports_cross_book_edge_types(tmp_path):
    edges = [
        {
            "edge_id": "sha256:one",
            "from_ref": {"kind": "concept", "key": "affordance", "document_id": "book-a"},
            "to_ref": {"kind": "concept", "key": "perceived_affordance", "document_id": "book-b"},
            "edge_type": "related_to",
            "confidence": 0.8,
            "evidence": "Both books discuss design cues for action.",
            "source": "document_understanding",
            "status": "active",
            "created_by": "agent",
            "created_at": "2026-05-13T00:00:00-07:00",
            "updated_at": "2026-05-13T00:00:00-07:00",
        }
    ]

    report = build_graph_backend_parity_report(edges)

    assert report["cross_document_edge_count"] == 1
    assert "related_to" in report["supported_cross_book_edge_types"]
```

- [ ] **Step 2: Run test and verify red**

Run: `.\venv\Scripts\python.exe -m pytest tests\test_graph_backend_eval.py -q`

Expected: fail because the helper does not exist.

- [ ] **Step 3: Implement parity report**

Report edge-count parity, missing fields, unsupported edge types, cross-document relationship counts, and whether Kuzu may only run behind daemon single ownership.

- [ ] **Step 4: Verify green**

Run: `.\venv\Scripts\python.exe -m pytest tests\test_graph_backend_eval.py tests\test_graph_backend_status.py -q`

- [ ] **Step 5: Commit**

Commit message: `feat: add graph backend parity gate`

### Task 5: Docs, Gates, And Full Verification

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `plan.md`
- Modify: `docs/ENGRAM_BACKEND_EVAL_2026_05_13.md`
- Modify: `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`

- [ ] **Step 1: Update public docs**

Record that the safe operational path is thin MCP clients attached to one daemon, while Chroma/JSON remain live until backend parity gates pass.

- [ ] **Step 2: Run focused tests**

Run: `.\venv\Scripts\python.exe -m pytest tests\test_server_daemon_client_entrypoint.py tests\test_backend_config.py tests\test_lancedb_vector_index.py tests\test_retrieval_backend_eval.py tests\test_graph_backend_eval.py tests\test_retrieval_backend_status.py tests\test_graph_backend_status.py -q`

- [ ] **Step 3: Run release gates**

Run:

```powershell
.\venv\Scripts\python.exe server.py --help
.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"
.\venv\Scripts\python.exe server.py --self-test
.\venv\Scripts\python.exe server.py --agent-eval
.\venv\Scripts\python.exe -m pytest -q
```

- [ ] **Step 4: Commit**

Commit message: `docs: record backend promotion gates`
