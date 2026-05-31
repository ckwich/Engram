from __future__ import annotations

import pytest

from core.policy.write_policy import (
    WritePolicy,
    assert_write_policy_metadata,
    validate_write_policy_metadata,
    write_policy_metadata,
)


def test_write_policy_metadata_builds_preview_contract():
    metadata = write_policy_metadata(WritePolicy.PREVIEW_ONLY)

    assert metadata == {
        "write_policy": "preview_only",
        "write_performed": False,
        "active_memory_write_performed": False,
    }
    assert validate_write_policy_metadata(metadata, operation="preview")["valid"] is True


def test_write_policy_validator_rejects_missing_active_write_flag():
    result = validate_write_policy_metadata(
        {"write_policy": "preview_only", "write_performed": False},
        operation="preview",
    )

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "missing_active_memory_write_performed"


def test_write_policy_validator_rejects_preview_that_writes():
    result = validate_write_policy_metadata(
        {
            "write_policy": "preview_only",
            "write_performed": True,
            "active_memory_write_performed": True,
        },
        operation="preview",
    )

    assert result["valid"] is False
    assert {error["code"] for error in result["errors"]} == {
        "unexpected_write",
        "unexpected_active_memory_write",
    }


def test_write_policy_validator_requires_active_flag_for_durable_write():
    result = validate_write_policy_metadata(
        {
            "write_policy": "allow_durable_write",
            "write_performed": True,
            "active_memory_write_performed": False,
        },
        operation="store_memory",
    )

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "missing_active_memory_write"


def test_assert_write_policy_metadata_raises_actionable_message():
    with pytest.raises(AssertionError, match="missing_write_performed"):
        assert_write_policy_metadata(
            {"write_policy": "read_only", "active_memory_write_performed": False},
            operation="bad_payload",
        )
