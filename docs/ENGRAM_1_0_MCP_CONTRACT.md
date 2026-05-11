# Engram 1.0 MCP Contract

Date: 2026-05-06
Status: Track 1 contract inventory
Source of truth: `server.py` MCP tool definitions plus `memory_protocol()`

## Product and Protocol Identity

Product release identity and MCP protocol identity are separate contracts.

| Field | Value | Contract |
|---|---|---|
| Product name | `Engram` | Public product identity. |
| Product version | `1.0.0-dev` | Development identity for the 1.0 release track. |
| Product release track | `1.0` | Public release readiness track. |
| Product stability | `development` | Not a final release tag. |
| Protocol version | `2` | Agent-facing MCP protocol payload version. |
| Protocol schema version | `2026-04-27` | Date-stamped protocol schema identity. |

Changing product version does not imply a protocol migration. Changing protocol
`version` or `schema_version` requires migration notes and tests.

## Stable Retrieval Ladder

Agents should still follow the three-tier retrieval ladder:

1. `search_memories`
2. `retrieve_chunk` or `retrieve_chunks`
3. `retrieve_memory` only when bounded chunks are insufficient

`context_pack` is the preferred shortcut when a compact working set is more
useful than individual chunk calls.

## MCP Tool Inventory

Return shapes below name the public top-level payload, not every nested field.
Nested payload details remain owned by the tool docstring, `core/tool_payloads.py`
where typed, and focused tests.

### Stable Structured Tools

| Tool | Stability | Return shape | Notes |
|---|---|---|---|
| `memory_protocol` | stable | `dict{name, product, version, schema_version, stability, retrieval_ladder, tool_groups, progressive_discovery, canonical_tools, aliases, examples, warnings}` | Agent discoverability entry point. |
| `search_memories` | stable | `dict{query, count, results, error}` | Structured semantic search; optional hybrid mode for identifier-heavy queries. |
| `find_memories` | stable alias | `dict{query, count, results, error}` | Alias for `search_memories`. |
| `context_pack` | stable | `dict{query, count, chunks, citations, omitted, budget_chars, used_chars, receipt, error}` | Bounded working-set helper with retrieval receipts. |
| `list_memories` | stable | `dict{count, memories, error, total, limit, offset, has_more}` | Metadata directory only; no memory bodies. |
| `retrieve_chunk` | stable | `dict{key, chunk_id, found, chunk, error}` | Preferred after search identifies a chunk reference. |
| `read_chunk` | stable alias | `dict{key, chunk_id, found, chunk, error}` | Alias for `retrieve_chunk`. |
| `retrieve_chunks` | stable | `dict{requested_count, found_count, results, error}` | Batch chunk retrieval, preserving request order. |
| `retrieve_memory` | stable | `dict{key, found, memory, error}` | Full memory body; token-expensive. |
| `read_memory` | stable alias/helper | `dict{mode, result|memory, guidance, error}` | Metadata by default, chunk with `chunk_id`, full only with `full=True`. |
| `prepare_memory` | stable | `dict{ready, draft, validation, duplicate, suggestion, guidance, error}` | Draft gate; no write. |
| `store_memory` | stable | `str` | Writes JSON first, then updates ChromaDB through `memory_manager`. |
| `write_memory` | stable alias | `str` | Alias for `store_memory`. |
| `check_duplicate` | stable | `dict{key, duplicate, match, error}` | Read-only duplicate check. |
| `suggest_memory_metadata` | stable | `dict{suggestion, error}` | Read-only metadata suggestion. |
| `validate_memory` | stable | `dict{valid, errors, normalized, error}` | Read-only payload validation. |
| `update_memory_metadata` | stable | `dict{key, updated, memory, error}` | Metadata-only update path. |
| `audit_memory_quality` | stable | `dict{schema_version, count, total, issue_count, summary, memories, write_performed, error}` | Read-only metadata quality audit; does not load memory bodies or write repairs. |
| `get_related_memories` | stable | `dict{key, found, forward, reverse, forward_count, reverse_count, error}` | Traverses explicit memory links. |
| `get_stale_memories` | stable | `dict{days, type, count, memories, error}` | Surfaces time/code stale candidates. |
| `delete_memory` | stable | `str` | Explicit delete by key. |

