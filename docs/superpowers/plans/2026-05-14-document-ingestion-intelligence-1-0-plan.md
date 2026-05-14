# Document Ingestion And Intelligence 1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to execute this plan.

**Goal:** Make Engram's document ingestion and intelligence tools usable end-to-end from the normal daemon-backed MCP entrypoint. A Codex session should be able to inspect a document, disassemble it, request missing OCR/visual/table coverage, prepare extraction results, prepare understanding packets, draft reviewed memories and graph proposals, store explicit ledgered document evidence artifacts, and query that evidence through EKC without silent promotion or uncited claims.

**Architecture:** Preserve the review-first Memory OS boundary. Direct `server.py` may keep the broad beta surface, but `server_daemon_client.py` must expose the stable document workflow through thin daemon calls. `engramd` owns every store-backed artifact. No MCP client imports document extractors, Poppler wrappers, memory stores, LanceDB, Kuzu, or Chroma. No document tool promotes active memory unless a reviewed promotion transaction is explicitly executed.

**Tech Stack:** Python 3.10+, FastMCP, Engram daemon HTTP API/client, SQLite Memory OS ledger, content-addressed artifact store, local Poppler tools (`pdfinfo`, `pdftotext`, `pdfimages`), pytest, synthetic document fixtures, optional env-gated local PDF smoke tests.

## Current Truth

- `server.py` already exposes the broad document-intelligence helpers.
- `server_daemon_client.py`, `core/engramd_api.py`, and `core/engramd_client.py` currently route only `prepare_document_disassembly`.
- The live daemon client exposes `prepare_document_disassembly` through MCP and returns structured `invalid_request` for missing files.
- The document test lane currently passes:
  - `tests/test_document_intelligence.py`
  - `tests/test_document_disassembly.py`
  - `tests/test_document_source_connectors.py`
  - `tests/mcp/test_no_write_tool_contracts.py`
  - `tests/memory_os/test_document_pipeline.py`
  - document daemon/client route tests
- `python server.py --agent-eval` passes and includes the Book Dismantling Gate.
- Poppler is installed on this machine through WinGet and the optional local PDF smoke lane can use `ENGRAM_DOCUMENT_FIXTURE_DIR` when needed.

## Product Definition

Document ingestion/intelligence is complete when these workflows work through the daemon-backed MCP path:

1. Discover document extractors and source connector support.
2. Preview a local source without writing durable memory.
3. Disassemble PDF/text/markdown documents into page, text, image, table, figure, quality, and artifact-manifest evidence.
4. Prepare extraction requests for missing OCR, table, and visual interpretation coverage.
5. Accept agent-supplied extraction results and normalize them into evidence records.
6. Preview a complete extraction packet with coverage receipts and failure metadata.
7. Prepare an understanding packet from agent synthesis with cited evidence and graph coverage proposals.
8. Prepare draft memory records and graph proposals without promoting them.
9. Prepare a promotion transaction that is explicit, reviewable, and rejected by default when required coverage is missing.
10. Store ledgered document evidence artifacts explicitly, separate from active memory promotion.
11. Query document orientation, review preparation, evidence audit, and bounded graph evidence through EKC from stored document evidence.
12. Surface the workflow clearly in `memory_protocol()`, README/docs, release gates, and tests.

## Non-Negotiable Boundaries

- No implicit memory promotion from any `prepare_*` or `preview_*` document tool.
- No daemon-client imports of document extractor modules or storage backends.
- No committing copyrighted PDFs, extracted book text, page images, OCR output, or table exports.
- No claims of reviewed-only context unless review state is actually enforced.
- No `no_answer` status for infrastructure failure; document pipeline failures must carry structured error categories.
- No artifact writes outside the configured Engram data root.
- No graph edge promotion without explicit reviewed transaction execution.

## Phase 0 - Lock The Current Contract

**Intent:** Add failing tests that prove the actual gap: direct mode advertises the document workflow, while daemon mode exposes only one tool.

**Files:**
- `tests/test_server_daemon_client.py`
- `tests/test_agent_protocol_tools.py`
- `tests/mcp/test_no_write_tool_contracts.py`
- `server_daemon_client.py`

