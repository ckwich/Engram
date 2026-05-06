# Engram 1.0 Track 0 Release-Readiness Audit

Date: 2026-05-05
Updated: 2026-05-06
Branch: `codex/collaboration-product-handoff-spec`
Scope: Repo hygiene, public baseline readiness, release-planning drift, MCP visibility, and 1.0 validation evidence.

## Summary

The current branch is healthy from a runtime and test perspective: MCP registration is present, Engram tools are callable after lazy discovery, the self-test and agent reliability harness pass, and the full test suite is green.

The main release-readiness blocker is not runtime behavior. It is branch and documentation hygiene. A public PR from this branch to `origin/main` would currently include both the prior source-intake hardening code changes and the new planning docs. Before starting Track 1 contract work, decide whether to publish the `4e6b6881` source-intake fix to `origin/main` first, then rebase/split the planning branch so each branch has one readable purpose.

## Findings

### P1: Current planning branch is not cleanly separable from the source-intake hardening fix

Evidence:

- `git status --short --branch` returned `## codex/collaboration-product-handoff-spec`.
- `git rev-list --left-right --count origin/main...HEAD` returned `0 3`.
- `git diff --name-status origin/main..HEAD` includes both source-intake code/test changes and planning docs:
  - `core/source_intake.py`
  - `server.py`
  - `tests/test_server_structured_tools.py`
  - `tests/test_source_intake.py`
  - `docs/COLLABORATION_PRODUCT_PRD.md`
  - `docs/ENGRAM_1_0_RELEASE_SPEC.md`
  - `docs/POST_1_COLLABORATION_PRODUCT_HANDOFF.md`

Impact:

A PR from this branch to `origin/main` would mix a runtime hardening fix with product/release planning docs. That makes review and public history harder to read, and it violates the Track 0 goal that each branch have one readable purpose.

Recommended action:

Publish or merge `4e6b6881 Harden source intake tool errors` to `origin/main` first, then rebase or recreate the planning branch on the updated public baseline. After that, keep the 1.0/collaboration planning docs as their own branch or PR.

Resolution update, 2026-05-06:

Local `main` was fast-forwarded from `4e6b6881` to `253de9c8`, bringing in the 1.0/collaboration planning docs and this audit. `main` is now ahead of `origin/main`; remote publication is still pending.

### P2: Public version identity is stale for a 1.0 release track

Evidence:

- Earlier Track 0 audit found the module docstring and CLI argparse description still using the old v0.1 product identity.
- `memory_protocol()` reports protocol `version: 2` and `schema_version: 2026-04-27`, while the release spec now targets Engram 1.0 readiness.

Impact:

The runtime contract has moved far beyond v0.1, but public CLI/module identity still advertises v0.1. This is not a functional bug, but it will confuse users, agents, and release notes during the 1.0 push.

Recommended action:

Track this under Release Track 1 or Track 6. Decide the canonical version source, update CLI/module/docs consistently, and keep protocol schema version separate from product release version.

Resolution update, 2026-05-06:

Track 1 chose product version `1.0.0-dev` for the 1.0 development line while preserving MCP protocol `version: 2` and `schema_version: "2026-04-27"`. `server.py`, `memory_protocol()`, README, and release docs now use that split identity.

### P2: `plan.md` contains stale open work relative to the live WebUI

Evidence:

- `plan.md:111` still lists the dashboard JSON serialization bug as open.
- `plan.md:114` still lists the hardcoded dashboard content textarea limit as open.
- Live code shows the form save path now uses `JSON.stringify(...)` in `static/app.js:588` and `static/app.js:599`.
- Live HTML shows `templates/index.html:287` has `<textarea id="form-content" placeholder="Memory content..."></textarea>` with no `maxlength`.

Impact:

The live code appears to have fixed at least two v0.4 WebUI items, but `plan.md` still presents them as pending. That makes the roadmap less reliable as the binding planning document for 1.0 work.

Recommended action:

Update `plan.md` before or during Track 6. Mark proven-complete items complete, keep only live gaps as open, and add the Engram 1.0 / collaboration-product boundary docs to the current planning state.

### P3: The historical operating-layer spec is ignored by git

Evidence:

- `git check-ignore -v docs/superpowers/specs/2026-04-27-engram-1-agent-operating-layer-design.md` returned `.gitignore:11:docs/superpowers/`.
- Track 0 in `docs/ENGRAM_1_0_RELEASE_SPEC.md` already acknowledges that `docs/superpowers/` planning artifacts are ignored.

Impact:

The 2026-04-27 design doc remains useful local context, but it is not a durable public artifact unless intentionally force-added. Release decisions that should survive in public history need to be mirrored into tracked docs.

Recommended action:

Keep `docs/superpowers/` ignored unless the repo policy changes. Mirror binding 1.0 decisions into tracked docs such as `docs/ENGRAM_1_0_RELEASE_SPEC.md`, `docs/COLLABORATION_PRODUCT_PRD.md`, and future release checklists.

## Positive Evidence

- `codex mcp get engram` succeeds and shows enabled stdio registration using `C:\Dev\Engram\venv\Scripts\python.exe C:\Dev\Engram\server.py`.
- Engram tools were not initially visible in the fresh tool surface, but `tool_search` lazy-loaded them and `memory_protocol()` then succeeded.
- `memory_protocol()` reports the expected progressive-discovery contract, retrieval ladder, canonical tool groups, aliases, and token-safety warnings.
- README `read_memory` description matches the live `server.py` helper behavior: metadata by default, chunk with `chunk_id`, full memory only with `full=True`.
- The public docs scan did not find leaked private project names in the tracked planning docs. Matches were generic guardrail language such as "private/customer/project names".
- The old WebUI v0.4 issues in `plan.md` appear stale rather than live based on current `static/app.js` and `templates/index.html`.

## Validation Run

Commands run from `C:\Dev\Engram`:

- `git status --short --branch` -> clean branch output.
- `codex mcp get engram` -> enabled stdio registration.
- `memory_protocol()` through the Engram MCP tool surface -> succeeded.
- `.\venv\Scripts\python.exe server.py --help` -> exit 0.
- `.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"` -> exit 0, printed `ok`.
- `.\venv\Scripts\python.exe server.py --self-test` -> exit 0, `Self-test PASSED`.
- `.\venv\Scripts\python.exe server.py --agent-eval` -> exit 0, summary status `pass`.
- `.\venv\Scripts\python.exe -m pytest -q` -> exit 0, `210 passed`.
- `git diff --check` -> exit 0.
- AST stdout audit for `server.py` and `core/memory_manager.py` found no bare `print()` calls in `core/memory_manager.py`; the only bare stdout calls in `server.py` are CLI/operator JSON outputs for `--agent-eval` and `--generate-config`.

## Recommended Next Slice

Do Track 0 cleanup before Track 1 contract freeze:

1. Publish local `main` when ready; it now contains `4e6b6881` plus the tracked planning/audit docs.
2. Keep or delete `codex/collaboration-product-handoff-spec` after remote publication.
3. Use `docs/ENGRAM_1_0_IMPLEMENTATION_PLAN.md` as the next execution plan.
4. Start Track 1 with a focused MCP/tool contract inventory: `memory_protocol()`, README tool tables, `server.py` docstrings, alias behavior, and return shapes.
