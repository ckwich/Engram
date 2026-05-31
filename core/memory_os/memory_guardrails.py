"""Deterministic guardrails for active Memory OS writes."""
from __future__ import annotations

import re
from typing import Any

from core.memory_os._records import hash_payload, now_iso, stable_id, upsert_record
from core.memory_os.ledger import MemoryOSLedger


MEMORY_GUARDRAIL_SCHEMA_VERSION = "2026-05-26.memory-guardrails.v1"
MAX_NON_SECRET_EXCERPT_CHARS = 120
SECRET_LIKE_CONTENT = "secret_like_content"
UNCITED_DOCUMENT_CLAIM = "uncited_document_claim"

SECRET_PATTERNS = (
    re.compile(
        r"(?i)(api[_-]?key|secret(?:[_-]?(?:access|key|token|password|credential|cred))*|token|password)\s*="
    ),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def evaluate_memory_write(memory: dict[str, Any]) -> dict[str, Any]:
    """Return a no-write guardrail decision for a proposed active memory write."""
    content = str(memory.get("content") or "")
    issues: list[dict[str, str]] = []
    if any(pattern.search(content) for pattern in SECRET_PATTERNS):
        issues.append(
            {
                "code": SECRET_LIKE_CONTENT,
                "severity": "blocker",
                "message": "Secret-like content must not be stored as active memory.",
            }
        )
    if str(memory.get("memory_type") or "").strip() == "document_claim" and not memory.get("citations"):
        issues.append(
            {
                "code": UNCITED_DOCUMENT_CLAIM,
                "severity": "review",
                "message": "Document claims require citations or an explicit review path.",
            }
        )

    severities = [issue["severity"] for issue in issues]
    decision = "allow"
    if "blocker" in severities:
        decision = "block"
    elif severities:
        decision = "require_review"
    highest_severity = "blocker" if "blocker" in severities else ("review" if severities else "none")
    return {
        "schema_version": MEMORY_GUARDRAIL_SCHEMA_VERSION,
        "decision": decision,
        "highest_severity": highest_severity,
        "issue_codes": [issue["code"] for issue in issues],
        "issues": issues,
        "write_performed": False,
        "active_memory_write_performed": False,
    }


def store_memory_guardrail_receipt(
    ledger: MemoryOSLedger,
    *,
    memory: dict[str, Any],
    guardrail: dict[str, Any],
    firewall_event_id: str | None = None,
    reviewed_by: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a redacted receipt for a non-allow memory guardrail decision."""
    normalized_key = str(memory.get("key") or "").strip()
    content = str(memory.get("content") or "")
    issue_codes = [str(code) for code in guardrail.get("issue_codes") or [] if str(code).strip()]
    content_hash = hash_payload(content)
    safe_context = _safe_context(context)
    receipt_id = stable_id(
        "memory_guardrail",
        {
            "key": normalized_key,
            "content_hash": content_hash,
            "decision": guardrail.get("decision"),
            "issue_codes": issue_codes,
            "context": safe_context,
        },
    )
    receipt = {
        "schema_version": MEMORY_GUARDRAIL_SCHEMA_VERSION,
        "receipt_id": receipt_id,
        "decision": guardrail.get("decision") or "allow",
        "highest_severity": guardrail.get("highest_severity") or "none",
        "issue_codes": issue_codes,
        "issues": _redacted_issues(guardrail.get("issues")),
        "affected_ref": {"kind": "memory", "key": normalized_key},
        "content_hash": content_hash,
        "metadata_hash": hash_payload(_metadata_fingerprint(memory)),
        "context_hash": hash_payload(safe_context),
        "created_at": now_iso(),
        "write_performed": True,
        "active_memory_write_performed": False,
    }
    if safe_context:
        receipt.update(safe_context)
    if firewall_event_id:
        receipt["firewall_event_id"] = firewall_event_id
    reviewer = str(reviewed_by or "").strip()
    if reviewer:
        receipt["reviewed_by"] = reviewer
    if SECRET_LIKE_CONTENT not in issue_codes:
        excerpt = _safe_excerpt(content)
        if excerpt:
            receipt["content_excerpt"] = excerpt
    upsert_record(ledger, "memory_guardrail_receipts", receipt_id, receipt)
    return receipt


def _metadata_fingerprint(memory: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": str(memory.get("key") or "").strip(),
        "memory_type": memory.get("memory_type"),
        "scope": memory.get("scope"),
        "trust_state": memory.get("trust_state"),
        "status": memory.get("status"),
        "project": memory.get("project"),
        "domain": memory.get("domain"),
        "citations_hash": hash_payload(memory.get("citations") or []),
    }


def _safe_context(context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(context, dict):
        return {}
    safe: dict[str, Any] = {}
    for field in (
        "operation_kind",
        "operation_index",
        "transaction_id",
        "knowledge_pr_id",
        "draft_id",
        "source",
    ):
        value = context.get(field)
        if value is None:
            continue
        if field == "operation_index":
            try:
                safe[field] = int(value)
            except (TypeError, ValueError):
                continue
        else:
            text = str(value).strip()
            if text:
                safe[field] = text
    return safe


def _redacted_issues(value: Any) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not isinstance(value, list):
        return issues
    for issue in value:
        if not isinstance(issue, dict):
            continue
        issues.append(
            {
                "code": str(issue.get("code") or "").strip(),
                "severity": str(issue.get("severity") or "").strip(),
                "message": str(issue.get("message") or "").strip(),
            }
        )
    return [issue for issue in issues if issue["code"]]


def _safe_excerpt(content: str) -> str:
    excerpt = " ".join(str(content or "").split())
    if len(excerpt) <= MAX_NON_SECRET_EXCERPT_CHARS:
        return excerpt
    return excerpt[:MAX_NON_SECRET_EXCERPT_CHARS].rstrip()
