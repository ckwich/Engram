# Engram 1.0 Memory OS and Document Disassembly Design

Status: Binding 1.0 rebuild design
Date: 2026-05-12
Scope: Public, generic, local-first, agent-facing memory OS

## Purpose

Engram 1.0 should be a powerful and easy-to-use persistent memory OS for
agents. The product should not merely save text snippets. It should let an
agent safely dismantle source material, understand evidence, promote durable
memory deliberately, and retrieve cited context with graph relationships.

The immediate forcing function is rich book-scale document intelligence. Engram
must be able to process documents like 250-page design books and larger 79 MB
image-heavy books without flattening away pages, figures, tables, captions,
OCR evidence, or provenance. The output must be reviewable evidence first, then
explicit memory and graph promotion.

## Consolidated 1.0 Tracks

The live 1.0 path combines the previous seven finish-line tracks with the six
new rebuild/document tracks, plus addendums from the book-dismantling review.

1. Daemon ownership: `engramd` owns mutable stores, jobs, drafts, imports,
   indexes, graph storage, repair jobs, and rebuild jobs.
2. Memory OS migration guarantees: legacy JSON memories, source drafts, graph
   edges, document evidence, chunks, and receipts import and round-trip without
   loss.
3. Codebase mapping modernization: mapping jobs are data-root aware, daemon
   owned, current with Memory OS modules, and useful as agent self-knowledge.
4. Document disassembly pipeline: local PDF/DOCX/text/HTML intake produces a
   page inventory, extracted text, layout cues, image refs, table refs, figure
   refs, section records, and chunk candidates.
5. Visual/OCR evidence pipeline: image-only pages, figures, diagrams, tables,
   screenshots, and low-text pages produce reviewable visual artifacts with
   page, coordinate, extractor, and confidence provenance.
6. Section and chunk provenance: every chunk links back to source hash,
   document id, page id, section id, text span, bounding box when available,
   extractor receipt, and related artifact ids.
7. Document understanding layer: agents receive analysis packets for summaries,
   concepts, claims, entities, examples, constraints, risks, contradictions,
   and high-value sections before promotion.
8. Graph edge extraction: document drafts propose typed edges such as
   `defines`, `explains`, `supports`, `contradicts`, `example_of`,
   `depends_on`, `cites`, `contains`, `illustrates`, and `supersedes`.
9. Review-first promotion transactions: document evidence becomes drafts and
   explicit memory/graph operations; no import auto-promotes active memory.
10. Retrieval backend decision gate: Chroma remains live until LanceDB or
    another backend proves real-corpus persistence, filtering, rebuild, hybrid
    lookup, and Windows reliability.
11. Graph backend decision gate: JSON graph storage remains live until Kuzu or
    another graph backend proves import parity, traversal behavior, persistence,
    and Windows reliability.
12. Agent reliability evaluations: golden evals cover codebase mapping, source
    intake, document disassembly, visual evidence, graph-aware retrieval, stale
    exclusion, and hybrid identifier lookup.
13. WebUI operator surface: the dashboard reviews health, imports, drafts,
    graph proposals, migration receipts, and evals without becoming the
    collaboration product.
14. Large corpus performance budget: 79 MB documents are processed with
    streaming, resumable jobs, bounded memory, cached page artifacts, retries,
    cancellation, and recovery receipts.
15. Citations and receipts everywhere: every retrieval result and promoted
    claim remains traceable to source, page, artifact, chunk, extractor, and
    graph evidence.
16. Document quality audit: imports report text coverage, failed pages,
    suspicious empty pages, OCR-needed pages, table/figure candidates,
    duplicate chunks, missing captions, and low-confidence regions.
17. Agent ergonomics polish: add agent-native helpers such as "what should I
    read first?", "explain this source", "show document graph", "why believe
    this?", and "promote the best reviewed chunks".
18. Release freeze: MCP docstrings, README, AGENTS.md, install path, daemon
    smoke, self-test, agent-eval, document smoke, and fresh-session MCP proof
    all pass before 1.0.

## Document Disassembly Model

The document pipeline is:

```text
source connector
-> source artifact
-> document inventory
-> page records
-> text extraction
-> layout and section detection
-> visual artifact detection
-> targeted OCR/vision
-> table and figure normalization
-> semantic chunking
-> document understanding packet
-> reviewable draft
-> explicit promotion transaction
```

Engram should keep the intermediate products. A large document import is not a
single memory. It is a source with many evidence records that can produce many
candidate memories and graph edges.

Required evidence records:

- `source`: raw file path/URI, source hash, observed timestamp, size, media
  type, connector id, and privacy classification.
- `document`: normalized title, source hash, page count, extraction status,
  content hash, extractor receipts, and quality summary.
- `page`: page number, dimensions, rotation, text coverage, image count,
  table/figure candidates, rendered page artifact id, and warnings.
- `section`: heading path, page span, text span, parent section id, and source
  locator.
- `chunk`: semantic text unit with source/page/section/span provenance and
  token/character estimates.
- `visual_artifact`: figure, diagram, screenshot, table image, page crop, OCR
  block, caption, or chart with page/coordinates/confidence.
- `table_artifact`: extracted table structure with page/coordinates, cells,
  caption, and parser confidence.
- `extraction_receipt`: parser version, command/provider, parameters, duration,
  warnings, and output hashes.
- `quality_report`: coverage and warning summary for agent judgment.

## Book Dismantling Gate