**Steps:**

1. Add a daemon-client protocol test asserting the stable document workflow is advertised by `memory_protocol()`:

```python
def test_daemon_protocol_advertises_document_workflow():
    protocol = memory_protocol()
    tools = protocol["tools"]

    expected = {
        "list_document_extractors",
        "preview_document_source_connector",
        "prepare_document_disassembly",
        "prepare_document_extraction_request",
        "prepare_document_extraction_result",
        "preview_document_extraction",
        "prepare_visual_extraction_request",
        "preview_visual_extraction",
        "prepare_document_understanding_packet",
        "prepare_document_draft",
        "prepare_document_promotion_transaction",
    }

    assert expected <= set(tools)
```

2. Add MCP no-write contract checks for each stable document tool:

```python
NO_WRITE_DOCUMENT_TOOLS = {
    "list_document_extractors",
    "preview_document_source_connector",
    "prepare_document_disassembly",
    "prepare_document_extraction_request",
    "prepare_document_extraction_result",
    "preview_document_extraction",
    "prepare_visual_extraction_request",
    "preview_visual_extraction",
    "prepare_document_understanding_packet",
    "prepare_document_draft",
    "prepare_document_promotion_transaction",
}

def test_document_tools_remain_no_write_surfaces():
    for name in NO_WRITE_DOCUMENT_TOOLS:
        doc = TOOL_DOCSTRINGS[name].lower()
        assert "no-write" in doc or "does not write" in doc
        assert "promote" in doc
```

3. Add route/client tests that fail until every stable document tool has an `engramd` endpoint and a daemon-client wrapper.

**Validation:**

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_server_daemon_client.py tests\test_agent_protocol_tools.py tests\mcp\test_no_write_tool_contracts.py -q
```

Expected state before implementation: targeted failures proving missing daemon-client document tool coverage.

## Phase 1 - Expose The Full No-Write Workflow Through The Daemon

**Intent:** Make the existing direct-server document workflow reachable from `server_daemon_client.py` without duplicating extractor logic in the client.

**Files:**
- `core/engramd_api.py`
- `core/engramd_client.py`
- `server_daemon_client.py`
- `server.py`
- `tests/test_engramd_api.py`
- `tests/test_engramd_client.py`
- `tests/test_server_daemon_client.py`

**Steps:**

1. Add daemon API handlers for each stable document helper. The handlers should call the existing core helper functions on the daemon side and return the same envelope shape direct mode returns.

```python
@app.post("/document/list_extractors")
def api_list_document_extractors() -> dict[str, Any]:
    return list_document_extractors()

@app.post("/document/preview_source")
def api_preview_document_source_connector(payload: dict[str, Any]) -> dict[str, Any]:
    return preview_document_source_connector(**payload)

@app.post("/document/prepare_extraction_request")
def api_prepare_document_extraction_request(payload: dict[str, Any]) -> dict[str, Any]:
    return prepare_document_extraction_request(**payload)
```

2. Keep existing structured exception translation. Missing file paths, malformed packets, unsupported extractors, and validation errors should return `invalid_request` or `schema_failed`, not transport exceptions.

```python
return {
    "result": None,
    "error": {
        "code": "invalid_request",
        "message": str(exc),
        "category": "validation",
    },
}
```

3. Add thin client methods that only POST JSON payloads:

```python
def preview_document_extraction(self, **payload: Any) -> dict[str, Any]:
    return self._post_json("/document/preview_extraction", payload)
```

4. Add FastMCP tools in `server_daemon_client.py` with docstrings that match direct mode's no-write contract.

5. Update daemon-client `memory_protocol()` so agents see the same stable document ladder:

```python
"document_workflow": [
    "list_document_extractors",
    "preview_document_source_connector",
    "prepare_document_disassembly",
    "prepare_document_extraction_request",
    "prepare_document_extraction_result",
    "preview_document_extraction",
    "prepare_visual_extraction_request",
    "preview_visual_extraction",
    "prepare_document_understanding_packet",
    "prepare_document_draft",
    "prepare_document_promotion_transaction",
]
```

**Validation:**

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_engramd_api.py tests\test_engramd_client.py tests\test_server_daemon_client.py tests\test_agent_protocol_tools.py -q
```

