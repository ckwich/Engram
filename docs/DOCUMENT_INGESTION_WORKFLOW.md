# Document Ingestion And Intelligence Workflow

Engram document intelligence is review-first. The daemon-backed MCP path can
inspect a document, prepare OCR/visual/table follow-up, store explicit ledgered
document evidence, and serve that evidence through EKC without promoting active
memory or graph edges.

## Recommended Daemon Path

Start the daemon, then use `server_daemon_client.py` or `server.py` with
`ENGRAM_DAEMON_URL`:

```powershell
.\venv\Scripts\python.exe engramd.py --host 127.0.0.1 --port 8765
$env:ENGRAM_DAEMON_URL = "http://127.0.0.1:8765"
.\venv\Scripts\python.exe server.py --help
```

Use `daemon_status()` before blaming retrieval or document tools. The thin
daemon client never imports document extractors, Chroma, LanceDB, Kuzu, or
local storage modules.

## Quick Document Orientation

```text
list_document_extractors
prepare_document_intake_review(source_path="C:/docs/book.pdf", max_pages=10)
query_knowledge({ask: {task_type: "document_orientation", project: "Engram", focus: [...]}})
```

`prepare_document_intake_review` returns a read-only packet with disassembly,
text preview, quality warnings, artifact manifest, coverage receipts, and the
next extraction request when OCR, visual, or table coverage is missing.

## Full Review Packet

```text
preview_document_source_connector
prepare_document_disassembly
prepare_document_intake_review
prepare_document_understanding_packet
prepare_document_draft
prepare_document_promotion_transaction
```

The review packet is evidence, not trusted memory. Drafts and graph proposals
remain proposals until a separate reviewed promotion path executes.

## Large Documents

Use bounded page ranges for book-scale work:

```text
prepare_document_disassembly(source_path="C:/docs/book.pdf", page_range="1-25")
prepare_document_disassembly(source_path="C:/docs/book.pdf", resume_token=packet.resume.resume_token)
```

Resume tokens carry the source hash. Engram rejects stale resume tokens when the
source file changes. Artifact manifests include page-range merge metadata so
ranged passes can be stitched into one evidence set.

## OCR, Visual, And Table Coverage

When a packet returns `extraction_request`, use an agent-native or external OCR
or vision tool, then return observations through:

```text
preview_visual_extraction(document_record=doc, visual_request=request, observations=[...])
```

Incomplete coverage returns `status: "partial"` with warnings such as
`unresolved_visual_evidence`, `missing_ocr_coverage`,
`missing_table_coverage`, or `low_confidence_ocr`. Engram does not invent image
or table interpretation itself.

## Artifact Storage

Ledgered document evidence is explicit:

```text
prepare_document_artifact_store(review_packet=packet)
store_document_artifact(prepared_transaction_id=txn, accept=True)
```

`store_document_artifact` writes document evidence artifacts, document/chunk
records, and coverage receipts. It does not promote active memories and does
not promote graph edges. Use `prepare_document_promotion_transaction` for
reviewed memory/graph promotion decisions.

## EKC Use

After artifact storage, use:

```text
query_knowledge(task_type="document_orientation")
query_knowledge(task_type="review_preparation")
query_knowledge(task_type="evidence_audit")
query_knowledge(task_type="graph_evidence")
```

EKC document responses cite document/artifact/graph evidence and report missing
coverage honestly. Infrastructure failures use `status: "unavailable"`, not
`no_answer`.

## Local Tooling

PDF disassembly uses Poppler-compatible local tools: `pdfinfo`, `pdftotext`,
and `pdfimages`. Run:

```powershell
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe -m pytest tests\test_document_disassembly.py -q
```

Optional local book smoke tests can use personal PDFs:

```powershell
$env:ENGRAM_DOCUMENT_FIXTURE_DIR = "C:\Users\colek\Downloads\Design Books"
.\venv\Scripts\python.exe -m pytest tests\test_document_disassembly.py -m local_pdf -q
Remove-Item Env:\ENGRAM_DOCUMENT_FIXTURE_DIR
```

Do not commit copyrighted PDFs, extracted book text, rendered page images, OCR
output, or table exports.
