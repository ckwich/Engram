from __future__ import annotations

from core.memory_quality import audit_memory_quality


def test_audit_memory_quality_reports_scope_and_retrieval_risks():
    payload = audit_memory_quality(
        [
            {
                "key": "good_memory",
                "title": "Good memory",
                "project": "C:/Dev/Engram",
                "domain": "agent-workflows",
                "tags": ["engram", "context"],
                "status": "active",
                "canonical": True,
                "chars": 1200,
                "chunk_count": 2,
            },
            {
                "key": "risky_memory",
                "title": "Risky memory",
                "project": None,
                "domain": None,
                "tags": [],
                "status": "superseded",
                "canonical": False,
                "chars": 16000,
                "chunk_count": "?",
            },
        ]
    )

    assert payload["schema_version"] == "2026-05-11.memory-quality.v1"
    assert payload["count"] == 2
    assert payload["issue_count"] == 5
    risky = payload["memories"][1]
    assert risky["quality_score"] == 35
    assert [issue["code"] for issue in risky["issues"]] == [
        "missing_project",
        "missing_domain",
        "missing_tags",
        "inactive_status",
        "large_memory",
    ]
    assert payload["summary"]["high_risk_count"] == 1


def test_audit_memory_quality_flags_unknown_chunk_count():
    payload = audit_memory_quality(
        [
            {
                "key": "unknown_chunks",
                "title": "Unknown chunks",
                "project": "C:/Dev/Engram",
                "domain": "agent-workflows",
                "tags": ["engram"],
                "status": "active",
                "canonical": True,
                "chars": 200,
                "chunk_count": "?",
            }
        ]
    )

    assert payload["memories"][0]["issues"][0]["code"] == "unknown_chunk_count"
    assert payload["summary"]["medium_risk_count"] == 1