## Phase 2 - Create A Single End-To-End Review Workflow

**Intent:** Provide an operator-grade happy path that stitches the no-write tools together without requiring the user to memorize tool order.

**Files:**
- `core/document_intake_workflow.py`
- `server.py`
- `server_daemon_client.py`
- `core/engramd_api.py`
- `core/engramd_client.py`
- `tests/test_document_intake_workflow.py`
- `tests/test_server_daemon_client.py`

**New helper:**

```python
def prepare_document_intake_review(
    source_path: str,
    extractor_id: str | None = None,
    max_pages: int | None = None,
    require_visual_coverage: bool = True,
    require_table_coverage: bool = True,
    require_ocr_coverage: bool = True,
) -> dict[str, Any]:
    ...
```

**Required envelope:**

```json
{
  "status": "ok|partial|no_answer|schema_failed|unavailable",
  "source": {"source_path": "...", "document_id": "...", "sha256": "..."},
  "disassembly": {},
  "extraction_request": {},
  "quality": {},
  "artifact_manifest": {},
  "draft_candidates": [],
  "promotion_guidance": {},
  "policy": {
    "write_behavior": "read_only",
    "active_memory_promoted": false,
    "graph_edges_promoted": false
  },
  "receipts": {}
}
```

**Steps:**

1. Implement the workflow as composition over existing helpers.
2. Do not bypass existing helper validation.
3. Return `partial` when a document can be disassembled but required visual/OCR/table coverage is missing.
4. Return `unavailable` with `error.category = "infrastructure"` when Poppler or a required local tool is missing.
5. Expose the workflow through direct server, daemon API/client, and thin daemon MCP.
6. Add tests for:
   - clean text PDF review packet
   - image-only PDF requiring OCR/visual coverage
   - table-heavy page requiring table extraction
   - missing Poppler mapped to infrastructure failure
   - missing source mapped to invalid request

**Validation:**

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_document_intake_workflow.py tests\test_document_disassembly.py -q
```

## Phase 3 - Materialize Document Evidence Artifacts Explicitly

**Intent:** Move from preview-only document intelligence to explicit, ledgered document evidence artifacts that EKC can read without pretending drafts are active memories.

**Files:**
- `core/memory_os/document_artifacts.py`
- `core/memory_os/document_pipeline.py`
- `core/memory_os/transactions.py`
- `core/memory_os/ledger.py`
- `core/engramd_api.py`
- `core/engramd_client.py`
- `server.py`
- `server_daemon_client.py`
- `tests/memory_os/test_document_pipeline.py`
- `tests/test_document_artifact_materialization.py`

**New tool split:**

```python
def prepare_document_artifact_store(
    review_packet: dict[str, Any],
    artifact_family: str = "document_evidence",
) -> dict[str, Any]:
    """Prepare an explicit write transaction for document evidence artifacts."""

def store_document_artifact(
    prepared_transaction_id: str,
    accept: bool = False,
) -> dict[str, Any]:
    """Store ledgered document evidence only when accept=True."""
```

**Storage contract:**

- Source bytes are addressed by hash and stored under the data root.
- Extracted text, page inventory, image inventory, OCR coverage receipts, table candidates, figure candidates, and quality reports are stored as artifact records.
- Artifact records include:
  - `artifact_id`
  - `document_id`
  - `source_sha256`
  - `artifact_type`
  - `content_ref`
  - `page_refs`
  - `coverage_receipt`
  - `created_by_tool`
  - `created_at`
  - `review_state`
- Active memory records remain untouched.
- Graph proposals remain proposals until a separate reviewed graph transaction executes.

**Steps:**

1. Extend existing document artifact manifests rather than creating a parallel manifest schema.
2. Add ledger writes through Memory OS transaction helpers.
3. Fail closed when the artifact content path would escape the data root.
4. Report `artifacts_built=1` for prepared ephemeral review packets and `artifacts_read=0`.
5. Report `artifacts_read=1` only when a persisted, ledgered document artifact is read back.
6. Add tests proving active memories and graph stores are unchanged after artifact storage.

**Validation:**

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_document_pipeline.py tests\test_document_artifact_materialization.py -q
```

