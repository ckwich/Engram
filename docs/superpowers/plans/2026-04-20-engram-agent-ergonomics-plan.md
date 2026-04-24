# Engram Agent Ergonomics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver all 8 agent-centered Engram improvements in one overnight session while preserving flat-file JSON memories as the source of truth, keeping ChromaDB rebuildable, and promoting the upgraded structured interface at the final verification gate if all checks pass.

**Architecture:** Build a structured agent-first interface beside the current string-returning MCP tools, enrich chunk and memory metadata without destructive migration, and add explicit helpers for validation, lifecycle, and session pinning. Use the new structured layer as the canonical internal contract, keep legacy text tools as wrappers during implementation, and only promote the new primary surface after full regression, health, export/import, and sampled retrieval checks pass.

**Tech Stack:** Python 3.10+, FastMCP, ChromaDB, sentence-transformers, pytest, PowerShell, existing Engram JSON + Chroma persistence model

---

## File Structure

### Create

- `tests/conftest.py`
- `tests/test_storage_invariants.py`
- `tests/test_chunker_metadata.py`
- `tests/test_server_structured_tools.py`
- `tests/test_memory_manager_filters.py`
- `tests/test_write_helpers.py`
- `tests/test_session_pins.py`
- `core/tool_payloads.py`
- `core/session_pins.py`

### Modify

- `core/chunker.py`
- `core/memory_manager.py`
- `server.py`
- `README.md`

### Responsibilities

- `tests/conftest.py`
  Provides isolated temp JSON/Chroma roots, fake embedder hooks, and server/memory manager fixtures so tests never touch the live `data/memories` or `data/chroma`.

- `tests/test_storage_invariants.py`
  Locks in JSON-first writes, Chroma-first deletes, rebuild safety, and backward compatibility for memories missing new metadata fields.

- `tests/test_chunker_metadata.py`
  Verifies that enriched chunk metadata is derived correctly while `chunk_content()` keeps the legacy return shape intact.

- `tests/test_server_structured_tools.py`
  Covers the new structured MCP tools, legacy wrapper behavior, and final canonical server contract.

- `tests/test_memory_manager_filters.py`
  Covers scoped search, metadata filters, explanations, batch retrieval, and stale/canonical handling.

- `tests/test_write_helpers.py`
  Covers duplicate inspection, validation, metadata suggestion, and lifecycle metadata updates.

- `tests/test_session_pins.py`
  Covers pin persistence, ordering, clearing, and search integration.

- `core/tool_payloads.py`
  Holds canonical payload builders and legacy string renderers so server code does not duplicate formatting logic.

- `core/session_pins.py`
  Stores per-session pinned keys outside permanent memory JSON and exposes a small API for pin operations.

- `core/chunker.py`
  Adds `chunk_content_with_metadata()` while preserving `chunk_content()` compatibility.

- `core/memory_manager.py`
  Gains additive metadata support, structured search/retrieval methods, batch retrieval, write helpers, lifecycle-aware updates, and search explanation fields.

- `server.py`
  Exposes new structured MCP tools, keeps legacy wrappers during implementation, expands self-test coverage, and handles final cutover logic.

- `README.md`
  Documents the new canonical structured interface, compatibility shims, session pins, and overnight-safe migration expectations.

---

## Execution Preconditions

Run these before touching code. Do not skip them.

```powershell
Set-Location C:\Dev\Engram

$stamp = "2026-04-20-agent-ergonomics"
$backupRoot = Join-Path ".overnight" $stamp
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $backupRoot "logs") | Out-Null

& C:\Dev\Engram\venv\Scripts\python.exe server.py --export 2>&1 |
  Tee-Object -FilePath (Join-Path $backupRoot "logs\export.txt")

Copy-Item data\memories (Join-Path $backupRoot "memories") -Recurse -Force
Copy-Item data\chroma (Join-Path $backupRoot "chroma") -Recurse -Force

& C:\Dev\Engram\venv\Scripts\python.exe server.py --help 2>&1 |
  Tee-Object -FilePath (Join-Path $backupRoot "logs\help.txt")

& C:\Dev\Engram\venv\Scripts\python.exe server.py --health 2>&1 |
  Tee-Object -FilePath (Join-Path $backupRoot "logs\health-baseline.txt")

& C:\Dev\Engram\venv\Scripts\python.exe server.py --self-test 2>&1 |
  Tee-Object -FilePath (Join-Path $backupRoot "logs\self-test-baseline.txt")

& C:\Dev\Engram\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')" 2>&1 |
  Tee-Object -FilePath (Join-Path $backupRoot "logs\import-baseline.txt")

& C:\Dev\Engram\venv\Scripts\python.exe -m pytest tests hooks/test_engram_evaluator.py -v 2>&1 |
  Tee-Object -FilePath (Join-Path $backupRoot "logs\pytest-baseline.txt")
```

Expected:

- `--help` exits `0`
- `--health` prints `Status: OK`
- `--self-test` prints `Self-test PASSED`
- import check prints `ok`
- pytest completes without touching live memory data

---

### Task 1: Build the Overnight Safety Harness

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_storage_invariants.py`
- Test: `tests/test_storage_invariants.py`

- [ ] **Step 1: Write the failing isolation and storage-order tests**

```python
# tests/test_storage_invariants.py
import json


def test_store_writes_json_before_chroma_upsert(isolated_manager, monkeypatch):
    calls = []

    monkeypatch.setattr(isolated_manager, "_save_json", lambda data: calls.append("json"))
    monkeypatch.setattr(isolated_manager, "_delete_chunks_from_chroma", lambda key: calls.append("delete"))
    monkeypatch.setattr(isolated_manager, "_index_chunks", lambda *args, **kwargs: calls.append("upsert"))

    isolated_manager.store_memory("alpha_memory", "## Alpha\n\nbody", ["engram"], "Alpha Memory")

    assert calls == ["json", "delete", "upsert"]


