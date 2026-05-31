---
name: engram-index
description: Run the Engram codebase indexer to synthesize architectural understanding into memories. Supports init, bootstrap, evolve, full, dry-run, and hook installation.
argument-hint: "[command: init | bootstrap | evolve | full | dry-run | install-hook] [options]"
---

The user wants to run the Engram codebase indexer. Parse $ARGUMENTS to determine the command and options, then execute the appropriate CLI invocation.

The indexer lives in the Engram checkout at `engram_index.py` and should be run
with that checkout's virtual-environment Python.

**Step 1 — Determine project path**

The project is the current working directory unless the user specifies otherwise.

**Step 2 — Parse the command from $ARGUMENTS**

Map the user's intent to the correct CLI flags:

| User says | CLI command |
|-----------|------------|
| `init` or `setup` or `configure` | `--init` |
| `bootstrap` or `full index` or `index everything` | `--mode bootstrap` |
| `evolve` or `update` or `reindex changed` | `--mode evolve` |
| `full` or `reindex all` or `complete reindex` | `--mode full` |
| `dry-run` or `preview` or `what would change` | `--mode bootstrap --dry-run` (or `--mode evolve --dry-run` if they say "evolve dry-run") |
| `install hook` or `hook` or `git hook` | `--install-hook` |
| `status` or `show config` | Read and display `.engram/config.json` from the project directory |
| (no arguments or `help`) | Show available commands |

Optional modifiers the user might include:
- A specific domain: `--domain auth` (e.g., "evolve auth" or "bootstrap the auth domain")
- Force flag: `--force` (e.g., "force bootstrap" or "reindex even if edited")

**Step 3 — Build and run the command**

Construct the command:

```
C:/Path/To/Engram/venv/Scripts/python.exe C:/Path/To/Engram/engram_index.py --project "{cwd}" {flags}
```

Where `{cwd}` is the current working directory and the Engram path is the local
Engram checkout path.

Run it using the Bash tool. If the command is `--init`, it requires interactive input — warn the user they need to run it in the terminal directly:

```
The init command requires interactive input. Run this in your terminal:

C:\Path\To\Engram\venv\Scripts\python.exe C:\Path\To\Engram\engram_index.py --project "{cwd}" --init
```

For all other commands, run via Bash and show the output.

**Step 4 — Report results**

After the command completes:
- If bootstrap/evolve/full succeeded: report which domains were synthesized and which skill files were generated
- If dry-run: show the summary table
- If install-hook: confirm the hook was written
- If errors occurred: show the error and suggest fixes

**Examples**

User: `/engram-index bootstrap`
-> `C:/Path/To/Engram/venv/Scripts/python.exe C:/Path/To/Engram/engram_index.py --project "C:/Projects/ExampleApp" --mode bootstrap`

User: `/engram-index evolve auth`
-> `C:/Path/To/Engram/venv/Scripts/python.exe C:/Path/To/Engram/engram_index.py --project "C:/Projects/ExampleApp" --mode evolve --domain auth`

User: `/engram-index dry-run`
-> `C:/Path/To/Engram/venv/Scripts/python.exe C:/Path/To/Engram/engram_index.py --project "C:/Projects/ExampleApp" --mode bootstrap --dry-run`

User: `/engram-index install hook`
-> `C:/Path/To/Engram/venv/Scripts/python.exe C:/Path/To/Engram/engram_index.py --project "C:/Projects/ExampleApp" --install-hook`
