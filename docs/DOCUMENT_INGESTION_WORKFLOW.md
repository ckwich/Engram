# Document Ingestion And Intelligence Workflow

Engram document intelligence is review-first. The daemon-backed MCP path can
inspect a document, prepare OCR/visual/table follow-up, store explicit ledgered
document evidence, and serve that evidence through EKC without promoting active
memory or graph edges.

Artifact storage and usable-document completion are separate gates. A staged
artifact can be audited, cited, and resumed, but EKC document orientation stays
partial until `prepare_document_ingestion_completion` proves complete coverage
and `complete_document_ingestion` accepts the reviewed graph-backed result.

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
query_knowledge({"ask": {"task_type": "document_orientation", "project": "Engram", "focus": [...]}})
```

`prepare_document_intake_review` returns a read-only packet with disassembly,
text preview, quality warnings, artifact manifest, coverage receipts, and the
next extraction request when OCR, visual, or table coverage is missing. It also
returns `review_completeness`, a compact reviewer-facing summary of the current
page window, missing coverage obligations, and whether the packet is complete
enough to accept as a reviewed artifact.

## Document Intelligence Ingestion

Use Document Intelligence Ingestion to turn a local document into searchable,
graph-covered Engram evidence through one resumable workflow. It orchestrates
the existing review-first document surfaces without changing the completion
rules: searchability can arrive before OCR, visual, table, semantic graph, and
usable completion gates are fully covered.

```text
prepare_document_ingestion_plan(source_path="C:/docs/book.pdf", ...)
run_document_ingestion(ingestion_id=plan.ingestion_id, accept=True, approved_by="agent-review")
prepare_document_coverage_pass(ingestion_record=record, review_packets=[...])
prepare_knowledge_pr(branch_id=branch.branch_id, proposed_operations=[...])
run_memory_ci(knowledge_pr_id=pr.knowledge_pr_id)
inspect_document_ingestion(ingestion_id=plan.ingestion_id)
resume_document_ingestion(ingestion_id=plan.ingestion_id, accept=True, approved_by="agent-review")
prepare_document_ingestion_completion(document_id=doc, ...)
complete_document_ingestion(document_id=doc, accept=True, approved_by="agent-review", ...)
query_knowledge({"ask": {"task_type": "document_orientation", "project": "Engram", "focus": [...]}})
```

Treat `status: "partial"` as resumable incomplete state, not final accepted
success. A partial document may already have indexed chunks and searchable
evidence, but it is not fully accepted as usable until the OCR, visual, table,
semantic graph, and completion gates report covered status. Use
`inspect_document_ingestion` to see the remaining retry surfaces, including
page windows, extraction requests, artifact storage, graph proposal review, and
usable-document completion.

The standard book-ingestion flow is:

1. Prepare the ingestion plan.
2. Run or resume ingestion until text/source evidence is staged.
3. Run the automatic coverage pass so OCR, table, and image evidence is prepared
   or blocked with explicit adapter receipts.
4. Prepare a Knowledge PR for proposed memory, graph, or completion operations.
5. Run Memory CI on that Knowledge PR and resolve blocked gates before merge.
6. Prepare document completion only after coverage, understanding, citations, and
   reviewed graph evidence are present.
7. Complete document ingestion with `accept=True` and `approved_by`.
8. Inspect, search, and query document orientation to verify the usable state.

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
store_document_artifact(prepared_transaction_id=txn, accept=True, review_packet=packet)
prepare_document_ingestion_completion(document_id=doc, artifact_id=artifact, ...)
complete_document_ingestion(document_id=doc, accept=True, approved_by="agent-review", ...)
```

`prepare_document_artifact_store` persists only a compact review intent,
review digest, and reviewer-facing summary. It does not store extracted text or
the full review packet before acceptance. `store_document_artifact` requires the
matching reviewed packet again, verifies the packet digest and source bytes when
the source file is available, then writes document evidence artifacts,
document/chunk records, and coverage receipts. It does not promote active
memories and does not promote graph edges. Use
`prepare_document_promotion_transaction` for reviewed memory/graph promotion
decisions.

After artifact storage, use `prepare_visual_extraction_request` and
`preview_visual_extraction` until all visual/OCR/table obligations are covered,
then pass the visual preview, `prepare_document_understanding_packet` result,
and `prepare_document_promotion_transaction` result to
`prepare_document_ingestion_completion`. Only
`complete_document_ingestion(..., accept=True, approved_by=...)` marks the
document usable; it refreshes the coverage map with visual and understanding
evidence, applies selected graph evidence, and writes a compact
`document_completion` artifact.

Document-intelligence ids are deterministic and readable for operators and
developers. Use document/source labels such as `doc_design_book` or
`doc_req_design_book_pdf_local_pdf_extractor_<digest>`; reserve short digest
suffixes for collision guards only, not as the whole id.

## Book Catalog Facets

Book-oriented document records carry deterministic `document_catalog` metadata
when materialized. The catalog records subject, collection, reading role, corpus
tags, and core-corpus exclusions. Retrieval chunk metadata mirrors those facets,
so agents can use tag filters such as `core-game-design` for game-design-only
reading and avoid adjacent UX/behavioral-design books unless those are requested
explicitly.

## EKC Use

After artifact storage, use:

```text
query_knowledge({"ask": {"task_type": "document_orientation", "document_id": doc}})
query_knowledge({"ask": {"task_type": "review_preparation", "document_id": doc}})
query_knowledge({"ask": {"task_type": "evidence_audit", "document_id": doc}})
query_knowledge({"ask": {"task_type": "graph_evidence", "document_id": doc}})
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

Optional local PDF smoke tests can use a private fixture directory:

```powershell
$env:ENGRAM_DOCUMENT_FIXTURE_DIR = "C:\Path\To\Private\PdfCorpus"
.\venv\Scripts\python.exe -m pytest tests\test_document_disassembly.py -m local_pdf -q
Remove-Item Env:\ENGRAM_DOCUMENT_FIXTURE_DIR
```

For an ad hoc PDF smoke that prints only metadata, receipts, ids, and coverage
state, use the reusable JSON runner:

```powershell
powershell -NoProfile -Command ".\venv\Scripts\python.exe scripts\document_pdf_smoke.py C:\docs\book.pdf --max-pages 25"
powershell -NoProfile -Command ".\venv\Scripts\python.exe scripts\document_pdf_smoke.py C:\docs\book.pdf --full --store-artifact --accept --timeout 600"
```

The smoke runner suppresses common local progress chatter and never prints
extracted page or chunk text. The daemon still receives the full reviewed packet
when `--store-artifact --accept` is used.

Do not commit copyrighted PDFs, extracted book text, rendered page images, OCR
output, or table exports.