def test_delete_stops_if_chroma_delete_fails(isolated_manager, monkeypatch):
    isolated_manager.store_memory("beta_memory", "## Beta\n\nbody", ["engram"], "Beta Memory")

    def blow_up(key):
        raise RuntimeError("chroma locked")

    monkeypatch.setattr(isolated_manager, "_delete_chunks_from_chroma", blow_up)

    try:
        isolated_manager.delete_memory("beta_memory")
    except RuntimeError:
        pass

    assert isolated_manager.retrieve_memory("beta_memory") is not None


def test_old_memory_without_new_fields_is_still_listed(isolated_manager, isolated_json_dir):
    payload = {
        "key": "legacy_memory",
        "title": "Legacy Memory",
        "content": "## Legacy\n\nbody",
        "tags": ["legacy"],
        "created_at": "2026-04-20T00:00:00-07:00",
        "updated_at": "2026-04-20T00:00:00-07:00",
        "chars": 16,
        "lines": 2,
        "chunk_count": 1,
    }
    target = next(isolated_json_dir.glob("*.json"), None)
    if target is None:
        target = isolated_json_dir / "legacy.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    listed = isolated_manager.list_memories()

    assert any(item["key"] == "legacy_memory" for item in listed)
```

- [ ] **Step 2: Run the tests to verify the harness is missing**

Run:

```powershell
& C:\Dev\Engram\venv\Scripts\python.exe -m pytest tests/test_storage_invariants.py -v
```

Expected:

- FAIL with `fixture 'isolated_manager' not found`

- [ ] **Step 3: Implement the isolated test harness**

```python
# tests/conftest.py
import importlib
from pathlib import Path

import pytest

import core.memory_manager as memory_manager_module


class FakeEmbedder:
    def embed(self, text: str) -> list[float]:
        base = float(len(text) % 17)
        return [base, base + 1.0, base + 2.0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]

    async def embed_async(self, text: str) -> list[float]:
        return self.embed(text)

    async def embed_batch_async(self, texts: list[str]) -> list[list[float]]:
        return self.embed_batch(texts)


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    json_dir = tmp_path / "memories"
    chroma_dir = tmp_path / "chroma"
    json_dir.mkdir()
    chroma_dir.mkdir()

    monkeypatch.setattr(memory_manager_module, "JSON_DIR", json_dir)
    monkeypatch.setattr(memory_manager_module, "CHROMA_DIR", chroma_dir)
    monkeypatch.setattr(memory_manager_module, "embedder", FakeEmbedder())

    manager = memory_manager_module.MemoryManager()
    yield manager, json_dir, chroma_dir


@pytest.fixture
def isolated_manager(isolated_paths):
    manager, _, _ = isolated_paths
    return manager


@pytest.fixture
def isolated_json_dir(isolated_paths):
    _, json_dir, _ = isolated_paths
    return json_dir
```

- [ ] **Step 4: Run the tests to verify the safety harness works**

Run:

```powershell
& C:\Dev\Engram\venv\Scripts\python.exe -m pytest tests/test_storage_invariants.py -v
```

Expected:

- PASS with `3 passed`

- [ ] **Step 5: Commit the harness**

```powershell
git add tests/conftest.py tests/test_storage_invariants.py
git commit -m "test: add isolated Engram storage regression harness"
```

---

### Task 2: Introduce Structured Payload Builders and Initial v2 Tools

**Files:**
- Create: `core/tool_payloads.py`
- Create: `tests/test_server_structured_tools.py`
- Modify: `server.py`
- Test: `tests/test_server_structured_tools.py`

- [ ] **Step 1: Write failing tests for `search_memories_v2` and `list_memories_v2`**

```python
# tests/test_server_structured_tools.py
import pytest

import server


@pytest.mark.asyncio
async def test_search_memories_v2_returns_structured_payload(monkeypatch):
    async def fake_search(query, limit=5, **kwargs):
        return [
            {
                "key": "engram_core",
                "chunk_id": 0,
                "title": "Engram Core",
                "score": 0.95,
                "snippet": "semantic memory",
                "tags": ["engram", "core"],
                "project": "engram",
                "domain": "core",
                "status": "active",
                "canonical": True,
                "stale_type": "none",
                "explanation": {"same_project": True},
            }
        ]

    monkeypatch.setattr(server.memory_manager, "search_memories_async", fake_search)

    payload = await server.search_memories_v2("semantic memory")

    assert payload["query"] == "semantic memory"
    assert payload["count"] == 1
    assert payload["results"][0]["key"] == "engram_core"


@pytest.mark.asyncio
async def test_list_memories_v2_returns_items(monkeypatch):
    async def fake_list():
        return [{"key": "engram_core", "title": "Engram Core", "tags": ["engram"], "chunk_count": 4}]

    monkeypatch.setattr(server.memory_manager, "list_memories_async", fake_list)

    payload = await server.list_memories_v2()

    assert payload["count"] == 1
    assert payload["memories"][0]["title"] == "Engram Core"
```

- [ ] **Step 2: Run the tests to verify the v2 tools do not exist yet**

Run:

```powershell
& C:\Dev\Engram\venv\Scripts\python.exe -m pytest tests/test_server_structured_tools.py -v
```

Expected:

- FAIL with `AttributeError: module 'server' has no attribute 'search_memories_v2'`

- [ ] **Step 3: Implement canonical payload builders and the first structured tools**

```python
# core/tool_payloads.py
def build_search_payload(query: str, results: list[dict]) -> dict:
    return {
        "query": query,
        "count": len(results),
        "results": results,
    }


def build_list_payload(memories: list[dict]) -> dict:
    return {
        "count": len(memories),
        "memories": memories,
    }


def render_search_payload(payload: dict) -> str:
    if payload["count"] == 0:
        return f"🔍 No memories found for '{payload['query']}'"
    lines = [f"🔍 {payload['count']} results for '{payload['query']}':\n"]
    for item in payload["results"]:
        tags = ", ".join(item.get("tags", [])) or "none"
        lines.append(
            f"[score: {item['score']}] {item['title']}\n"
            f"  key={item['key']}  chunk_id={item['chunk_id']}  tags={tags}\n"
            f"  snippet: {item['snippet']}\n"
        )
    return "\n".join(lines)