## Phase 4 - Add Resumable Large-Document Jobs

**Intent:** Make book-scale ingestion reliable by using jobs, checkpoints, and page ranges instead of one giant in-memory operation.

**Files:**
- `core/memory_os/jobs.py`
- `core/document_extractors.py`
- `core/document_artifacts.py`
- `core/document_intake_workflow.py`
- `core/engramd_api.py`
- `tests/test_document_disassembly.py`
- `tests/test_document_intake_jobs.py`

**New behavior:**

```python
def prepare_document_disassembly(
    source_path: str,
    extractor_id: str | None = None,
    page_range: str | None = None,
    resume_token: str | None = None,
    max_pages: int | None = None,
) -> dict[str, Any]:
    ...
```

**Steps:**

1. Add page-range support to local PDF disassembly.
2. Emit resume tokens for large or interrupted jobs.
3. Store job receipts in the daemon-owned job store.
4. Preserve no-write semantics for active memory.
5. Return deterministic `partial` packets when a range succeeds and additional ranges remain.
6. Add tests for resume token validation, stale source hash rejection, and page-range artifact manifest merging.

**Validation:**

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_document_intake_jobs.py tests\test_document_disassembly.py -q
```

## Phase 5 - Close The Visual, OCR, And Table Coverage Loop

**Intent:** Let agents supply missing visual/OCR/table interpretations and have Engram validate coverage instead of inventing document understanding itself.

**Files:**
- `core/document_intelligence.py`
- `core/document_quality.py`
- `server.py`
- `server_daemon_client.py`
- `core/engramd_api.py`
- `core/engramd_client.py`
- `tests/test_document_intelligence.py`
- `tests/test_document_visual_extraction.py`

**Coverage behavior:**

- `prepare_visual_extraction_request()` identifies every required image/page/table/figure reference.
- `preview_visual_extraction()` validates agent-supplied observations against requested refs.
- Missing required refs produce `partial` with coverage warnings.
- Supplied observations preserve:
  - page number
  - artifact id
  - image ref
  - coordinates or bounding boxes when available
  - confidence
  - extractor id
  - citation refs

**Steps:**

1. Make visual/OCR/table request and preview tools available in daemon mode.
2. Add strict coverage validation keyed by evidence refs.
3. Add fixture cases for image-only PDF, figure-caption page, table-heavy page, rotated page, and OCR-noise page.
4. Ensure quality reports distinguish:
   - missing OCR
   - low-confidence OCR
   - unresolved image evidence
   - unresolved table evidence
   - malformed supplied extraction result

**Validation:**

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_document_intelligence.py tests\test_document_visual_extraction.py -q
```

## Phase 6 - Wire Document Evidence Into EKC

**Intent:** Make `query_knowledge` use ledgered document evidence for orientation, review preparation, evidence audit, and bounded graph evidence.

**Files:**
- `core/memory_os/knowledge_orientations.py`
- `core/memory_os/knowledge_review.py`
- `core/memory_os/knowledge_audit.py`
- `core/memory_os/knowledge_graph.py`
- `core/memory_os/knowledge_planner.py`
- `core/memory_os/knowledge_response.py`
- `tests/memory_os/test_knowledge_document_orientation.py`
- `tests/memory_os/test_knowledge_evidence_audit.py`

**Required EKC behavior:**

- Document orientation reads ledgered document artifacts when present.
- Review preparation reads document drafts and quality warnings without promoting them.
- Evidence audit reports citation coverage, missing visual/OCR/table refs, stale source hashes, and unsupported inferences.
- Bounded graph evidence surfaces proposals, evidence, and contradictions without loading neighbor memory bodies.
- Planner receipts distinguish:
  - `artifacts_built`
  - `artifacts_read`
  - `documents_consulted`
  - `coverage_missing`
  - `policy_metadata.reviewed_source_state`

**Steps:**