### Beta Structured Tools

| Tool | Stability | Return shape | Notes |
|---|---|---|---|
| `pin_memory` | beta | `dict{session_id, count, pins, error}` | Session-local promotion; does not modify memory metadata. |
| `unpin_memory` | beta | `dict{session_id, count, pins, removed, error}` | Session-local only. |
| `list_pins` | beta | `dict{session_id, count, pins, error}` | Session-local only. |
| `clear_pins` | beta | `dict{session_id, count, pins, cleared, error}` | Session-local only. |
| `list_context_profiles` | beta | `dict{schema_version, count, profiles, write_performed, error}` | No-write retrieval profile catalog for task-focused context compilation. |
| `prepare_context` | beta | `dict{task, profile, packet, write_performed, error}` | No-write context compiler that wraps `context_pack` with profile defaults, citations, warnings, and next actions. |
| `make_handoff` | beta | `dict{task, profile, handoff, write_performed, error}` | No-write resume handoff packet with context refs, citations, next steps, validation notes, and blockers. |
| `prepare_project_capsule` | beta | `dict{project, capsule, write_performed, error}` | No-write project capsule draft from context refs and memory quality signals; does not store capsule memory. |
| `audit_memory_metadata` | beta | `dict{count, total, scanned_count, issue_count, repairable_count, limit, offset, has_more, memories, error}` | Read-only metadata hygiene audit. |
| `repair_memory_metadata` | beta | `dict{requested_count, repaired_count, dry_run, repairs, error}` | Dry-run by default; writes must preserve JSON-first ordering. |
| `add_graph_edge` | beta | `dict{edge, error}` | Stores compact graph edge records. |
| `list_graph_edges` | beta | `dict{count, edges, error}` | Lists graph records without loading memory bodies. |
| `impact_scan` | beta | `dict{root_ref, count, edges, error}` | Graph traversal returns refs/evidence, not neighbor bodies. |
| `conflict_scan` | beta | `dict{schema_version, ref, status, edge_types, count, conflicts, error}` | Read-only contradiction, invalidation, and supersession scan; returns refs/evidence only. |
| `audit_graph` | beta | `dict{issue_count, issues, error}` | Read-only graph hygiene check. |
| `list_ingestion_pipelines` | beta | `dict{pipelines, error}` | No-write source-intake preset catalog. |
| `preview_memory_chunks` | beta | `dict{title, chunk_count, chunks, omitted, error}` | No-write chunk boundary preview. |
| `preview_source_connector` | beta | `dict{connector_type, target, count, items, omitted, write_performed, error}` | No-write local source preview. |
| `list_document_extractors` | beta | `dict{catalog, error}` | No-write document extraction capability catalog; does not run providers. |
| `preview_document_source_connector` | beta | `dict{connector_type, target, count, items, omitted, write_performed, error}` | No-write local Markdown/text/HTML and URL preview; external formats return structured extraction-request arguments. |
| `prepare_document_extraction_request` | beta | `dict{request, error}` | No-write external parser request for PDF/DOCX/image-bearing sources; does not run a provider. |
| `prepare_document_extraction_result` | beta | `dict{result, error}` | No-write external parser result normalization; returns preview arguments and provenance. |
| `preview_document_extraction` | beta | `dict{preview, error}` | No-write document evidence/chunk preview. |
| `prepare_document_draft` | beta | `dict{draft, error}` | No-write document memory/graph proposal draft; does not promote. |
| `prepare_document_promotion_transaction` | beta | `dict{transaction, error}` | No-write operation plan for reviewed document draft promotion; does not execute writes. |
| `prepare_visual_extraction_request` | beta | `dict{request, error}` | No-write OCR/vision work request; does not run a provider. |
| `preview_visual_extraction` | beta | `dict{preview, error}` | No-write caller-supplied OCR/vision observation preview; does not run a provider. |
| `prepare_source_memory` | beta | `dict{draft, error}` | Draft only; malformed input returns structured errors. |
| `list_source_drafts` | beta | `dict{count, drafts, error}` | Draft inventory. |
| `discard_source_draft` | beta | `dict{discarded, draft_id, error}` | Rejects a draft while preserving an audit trail. |
| `store_prepared_memory` | beta | `dict{stored_count, stored, skipped, error}` | Explicit promotion of selected draft items. |
| `retrieval_eval` | beta | `dict{summary, scenarios, warnings, error}` | Deterministic retrieval quality check. |
| `usage_summary` | beta | `dict` summary | Engram-attributed estimates only, not billed provider tokens. |
| `list_usage_calls` | beta | `dict` call list | Privacy-safe usage records only. |
| `list_workflow_templates` | beta | `dict{templates, error}` | Static workflow recipes. |
| `list_operation_jobs` | beta | `dict{count, jobs, error}` | Local operation receipts. |
| `list_operation_events` | beta | `dict{count, events, error}` | Local operation events. |
| `read_codebase_mapping_config` | beta | `dict{exists, config, status, error}` | Reads mapping config/status; no source scan. |
| `draft_codebase_mapping_config` | beta | `dict{config, receipt, error}` | Draft only; no write. |
| `store_codebase_mapping_config` | beta | `dict{stored, error}` | Writes `.engram/config.json` with overwrite protection. |
| `preview_codebase_mapping` | beta | `dict{mode, domains, receipt, error}` | Dry-run mapping preview. |
| `prepare_codebase_mapping` | beta | `dict{job, receipt, error}` | Prepares bounded source context; no model subprocess. |
| `read_codebase_mapping_context` | beta | `dict{job_id, domain, part_index, context, receipt, error}` | Reads one prepared context part. |
| `store_codebase_mapping_result` | beta | `dict{stored, stale, error}` | Stores agent-authored mapping result with drift checks. |
| `install_codebase_mapping_hook` | beta | `dict{installed, path, error}` | Optional hook installation after explicit intent. |