def render_list_payload(payload: dict) -> str:
    if payload["count"] == 0:
        return "📭 No memories stored yet."
    lines = [f"📚 Engram Memory Directory — {payload['count']} memories\n{'='*50}\n"]
    for item in payload["memories"]:
        tags = ", ".join(item.get("tags", [])) or "none"
        lines.append(
            f"🔑 {item['key']}\n"
            f"   Title:   {item['title']}\n"
            f"   Tags:    {tags}\n"
            f"   Chunks:  {item['chunk_count']}\n"
        )
    return "\n".join(lines)
```

```python
# server.py
from core.tool_payloads import (
    build_list_payload,
    build_search_payload,
    render_list_payload,
    render_search_payload,
)


@mcp.tool()
async def search_memories_v2(query: str, limit: int = 5) -> dict:
    results = await memory_manager.search_memories_async(query.strip(), limit=min(max(limit, 1), 20))
    return build_search_payload(query.strip(), results)


@mcp.tool()
async def list_memories_v2() -> dict:
    memories = await memory_manager.list_memories_async()
    return build_list_payload(memories)


@mcp.tool()
async def search_memories(query: str, limit: int = 5) -> str:
    payload = await search_memories_v2(query, limit)
    return render_search_payload(payload)


@mcp.tool()
async def list_all_memories() -> str:
    payload = await list_memories_v2()
    return render_list_payload(payload)
```

- [ ] **Step 4: Run the structured-tool tests**

Run:

```powershell
& C:\Dev\Engram\venv\Scripts\python.exe -m pytest tests/test_server_structured_tools.py -v
```

Expected:

- PASS with `2 passed`

- [ ] **Step 5: Commit the structured payload foundation**

```powershell
git add core/tool_payloads.py server.py tests/test_server_structured_tools.py
git commit -m "feat: add structured Engram payload builders and v2 search tools"
```

---

### Task 3: Enrich Chunk Metadata Without Breaking `chunk_content()`

**Files:**
- Modify: `core/chunker.py`
- Create: `tests/test_chunker_metadata.py`
- Test: `tests/test_chunker_metadata.py`

- [ ] **Step 1: Write failing chunk metadata tests**

```python
# tests/test_chunker_metadata.py
from core.chunker import chunk_content, chunk_content_with_metadata


def test_chunk_content_with_metadata_tracks_heading_path():
    content = "# Root\n\n## Child\n\nParagraph one.\n\nParagraph two."

    chunks = chunk_content_with_metadata(content, max_size=80)

    assert chunks[0]["section_title"] == "Root"
    assert chunks[-1]["heading_path"][-1] == "Child"
    assert "chunk_kind" in chunks[0]


def test_chunk_content_keeps_legacy_shape():
    content = "# Root\n\nParagraph"

    chunks = chunk_content(content)

    assert chunks == [{"chunk_id": 0, "text": "# Root\n\nParagraph"}]
```

- [ ] **Step 2: Run the chunk metadata tests to confirm the helper is missing**

Run:

```powershell
& C:\Dev\Engram\venv\Scripts\python.exe -m pytest tests/test_chunker_metadata.py -v
```

Expected:

- FAIL with `ImportError` or `AttributeError` for `chunk_content_with_metadata`

- [ ] **Step 3: Implement metadata-aware chunking while preserving compatibility**

```python
# core/chunker.py
def chunk_content_with_metadata(content: str, max_size: int = MAX_CHUNK_SIZE) -> list[dict]:
    if not content or not content.strip():
        return [{
            "chunk_id": 0,
            "text": content.strip(),
            "section_title": "",
            "heading_path": [],
            "chunk_kind": "empty",
        }]

    sections = re.split(r'(?=^#{1,3}\s)', content, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()] or [content.strip()]

    final_chunks = []
    for section in sections:
        first_line = section.splitlines()[0].strip()
        section_title = first_line.lstrip("# ").strip() if first_line.startswith("#") else ""
        heading_path = [section_title] if section_title else []

        if len(section) <= max_size:
            final_chunks.append((section, section_title, heading_path, "section"))
            continue

        paragraphs = [p.strip() for p in section.split("\n\n") if p.strip()]
        current = ""
        for para in paragraphs:
            if not current:
                current = para
            elif len(current) + 2 + len(para) <= max_size:
                current += "\n\n" + para
            else:
                final_chunks.append((current, section_title, heading_path, "paragraph"))
                current = para
        if current:
            final_chunks.append((current, section_title, heading_path, "paragraph"))

    output = []
    next_id = 0
    for text, section_title, heading_path, chunk_kind in final_chunks:
        if len(text) <= max_size:
            output.append({
                "chunk_id": next_id,
                "text": text,
                "section_title": section_title,
                "heading_path": heading_path,
                "chunk_kind": chunk_kind,
            })
            next_id += 1
            continue

        for i in range(0, len(text), max_size):
            output.append({
                "chunk_id": next_id,
                "text": text[i:i + max_size],
                "section_title": section_title,
                "heading_path": heading_path,
                "chunk_kind": "hard_split",
            })
            next_id += 1

    return output


def chunk_content(content: str, max_size: int = MAX_CHUNK_SIZE) -> list[dict]:
    chunks = chunk_content_with_metadata(content, max_size=max_size)
    return [{"chunk_id": item["chunk_id"], "text": item["text"]} for item in chunks]
