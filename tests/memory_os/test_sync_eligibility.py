from core.memory_os.sync_eligibility import classify_sync_row


def test_memory_row_is_sync_eligible_by_default():
    result = classify_sync_row("memories", {"key": "project_decision", "scope": "project"})

    assert result == {"eligible": True, "reason": "eligible"}


def test_device_scope_memory_is_not_synced():
    result = classify_sync_row("memories", {"key": "local_path", "scope": "device"})

    assert result == {"eligible": False, "reason": "device_scope"}


def test_jobs_are_never_synced():
    result = classify_sync_row("jobs", {"job_id": "job:one"})

    assert result == {"eligible": False, "reason": "local_only_table"}


def test_drafts_require_explicit_sync_policy():
    assert classify_sync_row("drafts", {"draft_id": "draft:one"}) == {
        "eligible": False,
        "reason": "conditional_table",
    }
    assert classify_sync_row("drafts", {"draft_id": "draft:one", "sync_policy": "sync"}) == {
        "eligible": True,
        "reason": "conditional_table",
    }


def test_local_only_and_quarantined_rows_are_excluded():
    assert classify_sync_row("memories", {"key": "local", "sync_policy": "local_only"}) == {
        "eligible": False,
        "reason": "local_only_policy",
    }
    assert classify_sync_row("memories", {"key": "unsafe", "trust_state": "quarantined"}) == {
        "eligible": False,
        "reason": "quarantined",
    }


def test_ephemeral_rows_are_excluded():
    result = classify_sync_row("memories", {"key": "scratch", "retention_policy": "ephemeral"})

    assert result == {"eligible": False, "reason": "ephemeral_retention"}