### Legacy Text Wrappers

| Tool | Stability | Return shape | Notes |
|---|---|---|---|
| `search_memories_text` | legacy | `str` | Legacy wrapper; prefer `search_memories`. |
| `retrieve_chunk_text` | legacy | `str` | Legacy wrapper; prefer `retrieve_chunk`. |
| `retrieve_memory_text` | legacy | `str` | Legacy wrapper; prefer `retrieve_memory`. |
| `list_all_memories` | legacy | `str` | Legacy wrapper; prefer `list_memories`. |
| `get_related_memories_text` | legacy | `str` | Legacy wrapper; prefer `get_related_memories`. |
| `get_stale_memories_text` | legacy | `str` | Legacy wrapper; prefer `get_stale_memories`. |

## Public Data Contracts

- Memory JSON files remain the source of truth.
- ChromaDB remains a rebuildable vector index.
- Memory writes remain JSON-first, then ChromaDB.
- Chunk IDs remain stable `{md5(key)}_{chunk_index}` references.
- Graph edges preserve the required edge record fields named in `AGENTS.md`.
- Source connector and chunk preview tools remain no-write.
- Source intake remains draft-first and explicit-promotion only.
- Operation records are receipts, not schedulers or autonomous triggers.

## Non-Public Internals

The following are implementation details, not public contracts:

- Python module layout under `core/`, except where `AGENTS.md` names migration-sensitive responsibilities.
- ChromaDB collection names, embedding cache details, and local vector index storage layout.
- Flask dashboard routes and templates, except documented WebUI auth/fail-closed behavior.
- Operation-log storage paths and on-disk formatting.
- Codebase mapping job file layout under `.engram/`, except the reviewed `.engram/config.json` adapter surface.
- Any provider-specific model invocation path; codebase mapping remains agent-native and provider-neutral.

## Collaboration Adapter Boundary

The future collaboration product should consume Engram through MCP/API calls and
preserve Engram receipts. It should not rely on Python internals, ChromaDB files,
or private storage paths. Team auth, workspace permissions, comments, assignments,
mentions, role-aware visibility, and rich page editing belong to the collaboration
product, not Engram core.