```

- [ ] **Step 4: Run the chunk metadata tests**

Run:

```powershell
& C:\Dev\Engram\venv\Scripts\python.exe -m pytest tests/test_chunker_metadata.py -v
```

Expected:

- PASS with `2 passed`

- [ ] **Step 5: Commit the chunk metadata layer**

```powershell
git add core/chunker.py tests/test_chunker_metadata.py
git commit -m "feat: add metadata-aware chunking for Engram"
```

---

### Task 4: Add Structured Search Filters, Explanations, and Metadata Indexing

**Files:**
- Modify: `core/memory_manager.py`
- Create: `tests/test_memory_manager_filters.py`
- Test: `tests/test_memory_manager_filters.py`

- [ ] **Step 1: Write failing tests for scoped search and explanations**

```python
# tests/test_memory_manager_filters.py
def test_structured_search_filters_by_project_and_canonical(isolated_manager):
    isolated_manager.store_memory(
        "engram_core",
        "## Core\n\nSemantic memory internals",
        ["engram", "core"],
        "Engram Core",
        project="engram",
        domain="core",
        canonical=True,
        status="active",
    )
    isolated_manager.store_memory(
        "other_project",
        "## Other\n\nSemantic memory internals",
        ["other", "core"],
        "Other Core",
        project="other",
        domain="core",
        canonical=False,
        status="active",
    )

    payload = isolated_manager.search_memories_structured(
        "semantic memory",
        limit=5,
        project="engram",
        canonical_only=True,
    )

    assert payload["count"] == 1
    assert payload["results"][0]["key"] == "engram_core"
    assert payload["results"][0]["explanation"]["same_project"] is True


def test_structured_search_exposes_stale_and_status_fields(isolated_manager):
    isolated_manager.store_memory(
        "historical_memory",
        "## Historical\n\nOld architecture note",
        ["engram", "history"],
        "Historical Memory",
        project="engram",
        domain="history",
        canonical=False,
        status="historical",
    )

    payload = isolated_manager.search_memories_structured("architecture", limit=5)

    assert payload["results"][0]["status"] == "historical"
    assert "stale_type" in payload["results"][0]
```

- [ ] **Step 2: Run the scoped-search tests to verify the structured search API is missing**

Run:

```powershell
& C:\Dev\Engram\venv\Scripts\python.exe -m pytest tests/test_memory_manager_filters.py -v
```

Expected:

- FAIL with `TypeError` because `store_memory()` does not accept `project`
- FAIL with `AttributeError` because `search_memories_structured` does not exist

- [ ] **Step 3: Implement additive metadata persistence and structured search**

```python
# core/memory_manager.py
def _normalize_memory_metadata(
    self,
    *,
    project: str | None = None,
    domain: str | None = None,
    memory_type: str | None = None,
    source_kind: str | None = None,
    status: str = "active",
    canonical: bool = False,
    confidence: str | None = None,
    supersedes: list[str] | None = None,
    superseded_by: str | None = None,
) -> dict:
    return {
        "project": project,
        "domain": domain,
        "memory_type": memory_type,
        "source_kind": source_kind or "manual",
        "status": status,
        "canonical": canonical,
        "confidence": confidence,
        "supersedes": supersedes or [],
        "superseded_by": superseded_by,
    }


def _chunk_metadata(self, key: str, chunk: dict, title: str, tags: list[str], record: dict) -> dict:
    return {
        "parent_key": key,
        "chunk_id": chunk["chunk_id"],
        "title": title,
        "tags": ",".join(tags),
        "project": record.get("project") or "",
        "domain": record.get("domain") or "",
        "memory_type": record.get("memory_type") or "",
        "source_kind": record.get("source_kind") or "manual",
        "section_title": chunk.get("section_title", ""),
        "heading_path": " / ".join(chunk.get("heading_path", [])),
        "status": record.get("status", "active"),
        "canonical": str(bool(record.get("canonical", False))).lower(),
    }


def _prepare_store(
    self,
    key: str,
    content: str,
    tags: list[str] | None = None,
    title: str | None = None,
    related_to: list[str] | None = None,
    force: bool = False,
    *,
    metadata: dict | None = None,
) -> tuple[dict, list[dict]]:
    record = metadata or {}
    now = _now()
    existing = self._load_json(key)
    created_at = existing["created_at"] if existing else now
    resolved_title = title or (existing["title"] if existing else key)
    action = "Updated" if existing else "Created"
    content_with_log = f"{content}\n\n---\n**{now} | {action} via Engram**"

    data = {
        "key": key,
        "title": resolved_title,
        "content": content_with_log,
        "tags": tags or [],
        "created_at": created_at,
        "updated_at": now,
        "last_accessed": existing.get("last_accessed", None) if existing else None,
        "related_to": list(related_to or []),
        "chars": len(content_with_log),
        "lines": len(content_with_log.splitlines()),
        **record,
    }

    chunks = chunk_content_with_metadata(content_with_log)
    data["chunk_count"] = len(chunks)
    data["heading_index"] = [chunk.get("section_title", "") for chunk in chunks if chunk.get("section_title")]

    self._save_json(data)
    try:
        self._delete_chunks_from_chroma(key)
    except Exception as exc:
        print(f"[Engram] WARNING: Failed to delete old chunks for '{key}': {exc}", file=sys.stderr)

    return data, chunks


def store_memory(
    self,
    key: str,
    content: str,
    tags: list[str] | None = None,
    title: str | None = None,
    related_to: list[str] | None = None,
    *,
    project: str | None = None,
    domain: str | None = None,
    memory_type: str | None = None,
    source_kind: str | None = None,
    status: str = "active",
    canonical: bool = False,
    confidence: str | None = None,
    supersedes: list[str] | None = None,
    superseded_by: str | None = None,
    force: bool = False,
) -> dict:
    metadata = self._normalize_memory_metadata(
        project=project,
        domain=domain,
        memory_type=memory_type,
        source_kind=source_kind,
        status=status,
        canonical=canonical,
        confidence=confidence,
        supersedes=supersedes,
        superseded_by=superseded_by,
    )
    data, chunks = self._prepare_store(
        key,
        content,
        tags,
        title,
        related_to,
        force,
        metadata=metadata,
    )
    self._index_chunks(key, chunks, data["title"], data["tags"], data.get("related_to", []))
    return data


