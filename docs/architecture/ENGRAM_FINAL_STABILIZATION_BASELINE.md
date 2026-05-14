# Engram Final Stabilization Baseline

Date: 2026-05-14
Branch: `codex/ekc-v0-contract`
Commit: `79c630a6 docs: add Engram final stabilization plan`
Remote status: pushed to `origin/codex/ekc-v0-contract`; clean and aligned with origin after push.

## Branch Notes

The stabilization plan expected the branch to be ahead by one commit at the start
of Slice 0. The actual state was ahead by two because the stabilization plan
itself was committed after the earlier document-intake hardening commit.

Recent commits at baseline:

- `79c630a6 docs: add Engram final stabilization plan`
- `e7d1196c fix: harden document intake artifacts`
- `a7add89f docs: document ingestion intelligence workflow`
- `6dfdf058 feat: wire document evidence into ekc`
- `e52b4197 feat: validate visual ocr and table coverage`

## Validation

| Command | Result |
|---|---|
| `git push origin codex/ekc-v0-contract` | Passed; pushed `a7add89f..79c630a6` to origin. |
| `.\venv\Scripts\python.exe server.py --help` | Passed; CLI help rendered for `Engram 1.0.0`. |
| `.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"` | Passed; printed `ok`. |
| `.\venv\Scripts\python.exe engramd.py --doctor` | Passed; daemon health `ok`, process hygiene `daemon=1` and `daemon_launcher=1`, no warnings. |
| `.\venv\Scripts\python.exe engramd.py --smoke-test` | Passed; Memory OS store/search/read/delete smoke returned `status: ok`. |
| `.\venv\Scripts\python.exe -m pytest tests\architecture tests\test_server_daemon_client_entrypoint.py tests\policy tests\mcp\test_no_write_tool_contracts.py tests\backend_gates -q` | Passed; `23 passed in 1.43s`. |
| `.\venv\Scripts\python.exe -m pytest -q` | Passed; `591 passed, 2 skipped, 26 warnings in 40.17s`. |
| `git diff --check` | Passed. |

## Known Stabilization Targets

- Review and promotion ergonomics.
- Protocol metadata registry.
- Legacy adapter boundary.
- Codebase mapping drift hardening.
- WebUI inspector/review ergonomics.
- Backend truth and release docs alignment.
