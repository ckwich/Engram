#!/usr/bin/env python
"""
hooks/engram_evaluator.py -- Detached evaluator for Engram session evaluation.

Spawned by engram_stop.py as a background subprocess. Receives the Stop hook
payload as sys.argv[1] (JSON string). Loads per-project config, calls
claude.cmd -p with --json-schema for structured evaluation, then either
auto-stores (if confidence >= threshold) or writes a pending file for
human approval at next session start.

Dedup gate runs before any storage or pending file write.
"""
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Path setup ──────────────────────────────────────────────────────────────
ENGRAM_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ENGRAM_ROOT))

# ── Logging ─────────────────────────────────────────────────────────────────
LOG_FILE = ENGRAM_ROOT / ".engram" / "evaluator.log"

logger = logging.getLogger("engram_evaluator")
logger.setLevel(logging.INFO)

# ── Evaluation JSON schema ──────────────────────────────────────────────────
EVAL_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "worth_capturing": {"type": "boolean"},
        "confidence": {"type": "number"},
        "draft_key": {"type": "string"},
        "draft_title": {"type": "string"},
        "draft_content": {"type": "string"},
        "draft_tags": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
    },
    "required": [
        "worth_capturing", "confidence", "draft_key", "draft_title",
        "draft_content", "draft_tags", "reasoning",
    ],
}

# ── Default config ──────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "logic_win_triggers": [
        "bug resolved",
        "new capability added",
        "architectural decision made",
    ],
    "milestone_triggers": [
        "phase completed",
        "feature shipped",
        "significant refactor done",
    ],
    "auto_approve_threshold": 0.0,
}


def load_evaluator_config(cwd: str) -> dict:
    """
    Load session evaluator config from {cwd}/.engram/config.json.

    Reads the 'session_evaluator' section and merges with defaults.
    Returns defaults on any error (missing file, malformed JSON, etc.).
    """
    defaults = dict(DEFAULT_CONFIG)
    # Deep copy the list values so mutations don't affect DEFAULT_CONFIG
    defaults["logic_win_triggers"] = list(DEFAULT_CONFIG["logic_win_triggers"])
    defaults["milestone_triggers"] = list(DEFAULT_CONFIG["milestone_triggers"])

    config_path = Path(cwd) / ".engram" / "config.json"
    if not config_path.exists():
        return defaults

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        eval_section = raw.get("session_evaluator", {})
        defaults.update(eval_section)
    except Exception:
        pass  # malformed JSON or read error -- use defaults silently

    return defaults


def build_evaluation_prompt(payload: dict, config: dict) -> str:
    """
    Build the evaluation prompt for claude.cmd -p.

    Includes the last_assistant_message as primary context, plus
    logic_win_triggers and milestone_triggers from config.
    """
    session_id = payload.get("session_id", "unknown")
    cwd = payload.get("cwd", "unknown")
    last_message = payload.get("last_assistant_message", "")
    project_name = Path(cwd).name if cwd != "unknown" else "unknown"

    logic_triggers = "\n".join(f"  - {t}" for t in config.get("logic_win_triggers", []))
    milestone_triggers = "\n".join(f"  - {t}" for t in config.get("milestone_triggers", []))

    prompt = f"""You are evaluating a Claude Code session that just ended.

Session ID: {session_id}
Project: {project_name}
Working directory: {cwd}

## Last Assistant Message (primary context)

{last_message}

## Evaluation Criteria

Determine if this session produced something worth capturing as an Engram memory.

**Logic Win Triggers** (session produced a meaningful technical outcome):
{logic_triggers}

**Milestone Triggers** (session reached a significant project milestone):
{milestone_triggers}

## Instructions

Analyze the session context above. Return a JSON object with these fields:

- worth_capturing (boolean): true if the session produced something worth remembering
- confidence (float 0.0-1.0): how confident you are this is worth capturing
- draft_key (string): snake_case lowercase memory key (e.g. "auth_jwt_refresh_rotation")
- draft_title (string): "ProjectName \u2014 Topic" format with em dash
- draft_content (string): Memory content in this format:
  ## Context
  [What was happening, why this matters]

  ## Decision/Pattern/Finding
  [The actual insight, decision, or pattern worth remembering]

  ## Watch Out For
  [Edge cases, gotchas, or things to be aware of]

  Max 3000 characters for draft_content.
- draft_tags (array of 3 strings): [project_name, domain, type]
  where type is one of: decision, pattern, constraint, gotcha, architecture
- reasoning (string): brief explanation of why this is or isn't worth capturing

If nothing significant happened, set worth_capturing=false and provide minimal placeholder values for other fields.
"""
    return prompt