1. Add document artifact readers to the EKC planner context.
2. Add document citation refs to `core/memory_os/knowledge_citations.py`.
3. Enforce the v0/v1 read-only policy envelope for all document-backed EKC responses.
4. Add golden fixtures for:
   - complete document orientation
   - partial orientation with missing OCR coverage
   - evidence audit with unsupported inference
   - review preparation with draft warnings
   - unavailable artifact store
5. Assert every success and failure response validates with `validate_knowledge_response`.

**Validation:**

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_knowledge_document_orientation.py tests\memory_os\test_knowledge_evidence_audit.py tests\memory_os\test_knowledge_response_validation.py -q
```

## Phase 7 - Add Operator UX And Docs

**Intent:** Make the feature usable without source diving.

**Files:**
- `docs/DOCUMENT_INGESTION_WORKFLOW.md`
- `docs/RELEASE_GATES.md`
- `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`
- `README.md`
- `AGENTS.md`
- `server.py`
- `server_daemon_client.py`
- `tests/test_agent_protocol_tools.py`

**Docs must include:**

- Recommended daemon-backed workflow.
- Tool order for:
  - quick document orientation
  - full review packet
  - OCR/visual/table coverage loop
  - artifact storage
  - reviewed memory promotion
  - EKC document orientation
- Explicit no-write and promotion boundaries.
- Local Poppler setup and doctor checks.
- Optional local book smoke instructions using `ENGRAM_DOCUMENT_FIXTURE_DIR`.
- Copyright safety warning for local book tests.

**Validation:**

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_agent_protocol_tools.py tests\mcp\test_no_write_tool_contracts.py -q
rg -n "document ingestion|prepare_document_intake_review|store_document_artifact|ENGRAM_DOCUMENT_FIXTURE_DIR" README.md AGENTS.md docs
```

## Phase 8 - Release Gates And End-To-End Proof

**Intent:** Prove the complete feature in the same lanes agents and operators will use.

**Required gates:**

```powershell
.\venv\Scripts\python.exe server.py --help
.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe engramd.py --smoke-test
$env:ENGRAM_DATA_DIR = Join-Path $env:TEMP ("engram-doc-intel-" + [guid]::NewGuid().ToString("N"))
.\venv\Scripts\python.exe server.py --self-test
.\venv\Scripts\python.exe server.py --agent-eval
.\venv\Scripts\python.exe -m pytest tests\test_document_intelligence.py tests\test_document_disassembly.py tests\test_document_source_connectors.py tests\test_document_intake_workflow.py tests\test_document_visual_extraction.py tests\test_document_artifact_materialization.py tests\memory_os\test_document_pipeline.py tests\memory_os\test_knowledge_document_orientation.py tests\memory_os\test_knowledge_evidence_audit.py tests\mcp\test_no_write_tool_contracts.py -q
```

**Optional local book smoke:**

```powershell
$env:ENGRAM_DOCUMENT_FIXTURE_DIR = "C:\Users\colek\Downloads\Design Books"
.\venv\Scripts\python.exe -m pytest tests\test_document_disassembly.py -m local_pdf -q
Remove-Item Env:\ENGRAM_DOCUMENT_FIXTURE_DIR
```

**Completion evidence:**

- MCP daemon client lists the stable document workflow.
- Missing source and missing infrastructure return structured errors.
- Text PDF, image-only PDF, table-heavy page, and figure-caption page fixtures produce correct coverage receipts.
- A review packet stores ledgered document evidence only after explicit artifact-store acceptance.
- Active memory and graph stores remain unchanged unless a reviewed promotion transaction is explicitly executed.
- EKC document orientation cites document artifacts and reports missing coverage honestly.
- `python server.py --agent-eval` keeps the Book Dismantling Gate green.

## Recommended Commit Slices

1. `test: lock daemon document intelligence contract`
2. `feat: route document intelligence tools through daemon`
3. `feat: add document intake review workflow`
4. `feat: materialize reviewed document evidence artifacts`
5. `feat: add resumable document intake jobs`
6. `feat: validate visual ocr and table coverage`
7. `feat: wire document evidence into ekc`
8. `docs: document ingestion intelligence workflow`
9. `test: complete document ingestion release gates`

Each slice should run its targeted tests, commit, and write a concise Engram progress memory with branch, commit, validation, and next step.
