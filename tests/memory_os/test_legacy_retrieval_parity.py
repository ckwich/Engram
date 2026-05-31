from core.memory_os.runtime import MemoryOSRuntime
from core.vector_index import InMemoryVectorIndex


def _write_legacy(path, name, payload):
    import json

    (path / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _embed(text):
    text = str(text).lower()
    if "visual hierarchy" in text:
        return [1.0, 0.0, 0.0]
    if "daemon smoke" in text:
        return [0.0, 1.0, 0.0]
    return [0.0, 0.0, 1.0]


def test_legacy_retrieval_parity_report_covers_migrated_agent_ladder(tmp_path):
    from core.memory_os.legacy_retrieval_parity import run_legacy_retrieval_parity_check

    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    _write_legacy(
        legacy_dir,
        "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "# Alpha\n\nVisual hierarchy belongs in the migrated Engram corpus.",
            "project": "Engram",
            "status": "active",
            "chunk_count": 1,
        },
    )
    _write_legacy(
        legacy_dir,
        "windows_alias.json",
        {
            "key": "windows_alias",
            "title": "Windows Alias",
            "content": "Visual hierarchy belongs to the Windows imported path too.",
            "project": "C:\\Dev\\Engram",
            "status": "active",
            "chunk_count": 1,
        },
    )
    _write_legacy(
        legacy_dir,
        "identifier.json",
        {
            "key": "identifier",
            "title": "Identifier",
            "content": "Use MemoryOSApplyLegacyImporter when replaying the corpus.",
            "project": "C:/Dev/Engram",
            "status": "active",
            "chunk_count": 1,
        },
    )
    _write_legacy(
        legacy_dir,
        "draft.json",
        {
            "key": "draft_marker",
            "title": "Draft Marker",
            "content": "Draft-only retrieval marker must stay out of active searches.",
            "project": "Engram",
            "status": "draft",
            "chunk_count": 1,
        },
    )
    _write_legacy(
        legacy_dir,
        "historical.json",
        {
            "key": "historical_marker",
            "title": "Historical Marker",
            "content": "Historical-only retrieval marker must stay out of active searches.",
            "project": "Engram",
            "status": "historical",
            "chunk_count": 1,
        },
    )
    memory_os_root = tmp_path / "memory_os"
    memory_os_root.mkdir()
    runtime = MemoryOSRuntime(
        memory_os_root,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    applied = runtime.apply_legacy_memory_os_migration(
        legacy_dir=legacy_dir,
        accept=True,
        approved_by="agent-review",
    )

    report = run_legacy_retrieval_parity_check(
        runtime,
        probes=[
            {
                "name": "known_key_semantic_ladder",
                "query": "visual hierarchy",
                "expected_key": "alpha",
                "project": "Engram",
                "include_stale": False,
                "check_ladder": True,
                "expected_text_contains": "Visual hierarchy belongs",
            },
            {
                "name": "canonical_project_alias",
                "query": "visual hierarchy",
                "expected_key": "windows_alias",
                "project": "Engram",
                "include_stale": False,
                "limit": 10,
            },
            {
                "name": "hybrid_identifier",
                "query": "MemoryOSApplyLegacyImporter",
                "expected_key": "identifier",
                "project": "Engram",
                "include_stale": False,
                "retrieval_mode": "hybrid",
                "check_ladder": True,
                "expected_text_contains": "MemoryOSApplyLegacyImporter",
            },
            {
                "name": "draft_lifecycle_excluded",
                "query": "Draft-only retrieval marker",
                "expected_key": "draft_marker",
                "project": "Engram",
                "include_stale": False,
                "expect": "absent",
            },
            {
                "name": "historical_lifecycle_excluded",
                "query": "Historical-only retrieval marker",
                "expected_key": "historical_marker",
                "project": "Engram",
                "include_stale": False,
                "expect": "absent",
            },
        ],
        source_label="fixture_legacy_corpus",
    )

    assert applied["status"] == "ok"
    assert report["status"] == "pass"
    assert report["write_performed"] is False
    assert report["active_memory_write_performed"] is False
    assert report["graph_write_performed"] is False
    assert report["checked_count"] == 5
    assert report["passed_count"] == 5
    assert report["failed_count"] == 0
    assert report["error"] is None
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["known_key_semantic_ladder"]["ladder"]["chunk_found"] is True
    assert checks["known_key_semantic_ladder"]["ladder"]["memory_found"] is True
    assert checks["hybrid_identifier"]["retrieval_mode"] == "hybrid"
    assert checks["hybrid_identifier"]["ladder"]["text_contains_expected"] is True
    assert checks["draft_lifecycle_excluded"]["matched"] is False
    assert checks["historical_lifecycle_excluded"]["matched"] is False


def test_legacy_retrieval_parity_report_fails_missing_expected_key(tmp_path):
    from core.memory_os.legacy_retrieval_parity import run_legacy_retrieval_parity_check

    memory_os_root = tmp_path / "memory_os"
    memory_os_root.mkdir()
    runtime = MemoryOSRuntime(
        memory_os_root,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    runtime.store_memory(
        key="alpha",
        content="Visual hierarchy exists here.",
        project="Engram",
        status="active",
    )

    report = run_legacy_retrieval_parity_check(
        runtime,
        probes=[
            {
                "name": "missing_expected_key",
                "query": "visual hierarchy",
                "expected_key": "missing",
                "project": "Engram",
            }
        ],
    )

    assert report["status"] == "fail"
    assert report["failed_count"] == 1
    assert report["error"]["code"] == "retrieval_parity_failed"
    assert report["checks"][0]["passed"] is False
