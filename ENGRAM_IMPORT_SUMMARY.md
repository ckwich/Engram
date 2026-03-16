# Engram Vault Import Summary

**Date:** 2026-03-16
**Source:** C:\Obsidian\
**Total memories stored:** 20 (+ 2 pre-existing = 22 total)
**Total chunks indexed:** 697
**Errors:** 0

## Memories Stored

| Key | Title | Chunks | Source File |
|---|---|---|---|
| `vault_project_status` | Active Projects and Priorities | 10 | VAULT-INDEX.md |
| `lumen_knowledge_base` | Lumen GM Hub — Project Knowledge Base | 17 | brain/Lumen/lumen.md |
| `lumen_architecture_adrs` | Lumen — Architecture Decision Records | 75 | brain/Lumen/lumen-architecture.md |
| `lumen_business_model` | Lumen — Business Model and Go-to-Market | 19 | brain/Lumen/lumen-business.md |
| `sylvara_knowledge_base` | Sylvara — Project Knowledge Base | 11 | brain/Sylvara/sylvara.md |
| `sylvara_architecture` | Sylvara — Architecture and Technical Decisions | 19 | brain/Sylvara/sylvara-architecture.md |
| `sylvara_ops_runbook` | Sylvara — Operational Runbook | 15 | brain/Sylvara/sylvara-ops.md |
| `lumen_build_plan` | Lumen GM Hub — Build Plan (v0.1–v1.5+) | 34 | projects/Lumen/plan.md |
| `lumen_agents_guidelines` | Lumen — Codex Operational Guidelines | 26 | projects/Lumen/AGENTS.md |
| `lumen_product_spec_v3` | Lumen GM Hub — Full Product Specification v3 | 112 | projects/Lumen/lumen_gm_hub_spec_v3.md |
| `lumen_benchmark_phase1_vram` | Lumen — Phase 1 VRAM Benchmark Results | 11 | projects/Lumen/benchmarks/phase1_vram.md |
| `lumen_benchmark_phase3_stability` | Lumen — Phase 3 Stability Test (60-min) | 32 | projects/Lumen/benchmarks/phase3_stability.md |
| `lumen_benchmark_v01_integration` | Lumen — v0.1 Integration Test Results | 22 | projects/Lumen/benchmarks/v01_integration.md |
| `sylvara_agents_guidelines` | Sylvara — Codex Operational Guidelines | 62 | projects/Sylvara/AGENTS.md |
| `sylvara_scheduler_plan` | Sylvara Scheduler — Full Plan | 150 | projects/Sylvara/plan.md |
| `lumen_session_2026_03_10` | Lumen Session — 2026-03-10 (Planning & Architecture) | 10 | journal/Lumen/2026-03-10.md |
| `lumen_session_2026_03_11` | Lumen Session — 2026-03-11 (PoC Complete, Go Verdict) | 9 | journal/Lumen/2026-03-11.md |
| `lumen_session_2026_03_12` | Lumen Session — 2026-03-12 (v0.1 Build Complete) | 19 | journal/Lumen/2026-03-12.md |
| `lumen_session_2026_03_13` | Lumen Session — 2026-03-13 (v0.2 Suggestion Engine) | 10 | journal/Lumen/2026-03-13.md |
| `sylvara_session_2026_03_13` | Sylvara Session — 2026-03-13 (Production Deployment) | 14 | journal/Sylvara/2026-03-13.md |

## Pre-Existing (Skipped — Already Stored)

| Key | Reason |
|---|---|
| `cole_profile` | Already stored before import |
| `sylvara_strategy` | Already stored before import |

## Files Skipped

| File | Reason |
|---|---|
| `CLAUDE.md` | Vault governance doc — Claude Code operational rules for the vault, not project knowledge. Would shadow canonical governance patterns. |
| `projects/Lumen/benchmarks/v02_integration.md` | Empty template — no test data filled in. Scratchpad with placeholder checkboxes only. |

## Judgment Calls

1. **VAULT-INDEX.md stored as `vault_project_status`** — Cole's profile info is already in `cole_profile`, so this memory focuses on the project status table, priorities, open threads, and recent sessions. No duplication.

2. **Governance docs (AGENTS.md, plan.md) stored for both projects** — These are Lumen and Sylvara governance docs, not Engram's own governance. They contain valuable project-specific knowledge (tech stack decisions, coding standards, domain rules) that agents should be able to search semantically. They do not shadow Engram's own AGENTS.md or plan.md.

3. **Benchmark data with large latency tables stored as-is** — The phase3_stability.md and v01_integration.md files contain hundreds of rows of latency/VRAM samples. These create many chunks but the data is valuable for semantic search (e.g., "what was the VRAM usage during the stability test?"). The chunker handles them correctly.

4. **Lumen spec v3 stored as single memory** — At 112 chunks this is the largest memory, but it's a single coherent document (the full product spec). Splitting it into separate memories would break cross-references between sections.

5. **Business contact emails (John, Eric, Savannah, Larry) included** — These are Iron Tree Service business contacts in a professional context, not personal health/finance/password data. They appear in sylvara_knowledge_base.

6. **No vault files were modified** — All reads were read-only. Import script used `Path.read_text()` only.
