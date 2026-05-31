"""Tests for hooks/engram_evaluator.py — behavior tests for evaluator functions."""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# Import the module under test
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
from engram_evaluator import load_evaluator_config, build_evaluation_prompt, write_pending_file


# ── Test 1: load_evaluator_config with no config file returns defaults ──────

def test_load_evaluator_config_no_config_returns_defaults():
    with tempfile.TemporaryDirectory() as tmpdir:
        config = load_evaluator_config(tmpdir)
        assert len(config["logic_win_triggers"]) == 3
        assert "bug resolved" in config["logic_win_triggers"]
        assert config["auto_approve_threshold"] == 0.0


# ── Test 2: load_evaluator_config reads session_evaluator section ───────────

def test_load_evaluator_config_reads_custom_threshold():
    with tempfile.TemporaryDirectory() as tmpdir:
        engram_dir = Path(tmpdir) / ".engram"
        engram_dir.mkdir()
        config_data = {
            "session_evaluator": {
                "auto_approve_threshold": 0.9
            }
        }
        (engram_dir / "config.json").write_text(json.dumps(config_data), encoding="utf-8")
        config = load_evaluator_config(tmpdir)
        assert config["auto_approve_threshold"] == 0.9


# ── Test 3: load_evaluator_config with malformed JSON falls back to defaults ─

def test_load_evaluator_config_malformed_json_returns_defaults():
    with tempfile.TemporaryDirectory() as tmpdir:
        engram_dir = Path(tmpdir) / ".engram"
        engram_dir.mkdir()
        (engram_dir / "config.json").write_text("NOT VALID JSON {{{", encoding="utf-8")
        config = load_evaluator_config(tmpdir)
        assert len(config["logic_win_triggers"]) == 3
        assert config["auto_approve_threshold"] == 0.0


# ── Test 4: build_evaluation_prompt includes logic_win_triggers ─────────────

def test_build_evaluation_prompt_includes_triggers():
    payload = {
        "session_id": "test-123",
        "cwd": "C:/Dev/TestProject",
        "last_assistant_message": "Fixed a critical bug in auth",
    }
    config = {
        "logic_win_triggers": ["bug resolved", "new capability added"],
        "milestone_triggers": ["phase completed"],
        "auto_approve_threshold": 0.0,
    }
    prompt = build_evaluation_prompt(payload, config)
    assert "bug resolved" in prompt
    assert "new capability added" in prompt


# ── Test 5: build_evaluation_prompt includes last_assistant_message ─────────

def test_build_evaluation_prompt_includes_last_message():
    payload = {
        "session_id": "test-456",
        "cwd": "C:/Dev/TestProject",
        "last_assistant_message": "Implemented JWT refresh token rotation",
    }
    config = {
        "logic_win_triggers": ["bug resolved"],
        "milestone_triggers": ["phase completed"],
        "auto_approve_threshold": 0.0,
    }
    prompt = build_evaluation_prompt(payload, config)
    assert "Implemented JWT refresh token rotation" in prompt


# ── Test 6: write_pending_file creates correct file ────────────────────────

def test_write_pending_file_creates_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = {
            "draft_key": "test_memory",
            "draft_title": "TestProject \u2014 Auth Fix",
            "draft_content": "## Context\nFixed auth bug.",
            "draft_tags": ["testproject", "auth", "decision"],
            "confidence": 0.85,
            "reasoning": "Important bug fix",
        }
        payload = {
            "session_id": "sess-789",
            "cwd": tmpdir,
        }
        path = write_pending_file(result, payload, None)
        assert path.exists()
        assert path.parent.name == "pending_memories"
        assert "test_memory" in path.name
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["draft_key"] == "test_memory"
        assert data["session_id"] == "sess-789"
        assert data["confidence"] == 0.85
        assert "evaluated_at" in data


# ── Test 7: write_pending_file sets dedup_warning=None when no dup ─────────

def test_write_pending_file_no_dup_warning():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = {
            "draft_key": "some_key",
            "draft_title": "Title",
            "draft_content": "Content",
            "draft_tags": ["tag"],
            "confidence": 0.5,
            "reasoning": "reason",
        }
        payload = {"session_id": "s1", "cwd": tmpdir}
        path = write_pending_file(result, payload, None)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["dedup_warning"] is None


# ── Test 8: write_pending_file sets dedup_warning dict when dup_info ───────

def test_write_pending_file_with_dup_warning():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = {
            "draft_key": "dup_key",
            "draft_title": "Title",
            "draft_content": "Content",
            "draft_tags": ["tag"],
            "confidence": 0.7,
            "reasoning": "reason",
        }
        payload = {"session_id": "s2", "cwd": tmpdir}
        dup_info = {"status": "duplicate", "existing_key": "old_key", "score": 0.95}
        path = write_pending_file(result, payload, dup_info)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["dedup_warning"] is not None
        assert data["dedup_warning"]["existing_key"] == "old_key"
        assert data["dedup_warning"]["score"] == 0.95