def call_evaluator_claude(prompt: str) -> dict:
    """
    Call claude.cmd -p with --json-schema for structured evaluation output.

    Reuses the exact subprocess pattern from engram_index.py synthesize_domain().
    Returns parsed evaluation dict. On any failure, returns a safe
    not-worth-capturing result (never raises, never blocks).
    """
    fallback = {
        "worth_capturing": False,
        "confidence": 0.0,
        "draft_key": "",
        "draft_title": "",
        "draft_content": "",
        "draft_tags": [],
        "reasoning": "evaluation failed",
    }

    try:
        result = subprocess.run(
            [
                "claude.cmd", "-p",
                "--tools", "",
                "--no-session-persistence",
                "--output-format", "json",
                "--json-schema", json.dumps(EVAL_JSON_SCHEMA),
                "--model", "sonnet",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )

        data = json.loads(result.stdout)
        if data.get("is_error"):
            print(f"[evaluator] Claude returned error: {data.get('result', 'unknown')}", file=sys.stderr)
            return fallback

        return json.loads(data.get("result", "{}"))
    except Exception as e:
        print(f"[evaluator] Claude call failed: {e}", file=sys.stderr)
        return fallback


def write_pending_file(result: dict, payload: dict, dup_info: Optional[dict]) -> Path:
    """
    Write a pending memory draft to {cwd}/.engram/pending_memories/{date}_{key}.json.

    Includes all draft fields plus metadata (session_id, evaluated_at, dedup_warning).
    Returns the path to the written file.
    """
    pending = {
        "draft_key": result["draft_key"],
        "draft_title": result["draft_title"],
        "draft_content": result["draft_content"],
        "draft_tags": result["draft_tags"],
        "confidence": result["confidence"],
        "reasoning": result["reasoning"],
        "session_id": payload.get("session_id", "unknown"),
        "evaluated_at": datetime.now().astimezone().isoformat(),
        "cwd": payload.get("cwd", ""),
        "dedup_warning": dup_info,
    }

    pending_dir = Path(payload["cwd"]) / ".engram" / "pending_memories"
    pending_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{datetime.now().strftime('%Y%m%d')}_{result['draft_key']}.json"
    path = pending_dir / filename
    path.write_text(json.dumps(pending, indent=2), encoding="utf-8")

    return path


def run_evaluator(payload: dict) -> None:
    """
    Main evaluator control flow. Called from __main__ with parsed payload.

    1. Load config from project's .engram/config.json
    2. Build evaluation prompt
    3. Call claude.cmd -p for structured evaluation
    4. If not worth capturing, return early
    5. Run dedup gate
    6. Auto-store if confidence >= threshold (and threshold > 0), else write pending file
    """
    try:
        cwd = payload.get("cwd", "")
        config = load_evaluator_config(cwd)
        prompt = build_evaluation_prompt(payload, config)

        print(f"[evaluator] Evaluating session {payload.get('session_id', '?')}...")

        result = call_evaluator_claude(prompt)

        if not result.get("worth_capturing", False):
            print(f"[evaluator] Not worth capturing: {result.get('reasoning', 'no reason')}")
            return

        # Lazy import to avoid chromadb startup delay
        from core.memory_manager import memory_manager, DuplicateMemoryError

        # Dedup gate -- check before any storage decision (EVAL-05)
        dup_info = memory_manager._check_dedup(result["draft_content"], result["draft_key"])

        # Auto-store path: confidence >= threshold AND threshold > 0.0
        threshold = config.get("auto_approve_threshold", 0.0)
        if threshold > 0.0 and result["confidence"] >= threshold:
            try:
                memory_manager.store_memory(
                    key=result["draft_key"],
                    content=result["draft_content"],
                    tags=result["draft_tags"],
                    title=result["draft_title"],
                    force=True,  # bypass dedup since we already checked
                )
                print(f"[evaluator] Auto-stored: {result['draft_key']} (confidence={result['confidence']})")
                return
            except Exception as e:
                print(f"[evaluator] Auto-store failed: {e}. Writing pending file instead.", file=sys.stderr)

        # Pending file path: write draft for human approval
        path = write_pending_file(result, payload, dup_info)
        print(f"[evaluator] Pending draft written: {path.name}")

    except Exception as e:
        print(f"[evaluator] Fatal error: {e}", file=sys.stderr)


if __name__ == "__main__":
    try:
        payload = json.loads(sys.argv[1])
    except (IndexError, json.JSONDecodeError) as e:
        print(f"[evaluator] Invalid payload: {e}", file=sys.stderr)
        sys.exit(1)

    run_evaluator(payload)
