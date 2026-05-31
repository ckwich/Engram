#!/usr/bin/env python
"""
hooks/engram_stop.py -- Claude Code Stop hook entry point for Engram session evaluator.

Reads the Stop hook JSON payload from stdin, checks stop_hook_active first,
then spawns engram_evaluator.py as a detached subprocess. Exits in < 10 seconds.
Never blocks session end -- always exits 0.
"""
import json
# The hook spawns the trusted local evaluator with shell=False.
import subprocess  # nosec B404
import sys
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
# Resolve venv Python dynamically — works regardless of install location
ENGRAM_ROOT = Path(__file__).parent.parent
_is_windows = sys.platform == "win32"
VENV_PYTHON = str(ENGRAM_ROOT / "venv" / ("Scripts" if _is_windows else "bin") / ("python.exe" if _is_windows else "python"))


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
        popen_kwargs = {
            "stdin": subprocess.DEVNULL,
            "stderr": subprocess.STDOUT,
            "close_fds": True,
        }
        if _is_windows:
            popen_kwargs["creationflags"] = CREATE_NO_WINDOW
        with open(log_file, "a", encoding="utf-8") as log:
            popen_kwargs["stdout"] = log
            # Fixed venv Python and evaluator argv, invoked with shell=False.
            subprocess.Popen(  # nosec B603
                [VENV_PYTHON, str(evaluator), json.dumps(payload)],
                **popen_kwargs,
            )
    except Exception as e:
        print(f"[Engram] Stop hook spawn skipped: {e}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
