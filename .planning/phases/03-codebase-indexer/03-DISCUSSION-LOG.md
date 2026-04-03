# Phase 3: Codebase Indexer - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-03
**Phase:** 03-codebase-indexer
**Areas discussed:** Synthesis prompt design, Domain detection & config, Skill file generation, Git hook & evolve mode

---

## Synthesis Prompt Design

| Option | Description | Selected |
|--------|-------------|----------|
| Planning + source files | Feed both planning artifacts and domain source files | ✓ |
| Source files only | Only source code | |
| Planning only | Only planning docs | |

**User's choice:** Planning + source files

| Option | Description | Selected |
|--------|-------------|----------|
| Structured markdown | ## Architecture, ## Key Decisions, ## Patterns, ## Watch Out For | ✓ |
| Freeform prose | Let Sonnet write naturally | |
| Q&A format | Questions answered directly | |

**User's choice:** Structured markdown

**MAJOR PIVOT — API → CLI:**
User asked: "Is there a way to use the CLI instead of API? I'm already paying for the 20x plan, I really can't afford usage on top of that."
Decision: Use `claude -p` subprocess calls instead of anthropic SDK API calls. This is the Max subscription, zero extra cost.

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, use Claude CLI | Run `claude -p` as subprocess. Uses Max plan. | ✓ |
| Support both | Default CLI, fallback API | |

**User's choice:** Yes, use Claude CLI

| Option | Description | Selected |
|--------|-------------|----------|
| Haiku | Fastest, cheapest | |
| Sonnet | Better quality synthesis | ✓ |
| Configurable per project | .engram/config.json specifies model | |

**User's choice:** Sonnet

---

## Domain Detection & Config

| Option | Description | Selected |
|--------|-------------|----------|
| Config-defined only | User defines domains manually | |
| Auto-detect + override | Scan dirs, user overrides in config | |
| Hybrid | Auto-detect suggests, user confirms, config written | ✓ (custom) |

**User's choice:** "It should auto-detect and provide a confirmation to the user, allowing them to make changes to the domains before setting them in stone. Should be a discussion with Claude, I think, if that's possible."

| Option | Description | Selected |
|--------|-------------|----------|
| Domains with globs + questions | Full config shape with file_globs and questions per domain | ✓ |
| Flat file list | Simple file lists | |
| Directory-based | Top-level dirs as domains | |

**User's choice:** Domains with globs + questions

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, sensible defaults | Default questions for unconfigured domains | ✓ (custom) |
| Require explicit | No defaults | |

**User's choice:** "Yes, sensible defaults, but have a skill or tool in the CLI to assist with the domain setup as part of the initial planning process for a repo."

---

## Skill File Generation

| Option | Description | Selected |
|--------|-------------|----------|
| Glob-based context injection | Skill tells Claude to search Engram when editing matching files | ✓ |
| Always-on context | Skill always loads, higher token cost | |
| Manual trigger only | User must invoke explicitly | |

**User's choice:** Glob-based context injection

| Option | Description | Selected |
|--------|-------------|----------|
| Overwrite | Always regenerate from current index | ✓ |
| Merge | Preserve manual edits | |
| Backup + overwrite | Save .bak first | |

**User's choice:** Overwrite

---

## Git Hook & Evolve Mode

| Option | Description | Selected |
|--------|-------------|----------|
| CLI command | `--install-hook` writes to .git/hooks/post-commit | ✓ |
| Auto on bootstrap | Automatic after first index | |
| Manual instructions | Print script, user installs | |

**User's choice:** CLI command

| Option | Description | Selected |
|--------|-------------|----------|
| Background evolve | Detached process, commit not blocked, output to log | ✓ |
| Foreground evolve | Commit blocks until done | |
| Just flag changes | Write pending list, user runs manually | |

**User's choice:** Background evolve

| Option | Description | Selected |
|--------|-------------|----------|
| SHA256 per file | Hash manifest in index.json | ✓ |
| Git diff | Use git diff between commits | |
| Modification timestamps | File mtime comparison | |

**User's choice:** SHA256 per file

---

## Claude's Discretion

- Exact synthesis prompt wording and system message
- File size handling (truncate or skip)
- Whether to link domain memories via related_to
- CLI subprocess error handling
- Log formatting

## Deferred Ideas

- --watch mode (v2)
- AST/call graph parsing (out of scope)
- Multi-language support (v2)