async def store_memory_async(
    self,
    key: str,
    content: str,
    tags: list[str] | None = None,
    title: str | None = None,
    related_to: list[str] | None = None,
    **metadata_fields,
) -> dict:
    force = bool(metadata_fields.pop("force", False))
    metadata = self._normalize_memory_metadata(**metadata_fields)
    data, chunks = await _run_blocking(
        self._prepare_store,
        key,
        content,
        tags,
        title,
        related_to,
        force,
        metadata=metadata,
    )
    await self._index_chunks_async(key, chunks, data["title"], data["tags"], data.get("related_to", []))
    return data


def search_memories_structured(
    self,
    query: str,
    limit: int = 5,
    *,
    project: str | None = None,
    domain: str | None = None,
    tags: list[str] | None = None,
    include_stale: bool = True,
    canonical_only: bool = False,
    pinned_keys: list[str] | None = None,
    pinned_first: bool = False,
) -> dict:
    raw = self.search_memories(query, limit=max(limit * 5, 20))
    filtered = []
    wanted_tags = set(tags or [])
    pinned_key_set = set(pinned_keys or [])

    for item in raw:
        memory = self._load_json(item["key"]) or {}
        stale_type = "code" if memory.get("potentially_stale") else "none"
        if project and memory.get("project") != project:
            continue
        if domain and memory.get("domain") != domain:
            continue
        if wanted_tags and not wanted_tags.issubset(set(memory.get("tags", []))):
            continue
        if canonical_only and not memory.get("canonical", False):
            continue
        if not include_stale and stale_type != "none":
            continue

        item["project"] = memory.get("project")
        item["domain"] = memory.get("domain")
        item["status"] = memory.get("status", "active")
        item["canonical"] = memory.get("canonical", False)
        item["stale_type"] = stale_type
        item["explanation"] = {
            "same_project": bool(project and memory.get("project") == project),
            "matched_tags": sorted(wanted_tags.intersection(set(memory.get("tags", [])))),
            "is_pinned": item["key"] in pinned_key_set,
            "excluded_by_filters": [],
        }
        filtered.append(item)

    if pinned_first:
        filtered.sort(key=lambda row: (not row["explanation"]["is_pinned"], -row["score"]))

    payload = {"query": query, "count": min(len(filtered), limit), "results": filtered[:limit]}
    return payload


async def search_memories_structured_async(self, query: str, limit: int = 5, **filters) -> dict:
    return await _run_blocking(self.search_memories_structured, query, limit, **filters)
```

- [ ] **Step 4: Run the scoped-search tests**

Run:

```powershell
& C:\Dev\Engram\venv\Scripts\python.exe -m pytest tests/test_memory_manager_filters.py -v
```

Expected:

- PASS with `2 passed`

- [ ] **Step 5: Commit the structured search internals**

```powershell
git add core/memory_manager.py tests/test_memory_manager_filters.py
git commit -m "feat: add scoped structured search for Engram"
```

---

### Task 5: Add Structured Retrieval and Batch Retrieval

**Files:**
- Modify: `core/memory_manager.py`
- Modify: `server.py`
- Modify: `tests/test_server_structured_tools.py`
- Test: `tests/test_server_structured_tools.py`

- [ ] **Step 1: Extend the server tests with retrieval and batch retrieval failures**

```python
# tests/test_server_structured_tools.py
@pytest.mark.asyncio
async def test_retrieve_chunks_v2_returns_multiple_chunks(monkeypatch):
    async def fake_batch(requests):
        return [
            {"key": "engram_core", "chunk_id": 0, "title": "Engram Core", "text": "Chunk A"},
            {"key": "engram_core", "chunk_id": 1, "title": "Engram Core", "text": "Chunk B"},
        ]

    monkeypatch.setattr(server.memory_manager, "retrieve_chunks_async", fake_batch)

    payload = await server.retrieve_chunks_v2(
        [{"key": "engram_core", "chunk_id": 0}, {"key": "engram_core", "chunk_id": 1}]
    )

    assert payload["count"] == 2
    assert payload["chunks"][1]["text"] == "Chunk B"


@pytest.mark.asyncio
async def test_retrieve_memory_v2_returns_metadata_and_content(monkeypatch):
    async def fake_retrieve(key):
        return {
            "key": key,
            "title": "Engram Core",
            "content": "## Core\n\nbody",
            "tags": ["engram"],
            "chunk_count": 2,
            "status": "active",
            "canonical": True,
        }

    monkeypatch.setattr(server.memory_manager, "retrieve_memory_async", fake_retrieve)

    payload = await server.retrieve_memory_v2("engram_core")

    assert payload["memory"]["key"] == "engram_core"
    assert payload["memory"]["canonical"] is True
```

- [ ] **Step 2: Run the server tests to confirm the retrieval tools are missing**

Run:

```powershell
& C:\Dev\Engram\venv\Scripts\python.exe -m pytest tests/test_server_structured_tools.py -v
```

Expected:

- FAIL with missing `retrieve_chunks_v2` / `retrieve_memory_v2`

- [ ] **Step 3: Implement structured retrieval and batch retrieval**

```python
# core/memory_manager.py
def retrieve_chunks(self, requests: list[dict]) -> list[dict]:
    output = []
    for request in requests:
        chunk = self.retrieve_chunk(request["key"], int(request["chunk_id"]))
        if chunk:
            output.append(chunk)
    return output


async def retrieve_chunks_async(self, requests: list[dict]) -> list[dict]:
    return await _run_chroma(self.retrieve_chunks, requests)
```

```python
# server.py
@mcp.tool()
async def retrieve_chunk_v2(key: str, chunk_id: int) -> dict:
    chunk = await memory_manager.retrieve_chunk_async(key, chunk_id)
    if not chunk:
        return {"found": False, "key": key, "chunk_id": chunk_id}
    return {"found": True, "chunk": chunk}


@mcp.tool()
async def retrieve_chunks_v2(requests: list[dict]) -> dict:
    chunks = await memory_manager.retrieve_chunks_async(requests)
    return {"count": len(chunks), "chunks": chunks}


@mcp.tool()
async def retrieve_memory_v2(key: str) -> dict:
    memory = await memory_manager.retrieve_memory_async(key)
    if not memory:
        return {"found": False, "key": key}
    return {"found": True, "memory": memory}


