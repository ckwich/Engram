"""Review-first graph proposal pipeline for Memory OS records."""
from __future__ import annotations

import re
from typing import Any

from core.memory_os._records import (
    hash_payload,
    list_records,
    now_iso,
    stable_id,
    upsert_record,
)
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.project_identity import resolve_project_filter_values
from core.memory_os.schema import GRAPH_EDGE_TYPES


GRAPH_READINESS_SCHEMA_VERSION = "2026-05-14.graph-readiness.v1"
GRAPH_PROPOSAL_BATCH_SCHEMA_VERSION = "2026-05-14.graph-proposal-batch.v1"
GRAPH_PROPOSAL_APPLY_SCHEMA_VERSION = "2026-05-14.graph-proposal-apply.v1"
GRAPHABLE_MEMORY_STATUSES = {"active", "accepted", "reviewed"}
SUPPORTED_SCOPES = {"memory_os"}


class GraphProposalPipeline:
    """Prepare and promote evidence-backed graph proposals without surprise writes."""

    def __init__(self, ledger: MemoryOSLedger, runtime: Any) -> None:
        self.ledger = ledger
        self.runtime = runtime

    def prepare_graph_readiness_report(
        self,
        *,
        scope: str = "memory_os",
        project: str | None = None,
        exact_project_match: bool = False,
        domain: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return graphability inventory without reading full source bodies."""
        normalized_scope = _optional_text(scope) or "memory_os"
        if normalized_scope not in SUPPORTED_SCOPES:
            issue = _issue("unsupported_scope", f"graph pipeline scope is not supported yet: {normalized_scope}")
            return _readiness_response(
                scope=normalized_scope,
                status="partial",
                inventory=_empty_inventory(),
                eligible_sources=[],
                blocking_issues=[issue],
            )

        project_values = resolve_project_filter_values(
            self.ledger,
            project,
            exact=exact_project_match,
        )
        memories = _filter_project_domain(
            list_records(self.ledger, "memories"),
            project=project,
            project_values=project_values,
            domain=domain,
        )
        documents = _filter_project_domain(
            list_records(self.ledger, "documents"),
            project=project,
            project_values=project_values,
            domain=domain,
        )
        chunks = _filter_project_domain(
            list_records(self.ledger, "chunks"),
            project=project,
            project_values=project_values,
            domain=domain,
        )
        graph_edges = list_records(self.ledger, "graph_edges")
        entities = list_records(self.ledger, "entities")
        concepts = list_records(self.ledger, "concepts")
        aliases = list_records(self.ledger, "aliases")

        eligible_memories = [
            memory
            for memory in memories
            if str(memory.get("status") or "active").strip().lower() in GRAPHABLE_MEMORY_STATUSES
        ]
        usable_documents = [document for document in documents if _document_is_usable(document)]
        staged_documents = [document for document in documents if not _document_is_usable(document)]
        eligible_sources = [
            _memory_source_summary(memory)
            for memory in sorted(eligible_memories, key=lambda item: str(item.get("updated_at") or item.get("key") or ""))
        ]
        eligible_sources.extend(
            _document_source_summary(document)
            for document in sorted(usable_documents, key=lambda item: str(item.get("updated_at") or item.get("document_id") or ""))
        )
        bounded_limit = _bounded_limit(limit)
        blocking_issues: list[dict[str, Any]] = []
        if staged_documents:
            blocking_issues.append(
                _issue(
                    "staged_documents_excluded",
                    "Staged documents are excluded until complete_document_ingestion marks them usable.",
                    count=len(staged_documents),
                )
            )
        if not eligible_sources:
            blocking_issues.append(
                _issue("no_eligible_sources", "No graphable Memory OS memories or usable documents matched the request.")
            )

        inventory = {
            "memory_count": len(memories),
            "eligible_memory_count": len(eligible_memories),
            "document_count": len(documents),
            "usable_document_count": len(usable_documents),
            "staged_document_count": len(staged_documents),
            "chunk_count": len(chunks),
            "graph_edge_count": len(graph_edges),
            "entity_count": len(entities),
            "concept_count": len(concepts),
            "alias_count": len(aliases),
        }
        return _readiness_response(
            scope=normalized_scope,
            status="partial" if blocking_issues else "ok",
            inventory=inventory,
            eligible_sources=eligible_sources[:bounded_limit],
            blocking_issues=blocking_issues,
        )

    def prepare_graph_proposal_batch(
        self,
        *,
        scope: str = "memory_os",
        project: str | None = None,
        domain: str | None = None,
        source_refs: list[dict[str, Any]] | None = None,
        limit: int = 10,
        budget_chars: int = 12_000,
        candidate_graph_edges: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Prepare bounded evidence context and optionally validate candidate edges."""
        normalized_scope = _optional_text(scope) or "memory_os"
        if normalized_scope not in SUPPORTED_SCOPES:
            issue = _issue("unsupported_scope", f"graph pipeline scope is not supported yet: {normalized_scope}")
            return _proposal_response(
                scope=normalized_scope,
                source_items=[],
                validated_edges=[],
                blocking_issues=[issue],
                candidate_count=len(candidate_graph_edges or []),
            )

        selected_refs = self._select_source_refs(
            project=project,
            domain=domain,
            source_refs=source_refs,
            limit=limit,
        )
        source_items = self._build_source_items(selected_refs, budget_chars=max(int(budget_chars), 0))
        blocking_issues: list[dict[str, Any]] = []
        if not source_items:
            blocking_issues.append(_issue("no_source_items", "No graphable source items were available for the batch."))

        validation = self._validate_candidate_edges(candidate_graph_edges or [], source_items)
        blocking_issues.extend(validation["blocking_issues"])
        candidate_count = len(candidate_graph_edges or [])
        ready_to_promote = bool(candidate_count and validation["valid_edges"] and not blocking_issues)
        status = "ok" if (source_items and (not candidate_count or ready_to_promote)) else "partial"
        return _proposal_response(
            scope=normalized_scope,
            source_items=source_items,
            validated_edges=validation["valid_edges"],
            blocking_issues=blocking_issues,
            candidate_count=candidate_count,
            status=status,
            ready_to_promote=ready_to_promote,
            warnings=validation["warnings"],
        )

    def apply_graph_proposal_batch(
        self,
        *,
        scope: str = "memory_os",
        project: str | None = None,
        domain: str | None = None,
        source_refs: list[dict[str, Any]] | None = None,
        candidate_graph_edges: list[dict[str, Any]] | None = None,
        accept: bool = False,
        approved_by: str | None = None,
        limit: int = 10,
        budget_chars: int = 12_000,
    ) -> dict[str, Any]:
        """Promote reviewed graph proposal edges after explicit acceptance."""
        if not accept:
            return _apply_error(
                "policy_denied",
                "accept_required",
                "apply_graph_proposal_batch requires accept=True.",
                category="policy",
            )
        reviewer = _optional_text(approved_by)
        if not reviewer:
            return _apply_error(
                "schema_failed",
                "approved_by_required",
                "approved_by is required when accept=True.",
            )
        preliminary_edges = [
            _normalized_candidate_edge(candidate)
            for candidate in candidate_graph_edges or []
            if isinstance(candidate, dict)
        ]
        preliminary_idempotency_key = _apply_idempotency_key(
            reviewer=reviewer,
            edges=preliminary_edges,
            source_refs=source_refs or [],
        )
        existing_result = _existing_transaction_result(self.ledger, preliminary_idempotency_key)
        if existing_result is not None:
            replay = dict(existing_result)
            replay["idempotent_replay"] = True
            replay["write_performed"] = False
            replay["graph_write_performed"] = False
            receipt = dict(replay.get("transaction_receipt") or {})
            if receipt:
                receipt["idempotent_replay"] = True
            replay["transaction_receipt"] = receipt
            return replay

        prepared = self.prepare_graph_proposal_batch(
            scope=scope,
            project=project,
            domain=domain,
            source_refs=source_refs,
            limit=limit,
            budget_chars=budget_chars,
            candidate_graph_edges=candidate_graph_edges,
        )
        if prepared["proposal_validation"]["ready_to_promote"] is not True:
            return {
                **_apply_error(
                    "schema_failed",
                    "graph_proposal_batch_not_ready",
                    "Graph proposal batch is not ready for promotion.",
                ),
                "prepared_batch": prepared,
            }

        timestamp = now_iso()
        edges = []
        concept_writes: list[dict[str, Any]] = []
        entity_writes: list[dict[str, Any]] = []
        for edge in prepared["validated_edges"]:
            promoted = dict(edge)
            promoted["status"] = "active"
            promoted["created_by"] = reviewer
            promoted["created_at"] = edge.get("created_at") or timestamp
            promoted["updated_at"] = timestamp
            promoted["source"] = "graph_proposal_batch"
            edges.append(promoted)
            for ref in (promoted["from_ref"], promoted["to_ref"]):
                if ref.get("kind") == "concept":
                    concept_writes.append(_concept_record(ref, reviewer=reviewer, timestamp=timestamp))
                if ref.get("kind") == "entity":
                    entity_writes.append(_entity_record(ref, reviewer=reviewer, timestamp=timestamp))

        for concept in concept_writes:
            upsert_record(self.ledger, "concepts", concept["concept_id"], concept)
        for entity in entity_writes:
            upsert_record(self.ledger, "entities", entity["entity_id"], entity)
        self.runtime.graph.import_edges(edges)

        proposed_writes = [
            {"table": "graph_edges", "id": edge["edge_id"]}
            for edge in edges
        ]
        proposed_writes.extend({"table": "concepts", "id": concept["concept_id"]} for concept in concept_writes)
        proposed_writes.extend({"table": "entities", "id": entity["entity_id"]} for entity in entity_writes)
        idempotency_key = _apply_idempotency_key(
            reviewer=reviewer,
            edges=edges,
            source_refs=source_refs or [],
        )
        receipt = self.runtime.transactions.promote(
            operation_kind="apply_graph_proposal_batch",
            proposed_writes=proposed_writes,
            idempotency_key=idempotency_key,
            affected_refs=[
                {"kind": "graph_edge", "edge_id": edge["edge_id"]}
                for edge in edges
            ],
        )
        result = {
            "schema_version": GRAPH_PROPOSAL_APPLY_SCHEMA_VERSION,
            "status": "ok",
            "scope": scope,
            "approved_by": reviewer,
            "proposal_batch_id": prepared["proposal_batch_id"],
            "transaction_id": receipt["transaction_id"],
            "idempotency_key": idempotency_key,
            "idempotent_replay": bool(receipt.get("idempotent_replay", False)),
            "graph_edges_written": [edge["edge_id"] for edge in edges],
            "concepts_written": [concept["concept_id"] for concept in concept_writes],
            "entities_written": [entity["entity_id"] for entity in entity_writes],
            "validated_edges": edges,
            "transaction_receipt": receipt,
            "write_performed": True,
            "active_memory_write_performed": False,
            "graph_write_performed": bool(edges),
            "error": None,
            "errors": [],
        }
        upsert_record(self.ledger, "transactions", receipt["transaction_id"], result)
        return result

    def _select_source_refs(
        self,
        *,
        project: str | None,
        domain: str | None,
        source_refs: list[dict[str, Any]] | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if isinstance(source_refs, list) and source_refs:
            return [dict(ref) for ref in source_refs if isinstance(ref, dict)][: _bounded_limit(limit)]
        report = self.prepare_graph_readiness_report(project=project, domain=domain, limit=limit)
        return [dict(item["ref"]) for item in report.get("eligible_sources") or [] if isinstance(item.get("ref"), dict)]

    def _build_source_items(self, source_refs: list[dict[str, Any]], *, budget_chars: int) -> list[dict[str, Any]]:
        remaining = budget_chars
        items: list[dict[str, Any]] = []
        for ref in source_refs:
            item = self._source_item(ref, remaining)
            if item is None:
                continue
            items.append(item)
            remaining = max(0, remaining - len(item.get("evidence_excerpt") or ""))
        return items

    def _source_item(self, ref: dict[str, Any], budget_chars: int) -> dict[str, Any] | None:
        normalized = _normalize_ref(ref)
        if normalized.get("kind") == "memory":
            key = normalized.get("key")
            memory = _record_by_field(self.ledger, "memories", "key", key)
            if memory is None:
                return None
            chunks = [
                chunk
                for chunk in list_records(self.ledger, "chunks")
                if chunk.get("memory_key") == key
            ]
            text = "\n\n".join(str(chunk.get("text") or "") for chunk in chunks)
            excerpt = _bounded_text(text, budget_chars)
            citations = [
                {
                    "level": "chunk",
                    "key": key,
                    "chunk_id": chunk.get("chunk_id"),
                    "chunk_record_id": chunk.get("chunk_record_id"),
                }
                for chunk in chunks[:3]
            ]
            return {
                "ref": {"kind": "memory", "key": key},
                "title": memory.get("title") or key,
                "project": memory.get("project"),
                "domain": memory.get("domain"),
                "status": memory.get("status") or "active",
                "evidence_excerpt": excerpt,
                "citations": citations,
                "chunk_count": len(chunks),
            }
        if normalized.get("kind") == "document":
            document_id = normalized.get("document_id")
            document = _record_by_field(self.ledger, "documents", "document_id", document_id)
            if document is None or not _document_is_usable(document):
                return None
            chunks = [
                chunk
                for chunk in list_records(self.ledger, "chunks")
                if chunk.get("document_id") == document_id
            ]
            text = "\n\n".join(str(chunk.get("text") or "") for chunk in chunks)
            citations = [
                {
                    "level": "chunk",
                    "document_id": document_id,
                    "chunk_id": chunk.get("chunk_id"),
                    "chunk_record_id": chunk.get("chunk_record_id"),
                }
                for chunk in chunks[:3]
            ]
            return {
                "ref": {"kind": "document", "document_id": document_id},
                "title": document.get("title") or document_id,
                "project": document.get("project"),
                "domain": document.get("domain"),
                "status": document.get("ingestion_status") or "usable",
                "evidence_excerpt": _bounded_text(text, budget_chars),
                "citations": citations,
                "chunk_count": len(chunks),
            }
        return None

    def _validate_candidate_edges(
        self,
        candidate_edges: list[dict[str, Any]],
        source_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        valid_edges: list[dict[str, Any]] = []
        blocking_issues: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        if not candidate_edges:
            return {"valid_edges": [], "blocking_issues": [], "warnings": []}
        source_ref_keys = {_ref_key(item["ref"]) for item in source_items}
        existing_edge_keys = {
            _edge_key(edge)
            for edge in list_records(self.ledger, "graph_edges")
        }
        for index, candidate in enumerate(candidate_edges):
            issues = self._candidate_issues(candidate, source_ref_keys, existing_edge_keys, index=index)
            if issues:
                blocking_issues.extend(issues)
                continue
            edge = _normalized_candidate_edge(candidate)
            valid_edges.append(edge)
            if _edge_key(edge) in existing_edge_keys:
                warnings.append(_issue("duplicate_edge", "An equivalent graph edge already exists.", index=index))
        return {"valid_edges": valid_edges, "blocking_issues": blocking_issues, "warnings": warnings}

    def _candidate_issues(
        self,
        candidate: dict[str, Any],
        source_ref_keys: set[str],
        existing_edge_keys: set[tuple[str, str, str]],
        *,
        index: int,
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        if not isinstance(candidate, dict):
            return [_issue("edge_required", "candidate graph edge must be an object.", index=index)]
        from_ref = _normalize_ref(candidate.get("from_ref"))
        to_ref = _normalize_ref(candidate.get("to_ref"))
        if not from_ref:
            issues.append(_issue("edge_from_ref_required", "candidate graph edge requires from_ref.", index=index))
        if not to_ref:
            issues.append(_issue("edge_to_ref_required", "candidate graph edge requires to_ref.", index=index))
        edge_type = _optional_text(candidate.get("edge_type"))
        if edge_type not in GRAPH_EDGE_TYPES:
            issues.append(_issue("unsupported_edge_type", "candidate graph edge has an unsupported edge_type.", index=index))
        if not _optional_text(candidate.get("evidence")):
            issues.append(_issue("edge_evidence_required", "candidate graph edge requires evidence.", index=index))
        evidence_refs = candidate.get("evidence_refs")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            issues.append(_issue("edge_evidence_refs_required", "candidate graph edge requires evidence_refs.", index=index))
        elif not any(_ref_key(_normalize_ref(ref)) in source_ref_keys for ref in evidence_refs if isinstance(ref, dict)):
            issues.append(
                _issue(
                    "edge_evidence_ref_not_in_batch",
                    "candidate graph edge must cite at least one source in the proposal batch.",
                    index=index,
                )
            )
        for ref, field in ((from_ref, "from_ref"), (to_ref, "to_ref")):
            if ref and ref.get("kind") in {"memory", "document", "chunk"} and not self._ref_exists(ref):
                issues.append(_issue(f"edge_{field}_missing", f"candidate graph edge {field} does not exist.", index=index))
        if not issues:
            edge = _normalized_candidate_edge(candidate)
            if _edge_key(edge) in existing_edge_keys:
                issues.append(_issue("duplicate_edge", "An equivalent active graph edge already exists.", index=index))
        return issues

    def _ref_exists(self, ref: dict[str, Any]) -> bool:
        kind = ref.get("kind")
        if kind == "memory":
            return _record_by_field(self.ledger, "memories", "key", ref.get("key")) is not None
        if kind == "document":
            document = _record_by_field(self.ledger, "documents", "document_id", ref.get("document_id"))
            return document is not None and _document_is_usable(document)
        if kind == "chunk":
            return any(_ref_matches_chunk(ref, chunk) for chunk in list_records(self.ledger, "chunks"))
        return True


def _readiness_response(
    *,
    scope: str,
    status: str,
    inventory: dict[str, Any],
    eligible_sources: list[dict[str, Any]],
    blocking_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": GRAPH_READINESS_SCHEMA_VERSION,
        "status": status,
        "scope": scope,
        "inventory": inventory,
        "eligible_source_count": len(eligible_sources),
        "eligible_sources": eligible_sources,
        "blocking_issues": blocking_issues,
        "policy": _policy(),
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "error": None if status == "ok" else {"code": "graph_readiness_partial", "category": "validation"},
    }


def _proposal_response(
    *,
    scope: str,
    source_items: list[dict[str, Any]],
    validated_edges: list[dict[str, Any]],
    blocking_issues: list[dict[str, Any]],
    candidate_count: int,
    status: str = "partial",
    ready_to_promote: bool = False,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": GRAPH_PROPOSAL_BATCH_SCHEMA_VERSION,
        "status": status,
        "scope": scope,
        "proposal_batch_id": stable_id(
            "graph_batch",
            {
                "scope": scope,
                "source_refs": [item.get("ref") for item in source_items],
                "validated_edges": [edge.get("edge_id") for edge in validated_edges],
            },
        ),
        "source_count": len(source_items),
        "source_items": source_items,
        "proposal_schema": {
            "required_edge_fields": ["from_ref", "to_ref", "edge_type", "evidence", "evidence_refs"],
            "allowed_edge_types": list(GRAPH_EDGE_TYPES),
            "supported_ref_kinds": ["memory", "document", "chunk", "concept", "entity", "claim"],
        },
        "proposal_validation": {
            "candidate_count": candidate_count,
            "valid_count": len(validated_edges),
            "invalid_count": max(candidate_count - len(validated_edges), 0),
            "ready_to_promote": ready_to_promote,
        },
        "validated_edges": validated_edges,
        "blocking_issues": blocking_issues,
        "warnings": warnings or [],
        "policy": _policy(),
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "error": None if status == "ok" else {"code": "graph_proposal_batch_partial", "category": "validation"},
    }
    return payload


def _apply_error(status: str, code: str, message: str, *, category: str = "schema") -> dict[str, Any]:
    error = {"code": code, "category": category, "message": message}
    return {
        "schema_version": GRAPH_PROPOSAL_APPLY_SCHEMA_VERSION,
        "status": status,
        "graph_edges_written": [],
        "concepts_written": [],
        "entities_written": [],
        "validated_edges": [],
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "error": error,
        "errors": [error],
    }


def _policy() -> dict[str, Any]:
    return {
        "write_behavior": "read_only",
        "review_required": True,
        "promotion_requires_acceptance": True,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "reviewed_source_semantics": (
            "Memory OS memory records are graphable when their lifecycle status is active, accepted, or reviewed; "
            "documents are graphable only after complete_document_ingestion marks them usable."
        ),
    }


def _empty_inventory() -> dict[str, int]:
    return {
        "memory_count": 0,
        "eligible_memory_count": 0,
        "document_count": 0,
        "usable_document_count": 0,
        "staged_document_count": 0,
        "chunk_count": 0,
        "graph_edge_count": 0,
        "entity_count": 0,
        "concept_count": 0,
        "alias_count": 0,
    }


def _filter_project_domain(
    records: list[dict[str, Any]],
    *,
    project: str | None,
    project_values: list[str] | None = None,
    domain: str | None,
) -> list[dict[str, Any]]:
    project_text = _optional_text(project)
    project_value_set = set(project_values or [])
    domain_text = _optional_text(domain)
    filtered = []
    for record in records:
        if project_text and record.get("project") not in project_value_set:
            continue
        if domain_text and record.get("domain") != domain_text:
            continue
        filtered.append(record)
    return filtered


def _memory_source_summary(memory: dict[str, Any]) -> dict[str, Any]:
    key = str(memory.get("key") or "")
    return {
        "ref": {"kind": "memory", "key": key},
        "title": memory.get("title") or key,
        "project": memory.get("project"),
        "domain": memory.get("domain"),
        "status": memory.get("status") or "active",
        "chunk_count": int(memory.get("chunk_count") or 0),
        "updated_at": memory.get("updated_at"),
    }


def _document_source_summary(document: dict[str, Any]) -> dict[str, Any]:
    document_id = str(document.get("document_id") or "")
    return {
        "ref": {"kind": "document", "document_id": document_id},
        "title": document.get("title") or document_id,
        "project": document.get("project"),
        "domain": document.get("domain"),
        "status": document.get("ingestion_status") or "usable",
        "chunk_count": int(document.get("chunk_count") or 0),
        "updated_at": document.get("updated_at"),
    }


def _document_is_usable(document: dict[str, Any]) -> bool:
    return bool(
        document.get("usable") is True
        or document.get("ingestion_status") == "usable"
        or document.get("completion_artifact_id")
    )


def _normalize_ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    kind = _optional_text(value.get("kind"))
    if not kind:
        return {}
    if kind == "memory":
        key = _optional_text(value.get("key") or value.get("memory_key"))
        return {"kind": "memory", "key": key} if key else {}
    if kind == "document":
        document_id = _optional_text(value.get("document_id") or value.get("id"))
        return {"kind": "document", "document_id": document_id} if document_id else {}
    if kind == "chunk":
        ref = {"kind": "chunk"}
        for field in ("chunk_record_id", "memory_key", "key", "document_id", "chunk_id"):
            if value.get(field) is not None:
                ref[field] = value[field]
        return ref if len(ref) > 1 else {}
    if kind == "concept":
        name = _optional_text(value.get("name") or value.get("label") or value.get("id"))
        concept_id = _optional_text(value.get("id")) or (f"concept:{_slugify(name)}" if name else None)
        return {"kind": "concept", "id": concept_id, "name": name or concept_id} if concept_id else {}
    if kind == "entity":
        name = _optional_text(value.get("name") or value.get("label") or value.get("id"))
        entity_id = _optional_text(value.get("id")) or (f"entity:{_slugify(name)}" if name else None)
        return {"kind": "entity", "id": entity_id, "name": name or entity_id} if entity_id else {}
    if kind == "claim":
        claim_id = _optional_text(value.get("id") or value.get("claim_id"))
        text = _optional_text(value.get("text") or value.get("name"))
        if not claim_id and text:
            claim_id = f"claim:{_slugify(text)[:80]}"
        return {"kind": "claim", "id": claim_id, "text": text} if claim_id else {}
    normalized = {key: item for key, item in value.items() if item is not None}
    normalized["kind"] = kind
    return normalized


def _normalized_candidate_edge(candidate: dict[str, Any]) -> dict[str, Any]:
    from_ref = _normalize_ref(candidate.get("from_ref"))
    to_ref = _normalize_ref(candidate.get("to_ref"))
    edge_type = _optional_text(candidate.get("edge_type")) or "related_to"
    evidence = _optional_text(candidate.get("evidence")) or ""
    confidence = _confidence(candidate.get("confidence"))
    edge_id = _optional_text(candidate.get("edge_id")) or _edge_id(from_ref, edge_type, to_ref, evidence)
    timestamp = now_iso()
    return {
        "edge_id": edge_id,
        "from_ref": from_ref,
        "to_ref": to_ref,
        "edge_type": edge_type,
        "confidence": confidence,
        "evidence": evidence,
        "evidence_refs": [_normalize_ref(ref) for ref in candidate.get("evidence_refs") or [] if _normalize_ref(ref)],
        "source": _optional_text(candidate.get("source")) or "graph_proposal_batch",
        "status": _optional_text(candidate.get("status")) or "candidate",
        "created_by": _optional_text(candidate.get("created_by")) or "graph_proposal_pipeline",
        "created_at": _optional_text(candidate.get("created_at")) or timestamp,
        "updated_at": timestamp,
    }


def _edge_id(from_ref: dict[str, Any], edge_type: str, to_ref: dict[str, Any], evidence: str) -> str:
    left = _slugify(_ref_label(from_ref))
    right = _slugify(_ref_label(to_ref))
    fingerprint = stable_id(
        "edge",
        {"from_ref": from_ref, "to_ref": to_ref, "edge_type": edge_type, "evidence": evidence},
    ).split(":", 1)[1][:10]
    return f"edge:{left}:{edge_type}:{right}:{fingerprint}"


def _edge_key(edge: dict[str, Any]) -> tuple[str, str, str]:
    return (
        hash_payload(edge.get("from_ref") or {}),
        str(edge.get("edge_type") or ""),
        hash_payload(edge.get("to_ref") or {}),
    )


def _record_by_field(ledger: MemoryOSLedger, table: str, field: str, value: Any) -> dict[str, Any] | None:
    for record in list_records(ledger, table):
        if record.get(field) == value:
            return record
    return None


def _ref_matches_chunk(ref: dict[str, Any], chunk: dict[str, Any]) -> bool:
    if ref.get("chunk_record_id"):
        return chunk.get("chunk_record_id") == ref.get("chunk_record_id")
    if ref.get("memory_key") or ref.get("key"):
        if chunk.get("memory_key") != (ref.get("memory_key") or ref.get("key")):
            return False
    if ref.get("document_id") and chunk.get("document_id") != ref.get("document_id"):
        return False
    if ref.get("chunk_id") is not None and str(chunk.get("chunk_id")) != str(ref.get("chunk_id")):
        return False
    return True


def _concept_record(ref: dict[str, Any], *, reviewer: str, timestamp: str) -> dict[str, Any]:
    return {
        "concept_id": ref["id"],
        "name": ref.get("name") or ref["id"],
        "slug": _slugify(ref.get("name") or ref["id"]),
        "status": "active",
        "created_by": reviewer,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def _entity_record(ref: dict[str, Any], *, reviewer: str, timestamp: str) -> dict[str, Any]:
    return {
        "entity_id": ref["id"],
        "name": ref.get("name") or ref["id"],
        "slug": _slugify(ref.get("name") or ref["id"]),
        "status": "active",
        "created_by": reviewer,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def _apply_idempotency_key(*, reviewer: str, edges: list[dict[str, Any]], source_refs: list[dict[str, Any]]) -> str:
    return stable_id(
        "apply_graph_proposal_batch",
        {
            "approved_by": reviewer,
            "edge_ids": [edge.get("edge_id") for edge in edges],
            "source_refs": source_refs,
        },
    )


def _existing_transaction_result(ledger: MemoryOSLedger, idempotency_key: str) -> dict[str, Any] | None:
    if not idempotency_key:
        return None
    for record in list_records(ledger, "transactions"):
        if record.get("idempotency_key") == idempotency_key and record.get("status") == "ok":
            return record
    return None


def _ref_key(ref: dict[str, Any]) -> str:
    return hash_payload(ref)


def _ref_label(ref: dict[str, Any]) -> str:
    if ref.get("kind") == "memory":
        return str(ref.get("key") or "memory")
    if ref.get("kind") == "document":
        return str(ref.get("document_id") or "document")
    if ref.get("kind") in {"concept", "entity"}:
        return str(ref.get("name") or ref.get("id") or ref.get("kind"))
    if ref.get("kind") == "claim":
        return str(ref.get("text") or ref.get("id") or "claim")
    return str(ref.get("id") or ref.get("kind") or "ref")


def _bounded_text(text: str, budget_chars: int) -> str:
    if budget_chars <= 0:
        return ""
    if len(text) <= budget_chars:
        return text
    return text[: max(budget_chars - 1, 0)].rstrip()


def _bounded_limit(value: int) -> int:
    return max(1, min(int(value or 1), 100))


def _confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.5
    return max(0.0, min(confidence, 1.0))


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _slugify(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "ref"


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "message": message}
    issue.update(extra)
    return issue
