#!/usr/bin/env python
"""
hooks/engram_stop.py -- Claude Code Stop hook entry point for Engram session evaluator.

Reads the Stop hook JSON payload from stdin, checks stop_hook_active first,
then spawns engram_evaluator.py as a detached subprocess. Exits in < 10 seconds.
Never blocks session end -- always exits 0.
"""
import json
import subprocess
import sys
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
VENV_PYTHON = r"C:/Dev/Engram/venv/Scripts/python.exe"


def main() -> None:
    # Parse payload -- malformed input exits 0 (fail-open)
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    # CRITICAL: stop_hook_active check MUST be first -- prevents infinite loop (EVAL-08)
    if payload.get("stop_hook_active"):
        sys.exit(0)

    evaluator = Path(__file__).parent / "engram_evaluator.py"
    log_file = Path(__file__).parent.parent / ".engram" / "evaluator.log"

    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as log:
            subprocess.Popen(
                [VENV_PYTHON, str(evaluator), json.dumps(payload)],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
                close_fds=True,
            )
    except Exception:
        pass  # fail-open: never block session end (D-04)

    sys.exit(0)


if __name__ == "__main__":
    main()
