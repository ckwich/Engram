# Requirements: Engram Enhancement Suite

**Defined:** 2026-03-29
**Core Value:** AI agents working on any indexed project should automatically receive relevant architectural context, create memories naturally, and never lose important decisions or patterns.

## v1 Requirements

Requirements for this milestone. Each maps to roadmap phases.

### Engramize Skill

- [ ] **SKIL-01**: User can say "engramize [description]" mid-session and Code creates a properly formatted memory automatically
- [ ] **SKIL-02**: Skill enforces naming conventions (underscore keys, lowercase, descriptive)
- [ ] **SKIL-03**: Skill enforces tagging standards (project name, domain, type: decision/pattern/constraint/gotcha/architecture)
- [ ] **SKIL-04**: Skill enforces content limit (under 3000 characters)
- [ ] **SKIL-05**: Skill produces human-readable titles ("Sylvara — Billing Webhook Pattern")
- [ ] **SKIL-06**: Skill file installed globally at ~/.claude/skills/engramize/skill.md

### Core Memory — Tracking

- [x] **TRAK-01**: Every memory has a last_accessed timestamp that updates on retrieve_memory and retrieve_chunk calls
- [x] **TRAK-02**: search_memories hits update last_accessed for returned memories
- [x] **TRAK-03**: Existing memories get last_accessed: null until first retrieval (backward compatible)
- [x] **TRAK-04**: last_accessed stored in JSON metadata alongside created_at and updated_at

### Core Memory — Deduplication

- [x] **DEDU-01**: store_memory runs similarity search before writing; scores above 0.92 cosine return a warning with similar memory key, title, and score
- [x] **DEDU-02**: Caller can pass force=True to override deduplication warning and write anyway
- [x] **DEDU-03**: Dedup threshold is configurable (default 0.92)
- [x] **DEDU-04**: Dedup comparison strips audit log suffix before embedding to prevent false negatives

### Core Memory — Relationships

- [x] **RELM-01**: store_memory accepts optional related_to list of existing memory keys
- [x] **RELM-02**: related_to stored in JSON metadata and as comma-string in ChromaDB metadata (not empty array)
- [x] **RELM-03**: New MCP tool get_related_memories(key) returns all memories explicitly linked to the given key
- [x] **RELM-04**: get_related_memories returns bidirectional results (A links to B means B appears when querying A, and vice versa)
- [x] **RELM-05**: WebUI displays related memories as clickable links on memory detail view

### Codebase Indexer

- [x] **INDX-01**: engram_index.py CLI tool synthesizes architectural understanding from codebases into Engram memories
- [x] **INDX-02**: Model B architecture — captures why, what was learned, what to watch out for (not file-by-file descriptions)
- [x] **INDX-03**: Per-project config at {project_root}/.engram/config.json with configurable domain questions
- [x] **INDX-04**: Memory namespace: codebase/{project}/{domain}/architecture
- [x] **INDX-05**: Two outputs per domain: Engram memory AND thin skill file at ~/.claude/skills/ triggering retrieval on relevant file globs
- [x] **INDX-06**: Skill files never contain content directly — Engram is always source of truth
- [x] **INDX-07**: Index manifest at {project}/.engram/index.json tracks file hashes for incremental re-indexing
- [x] **INDX-08**: bootstrap mode — reads planning artifacts + source files, full synthesis pass
- [x] **INDX-09**: evolve mode — hash-compares files since last run, re-synthesizes only changed domains
- [x] **INDX-10**: full mode — complete re-index of everything
- [x] **INDX-11**: Git post-commit hook for automatic evolve mode on changed files only
- [x] **INDX-12**: Hook uses absolute venv Python path (no PATH dependency on Windows)
- [x] **INDX-13**: Manual edits to Engram memories win over re-index unless --force is passed
- [x] **INDX-14**: CLI supports --project, --mode, --domain, --dry-run, --force, --init, --install-hook flags (--watch deferred to v2 per INDX-19)
- [x] **INDX-15**: Synthesis uses Sonnet via Claude Code CLI (changed from anthropic SDK per D-01 decision)
- [x] **INDX-16**: Cost controls: dry-run estimation, invocation count display (token budget N/A — uses CLI subscription)

### Staleness Detection

- [ ] **STAL-01**: WebUI gets a "Stale Memories" tab showing memories not accessed in 90 days (configurable threshold)
- [x] **STAL-02**: When indexer detects file changes in a domain, it flags corresponding memory as potentially_stale in JSON metadata
- [x] **STAL-03**: New MCP tool get_stale_memories(days=90) returns memories past the threshold
- [x] **STAL-04**: No automatic deletion — surfacing only, human decides

### Session Evaluator