@mcp.tool()
async def get_related_memories_v2(key: str) -> dict:
    return await memory_manager.get_related_memories_async(key)


@mcp.tool()
async def get_stale_memories_v2(days: int = 90, type: str = "all") -> dict:
    results = await memory_manager.get_stale_memories_async(days=days, type=type)
    return {"count": len(results), "memories": results, "days": days, "type": type}
```

- [ ] **Step 4: Run the structured server tests**

Run:

```powershell
& C:\Dev\Engram\venv\Scripts\python.exe -m pytest tests/test_server_structured_tools.py -v
```

Expected:

- PASS with `4 passed`

- [ ] **Step 5: Commit the retrieval layer**

```powershell
git add core/memory_manager.py server.py tests/test_server_structured_tools.py
git commit -m "feat: add structured Engram retrieval and batch chunk APIs"
```

---

### Task 6: Add Safer Write Helpers and Lifecycle Metadata Updates

**Files:**
- Create: `tests/test_write_helpers.py`
- Modify: `core/memory_manager.py`
- Modify: `server.py`
- Test: `tests/test_write_helpers.py`

- [ ] **Step 1: Write failing tests for duplicate checks, validation, metadata suggestion, and lifecycle updates**

```python
# tests/test_write_helpers.py
def test_suggest_memory_metadata_uses_heading_and_tags(isolated_manager):
    suggestion = isolated_manager.suggest_memory_metadata(
        "## Scheduler backlog\n\nDispatch travel rule decisions."
    )

    assert suggestion["key"] == "scheduler_backlog"
    assert "scheduler" in suggestion["tags"]


def test_validate_memory_flags_oversized_and_invalid_relationships(isolated_manager):
    payload = isolated_manager.validate_memory(
        key="too_big",
        content="x" * 16001,
        related_to=["a"] * 11,
    )

    assert payload["ok"] is False
    assert any("15,000" in error for error in payload["errors"])
    assert any("maximum is 10" in error for error in payload["errors"])


def test_update_memory_metadata_reindexes_existing_memory(isolated_manager):
    isolated_manager.store_memory("alpha_memory", "## Alpha\n\nbody", ["engram"], "Alpha Memory")

    updated = isolated_manager.update_memory_metadata(
        "alpha_memory",
        canonical=True,
        status="historical",
        project="engram",
        domain="core",
    )

    assert updated["canonical"] is True
    assert updated["status"] == "historical"
    assert updated["project"] == "engram"
```

- [ ] **Step 2: Run the write-helper tests to verify the helpers do not exist**

Run:

```powershell
& C:\Dev\Engram\venv\Scripts\python.exe -m pytest tests/test_write_helpers.py -v
```

Expected:

- FAIL with missing helper methods

- [ ] **Step 3: Implement the write helpers and lifecycle-aware metadata updates**

```python
# core/memory_manager.py
def suggest_memory_metadata(self, content: str) -> dict:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    heading = next((line.lstrip("# ").strip() for line in lines if line.startswith("#")), "memory")
    key = re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_") or "memory"
    words = [word for word in re.findall(r"[a-zA-Z0-9]+", content.lower()) if len(word) > 3]
    tags = list(dict.fromkeys(words[:3]))
    return {"key": key, "title": heading, "tags": tags}


async def suggest_memory_metadata_async(self, content: str) -> dict:
    return await _run_blocking(self.suggest_memory_metadata, content)


def validate_memory(self, *, key: str, content: str, related_to: list[str] | None = None, **kwargs) -> dict:
    errors = []
    if len(content) > MAX_MEMORY_CHARS:
        errors.append(f"Content exceeds the {MAX_MEMORY_CHARS:,} char limit.")
    if related_to and len(related_to) > 10:
        errors.append("related_to maximum is 10 entries.")
    if kwargs.get("status") and kwargs["status"] not in {"active", "draft", "historical", "superseded", "archived"}:
        errors.append("status must be one of active, draft, historical, superseded, archived.")
    return {"ok": not errors, "errors": errors}


async def validate_memory_async(self, **payload) -> dict:
    return await _run_blocking(self.validate_memory, **payload)


def update_memory_metadata(self, key: str, **changes) -> dict:
    data = self._load_json(key)
    if data is None:
        raise ValueError(f"Memory not found: {key}")

    data.update(changes)
    data["updated_at"] = _now()
    self._save_json(data)

    chunks = chunk_content_with_metadata(data["content"])
    self._delete_chunks_from_chroma(key)
    self._index_chunks(key, chunks, data["title"], data.get("tags", []), data.get("related_to", []))
    return data


async def update_memory_metadata_async(self, key: str, **changes) -> dict:
    return await _run_blocking(self.update_memory_metadata, key, **changes)
```

```python
# server.py
from core.memory_manager import _run_blocking

@mcp.tool()
async def check_duplicate(key: str, content: str) -> dict:
    duplicate = await _run_blocking(memory_manager._check_dedup, content, key)
    return {"duplicate": duplicate is not None, "match": duplicate}


@mcp.tool()
async def suggest_memory_metadata(content: str) -> dict:
    return await memory_manager.suggest_memory_metadata_async(content)


@mcp.tool()
async def validate_memory(key: str, content: str, related_to: str = "", status: str = "active") -> dict:
    related_list = [item.strip() for item in related_to.split(",") if item.strip()]
    return await memory_manager.validate_memory_async(
        key=key,
        content=content,
        related_to=related_list,
        status=status,
    )


@mcp.tool()
async def update_memory_metadata(key: str, canonical: bool = False, status: str = "active", project: str = "", domain: str = "") -> dict:
    return await memory_manager.update_memory_metadata_async(
        key,
        canonical=canonical,
        status=status,
        project=project or None,
        domain=domain or None,
    )
