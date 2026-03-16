"""
import_vault.py — One-time import of Cole's Obsidian vault into Engram.

Reads markdown files from C:\Obsidian\, applies judgment rules,
and stores each as a memory via memory_manager.store_memory().
"""
import sys
from pathlib import Path

from core.memory_manager import memory_manager

VAULT = Path(r"C:\Obsidian")

# Already stored — skip these keys
ALREADY_STORED = {"cole_profile", "sylvara_strategy"}

# Import plan: (source_path, key, title, tags)
IMPORTS = [
    # ── Vault-level ──────────────────────────────────────────────────────────
    (
        "VAULT-INDEX.md",
        "vault_project_status",
        "Active Projects and Priorities",
        ["vault", "projects", "status"],
    ),
    # ── Lumen brain files ────────────────────────────────────────────────────
    (
        "brain/Lumen/lumen.md",
        "lumen_knowledge_base",
        "Lumen GM Hub — Project Knowledge Base",
        ["lumen", "knowledge-base"],
    ),
    (
        "brain/Lumen/lumen-architecture.md",
        "lumen_architecture_adrs",
        "Lumen — Architecture Decision Records",
        ["lumen", "architecture", "adrs"],
    ),
    (
        "brain/Lumen/lumen-business.md",
        "lumen_business_model",
        "Lumen — Business Model and Go-to-Market",
        ["lumen", "business", "pricing"],
    ),
    # ── Sylvara brain files ──────────────────────────────────────────────────
    (
        "brain/Sylvara/sylvara.md",
        "sylvara_knowledge_base",
        "Sylvara — Project Knowledge Base",
        ["sylvara", "knowledge-base"],
    ),
    (
        "brain/Sylvara/sylvara-architecture.md",
        "sylvara_architecture",
        "Sylvara — Architecture and Technical Decisions",
        ["sylvara", "architecture"],
    ),
    (
        "brain/Sylvara/sylvara-ops.md",
        "sylvara_ops_runbook",
        "Sylvara — Operational Runbook",
        ["sylvara", "operations", "deployment"],
    ),
    # ── Lumen project docs ───────────────────────────────────────────────────
    (
        "projects/Lumen/plan.md",
        "lumen_build_plan",
        "Lumen GM Hub — Build Plan (v0.1–v1.5+)",
        ["lumen", "plan", "roadmap"],
    ),
    (
        "projects/Lumen/AGENTS.md",
        "lumen_agents_guidelines",
        "Lumen — Codex Operational Guidelines",
        ["lumen", "agents", "guidelines"],
    ),
    (
        "projects/Lumen/lumen_gm_hub_spec_v3.md",
        "lumen_product_spec_v3",
        "Lumen GM Hub — Full Product Specification v3",
        ["lumen", "spec", "product"],
    ),
    # ── Lumen benchmarks ─────────────────────────────────────────────────────
    (
        "projects/Lumen/benchmarks/phase1_vram.md",
        "lumen_benchmark_phase1_vram",
        "Lumen — Phase 1 VRAM Benchmark Results",
        ["lumen", "benchmark", "vram"],
    ),
    (
        "projects/Lumen/benchmarks/phase3_stability.md",
        "lumen_benchmark_phase3_stability",
        "Lumen — Phase 3 Stability Test (60-min)",
        ["lumen", "benchmark", "stability"],
    ),
    (
        "projects/Lumen/benchmarks/v01_integration.md",
        "lumen_benchmark_v01_integration",
        "Lumen — v0.1 Integration Test Results",
        ["lumen", "benchmark", "integration"],
    ),
    # ── Sylvara project docs ─────────────────────────────────────────────────
    (
        "projects/Sylvara/AGENTS.md",
        "sylvara_agents_guidelines",
        "Sylvara — Codex Operational Guidelines",
        ["sylvara", "agents", "guidelines"],
    ),
    (
        "projects/Sylvara/plan.md",
        "sylvara_scheduler_plan",
        "Sylvara Scheduler — Full Plan",
        ["sylvara", "plan", "scheduler"],
    ),
    # ── Lumen journal ────────────────────────────────────────────────────────
    (
        "journal/Lumen/2026-03-10.md",
        "lumen_session_2026_03_10",
        "Lumen Session — 2026-03-10 (Planning & Architecture)",
        ["lumen", "journal", "session"],
    ),
    (
        "journal/Lumen/2026-03-11.md",
        "lumen_session_2026_03_11",
        "Lumen Session — 2026-03-11 (PoC Complete, Go Verdict)",
        ["lumen", "journal", "session"],
    ),
    (
        "journal/Lumen/2026-03-12.md",
        "lumen_session_2026_03_12",
        "Lumen Session — 2026-03-12 (v0.1 Build Complete)",
        ["lumen", "journal", "session"],
    ),
    (
        "journal/Lumen/2026-03-13.md",
        "lumen_session_2026_03_13",
        "Lumen Session — 2026-03-13 (v0.2 Suggestion Engine)",
        ["lumen", "journal", "session"],
    ),
    # ── Sylvara journal ──────────────────────────────────────────────────────
    (
        "journal/Sylvara/2026-03-13.md",
        "sylvara_session_2026_03_13",
        "Sylvara Session — 2026-03-13 (Production Deployment)",
        ["sylvara", "journal", "session"],
    ),
]

# Files to skip with reasons
SKIPPED = [
    ("CLAUDE.md", "Vault governance doc — Claude Code operational rules, not project knowledge"),
    ("projects/Lumen/benchmarks/v02_integration.md", "Empty template — no test data filled in yet"),
]


def main():
    stored = 0
    errors = []

    print(f"[Import] Starting vault import from {VAULT}", file=sys.stderr)
    print(f"[Import] {len(IMPORTS)} files to import, {len(SKIPPED)} to skip", file=sys.stderr)
    print(f"[Import] Already stored (will skip): {ALREADY_STORED}", file=sys.stderr)
    print(file=sys.stderr)

    for rel_path, key, title, tags in IMPORTS:
        if key in ALREADY_STORED:
            print(f"  SKIP (already stored): {key}", file=sys.stderr)
            continue

        filepath = VAULT / rel_path
        if not filepath.exists():
            msg = f"File not found: {filepath}"
            print(f"  ERROR: {msg}", file=sys.stderr)
            errors.append((key, msg))
            continue

        content = filepath.read_text(encoding="utf-8")
        if not content.strip():
            msg = f"Empty file: {filepath}"
            print(f"  SKIP (empty): {key}", file=sys.stderr)
            errors.append((key, msg))
            continue

        try:
            result = memory_manager.store_memory(key, content, tags, title)
            chunks = result.get("chunk_count", "?")
            chars = result.get("chars", 0)
            print(f"  OK: {key} ({chunks} chunks, {chars} chars)", file=sys.stderr)
            stored += 1
        except Exception as e:
            msg = f"store_memory failed: {e}"
            print(f"  ERROR: {key} — {msg}", file=sys.stderr)
            errors.append((key, msg))

    print(file=sys.stderr)
    print(f"[Import] Done. {stored} stored, {len(errors)} errors.", file=sys.stderr)

    for path, reason in SKIPPED:
        print(f"  SKIPPED: {path} — {reason}", file=sys.stderr)

    if errors:
        print(f"\n[Import] Errors:", file=sys.stderr)
        for key, msg in errors:
            print(f"  {key}: {msg}", file=sys.stderr)

    return stored, errors


if __name__ == "__main__":
    stored, errors = main()
    sys.exit(1 if errors else 0)
