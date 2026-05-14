"""Daemon-owned Memory OS service container."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from core.chunker import chunk_content_with_metadata
from core.memory_os._records import (
    hash_payload,
    list_records,
    now_iso,
    read_record,
    upsert_record,
)
from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.firewall import MemoryFirewall
from core.memory_os.graph import MemoryOSGraph
from core.memory_os.inspector import build_memory_os_inspector
from core.memory_os.jobs import JobQueue
from core.memory_os.knowledge_artifact_families import (
    SUPPORTED_ARTIFACT_FAMILIES,
    build_artifact_family_packet,
)
from core.memory_os.knowledge_artifacts import KnowledgeArtifactStore
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.knowledge_audit import build_evidence_audit
from core.memory_os.knowledge_citations import normalize_knowledge_citations
from core.memory_os.knowledge_contract import (
    RESPONSE_SCHEMA_VERSION,
    no_answer_response,
    normalize_knowledge_request,
    ok_response,
)
from core.memory_os.knowledge_graph import build_graph_evidence
from core.memory_os.knowledge_orientations import (
    build_document_orientation,
    build_source_orientation,
)
from core.memory_os.knowledge_planner import build_planner_receipt
from core.memory_os.knowledge_review import build_review_preparation
from core.memory_os.project_capsule_artifact import build_project_capsule_artifact
from core.memory_os.retrieval import MemoryOSRetrievalIndex
from core.memory_os.snapshots import SnapshotService
from core.memory_os.transactions import MemoryTransactionService


class MemoryOSRuntime:
    """Container for daemon-owned Memory OS stores, indexes, and services."""

    def __init__(
        self,
        root: str | Path,
        *,
        embed_text: Callable[[str], list[float]] | None = None,
        vector_index: Any | None = None,
        graph_store: Any | None = None,
    ) -> None:
        self.root = Path(root)
        self.ledger = MemoryOSLedger(self.root / "ledger.sqlite3")
        self.content_store = ContentAddressedStore(self.root / "objects")
        self.jobs = JobQueue(self.ledger)
        self.transactions = MemoryTransactionService(self.ledger)
        self.snapshots = SnapshotService(self.ledger)
        self.firewall = MemoryFirewall(self.ledger)
        self.retrieval = MemoryOSRetrievalIndex(
            self.ledger,
            self.root / "lance",
            embed_text=embed_text or _default_embed_text,
            vector_index=vector_index,
        )
        self.graph = MemoryOSGraph(
            self.ledger,
            graph_store=graph_store,
            database_path=self.root / "kuzu",
        )
        self.knowledge_artifacts = KnowledgeArtifactStore(self.ledger, self.content_store)

    def initialize(self) -> dict[str, Any]:
        """Initialize durable Memory OS stores and return a status payload."""
        self.ledger.initialize()
        self.content_store.root.mkdir(parents=True, exist_ok=True)
        self.graph.load_edges()
        self.retrieval.rebuild_from_ledger()
        return self.status()

    def status(self) -> dict[str, Any]:
        """Return a compact Memory OS component status."""
        return {
            "status": "ok",
            "root": str(self.root),
            "components": {
                "ledger": {
                    "path": str(self.ledger.path),
                    "exists": self.ledger.path.exists(),
                },
                "content_store": {
                    "path": str(self.content_store.root),
                    "exists": self.content_store.root.exists(),
                },
                "retrieval": {
                    "backend": type(self.retrieval.vector_index).__name__,
                    "path": str(self.root / "lance"),
                },
                "graph": {
                    "backend": type(self.graph.graph_store).__name__,
                    "path": str(self.root / "kuzu"),
                },
                "jobs": {"status": "ready"},
                "transactions": {"status": "ready"},
                "snapshots": {"status": "ready"},
                "firewall": {"status": "ready"},
            },
        }

    def inspector(self, *, limit: int = 20) -> dict[str, Any]:
        """Return a read-only Memory OS inspector payload."""
        return build_memory_os_inspector(self, limit=limit)

    def prepare_source_import_job(
        self,
        *,
        source_ref: dict[str, Any],
        source_type: str,
        connector_id: str = "manual",
    ) -> dict[str, Any]:
        """Create a queued source import job without blocking an MCP process."""
        return self.jobs.enqueue(
            "source_import",
            {
                "source_ref": source_ref,
                "source_type": source_type,
                "connector_id": connector_id,
            },
        )

    def store_memory(
        self,
        *,
        key: str,
        content: str,
        tags: list[str] | None = None,
        title: str | None = None,
        related_to: list[str] | None = None,
        force: bool = False,
        project: str | None = None,
        domain: str | None = None,
        status: str | None = None,
        canonical: bool | None = None,
    ) -> dict[str, Any]:
        """Store one reviewed memory in the Memory OS ledger and retrieval index."""
        normalized_key = _required_text(key, "key")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content is required")
        now = now_iso()
        existing = read_record(self.ledger, "memories", normalized_key)
        if existing and not force:
            # Explicit overwrites are allowed because stable memory writes are updates.
            pass
        normalized_tags = _string_list(tags)
        artifact_id = self.content_store.put_bytes(content.encode("utf-8"), suffix=".md")
        chunks = chunk_content_with_metadata(content)
        memory = {
            "key": normalized_key,
            "title": title or normalized_key,
            "content_artifact_id": artifact_id,
            "tags": normalized_tags,
            "related_to": _string_list(related_to),
            "project": _optional_text(project),
            "domain": _optional_text(domain),
            "status": _optional_text(status) or "active",
            "canonical": bool(canonical) if canonical is not None else False,
            "chars": len(content),
            "lines": len(content.splitlines()),
            "chunk_count": len(chunks),
            "content_hash": hash_payload(content),
            "created_at": existing.get("created_at") if existing else now,
            "updated_at": now,
            "storage_backend": "memory_os",
        }
        self._delete_chunks(normalized_key)
        upsert_record(self.ledger, "memories", normalized_key, memory)
        for chunk in chunks:
            chunk_record = {
                "chunk_record_id": f"{normalized_key}:chunk:{int(chunk['chunk_id'])}",
                "document_id": f"{normalized_key}:chunk:{int(chunk['chunk_id'])}",
                "memory_key": normalized_key,
                "chunk_id": int(chunk["chunk_id"]),
                "chunk_index": int(chunk["chunk_id"]),
                "title": memory["title"],
                "text": str(chunk["text"]),
                "text_hash": hash_payload(str(chunk["text"])),
                "tags": normalized_tags,
                "project": memory["project"],
                "domain": memory["domain"],
                "status": memory["status"],
                "canonical": memory["canonical"],
                "section_title": chunk.get("section_title"),
                "heading_path": list(chunk.get("heading_path") or []),
                "chunk_kind": chunk.get("chunk_kind"),
                "created_at": now,
                "updated_at": now,
            }
            upsert_record(self.ledger, "chunks", chunk_record["chunk_record_id"], chunk_record)
        receipt_fingerprint = hash_payload(
            {
                "content_hash": memory["content_hash"],
                "title": memory["title"],
                "tags": memory["tags"],
                "related_to": memory["related_to"],
                "project": memory["project"],
                "domain": memory["domain"],
                "status": memory["status"],
                "canonical": memory["canonical"],
            }
        )
        receipt = self.transactions.promote(
            operation_kind="store_memory",
            proposed_writes=[{"table": "memories", "id": normalized_key}],
            idempotency_key=f"store_memory:{normalized_key}:{receipt_fingerprint}",
            affected_refs=[{"kind": "memory", "key": normalized_key}],
        )
        self.retrieval.rebuild_from_ledger()
        return {**memory, "transaction_id": receipt["transaction_id"]}

    def check_duplicate(self, key: str, content: str) -> dict[str, Any]:
        """Return duplicate risk for the Memory OS ledger without writing."""
        normalized_key = str(key or "").strip()
        existing = read_record(self.ledger, "memories", normalized_key) if normalized_key else None
        if existing:
            return {
                "key": normalized_key,
                "duplicate": True,
                "match": {
                    "status": "duplicate",
                    "existing_key": normalized_key,
                    "existing_title": existing.get("title") or normalized_key,
                    "score": 1.0,
                },
                "error": None,
            }
        return {"key": normalized_key, "duplicate": False, "match": None, "error": None}

    def search_memories(
        self,
        query: str,
        *,
        limit: int = 5,
        project: str | None = None,
        domain: str | None = None,
        tags: list[str] | None = None,
        include_stale: bool = True,
        canonical_only: bool = False,
        pinned_keys: list[str] | None = None,
        pinned_first: bool = False,
        retrieval_mode: str = "semantic",
    ) -> dict[str, Any]:
        """Search Memory OS chunks through the daemon-owned retrieval index."""
        search_text = _required_text(query, "query")
        filters: dict[str, Any] = {}
        if project:
            filters["project"] = project
        if domain:
            filters["domain"] = domain
        if canonical_only:
            filters["canonical"] = True
        if not include_stale:
            filters["status"] = "active"
        search = (
            self.retrieval.hybrid_search(search_text, filters=filters, limit=max(int(limit), 1))
            if retrieval_mode == "hybrid"
            else self.retrieval.search(search_text, filters=filters, limit=max(int(limit), 1))
        )
        requested_tags = set(_string_list(tags))
        results = [
            _search_result_payload(result)
            for result in search.get("results", [])
            if _result_has_tags(result, requested_tags)
        ]
        if pinned_first and pinned_keys:
            pinned = {str(key) for key in pinned_keys}
            results.sort(key=lambda item: (0 if item["key"] in pinned else 1, -float(item["score"])))
        return {
            "query": search_text,
            "backend": "memory_os",
            "retrieval_mode": search.get("retrieval_mode", retrieval_mode),
            "count": len(results),
            "results": results[: max(int(limit), 1)],
            "error": None,
        }

    def query_knowledge(self, request: dict[str, Any]) -> dict[str, Any]:
        """Return an EKC v0 typed project capsule response without writing memory."""
        normalized = normalize_knowledge_request(request)
        if normalized.get("contract_version") == RESPONSE_SCHEMA_VERSION:
            return normalized

        ask = normalized["ask"]
        if ask["task_type"] == "source_orientation":
            return _orientation_response(
                normalized,
                build_source_orientation(
                    self.ledger,
                    project=ask["project"],
                    focus=ask["focus"],
                    max_records=int(normalized["budget"].get("max_source_reads", 12)),
                ),
                strategy="source_orientation",
            )
        if ask["task_type"] == "document_orientation":
            return _orientation_response(
                normalized,
                build_document_orientation(
                    self.ledger,
                    project=ask["project"],
                    focus=ask["focus"],
                    max_records=int(normalized["budget"].get("max_source_reads", 12)),
                ),
                strategy="document_orientation",
            )
        if ask["task_type"] == "review_preparation":
            return _orientation_response(
                normalized,
                build_review_preparation(
                    self.ledger,
                    project=ask["project"],
                    focus=ask["focus"],
                    max_records=int(normalized["budget"].get("max_source_reads", 12)),
                ),
                strategy="review_preparation",
            )
        if ask["task_type"] == "evidence_audit":
            return _orientation_response(
                normalized,
                build_evidence_audit(
                    self.ledger,
                    project=ask["project"],
                    focus=ask["focus"],
                    max_records=int(normalized["budget"].get("max_source_reads", 12)),
                ),
                strategy="evidence_audit",
            )
        if ask["task_type"] == "graph_evidence":
            return _orientation_response(
                normalized,
                build_graph_evidence(
                    self.ledger,
                    project=ask["project"],
                    focus=ask["focus"],
                    max_records=int(normalized["budget"].get("max_source_reads", 12)),
                ),
                strategy="graph_evidence",
            )
        if ask["task_type"] in SUPPORTED_ARTIFACT_FAMILIES:
            return _orientation_response(
                normalized,
                build_artifact_family_packet(
                    self.ledger,
                    artifact_family=ask["task_type"],
                    project=ask["project"],
                    focus=ask["focus"],
                    max_records=int(normalized["budget"].get("max_source_reads", 12)),
                ),
                strategy=ask["task_type"],
            )
        persisted = self.knowledge_artifacts.read_latest_artifact(
            project=ask["project"],
            artifact_type="project_capsule",
            artifact_version="v0",
            require_fresh=True,
        )
        if persisted is not None:
            return _project_capsule_response(
                normalized,
                artifact_record=persisted,
                planner=build_planner_receipt(
                    strategy="project_capsule",
                    methods_used=["persisted_artifact"],
                    request_budget=normalized["budget"],
                ),
                artifacts_built=0,
                artifacts_read=1,
                source_reads=0,
            )

        built = self._build_project_capsule_artifact(normalized)
        if built.get("response") is not None:
            return built["response"]

        return _project_capsule_response(
            normalized,
            artifact_record={"artifact": built["artifact"]},
            planner=built["planner"],
            artifacts_built=1,
            artifacts_read=0,
            source_reads=len(built["results"]),
        )

    def materialize_project_capsule_artifact(self, request: dict[str, Any]) -> dict[str, Any]:
        """Explicitly persist a project capsule artifact for later read-only EKC serving."""
        normalized = normalize_knowledge_request(request)
        if normalized.get("contract_version") == RESPONSE_SCHEMA_VERSION:
            return {**normalized, "write_performed": False}

        built = self._build_project_capsule_artifact(normalized)
        if built.get("response") is not None:
            return {**built["response"], "write_performed": False}

        artifact_record = self.knowledge_artifacts.store_artifact(
            built["artifact"],
            request_id=normalized["request_id"],
        )
        receipt = self.transactions.promote(
            operation_kind="materialize_knowledge_artifact",
            proposed_writes=[
                {"table": "knowledge_artifacts", "id": artifact_record["artifact_id"]},
            ],
            idempotency_key=f"materialize_knowledge_artifact:{artifact_record['artifact_id']}",
            affected_refs=[
                {
                    "kind": "knowledge_artifact",
                    "artifact_id": artifact_record["artifact_id"],
                    "project": artifact_record["project"],
                },
            ],
        )
        return {
            "status": "ok",
            "write_performed": True,
            "artifact_record": artifact_record,
            "transaction_id": receipt["transaction_id"],
            "error": None,
        }

    def _build_project_capsule_artifact(self, normalized: dict[str, Any]) -> dict[str, Any]:
        budget = normalized["budget"]
        ask = normalized["ask"]
        query = _knowledge_search_query(ask)
        max_source_reads = max(int(budget.get("max_source_reads", 12)), 1)
        search = self.search_memories(
            query,
            limit=max_source_reads * 2,
            project=ask["project"],
            include_stale=False,
            retrieval_mode="hybrid",
        )
        results = _prepare_knowledge_results(
            self.ledger,
            list(search.get("results") or []),
            ask=ask,
            limit=max_source_reads,
        )
        planner = build_planner_receipt(
            strategy="project_capsule",
            methods_used=["artifact", "hybrid_search", "chunk_hydration", "focus_rerank"],
            request_budget=budget,
        )
        if not results:
            return {
                "response": no_answer_response(
                    request_id=normalized["request_id"],
                    code="no_project_sources",
                    message=f"No eligible project sources found for {ask['project']}.",
                    planner=planner,
                )
            }

        context_packet = {
            "profile": {"id": "project_capsule"},
            "context": {
                "chunks": results,
                "citations": [
                    result.get("citation")
                    for result in results
                    if result.get("citation")
                ],
            },
            "warnings": [],
        }
        artifact = build_project_capsule_artifact(
            project=ask["project"],
            goal=ask["goal"],
            focus=ask["focus"],
            context_packet=context_packet,
            quality_payload={"summary": {}, "issue_count": 0},
            source_snapshot_id="memory_os:latest",
        )
        return {"artifact": artifact, "results": results, "planner": planner, "response": None}

    def retrieve_chunk(self, key: str, chunk_id: int) -> dict[str, Any]:
        """Retrieve one Memory OS chunk by memory key and chunk id."""
        normalized_key = _required_text(key, "key")
        record = read_record(self.ledger, "chunks", f"{normalized_key}:chunk:{int(chunk_id)}")
        if record is None:
            return {"key": normalized_key, "chunk_id": int(chunk_id), "found": False, "chunk": None, "error": None}
        return {
            "key": normalized_key,
            "chunk_id": int(chunk_id),
            "found": True,
            "chunk": {
                "title": record.get("title") or normalized_key,
                "text": record.get("text"),
                "section_title": record.get("section_title"),
                "heading_path": record.get("heading_path") or [],
                "chunk_kind": record.get("chunk_kind"),
            },
            "error": None,
        }

    def retrieve_memory(self, key: str) -> dict[str, Any]:
        """Retrieve one full Memory OS memory body from the content store."""
        normalized_key = _required_text(key, "key")
        memory = read_record(self.ledger, "memories", normalized_key)
        if memory is None:
            return {"key": normalized_key, "found": False, "memory": None, "error": None}
        content = self.content_store.read_bytes(str(memory["content_artifact_id"])).decode("utf-8")
        return {
            "key": normalized_key,
            "found": True,
            "memory": {**memory, "content": content},
            "error": None,
        }

    def update_memory_metadata(self, key: str, **changes: Any) -> dict[str, Any]:
        """Update selected Memory OS memory metadata and refresh chunk metadata."""
        normalized_key = _required_text(key, "key")
        current = self.retrieve_memory(normalized_key)
        if not current["found"]:
            return {"key": normalized_key, "updated": False, "memory": None, "error": {"code": "not_found", "message": f"Memory not found: {normalized_key}"}}
        memory = current["memory"]
        updated = self.store_memory(
            key=normalized_key,
            content=str(memory["content"]),
            tags=_string_list(changes["tags"]) if "tags" in changes else memory.get("tags", []),
            title=changes.get("title", memory.get("title")),
            related_to=_string_list(changes["related_to"]) if "related_to" in changes else memory.get("related_to", []),
            force=True,
            project=changes.get("project", memory.get("project")),
            domain=changes.get("domain", memory.get("domain")),
            status=changes.get("status", memory.get("status")),
            canonical=changes.get("canonical", memory.get("canonical")),
        )
        return {"key": normalized_key, "updated": True, "memory": updated, "error": None}

    def repair_memory_metadata(self, keys: list[str], *, dry_run: bool = True) -> dict[str, Any]:
        """Return simple Memory OS metadata repair receipts."""
        repairs = []
        repaired_count = 0
        for key in _string_list(keys):
            exists = read_record(self.ledger, "memories", key) is not None
            repaired = bool(exists and not dry_run)
            repaired_count += 1 if repaired else 0
            repairs.append({"key": key, "exists": exists, "repaired": repaired, "issues": []})
        return {
            "requested_count": len(repairs),
            "repaired_count": repaired_count,
            "dry_run": dry_run,
            "repairs": repairs,
            "error": None,
        }

    def delete_memory(self, key: str) -> dict[str, Any]:
        """Delete one Memory OS memory and its retrieval chunks."""
        normalized_key = _required_text(key, "key")
        existed = read_record(self.ledger, "memories", normalized_key) is not None
        if not existed:
            return {"key": normalized_key, "deleted": False, "error": None}
        self.retrieval.vector_index.delete_by_parent_key(normalized_key)
        self._delete_chunks(normalized_key)
        self._delete_record("memories", normalized_key)
        self.transactions.promote(
            operation_kind="delete_memory",
            proposed_writes=[{"table": "memories", "id": normalized_key, "delete": True}],
            idempotency_key=f"delete_memory:{normalized_key}:{now_iso()}",
            affected_refs=[{"kind": "memory", "key": normalized_key}],
        )
        return {"key": normalized_key, "deleted": True, "error": None}

    def _delete_chunks(self, key: str) -> None:
        for record in list_records(self.ledger, "chunks"):
            if record.get("memory_key") == key and record.get("chunk_record_id"):
                self._delete_record("chunks", str(record["chunk_record_id"]))

    def _delete_record(self, table: str, record_id: str) -> None:
        self.ledger.initialize()
        with self.ledger.connect() as conn:
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))
            conn.commit()


def _knowledge_search_query(ask: dict[str, Any]) -> str:
    parts = [ask.get("goal") or "project orientation", ask.get("project") or ""]
    parts.extend(ask.get("focus") or [])
    return " ".join(str(part).strip() for part in parts if str(part).strip())


def _prepare_knowledge_results(
    ledger: MemoryOSLedger,
    results: list[dict[str, Any]],
    *,
    ask: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    focus_terms = _knowledge_focus_terms(ask)
    hydrated: list[dict[str, Any]] = []
    for result in results:
        item = dict(result)
        key = str(item.get("key") or "")
        chunk_id = int(item.get("chunk_id") or 0)
        chunk_record = read_record(ledger, "chunks", f"{key}:chunk:{chunk_id}") if key else None
        if chunk_record:
            text = str(chunk_record.get("text") or item.get("snippet") or "")
            item["text"] = text
            item["snippet"] = text[:300]
            item["title"] = chunk_record.get("title") or item.get("title") or key
            item["tags"] = chunk_record.get("tags") or item.get("tags") or []
            item["project"] = chunk_record.get("project") or item.get("project")
            item["domain"] = chunk_record.get("domain") or item.get("domain")
            item["_ekc_updated_at"] = str(chunk_record.get("updated_at") or "")
            item["_ekc_focus_score"] = _knowledge_focus_score(chunk_record, focus_terms)
        else:
            item["text"] = str(item.get("text") or item.get("snippet") or "")
            item["_ekc_updated_at"] = ""
            item["_ekc_focus_score"] = _knowledge_focus_score(item, focus_terms)
        hydrated.append(item)

    hydrated.sort(
        key=lambda item: (
            int(item.get("_ekc_focus_score") or 0),
            str(item.get("_ekc_updated_at") or ""),
            float(item.get("score") or 0.0),
        ),
        reverse=True,
    )
    return [
        {key: value for key, value in item.items() if not str(key).startswith("_ekc_")}
        for item in hydrated[: max(int(limit), 1)]
    ]


def _knowledge_focus_terms(ask: dict[str, Any]) -> list[str]:
    terms = [str(term).strip().lower() for term in ask.get("focus") or [] if str(term).strip()]
    return terms


def _knowledge_focus_score(record: dict[str, Any], focus_terms: list[str]) -> int:
    if not focus_terms:
        return 0
    haystack = str(record).lower()
    return sum(1 for term in focus_terms if term in haystack)


def _project_capsule_response(
    normalized: dict[str, Any],
    *,
    artifact_record: dict[str, Any],
    planner: dict[str, Any],
    artifacts_built: int,
    artifacts_read: int,
    source_reads: int,
) -> dict[str, Any]:
    artifact = dict(artifact_record.get("artifact") or {})
    answer = {
        "project": artifact.get("project"),
        "summary": artifact.get("summary") or "",
        "current_goals": list(artifact.get("current_goals") or []),
        "active_decisions": list(artifact.get("active_decisions") or []),
        "constraints": list(artifact.get("constraints") or []),
        "open_questions": list(artifact.get("open_questions") or []),
        "important_entities": list(artifact.get("important_entities") or []),
        "recent_changes": list(artifact.get("recent_changes") or []),
    }
    citations = _artifact_response_citations(artifact_record)
    staleness = dict(artifact.get("staleness") or {})
    partial = staleness.get("state") != "fresh" or not answer["summary"]
    freshness = {
        "state": staleness.get("state") or "unknown",
        "artifact_generated_at": artifact.get("generated_at"),
        "source_snapshot_id": artifact.get("source_snapshot_id"),
    }
    if artifact_record.get("artifact_id"):
        freshness["artifact_id"] = artifact_record["artifact_id"]
        freshness["artifact_persisted_at"] = artifact_record.get("created_at")
    return ok_response(
        request_id=normalized["request_id"],
        answer=answer,
        citations=citations,
        freshness=freshness,
        budget_used={
            "artifacts_built": artifacts_built,
            "artifacts_read": artifacts_read,
            "source_reads": source_reads,
            "tokens_out_estimate": len(str(answer)) // 4,
        },
        planner=planner,
        partial=partial,
        errors=[]
        if not partial
        else [
            {
                "code": "partial_capsule",
                "message": "Capsule is missing one or more optional orientation fields.",
            }
        ],
    )


def _artifact_response_citations(artifact_record: dict[str, Any]) -> list[dict[str, Any]]:
    artifact = dict(artifact_record.get("artifact") or {})
    citations = []
    artifact_id = artifact_record.get("artifact_id")
    if artifact_id:
        citations.append(
            {
                "citation_id": "artifact_001",
                "level": "artifact",
                "artifact_id": artifact_id,
                "artifact_type": artifact_record.get("artifact_type"),
                "artifact_version": artifact_record.get("artifact_version"),
                "project": artifact_record.get("project"),
                "source": "memory_os",
            }
        )
    citations.extend(
        citation
        for citation in list(artifact.get("citations") or [])
        if isinstance(citation, dict)
    )
    return normalize_knowledge_citations(citations, default_source="memory_os")


def _orientation_response(
    normalized: dict[str, Any],
    orientation: dict[str, Any],
    *,
    strategy: str,
) -> dict[str, Any]:
    planner = build_planner_receipt(
        strategy=strategy,
        methods_used=["ledger_records"],
        request_budget=normalized["budget"],
        omissions=list(orientation.get("omissions") or []),
    )
    if orientation.get("status") == "no_answer":
        error = (orientation.get("errors") or [{}])[0]
        return no_answer_response(
            request_id=normalized["request_id"],
            code=str(error.get("code") or "no_orientation_evidence"),
            message=str(error.get("message") or "No orientation evidence was available."),
            planner=planner,
        )
    answer = dict(orientation.get("answer") or {})
    return ok_response(
        request_id=normalized["request_id"],
        answer=answer,
        citations=list(orientation.get("citations") or []),
        freshness={"state": "fresh", "source_snapshot_id": "memory_os:latest"},
        budget_used={
            "artifacts_built": 0,
            "artifacts_read": 0,
            "source_reads": int(orientation.get("source_reads") or 0),
            "tokens_out_estimate": len(str(answer)) // 4,
        },
        planner=planner,
        partial=orientation.get("status") == "partial",
        errors=list(orientation.get("errors") or []),
    )


def _default_embed_text(text: str) -> list[float]:
    from core.embedder import embedder

    return list(embedder.embed(text))


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    raw_items = value.split(",") if isinstance(value, str) else list(value)
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _result_has_tags(result: dict[str, Any], requested_tags: set[str]) -> bool:
    if not requested_tags:
        return True
    actual = set(result.get("metadata", {}).get("tags") or [])
    return requested_tags.issubset(actual)


def _search_result_payload(result: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(result.get("metadata") or {})
    text = str(result.get("text") or "")
    return {
        "key": result.get("key"),
        "chunk_id": result.get("chunk_id"),
        "title": metadata.get("title") or result.get("key"),
        "score": result.get("score", 0.0),
        "snippet": text[:300],
        "tags": metadata.get("tags") or [],
        "project": metadata.get("project"),
        "domain": metadata.get("domain"),
        "citation": result.get("citation"),
    }