```

- [ ] **Step 4: Run the write-helper tests**

Run:

```powershell
& C:\Dev\Engram\venv\Scripts\python.exe -m pytest tests/test_write_helpers.py -v
```

Expected:

- PASS with `3 passed`

- [ ] **Step 5: Commit the safer write helpers**

```powershell
git add core/memory_manager.py server.py tests/test_write_helpers.py
git commit -m "feat: add Engram write validation and lifecycle helpers"
```

---

### Task 7: Add Session Pins and Pinned-First Search

**Files:**
- Create: `core/session_pins.py`
- Create: `tests/test_session_pins.py`
- Modify: `server.py`
- Modify: `core/memory_manager.py`
- Test: `tests/test_session_pins.py`

- [ ] **Step 1: Write failing tests for pinning and pinned-first ordering**

```python
# tests/test_session_pins.py
from core.session_pins import SessionPinStore


def test_pin_store_round_trip(tmp_path):
    store = SessionPinStore(tmp_path / "pins.json")

    store.pin("default", "engram_core")
    store.pin("default", "engram_core")
    store.pin("default", "engram_indexer")

    assert store.list_pins("default") == ["engram_core", "engram_indexer"]

    store.unpin("default", "engram_core")
    assert store.list_pins("default") == ["engram_indexer"]


def test_pinned_results_sort_first(isolated_manager, monkeypatch):
    results = [
        {"key": "b", "score": 0.99, "title": "B", "chunk_id": 0, "snippet": "b", "tags": []},
        {"key": "a", "score": 0.80, "title": "A", "chunk_id": 0, "snippet": "a", "tags": []},
    ]

    monkeypatch.setattr(isolated_manager, "search_memories", lambda query, limit=5: results)

    payload = isolated_manager.search_memories_structured(
        "x",
        limit=5,
        pinned_keys=["a"],
        pinned_first=True,
    )

    assert payload["results"][0]["key"] == "a"
    assert payload["results"][0]["explanation"]["is_pinned"] is True
```

- [ ] **Step 2: Run the pinning tests to verify the store is missing**

Run:

```powershell
& C:\Dev\Engram\venv\Scripts\python.exe -m pytest tests/test_session_pins.py -v
```

Expected:

- FAIL with `ModuleNotFoundError: No module named 'core.session_pins'`

- [ ] **Step 3: Implement the session pin store and pin-aware search**

```python
# core/session_pins.py
import json
from pathlib import Path


class SessionPinStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def pin(self, session_id: str, key: str) -> list[str]:
        data = self._load()
        current = data.setdefault(session_id, [])
        if key not in current:
            current.append(key)
            self._save(data)
        return current

    def unpin(self, session_id: str, key: str) -> list[str]:
        data = self._load()
        current = data.setdefault(session_id, [])
        data[session_id] = [item for item in current if item != key]
        self._save(data)
        return data[session_id]

    def list_pins(self, session_id: str) -> list[str]:
        return self._load().get(session_id, [])

    def clear(self, session_id: str) -> list[str]:
        data = self._load()
        data[session_id] = []
        self._save(data)
        return []
```

```python
# server.py
from core.memory_manager import _run_blocking
from pathlib import Path
from core.session_pins import SessionPinStore

pin_store = SessionPinStore(Path(__file__).parent / "data" / "session_state" / "pins.json")


@mcp.tool()
async def pin_memory(session_id: str, key: str) -> dict:
    pins = await _run_blocking(pin_store.pin, session_id, key)
    return {"session_id": session_id, "pins": pins}


@mcp.tool()
async def unpin_memory(session_id: str, key: str) -> dict:
    pins = await _run_blocking(pin_store.unpin, session_id, key)
    return {"session_id": session_id, "pins": pins}


@mcp.tool()
async def list_pins(session_id: str) -> dict:
    pins = await _run_blocking(pin_store.list_pins, session_id)
    return {"session_id": session_id, "pins": pins}


@mcp.tool()
async def clear_pins(session_id: str) -> dict:
    pins = await _run_blocking(pin_store.clear, session_id)
    return {"session_id": session_id, "pins": pins}


@mcp.tool()
async def search_memories_v2(
    query: str,
    limit: int = 5,
    project: str = "",
    domain: str = "",
    tags: list[str] | None = None,
    include_stale: bool = True,
    canonical_only: bool = False,
    session_id: str = "",
    pinned_first: bool = False,
) -> dict:
    pinned_keys = await _run_blocking(pin_store.list_pins, session_id) if session_id else []
    return await memory_manager.search_memories_structured_async(
        query.strip(),
        limit=min(max(limit, 1), 20),
        project=project or None,
        domain=domain or None,
        tags=tags or [],
        include_stale=include_stale,
        canonical_only=canonical_only,
        pinned_keys=pinned_keys,
        pinned_first=pinned_first,
    )
```

- [ ] **Step 4: Run the pinning tests**

Run:

```powershell
& C:\Dev\Engram\venv\Scripts\python.exe -m pytest tests/test_session_pins.py -v
```

Expected:

- PASS with `2 passed`

- [ ] **Step 5: Commit the session working-set layer**

```powershell
git add core/session_pins.py core/memory_manager.py server.py tests/test_session_pins.py
git commit -m "feat: add Engram session pinning and pinned-first search"
```

---

### Task 8: Final Cutover, Docs, and Full Verification

**Files:**
- Modify: `server.py`
- Modify: `README.md`
- Modify: `tests/test_server_structured_tools.py`
- Test: `tests/test_server_structured_tools.py`, `tests/test_storage_invariants.py`, `tests/test_chunker_metadata.py`, `tests/test_memory_manager_filters.py`, `tests/test_write_helpers.py`, `tests/test_session_pins.py`, `hooks/test_engram_evaluator.py`

- [ ] **Step 1: Write failing compatibility and final-surface tests**

```python
# tests/test_server_structured_tools.py
@pytest.mark.asyncio
async def test_legacy_search_tool_is_rendered_from_structured_payload(monkeypatch):
    async def fake_search_v2(query, limit=5):
        return {
            "query": query,
            "count": 1,
            "results": [
                {
                    "key": "engram_core",
                    "chunk_id": 0,
                    "title": "Engram Core",
                    "score": 0.95,
                    "snippet": "semantic memory",
                    "tags": ["engram"],
                }
            ],
        }

    monkeypatch.setattr(server, "search_memories_v2", fake_search_v2)

    text = await server.search_memories("semantic memory")

    assert "engram_core" in text
    assert "semantic memory" in text