Engram 1.0 cannot claim rich document intelligence until the Book Dismantling
Gate passes. The gate uses at least:

- a clean text PDF fixture
- a 250-page book-style PDF fixture
- a large image-heavy PDF fixture near the 79 MB class
- an image-only scanned PDF fixture
- a multi-column page fixture
- a table-heavy fixture with merged/irregular cells
- a figure/caption fixture
- a rotated-page fixture
- an OCR-noise fixture
- a mixed text/image page fixture

The gate passes when Engram can:

- inventory all pages without loading the full document into memory at once
- extract available text and identify low/no-text pages
- detect image, table, figure, and caption candidates
- create visual/OCR work requests only for pages or regions that need them
- preserve page and coordinate provenance for extracted artifacts
- produce chunk manifests with source/page/section refs
- produce a quality report with failed pages and low-confidence regions
- propose memories and graph edges without auto-promoting them
- resume after interruption without duplicating artifacts
- retrieve chunks with citations back to page and artifact ids

Manual release verification may use local PDFs from
`C:\Users\colek\Downloads\Design Books`, including large image-heavy books.
Those files are test corpus inputs only. Do not commit copyrighted PDFs,
extracted book text, rendered page images, OCR output, or table exports. Commit
only deterministic fixtures, fixture manifests, hashes, counts, receipts,
quality summaries, and redacted snippets.

## Codebase Mapping 1.0 Requirements

Codebase mapping remains part of Engram, but it must align with the Memory OS
runtime:

- mapping configs must include daemon, migration, document intelligence,
  backend-status, graph, source, WebUI, and reliability domains
- large central files such as `server.py` and `memory_manager.py` must not be
  silently excluded by a too-low `max_file_size_kb`
- mapping jobs must honor `ENGRAM_DATA_DIR`
- mapping jobs must honor `ENGRAM_DATA_DIR` before 1.0; daemon-routed
  mapping jobs require a future durable job store and are post-1.0
- stored architecture memories must be produced by the connected agent, not a
  provider-specific subprocess
- source drift must block stale stores unless the agent explicitly forces after
  review

## Steelman Review

The strongest argument against this plan is that it risks turning 1.0 into a
large document-processing platform instead of shipping a memory system. A full
general-purpose PDF/DOCX/OCR/table extractor can swallow the project.

The answer is to keep Engram's core responsibility clear:

- Engram owns evidence records, provenance, chunking, quality reports, draft
  proposals, graph proposals, retrieval, and promotion transactions.
- Extractors are adapters. They may be local tools, Python libraries, OCR
  engines, agent-native vision, or external frameworks.
- 1.0 must include a working local PDF text/page/image inventory adapter because
  book-scale documents are central to the product promise.
- 1.0 does not need perfect universal table reconstruction or perfect image
  understanding. It needs truthful evidence, confidence, review gates, and the
  ability to ask for targeted visual work when extraction is incomplete.

The second strongest argument is that daemon, migration, backend, codebase
mapping, WebUI, and document intelligence are too many tracks. The mitigation
is sequencing:

1. Make the plan and acceptance gates explicit.
2. Modernize codebase mapping so agents understand the rebuilt repo.
3. Build local PDF disassembly as a no-write evidence pipeline.
4. Add quality reports and review packets.
5. Add promotion transactions and evals.
6. Only then revisit backend switching and WebUI polish.

The third strongest argument is that storing a full book's every page, image,
table, and chunk could bloat local storage. The mitigation is
content-addressed artifacts, deduplication, page-level manifests, and explicit
retention policies. Engram should store source artifacts and derived evidence
once, then rebuild indexes from receipts.

## Addendums After Steelman

The following fixes are binding:

- Add a "lite extraction" mode for text/page inventory only.
- Add a "full dismantle" mode for page images, visual artifacts, OCR requests,
  tables, figures, graph proposals, and quality audit.
- Add a per-import budget that limits rendered page DPI, max pages processed,
  max image artifacts, and OCR queue size while still recording skipped work.
- Add import manifests so interrupted jobs resume from the last completed page.
- Keep copyrighted source text out of public docs and support bundles by
  default; support bundles include hashes, counts, receipts, and redacted
  snippets unless explicitly exported by the user.
- Treat table extraction as structured evidence with confidence, not as trusted
  facts until reviewed.
- Require every promoted claim from a visual artifact to retain the artifact id
  and page coordinate provenance.

## Non-Goals For Engram 1.0

- Team workspaces, comments, assignments, mentions, and rich collaborative
  pages remain outside this repo.
- Hosted tenant isolation is not part of local 1.0, though hosted requirements
  remain documented for later.
- Perfect OCR or perfect PDF layout reconstruction is not required. Honest
  quality reporting and reviewable evidence are required.
- Engram should not add a provider-specific model subprocess for document
  understanding. The connected agent performs synthesis.

## 1.0 Readiness Definition

Engram 1.0 is ready when a fresh agent can:

- discover the protocol with `memory_protocol`
- use direct MCP mode or opt-in daemon mode without corrupting Chroma or draft
  stores
- import or round-trip the current JSON memory corpus without loss
- map the Engram codebase with current Memory OS domains
- dismantle a book-style PDF into evidence records, chunks, quality reports,
  and draft memory/graph proposals
- retrieve cited chunks with source/page/artifact provenance
- inspect graph evidence without surprise memory body loads
- run release gates from README/AGENTS without hidden setup