- [x] **EVAL-01**: Claude Code Stop hook evaluates completed sessions against configurable criteria
- [x] **EVAL-02**: "Logic Win" triggers: bug resolved, new capability added, architectural decision made (configurable)
- [x] **EVAL-03**: "Milestone" triggers: phase completed, feature shipped, significant refactor done (configurable)
- [ ] **EVAL-04**: If criteria met, drafts a memory and presents for approval before storing
- [x] **EVAL-05**: Deduplication gate (DEDU-01) runs automatically before approval prompt
- [x] **EVAL-06**: Criteria configurable per project in .engram/config.json session_evaluator section
- [x] **EVAL-07**: auto_approve_threshold of 0.0 means always ask; higher values auto-approve high-confidence captures
- [x] **EVAL-08**: Stop hook checks stop_hook_active flag to prevent infinite evaluation loops
- [x] **EVAL-09**: Evaluator spawns as detached subprocess — hook exits in under 10 seconds
- [x] **EVAL-10**: Always-on for every session (not gated to indexed projects)

## v2 Requirements

Deferred to future milestone. Tracked but not in current roadmap.

### Advanced Relationships

- **RELM-06**: Graph visualization of memory relationships in WebUI
- **RELM-07**: Transitive relationship traversal (A→B→C when querying A)

### Indexer Enhancements

- **INDX-17**: AST/call graph parsing for deeper code understanding
- **INDX-18**: Multi-language support beyond Python projects
- **INDX-19**: Watch mode (--watch flag) for continuous indexing

### Memory Intelligence

- **INTL-01**: Automatic memory merging for related memories
- **INTL-02**: Memory importance scoring based on access patterns
- **INTL-03**: Memory summarization for oversized memories

## Out of Scope

| Feature | Reason |
|---------|--------|
| Graph DB migration | Revisit after related_to usage validates the need |
| AST/call graph parsing | Too complex; Claude-based synthesis covers the value |
| Multi-user support | Local-first, single user architecture |
| Cloud sync | Local-first design; portability via export/import |
| Automatic memory deletion | Staleness surfaces only; human decides |
| Auto-merge of similar memories | Silent data loss risk (confirmed by ecosystem research) |
| Emotional/sentiment metadata | Not relevant to architectural knowledge system |
| Ebbinghaus decay curves | Over-engineered for this use case |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SKIL-01 | Phase 1 | Pending |
| SKIL-02 | Phase 1 | Pending |
| SKIL-03 | Phase 1 | Pending |
| SKIL-04 | Phase 1 | Pending |
| SKIL-05 | Phase 1 | Pending |
| SKIL-06 | Phase 1 | Pending |
| TRAK-01 | Phase 2 | Complete |
| TRAK-02 | Phase 2 | Complete |
| TRAK-03 | Phase 2 | Complete |
| TRAK-04 | Phase 2 | Complete |
| DEDU-01 | Phase 2 | Complete |
| DEDU-02 | Phase 2 | Complete |
| DEDU-03 | Phase 2 | Complete |
| DEDU-04 | Phase 2 | Complete |
| RELM-01 | Phase 2 | Complete |
| RELM-02 | Phase 2 | Complete |
| RELM-03 | Phase 2 | Complete |
| RELM-04 | Phase 2 | Complete |
| RELM-05 | Phase 2 | Complete |
| INDX-01 | Phase 3 | Complete |
| INDX-02 | Phase 3 | Complete |
| INDX-03 | Phase 3 | Complete |
| INDX-04 | Phase 3 | Complete |
| INDX-05 | Phase 3 | Complete |
| INDX-06 | Phase 3 | Complete |
| INDX-07 | Phase 3 | Complete |
| INDX-08 | Phase 3 | Complete |
| INDX-09 | Phase 3 | Complete |
| INDX-10 | Phase 3 | Complete |
| INDX-11 | Phase 3 | Complete |
| INDX-12 | Phase 3 | Complete |
| INDX-13 | Phase 3 | Complete |
| INDX-14 | Phase 3 | Complete |
| INDX-15 | Phase 3 | Complete |
| INDX-16 | Phase 3 | Complete |
| STAL-01 | Phase 4 | Pending |
| STAL-02 | Phase 4 | Complete |
| STAL-03 | Phase 4 | Complete |
| STAL-04 | Phase 4 | Complete |
| EVAL-01 | Phase 5 | Complete |
| EVAL-02 | Phase 5 | Complete |
| EVAL-03 | Phase 5 | Complete |
| EVAL-04 | Phase 5 | Pending |
| EVAL-05 | Phase 5 | Complete |
| EVAL-06 | Phase 5 | Complete |
| EVAL-07 | Phase 5 | Complete |
| EVAL-08 | Phase 5 | Complete |
| EVAL-09 | Phase 5 | Complete |
| EVAL-10 | Phase 5 | Complete |

**Coverage:**
- v1 requirements: 45 total
- Mapped to phases: 45
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-29*
*Last updated: 2026-03-29 after initial definition*