@pytest.mark.asyncio
async def test_legacy_list_tool_is_rendered_from_structured_payload(monkeypatch):
    async def fake_list_v2():
        return {
            "count": 1,
            "memories": [
                {"key": "engram_core", "title": "Engram Core", "tags": ["engram"], "chunk_count": 4}
            ],
        }

    monkeypatch.setattr(server, "list_memories_v2", fake_list_v2)

    text = await server.list_all_memories()

    assert "Engram Core" in text
    assert "chunk_count" not in text
```

- [ ] **Step 2: Run the full targeted suite to identify any remaining gaps**

Run:

```powershell
& C:\Dev\Engram\venv\Scripts\python.exe -m pytest `
  tests/test_storage_invariants.py `
  tests/test_chunker_metadata.py `
  tests/test_server_structured_tools.py `
  tests/test_memory_manager_filters.py `
  tests/test_write_helpers.py `
  tests/test_session_pins.py `
  hooks/test_engram_evaluator.py -v
```

Expected:

- FAIL anywhere legacy wrappers are not fully routed through structured payload builders

- [ ] **Step 3: Finish the cutover and documentation updates**

```python
# server.py
@mcp.tool()
async def search_memories(query: str, limit: int = 5) -> str:
    payload = await search_memories_v2(query, limit)
    return render_search_payload(payload)


@mcp.tool()
async def retrieve_chunk(key: str, chunk_id: int) -> str:
    payload = await retrieve_chunk_v2(key, chunk_id)
    if not payload["found"]:
        return f"❌ Chunk not found: key='{key}' chunk_id={chunk_id}"
    chunk = payload["chunk"]
    return f"📄 Chunk {chunk['chunk_id']} from '{chunk['title']}'\n🔑 Key: {chunk['key']}\n\n{chunk['text']}"
```

```markdown
<!-- README.md -->
## Agent-First Structured Tools

Engram now exposes a canonical structured tool surface for agent use:

- `search_memories_v2`
- `list_memories_v2`
- `retrieve_chunk_v2`
- `retrieve_chunks_v2`
- `retrieve_memory_v2`
- `get_related_memories_v2`
- `get_stale_memories_v2`
- `check_duplicate`
- `suggest_memory_metadata`
- `validate_memory`
- `update_memory_metadata`
- `pin_memory`
- `unpin_memory`
- `list_pins`
- `clear_pins`

The legacy text-returning tools remain as compatibility wrappers over the same canonical payload builders.
```

- [ ] **Step 4: Run the final overnight verification sequence**

Run:

```powershell
& C:\Dev\Engram\venv\Scripts\python.exe -m pytest `
  tests/test_storage_invariants.py `
  tests/test_chunker_metadata.py `
  tests/test_server_structured_tools.py `
  tests/test_memory_manager_filters.py `
  tests/test_write_helpers.py `
  tests/test_session_pins.py `
  hooks/test_engram_evaluator.py -v

& C:\Dev\Engram\venv\Scripts\python.exe server.py --self-test
& C:\Dev\Engram\venv\Scripts\python.exe server.py --health
& C:\Dev\Engram\venv\Scripts\python.exe server.py --export

@'
import json
import tempfile
from pathlib import Path

import core.memory_manager as mm
from core.memory_manager import MemoryManager

bundle_path = sorted(Path(".").glob("engram_export_*.json"))[-1]
bundle = json.loads(bundle_path.read_text(encoding="utf-8"))

tmp = Path(tempfile.mkdtemp())
json_dir = tmp / "memories"
chroma_dir = tmp / "chroma"
json_dir.mkdir()
chroma_dir.mkdir()

mm.JSON_DIR = json_dir
mm.CHROMA_DIR = chroma_dir
manager = MemoryManager()

for record in bundle[:3]:
    manager.store_memory(record["key"], record["content"], record.get("tags", []), record.get("title"))

assert manager.list_memories(), "import smoke created no memories"
print("import smoke ok")
'@ | & C:\Dev\Engram\venv\Scripts\python.exe -
```

Expected:

- All pytest targets PASS
- `Self-test PASSED`
- `Status: OK`
- export succeeds without dropping memory count

- [ ] **Step 5: Commit the cutover-ready overnight release**

```powershell
git add core/chunker.py core/memory_manager.py core/tool_payloads.py core/session_pins.py `
  server.py README.md tests/conftest.py tests/test_storage_invariants.py `
  tests/test_chunker_metadata.py tests/test_server_structured_tools.py `
  tests/test_memory_manager_filters.py tests/test_write_helpers.py `
  tests/test_session_pins.py
git commit -m "feat: deliver Engram agent ergonomics upgrade suite"
```

---

## Spec Coverage Check

- Structured outputs: Task 2, Task 5, Task 8
- Scoped search filters: Task 4
- Richer chunk metadata: Task 3 and Task 4
- Batch retrieval: Task 5
- Safer write helpers: Task 6
- Lifecycle semantics: Task 4 and Task 6
- Search explanations / confidence signals: Task 4 and Task 7
- Session working set / pinning: Task 7
- Final verified cutover gate: Task 8

## Placeholder Scan

- No `TODO`, `TBD`, or deferred implementation notes are allowed during execution.
- If a step reveals an unplanned dependency, add a concrete task to this plan before implementation continues.

## Type Consistency Check

- Canonical structured search entry keys:
  - `key`
  - `chunk_id`
  - `title`
  - `score`
  - `snippet`
  - `tags`
  - `project`
  - `domain`
  - `status`
  - `canonical`
  - `stale_type`
  - `explanation`
- Session pin methods use `session_id` and `key` consistently.
- Lifecycle states remain exactly:
  - `active`
  - `draft`
  - `historical`
  - `superseded`
  - `archived`
