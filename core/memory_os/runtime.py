"""Daemon-owned Memory OS service container."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from core.chunker import chunk_content_with_metadata
from core.memory_os._records import (
    hash_payload,
    list_records,
    now_iso,
    read_chunk_by_lookup,
    read_record,
    upsert_record,
)
from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.capability_discovery import build_capability_catalog
from core.memory_os.document_artifacts import DocumentArtifactMaterializer
from core.memory_os.document_completion import DocumentIngestionCompletionGate
from core.memory_os.document_coverage_pass import DocumentCoveragePassService
from core.memory_os.document_ingestion import DocumentIngestionOrchestrator
from core.memory_os.firewall import MemoryFirewall
from core.memory_os.graph import MemoryOSGraph
from core.memory_os.graph_ref_repair import GraphReferenceRepairService
from core.memory_os.graph_pipeline import GraphProposalPipeline
from core.memory_os.inspector import build_memory_os_inspector
from core.memory_os.job_runner import LocalJobRunner
from core.memory_os.jobs import JobQueue
from core.memory_os.knowledge_artifacts import KnowledgeArtifactStore
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.knowledge_service import KnowledgeQueryService
from core.memory_os.knowledge_pr import KnowledgePRService
from core.memory_os.legacy_migration_service import LegacyMigrationService
from core.memory_os.metadata_repair import MetadataRepairService
from core.memory_os.document_promotion import (
    apply_document_promotion_transaction as apply_reviewed_document_promotion,
)
from core.memory_os.memory_graphing import graph_memory_metadata
from core.memory_os.memory_semantic_graphing import graph_memory_semantics
from core.memory_os.memory_activation import (
    score_activation,
    store_activation_receipt as store_activation_receipt_record,
)
from core.memory_os.memory_guardrails import evaluate_memory_write, store_memory_guardrail_receipt
from core.memory_os.memory_benchmarks import (
    inspect_benchmark_run as inspect_memory_benchmark_run,
    list_memory_benchmark_suites,
    run_memory_benchmark as run_memory_benchmark_suite,
)
from core.memory_os.memory_taxonomy import classify_memory_request, normalize_memory_payload
from core.memory_limits import MAX_DIRECT_MEMORY_CHARS, direct_memory_too_long_message
from core.memory_os.project_identity import resolve_project_filter_values
from core.memory_os.retrieval import MemoryOSRetrievalIndex
from core.memory_os.snapshots import SnapshotService
from core.memory_os.sync_identity import (
    LOCAL_DEVICE_RECORD_ID,
    build_sync_status,
    ensure_device_identity,
    export_local_sync_identity,
    register_sync_peer,
)
from core.memory_os.sync_changesets import (
    export_sync_changeset as export_reviewed_sync_changeset,
    inspect_sync_convergence as inspect_runtime_sync_convergence,
    inspect_sync_state as inspect_runtime_sync_state,
    prepare_sync_changeset as prepare_reviewed_sync_changeset,
)
from core.memory_os.sync_apply import (
    apply_sync_changeset as apply_reviewed_sync_changeset,
    list_sync_conflicts as list_runtime_sync_conflicts,
    prepare_sync_apply as prepare_reviewed_sync_apply,
    resolve_sync_conflict as resolve_reviewed_sync_conflict,
)
from core.memory_os.sync_inbox_apply import (
    apply_sync_inbox as apply_staged_sync_inbox,
    prepare_sync_inbox_apply as prepare_staged_sync_inbox_apply,
    prune_applied_sync_inbox_artifacts as prune_staged_sync_inbox_artifacts,
)
from core.memory_os.sync_peer_transport import (
    configure_sync_peer_transport as configure_reviewed_sync_peer_transport,
    inspect_sync_peer as inspect_runtime_sync_peer,
    push_sync_changeset as push_reviewed_sync_changeset,
)
from core.memory_os.sync_transport import list_sync_inbox as list_runtime_sync_inbox
from core.memory_os.transactions import MemoryTransactionService


CURRENT_MEMORY_STATUSES = ("active", "accepted", "reviewed")
RETRIEVAL_MANIFEST_REFRESH_JOB_KIND = "retrieval_manifest_refresh"
MEMORY_RETRIEVAL_REFRESH_JOB_KIND = "memory_retrieval_refresh"
PENDING_RETRIEVAL_MANIFEST_STATUS = "ready_pending_manifest_refresh"


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
        self.write_lock = threading.RLock()
        self.ledger = MemoryOSLedger(self.root / "ledger.sqlite3")
        self.content_store = ContentAddressedStore(self.root / "objects")
        self.jobs = JobQueue(self.ledger)
        self.job_runner = LocalJobRunner(self.ledger, queue=self.jobs)
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
        self.graph_pipeline = GraphProposalPipeline(self.ledger, self)
        self.knowledge_prs = KnowledgePRService(self.ledger, self)
        self.knowledge_artifacts = KnowledgeArtifactStore(self.ledger, self.content_store)
        self.document_artifacts = DocumentArtifactMaterializer(self.ledger, self.content_store)
        self.document_completion = DocumentIngestionCompletionGate(self.ledger, self.content_store, self)
        self.document_coverage_pass = DocumentCoveragePassService(self)
        self.document_ingestion = DocumentIngestionOrchestrator(self)
        self.legacy_migration = LegacyMigrationService(
            root=self.root,
            ledger=self.ledger,
            transactions=self.transactions,
            content_store=self.content_store,
            store_memory=self.store_memory,
            graph=self.graph,
        )
        self.knowledge_service = KnowledgeQueryService(
            ledger=self.ledger,
            transactions=self.transactions,
            knowledge_artifacts=self.knowledge_artifacts,
            search_memories=self.search_memories,
        )
        self.metadata_repair = MetadataRepairService(ledger=self.ledger, retrieval=self.retrieval)
        self.graph_ref_repair = GraphReferenceRepairService(
            ledger=self.ledger,
            graph=self.graph,
            transactions=self.transactions,
        )
        self.preflight_report: dict[str, Any] | None = None
        self._retrieval_state: dict[str, Any] = {
            "status": "not_initialized",
            "ready": False,
            "manifest": None,
            "error": None,
        }

    @property
    def retrieval_ready(self) -> bool:
        """Return whether Memory OS retrieval is ready for primary search/write paths."""
        return bool(self._retrieval_state.get("ready"))

    def retrieval_state(self) -> dict[str, Any]:
        """Return a compact retrieval startup/rebuild state payload."""
        if self._retrieval_state.get("manifest_refresh_required") is True:
            try:
                source_count = self.retrieval.source_record_count()
                indexed_count = int(
                    ((self._retrieval_state.get("manifest") or {}).get("indexed_count"))
                    or self.retrieval.vector_index.stats().get("document_count", 0)
                )
            except Exception:
                return dict(self._retrieval_state)
            if source_count != indexed_count:
                self._retrieval_state = {
                    "status": "needs_rebuild",
                    "ready": False,
                    "manifest": self._retrieval_state.get("manifest"),
                    "manifest_refresh_required": True,
                    "pending_job_id": self._retrieval_state.get("pending_job_id"),
                    "diagnostics": {
                        "gate": "retrieval_incremental_count_consistency",
                        "mismatches": ["indexed_count"],
                        "source_count": source_count,
                        "indexed_count": indexed_count,
                    },
                    "repair_guidance": (
                        "Retrieval index count no longer matches the Memory OS ledger. "
                        "Run the queued manifest refresh or rebuild retrieval from the ledger."
                    ),
                    "error": None,
                }
            return dict(self._retrieval_state)
        if self._retrieval_state.get("ready"):
            try:
                refreshed = self.retrieval.existing_index_state()
            except Exception:
                return dict(self._retrieval_state)
            if refreshed.get("ready"):
                self._retrieval_state = {
                    **refreshed,
                    "status": self._retrieval_state.get("status") or refreshed.get("status"),
                }
            elif refreshed.get("status") in {"needs_rebuild", "stale_manifest"}:
                self._retrieval_state = refreshed
        return dict(self._retrieval_state)

    def initialize(self, *, rebuild_retrieval: bool = True) -> dict[str, Any]:
        """Initialize durable Memory OS stores and return a status payload."""
        self.ledger.initialize()
        self.content_store.root.mkdir(parents=True, exist_ok=True)
        self.graph.load_edges()
        if rebuild_retrieval:
            self.rebuild_retrieval_from_ledger()
        else:
            self._retrieval_state = self.retrieval.existing_index_state()
        return self.status()

    def rebuild_retrieval_from_ledger(self) -> dict[str, Any]:
        """Rebuild Memory OS retrieval from durable ledger chunks."""
        self._retrieval_state = {
            "status": "rebuilding",
            "ready": False,
            "manifest": None,
            "error": None,
        }
        try:
            manifest = self.retrieval.rebuild_from_ledger()
        except Exception as exc:
            self._retrieval_state = {
                "status": "error",
                "ready": False,
                "manifest": None,
                "error": str(exc),
            }
            raise
        self._retrieval_state = {
            "status": "ready",
            "ready": True,
            "manifest": manifest,
            "error": None,
        }
        return manifest

    def refresh_retrieval_manifest_from_ledger(self) -> dict[str, Any]:
        """Refresh retrieval manifest metadata when the existing index is current."""
        manifest = self.retrieval.refresh_manifest_from_ledger()
        self._retrieval_state = {
            "status": "ready",
            "ready": True,
            "manifest": manifest,
            "error": None,
        }
        return manifest

    def status(self) -> dict[str, Any]:
        """Return a compact Memory OS component status."""
        return {
            "status": "ok",
            "root": str(self.root),
            "components": {
                "ledger": {
                    "path": str(self.ledger.path),
                    "exists": self.ledger.path.exists(),
                    "connection_profile": self.ledger.connection_profile(),
                },
                "content_store": {
                    "path": str(self.content_store.root),
                    "exists": self.content_store.root.exists(),
                },
                "retrieval": {
                    "backend": type(self.retrieval.vector_index).__name__,
                    "path": str(self.root / "lance"),
                    "state": self.retrieval_state(),
                },
                "graph": {
                    "backend": type(self.graph.graph_store).__name__,
                    "path": str(self.root / "kuzu"),
                    "state": self.graph.reconciliation_state(),
                },
                "jobs": self.job_runner.queue_health(),
                "transactions": {"status": "ready"},
                "snapshots": {"status": "ready"},
                "runtime_preflight": self.preflight_report or {"status": "unknown"},
                "firewall": {"status": "ready"},
                "sync": self.sync_status(),
            },
        }

    def sync_status(self) -> dict[str, Any]:
        """Return local sync identity and peer readiness without private keys."""
        return build_sync_status(self.ledger)

    def ensure_sync_device_identity(self, *, device_name: str = "local") -> dict[str, Any]:
        """Ensure and return the local public sync identity."""
        existing = read_record(self.ledger, "sync_devices", LOCAL_DEVICE_RECORD_ID)
        write_required = not existing or existing.get("status") != "active"
        local_device = ensure_device_identity(self.ledger, device_name=device_name)
        return {
            "status": "ready",
            "write_performed": write_required,
            "local_device": local_device,
            "sync_status": self.sync_status(),
            "error": None,
        }

    def export_local_sync_identity(self) -> dict[str, Any]:
        """Return a public-only local sync identity packet."""
        return export_local_sync_identity(self.ledger)

    def register_sync_peer(
        self,
        *,
        peer_identity_packet: dict[str, Any],
        accept: bool,
        approved_by: str | None,
    ) -> dict[str, Any]:
        """Register a reviewed peer public identity packet."""
        return register_sync_peer(
            self.ledger,
            peer_identity_packet,
            accept=accept,
            approved_by=approved_by,
        )

    def inspect_sync_state(self) -> dict[str, Any]:
        """Return read-only sync state for identity, cursors, changesets, and conflicts."""
        return inspect_runtime_sync_state(self)

    def prepare_sync_changeset(self, *, peer_id: str) -> dict[str, Any]:
        """Prepare a no-write signed/encrypted changeset export packet."""
        return prepare_reviewed_sync_changeset(self, peer_id=peer_id)

    def export_sync_changeset(
        self,
        *,
        plan: dict[str, Any],
        accept: bool,
        approved_by: str | None,
    ) -> dict[str, Any]:
        """Export a reviewed sync changeset as an encrypted content artifact."""
        return export_reviewed_sync_changeset(
            self,
            plan,
            accept=accept,
            approved_by=approved_by,
        )

    def prepare_sync_apply(self, *, bundle_bytes: bytes) -> dict[str, Any]:
        """Prepare a no-write plan for applying a signed encrypted changeset bundle."""
        return prepare_reviewed_sync_apply(self, bundle_bytes)

    def apply_sync_changeset(
        self,
        *,
        bundle_bytes: bytes,
        plan: dict[str, Any],
        accept: bool,
        approved_by: str | None,
    ) -> dict[str, Any]:
        """Apply a reviewed sync changeset after re-verifying the encrypted bundle."""
        return apply_reviewed_sync_changeset(
            self,
            bundle_bytes,
            plan,
            accept=accept,
            approved_by=approved_by,
        )

    def prepare_sync_inbox_apply(
        self,
        *,
        peer_id: str | None = None,
        limit: int | None = 50,
    ) -> dict[str, Any]:
        """Prepare a compact plan for staged sync inbox bundles."""
        return prepare_staged_sync_inbox_apply(self, peer_id=peer_id, limit=limit)

    def apply_sync_inbox(
        self,
        *,
        accept: bool,
        approved_by: str | None,
        peer_id: str | None = None,
        limit: int | None = 50,
        stop_on_error: bool = True,
    ) -> dict[str, Any]:
        """Apply reviewed sync bundles already staged in the local inbox."""
        return apply_staged_sync_inbox(
            self,
            accept=accept,
            approved_by=approved_by,
            peer_id=peer_id,
            limit=limit,
            stop_on_error=stop_on_error,
        )

    def prune_applied_sync_inbox_artifacts(
        self,
        *,
        accept: bool,
        approved_by: str | None,
        peer_id: str | None = None,
        limit: int | None = 50,
    ) -> dict[str, Any]:
        """Prune encrypted bytes for already-applied staged sync bundles."""
        return prune_staged_sync_inbox_artifacts(
            self,
            accept=accept,
            approved_by=approved_by,
            peer_id=peer_id,
            limit=limit,
        )

    def inspect_sync_convergence(self, *, peer_id: str) -> dict[str, Any]:
        """Inspect unresolved conflicts for one sync peer."""
        return inspect_runtime_sync_convergence(self, peer_id=peer_id)

    def list_sync_conflicts(self, *, status: str | None = None) -> dict[str, Any]:
        """List sync conflicts without exposing remote payload bodies."""
        return list_runtime_sync_conflicts(self, status=status)

    def resolve_sync_conflict(
        self,
        *,
        conflict_id: str,
        resolution: str,
        accept: bool,
        approved_by: str | None,
    ) -> dict[str, Any]:
        """Mark a sync conflict reviewed without directly overwriting memory rows."""
        return resolve_reviewed_sync_conflict(
            self,
            conflict_id,
            resolution=resolution,
            accept=accept,
            approved_by=approved_by,
        )

    def configure_sync_peer_transport(
        self,
        *,
        peer_id: str,
        url: str,
        mode: str = "manual",
        allow_pull: bool = False,
        accept: bool,
        approved_by: str | None,
    ) -> dict[str, Any]:
        """Attach reviewed LAN/Tailscale/file transport coordinates to a peer."""
        return configure_reviewed_sync_peer_transport(
            self,
            peer_id=peer_id,
            url=url,
            mode=mode,
            allow_pull=allow_pull,
            accept=accept,
            approved_by=approved_by,
        )

    def inspect_sync_peer(self, *, peer_id: str) -> dict[str, Any]:
        """Inspect one registered sync peer and transport state."""
        return inspect_runtime_sync_peer(self, peer_id=peer_id)

    def push_sync_changeset(
        self,
        *,
        peer_id: str,
        accept: bool,
        approved_by: str | None,
    ) -> dict[str, Any]:
        """Prepare, export, and push one reviewed sync changeset to a configured peer."""
        return push_reviewed_sync_changeset(
            self,
            peer_id=peer_id,
            accept=accept,
            approved_by=approved_by,
        )

    def list_sync_inbox(self, *, peer_id: str | None = None) -> dict[str, Any]:
        """List staged encrypted sync bundles without applying them."""
        return list_runtime_sync_inbox(self, peer_id=peer_id)

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

    def prepare_legacy_memory_os_migration(
        self,
        *,
        legacy_dir: str | Path,
        include_details: bool = False,
    ) -> dict[str, Any]:
        """Prepare a no-write legacy JSON migration transaction."""
        return self.legacy_migration.prepare_legacy_memory_os_migration(
            legacy_dir=legacy_dir,
            include_details=include_details,
        )

    def apply_legacy_memory_os_migration(
        self,
        *,
        legacy_dir: str | Path,
        accept: bool = False,
        approved_by: str | None = None,
        include_details: bool = False,
    ) -> dict[str, Any]:
        """Apply reviewed legacy JSON migration writes after explicit acceptance."""
        return self.legacy_migration.apply_legacy_memory_os_migration(
            legacy_dir=legacy_dir,
            accept=accept,
            approved_by=approved_by,
            include_details=include_details,
        )

    def prepare_legacy_related_to_graph_migration(
        self,
        *,
        legacy_dir: str | Path,
        include_details: bool = False,
    ) -> dict[str, Any]:
        """Prepare a no-write legacy related_to graph migration transaction."""
        return self.legacy_migration.prepare_legacy_related_to_graph_migration(
            legacy_dir=legacy_dir,
            include_details=include_details,
        )

    def apply_legacy_related_to_graph_migration(
        self,
        *,
        legacy_dir: str | Path,
        accept: bool = False,
        approved_by: str | None = None,
        include_details: bool = False,
    ) -> dict[str, Any]:
        """Apply reviewed legacy related_to graph edges after explicit acceptance."""
        return self.legacy_migration.apply_legacy_related_to_graph_migration(
            legacy_dir=legacy_dir,
            accept=accept,
            approved_by=approved_by,
            include_details=include_details,
        )

    def record_document_disassembly_job(
        self,
        disassembly: dict[str, Any],
        *,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        """Record daemon-owned document disassembly job receipts."""
        document = disassembly.get("document") if isinstance(disassembly.get("document"), dict) else {}
        source = disassembly.get("source") if isinstance(disassembly.get("source"), dict) else {}
        job = self.jobs.enqueue(
            "document_disassembly",
            {
                "document_id": document.get("document_id"),
                "source_uri": source.get("source_uri"),
                "page_range": document.get("page_range"),
                "resume": disassembly.get("resume"),
                "request": request,
            },
        )
        return self.jobs.succeed(
            job["job_id"],
            result={
                "document_id": document.get("document_id"),
                "status": disassembly.get("status") or "ok",
                "resume": disassembly.get("resume"),
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
        memory_type: str | None = None,
        scope: str | None = None,
        trust_state: str | None = None,
        retention_policy: str | None = None,
        sync_policy: str | None = None,
        document_id: str | None = None,
        source_id: str | None = None,
        source_document: dict[str, Any] | None = None,
        citations: list[dict[str, Any]] | None = None,
        approved_by: str | None = None,
        guardrail_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store one reviewed memory in the Memory OS ledger and retrieval index."""
        normalized_key = _required_text(key, "key")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content is required")
        if len(content) > MAX_DIRECT_MEMORY_CHARS:
            raise ValueError(direct_memory_too_long_message(len(content)))
        now = now_iso()
        existing = read_record(self.ledger, "memories", normalized_key)
        if existing and not force:
            # Explicit overwrites are allowed because stable memory writes are updates.
            pass
        normalized_tags = _string_list(tags)
        normalized_related_to = _string_list(related_to)
        normalized_project = _optional_text(project)
        normalized_domain = _optional_text(domain)
        normalized_status = _optional_text(status) or "active"
        normalized_canonical = bool(canonical) if canonical is not None else False
        normalized_source_document = dict(source_document) if isinstance(source_document, dict) else None
        normalized_citations = _dict_list(citations)
        normalized_document_id = _optional_text(document_id) or (
            _optional_text(normalized_source_document.get("document_id"))
            if normalized_source_document is not None
            else None
        )
        normalized_source_id = _optional_text(source_id) or (
            _optional_text(normalized_source_document.get("source_id"))
            if normalized_source_document is not None
            else None
        )
        classification = classify_memory_request(
            {
                "key": normalized_key,
                "content": content,
                "tags": normalized_tags,
                "project": normalized_project,
                "domain": normalized_domain,
                "status": normalized_status,
                "document_id": normalized_document_id,
                "source_id": normalized_source_id,
                "source_document": normalized_source_document,
                "memory_type": memory_type,
                "scope": scope,
                "trust_state": trust_state,
                "retention_policy": retention_policy,
                "sync_policy": sync_policy,
            }
        )
        guardrail_treatment = self._enforce_memory_guardrails(
            memory={
                "key": normalized_key,
                "content": content,
                "memory_type": classification.memory_type,
                "scope": classification.scope,
                "trust_state": classification.trust_state,
                "status": normalized_status,
                "project": normalized_project,
                "domain": normalized_domain,
                "citations": normalized_citations,
            },
            approved_by=approved_by,
            context=guardrail_context,
        )
        if guardrail_treatment.get("allowed") is not True:
            return self._memory_guardrail_error_response(
                key=normalized_key,
                treatment=guardrail_treatment,
            )
        memory_title = title or normalized_key
        content_hash = hash_payload(content)
        receipt_fingerprint = hash_payload(
            {
                "content_hash": content_hash,
                "title": memory_title,
                "tags": normalized_tags,
                "related_to": normalized_related_to,
                "project": normalized_project,
                "domain": normalized_domain,
                "status": normalized_status,
                "canonical": normalized_canonical,
                "memory_type": classification.memory_type,
                "scope": classification.scope,
                "trust_state": classification.trust_state,
                "retention_policy": classification.retention_policy,
                "sync_policy": classification.sync_policy,
                "document_id": normalized_document_id,
                "source_id": normalized_source_id,
                "source_document": normalized_source_document,
                "citations": normalized_citations,
            }
        )
        idempotency_key = f"store_memory:{normalized_key}:{receipt_fingerprint}"
        proposed_writes = [{"table": "memories", "id": normalized_key}]
        affected_refs = [{"kind": "memory", "key": normalized_key}]
        existing_receipt = self.transactions.find_by_idempotency_key(idempotency_key)
        if (
            existing_receipt is not None
            and existing_receipt.get("status") == "promoted"
            and isinstance(existing, dict)
            and _matches_store_memory_request(
                existing,
                content_hash=content_hash,
                title=memory_title,
                tags=normalized_tags,
                related_to=normalized_related_to,
                project=normalized_project,
                domain=normalized_domain,
                status=normalized_status,
                canonical=normalized_canonical,
                memory_type=classification.memory_type,
                scope=classification.scope,
                trust_state=classification.trust_state,
                retention_policy=classification.retention_policy,
                sync_policy=classification.sync_policy,
                document_id=normalized_document_id,
                source_id=normalized_source_id,
                source_document=normalized_source_document,
            )
            and _complete_store_state(existing)
            and existing.get("repair_required") is not True
        ):
            replay = dict(existing_receipt)
            replay["idempotent_replay"] = True
            repaired_ids = self.transactions.mark_degraded_children_repaired(
                idempotency_key,
                repaired_by_transaction_id=str(replay["transaction_id"]),
            )
            if repaired_ids:
                replay["repaired_degraded_transaction_ids"] = repaired_ids
            return {
                **existing,
                "transaction_id": replay["transaction_id"],
                "transaction_receipt": replay,
                "idempotent_replay": True,
                "graph_treatment": self._metadata_graph_replay_receipt(normalized_key),
                "semantic_graph_treatment": self._semantic_graph_replay_receipt(normalized_key),
                "guardrail_treatment": _compact_guardrail_treatment(guardrail_treatment),
            }
        artifact_id = self.content_store.put_bytes(content.encode("utf-8"), suffix=".md")
        chunks = chunk_content_with_metadata(content)
        memory = {
            "key": normalized_key,
            "title": memory_title,
            "content_artifact_id": artifact_id,
            "tags": normalized_tags,
            "related_to": normalized_related_to,
            "project": normalized_project,
            "domain": normalized_domain,
            "status": normalized_status,
            "canonical": normalized_canonical,
            "memory_type": classification.memory_type,
            "scope": classification.scope,
            "trust_state": classification.trust_state,
            "retention_policy": classification.retention_policy,
            "sync_policy": classification.sync_policy,
            "document_id": normalized_document_id,
            "source_id": normalized_source_id,
            "source_document": normalized_source_document,
            "citations": normalized_citations,
            "chars": len(content),
            "lines": len(content.splitlines()),
            "chunk_count": len(chunks),
            "content_hash": content_hash,
            "created_at": existing.get("created_at") if existing else now,
            "updated_at": now,
            "storage_backend": "memory_os",
            "write_state": "pending",
            "retrieval_state": "pending",
            "graph_state": "pending",
            "repair_required": False,
            "metadata_graph_edge_ids": list((existing or {}).get("metadata_graph_edge_ids") or []),
            "metadata_graph_concept_ids": list((existing or {}).get("metadata_graph_concept_ids") or []),
            "metadata_graph_entity_ids": list((existing or {}).get("metadata_graph_entity_ids") or []),
            "metadata_graph_missing_related_to": list(
                (existing or {}).get("metadata_graph_missing_related_to") or []
            ),
            "semantic_graph_edge_ids": list((existing or {}).get("semantic_graph_edge_ids") or []),
            "semantic_graph_job_id": (existing or {}).get("semantic_graph_job_id"),
        }
        self._delete_chunks(normalized_key, memory=existing)
        upsert_record(self.ledger, "memories", normalized_key, memory)
        chunk_records: list[dict[str, Any]] = []
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
                "memory_type": memory["memory_type"],
                "scope": memory["scope"],
                "trust_state": memory["trust_state"],
                "retention_policy": memory["retention_policy"],
                "sync_policy": memory["sync_policy"],
                "document_id": memory.get("document_id"),
                "source_id": memory.get("source_id"),
                "source_document": memory.get("source_document"),
                "citations": memory.get("citations"),
                "section_title": chunk.get("section_title"),
                "heading_path": list(chunk.get("heading_path") or []),
                "chunk_kind": chunk.get("chunk_kind"),
                "created_at": now,
                "updated_at": now,
                "write_state": "pending",
                "retrieval_state": "pending",
                "graph_state": "pending",
                "repair_required": False,
            }
            upsert_record(self.ledger, "chunks", chunk_record["chunk_record_id"], chunk_record)
            chunk_records.append(chunk_record)
        try:
            retrieval_treatment = self.retrieval.upsert_chunk_records(normalized_key, chunk_records)
        except Exception as exc:  # noqa: BLE001 - capture durable repair envelope
            return self._mark_store_memory_degraded(
                memory=memory,
                chunk_records=chunk_records,
                proposed_writes=proposed_writes,
                idempotency_key=idempotency_key,
                affected_refs=affected_refs,
                failed_gate="retrieval",
                exc=exc,
                retrieval_state="repair_pending",
                graph_state="not_attempted",
            )
        manifest_job = self._mark_retrieval_manifest_refresh_pending(
            retrieval_treatment,
            reason="store_memory",
            memory_key=normalized_key,
        )

        for chunk_record in chunk_records:
            chunk_record["retrieval_state"] = "indexed"
            upsert_record(self.ledger, "chunks", chunk_record["chunk_record_id"], chunk_record)
        memory["retrieval_state"] = "indexed"
        upsert_record(self.ledger, "memories", normalized_key, memory)

        try:
            graph_treatment = graph_memory_metadata(
                ledger=self.ledger,
                graph=self.graph,
                memory=memory,
                chunks=chunk_records,
            )
        except Exception as exc:  # noqa: BLE001 - capture durable repair envelope
            return self._mark_store_memory_degraded(
                memory=memory,
                chunk_records=chunk_records,
                proposed_writes=proposed_writes,
                idempotency_key=idempotency_key,
                affected_refs=affected_refs,
                failed_gate="metadata_graph",
                exc=exc,
                retrieval_state="indexed",
                graph_state="repair_pending",
            )

        try:
            semantic_graph_treatment = graph_memory_semantics(
                ledger=self.ledger,
                graph=self.graph,
                memory=memory,
                chunks=chunk_records,
            )
        except Exception as exc:  # noqa: BLE001 - capture durable repair envelope
            return self._mark_store_memory_degraded(
                memory=memory,
                chunk_records=chunk_records,
                proposed_writes=proposed_writes,
                idempotency_key=idempotency_key,
                affected_refs=affected_refs,
                failed_gate="semantic_graph",
                exc=exc,
                retrieval_state="indexed",
                graph_state="repair_pending",
                graph_treatment=graph_treatment,
            )

        for chunk_record in chunk_records:
            chunk_record["write_state"] = "complete"
            chunk_record["graph_state"] = "complete"
            chunk_record["repair_required"] = False
            upsert_record(self.ledger, "chunks", chunk_record["chunk_record_id"], chunk_record)
        memory["write_state"] = "complete"
        memory["graph_state"] = "complete"
        memory["metadata_graph_edge_ids"] = list(graph_treatment.get("graph_edges_written") or [])
        memory["metadata_graph_concept_ids"] = list(graph_treatment.get("concepts_written") or [])
        memory["metadata_graph_entity_ids"] = list(graph_treatment.get("entities_written") or [])
        memory["metadata_graph_missing_related_to"] = list(graph_treatment.get("missing_related_to") or [])
        memory["semantic_graph_edge_ids"] = list(
            semantic_graph_treatment.get("graph_edges_written") or []
        )
        memory["semantic_graph_job_id"] = semantic_graph_treatment.get("job_id")
        memory["repair_required"] = False
        upsert_record(self.ledger, "memories", normalized_key, memory)
        receipt = self.transactions.promote(
            operation_kind="store_memory",
            proposed_writes=proposed_writes,
            idempotency_key=idempotency_key,
            affected_refs=affected_refs,
        )
        return {
            **memory,
            "transaction_id": receipt["transaction_id"],
            "retrieval_treatment": {
                **retrieval_treatment,
                "manifest_refresh_job": _job_summary(manifest_job),
            },
            "graph_treatment": graph_treatment,
            "semantic_graph_treatment": semantic_graph_treatment,
            "guardrail_treatment": _compact_guardrail_treatment(guardrail_treatment),
        }

    def _enforce_memory_guardrails(
        self,
        *,
        memory: dict[str, Any],
        approved_by: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        guardrail = evaluate_memory_write(memory)
        if guardrail.get("decision") == "allow":
            return {
                "allowed": True,
                "guardrail": guardrail,
                "receipt": None,
                "firewall_event": None,
            }
        decision = str(guardrail.get("decision") or "").strip()
        reviewer = str(approved_by or "").strip()
        event = self.firewall.record_memory_guardrail(
            guardrail,
            memory_key=str(memory.get("key") or ""),
            context=context,
        )
        receipt = store_memory_guardrail_receipt(
            self.ledger,
            memory=memory,
            guardrail=guardrail,
            firewall_event_id=event["event_id"],
            reviewed_by=reviewer if decision == "require_review" and reviewer else None,
            context=context,
        )
        allowed = decision == "require_review" and bool(reviewer)
        return {
            "allowed": allowed,
            "guardrail": {
                **guardrail,
                "receipt_id": receipt["receipt_id"],
                "firewall_event_id": event["event_id"],
                "reviewed_by": reviewer if allowed else None,
            },
            "receipt": receipt,
            "firewall_event": event,
        }

    def _memory_guardrail_error_response(
        self,
        *,
        key: str,
        treatment: dict[str, Any],
    ) -> dict[str, Any]:
        guardrail = treatment.get("guardrail") if isinstance(treatment.get("guardrail"), dict) else {}
        decision = str(guardrail.get("decision") or "").strip()
        if decision == "block":
            status = "policy_denied"
            code = "memory_guardrail_blocked"
            message = "Memory guardrails blocked this active memory write."
        else:
            status = "review_required"
            code = "memory_guardrail_review_required"
            message = "Memory guardrails require an explicit reviewed promotion path."
        error = {
            "code": code,
            "category": "memory_guardrail",
            "message": message,
            "issue_codes": list(guardrail.get("issue_codes") or []),
        }
        return {
            "schema_version": guardrail.get("schema_version"),
            "status": status,
            "stored": False,
            "key": key,
            "guardrail": guardrail,
            "guardrail_receipt": treatment.get("receipt"),
            "firewall_event": treatment.get("firewall_event"),
            "write_performed": bool(treatment.get("receipt") or treatment.get("firewall_event")),
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "repair_required": False,
            "error": error,
            "errors": [error],
        }

    def _mark_store_memory_degraded(
        self,
        *,
        memory: dict[str, Any],
        chunk_records: list[dict[str, Any]],
        proposed_writes: list[dict[str, Any]],
        idempotency_key: str,
        affected_refs: list[dict[str, Any]],
        failed_gate: str,
        exc: Exception,
        retrieval_state: str,
        graph_state: str,
        graph_treatment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        error = {
            "code": "memory_write_degraded",
            "failed_gate": failed_gate,
            "exception_type": type(exc).__name__,
            "message": str(exc),
        }
        repair_guidance = (
            f"Repair store_memory for '{memory['key']}' by retrying the write or running "
            f"a targeted repair for the {failed_gate} gate."
        )
        now = now_iso()
        receipt = self.transactions.degraded(
            operation_kind="store_memory",
            proposed_writes=proposed_writes,
            idempotency_key=idempotency_key,
            affected_refs=affected_refs,
            failed_gate=failed_gate,
            error=error,
            repair_guidance=repair_guidance,
        )
        degraded_memory = {
            **memory,
            "write_state": "repair_pending",
            "retrieval_state": retrieval_state,
            "graph_state": graph_state,
            "repair_required": True,
            "failed_gate": failed_gate,
            "last_error": error,
            "repair_guidance": repair_guidance,
            "updated_at": now,
        }
        upsert_record(self.ledger, "memories", degraded_memory["key"], degraded_memory)
        for chunk_record in chunk_records:
            degraded_chunk = {
                **chunk_record,
                "write_state": "repair_pending",
                "retrieval_state": retrieval_state,
                "graph_state": graph_state,
                "repair_required": True,
                "failed_gate": failed_gate,
                "updated_at": now,
            }
            upsert_record(self.ledger, "chunks", degraded_chunk["chunk_record_id"], degraded_chunk)
        return {
            **degraded_memory,
            "transaction_id": receipt["transaction_id"],
            "transaction_receipt": receipt,
            "write_degraded": True,
            "error": error,
            "graph_treatment": graph_treatment,
            "semantic_graph_treatment": None,
        }

    def _metadata_graph_replay_receipt(self, memory_key: str) -> dict[str, Any]:
        memory = read_record(self.ledger, "memories", memory_key)
        if isinstance(memory, dict) and "metadata_graph_edge_ids" in memory:
            return {
                "source": "memory_metadata_graph",
                "graph_edges_written": list(memory.get("metadata_graph_edge_ids") or []),
                "concepts_written": list(memory.get("metadata_graph_concept_ids") or []),
                "entities_written": list(memory.get("metadata_graph_entity_ids") or []),
                "missing_related_to": list(memory.get("metadata_graph_missing_related_to") or []),
                "write_performed": False,
                "active_memory_write_performed": False,
                "graph_write_performed": False,
                "idempotent_replay": True,
            }
        edges = [
            edge
            for edge in list_records(self.ledger, "graph_edges")
            if edge.get("source") == "memory_metadata_graph"
            and edge.get("from_ref") == {"kind": "memory", "key": memory_key}
        ]
        return {
            "source": "memory_metadata_graph",
            "graph_edges_written": [edge["edge_id"] for edge in edges],
            "concepts_written": [],
            "entities_written": [],
            "missing_related_to": [],
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "idempotent_replay": True,
        }

    def _semantic_graph_replay_receipt(self, memory_key: str) -> dict[str, Any]:
        memory = read_record(self.ledger, "memories", memory_key)
        if isinstance(memory, dict) and (
            memory.get("semantic_graph_job_id") or memory.get("semantic_graph_edge_ids")
        ):
            return {
                "source": "memory_semantic_graph",
                "job_kind": "memory_graph_enrichment",
                "job_id": memory.get("semantic_graph_job_id") or "",
                "fingerprint": "",
                "status": "succeeded" if memory.get("semantic_graph_edge_ids") else "skipped",
                "graph_edges_written": list(memory.get("semantic_graph_edge_ids") or []),
                "graph_edges_deactivated": [],
                "concepts_written": [],
                "write_performed": False,
                "graph_write_performed": False,
                "active_memory_write_performed": False,
                "idempotent_replay": True,
                "error": None,
            }
        for job in reversed(list_records(self.ledger, "jobs")):
            if (
                job.get("job_kind") == "memory_graph_enrichment"
                and isinstance(job.get("payload"), dict)
                and job["payload"].get("memory_key") == memory_key
                and isinstance(job.get("result"), dict)
            ):
                result = dict(job["result"])
                result["idempotent_replay"] = True
                result["write_performed"] = False
                result["graph_write_performed"] = False
                return result
        return {
            "source": "memory_semantic_graph",
            "job_kind": "memory_graph_enrichment",
            "job_id": "",
            "fingerprint": "",
            "status": "skipped",
            "graph_edges_written": [],
            "graph_edges_deactivated": [],
            "concepts_written": [],
            "write_performed": False,
            "graph_write_performed": False,
            "active_memory_write_performed": False,
            "idempotent_replay": True,
            "warnings": ["no prior semantic graph job found for replay."],
            "error": None,
        }

    def _mark_retrieval_manifest_refresh_pending(
        self,
        retrieval_treatment: dict[str, Any],
        *,
        reason: str,
        memory_key: str,
    ) -> dict[str, Any]:
        job = self.job_runner.enqueue(
            RETRIEVAL_MANIFEST_REFRESH_JOB_KIND,
            {
                "reason": reason,
                "memory_key": memory_key,
                "manifest": retrieval_treatment.get("manifest"),
            },
            idempotency_key=(
                f"{RETRIEVAL_MANIFEST_REFRESH_JOB_KIND}:"
                f"{reason}:{memory_key}:{hash_payload(retrieval_treatment.get('manifest') or {})}"
            ),
            max_attempts=3,
        )
        self._retrieval_state = {
            "status": PENDING_RETRIEVAL_MANIFEST_STATUS,
            "ready": True,
            "manifest": retrieval_treatment.get("manifest"),
            "manifest_refresh_required": True,
            "pending_job_id": job.get("job_id"),
            "error": None,
        }
        return job

    def _enqueue_memory_retrieval_refresh(self, memory_key: str) -> dict[str, Any]:
        memory = read_record(self.ledger, "memories", memory_key) or {}
        return self.job_runner.enqueue(
            MEMORY_RETRIEVAL_REFRESH_JOB_KIND,
            {
                "memory_key": memory_key,
                "content_hash": memory.get("content_hash"),
                "metadata_hash": hash_payload(
                    {
                        "title": memory.get("title"),
                        "tags": memory.get("tags") or [],
                        "project": memory.get("project"),
                        "domain": memory.get("domain"),
                        "status": memory.get("status"),
                        "canonical": memory.get("canonical"),
                        "memory_type": memory.get("memory_type"),
                        "scope": memory.get("scope"),
                        "trust_state": memory.get("trust_state"),
                        "retention_policy": memory.get("retention_policy"),
                        "sync_policy": memory.get("sync_policy"),
                        "document_id": memory.get("document_id"),
                        "source_id": memory.get("source_id"),
                        "source_document": memory.get("source_document"),
                    }
                ),
            },
            idempotency_key=(
                f"{MEMORY_RETRIEVAL_REFRESH_JOB_KIND}:"
                f"{memory_key}:{memory.get('content_hash')}:{hash_payload(memory)}"
            ),
            max_attempts=3,
        )

    def run_queued_maintenance_job(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 120,
    ) -> dict[str, Any]:
        """Acquire and process one queued Memory OS maintenance job."""
        for job_kind in (MEMORY_RETRIEVAL_REFRESH_JOB_KIND, RETRIEVAL_MANIFEST_REFRESH_JOB_KIND):
            job = self.job_runner.acquire(
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                job_kind=job_kind,
            )
            if job is None:
                continue
            try:
                if job_kind == MEMORY_RETRIEVAL_REFRESH_JOB_KIND:
                    result = self._run_memory_retrieval_refresh_job(job)
                else:
                    result = self._run_retrieval_manifest_refresh_job(job)
            except Exception as exc:  # noqa: BLE001 - worker failures are durable
                failed = self.job_runner.fail(job["job_id"], worker_id=worker_id, error=str(exc))
                return {
                    "status": failed.get("status"),
                    "worker_id": worker_id,
                    "processed": False,
                    "background_job": _job_summary(failed),
                    "error": {
                        "code": "memory_os_maintenance_failed",
                        "message": str(exc),
                        "exception_type": type(exc).__name__,
                    },
                }
            completed = self.job_runner.complete(
                job["job_id"],
                worker_id=worker_id,
                result=result,
            )
            return {
                "status": "completed",
                "worker_id": worker_id,
                "processed": True,
                "background_job": _job_summary(completed),
                "result": result,
                "error": None,
            }
        return {
            "status": "idle",
            "worker_id": worker_id,
            "processed": False,
            "error": None,
        }

    def _run_memory_retrieval_refresh_job(self, job: dict[str, Any]) -> dict[str, Any]:
        payload = dict(job.get("payload") or {})
        memory_key = _required_text(payload.get("memory_key"), "memory_key")
        memory = read_record(self.ledger, "memories", memory_key)
        if memory is None:
            return {"status": "skipped", "memory_key": memory_key, "reason": "memory_not_found"}
        chunks = self._read_chunk_records_for_memory(memory_key, memory=memory)
        retrieval_treatment = self.retrieval.upsert_chunk_records(memory_key, chunks)
        manifest_job = self._mark_retrieval_manifest_refresh_pending(
            retrieval_treatment,
            reason=MEMORY_RETRIEVAL_REFRESH_JOB_KIND,
            memory_key=memory_key,
        )
        now = now_iso()
        memory["retrieval_state"] = "indexed"
        memory["updated_at"] = now
        upsert_record(self.ledger, "memories", memory_key, memory)
        for chunk in chunks:
            chunk["retrieval_state"] = "indexed"
            chunk["updated_at"] = now
            upsert_record(self.ledger, "chunks", str(chunk["chunk_record_id"]), chunk)
        return {
            "status": "ok",
            "memory_key": memory_key,
            "retrieval_treatment": retrieval_treatment,
            "manifest_refresh_job": _job_summary(manifest_job),
        }

    def _run_retrieval_manifest_refresh_job(self, job: dict[str, Any]) -> dict[str, Any]:
        manifest = self.retrieval.refresh_manifest_from_ledger()
        self._retrieval_state = {
            "status": "ready",
            "ready": True,
            "manifest": manifest,
            "manifest_refresh_required": False,
            "error": None,
        }
        return {
            "status": "ok",
            "job_id": job.get("job_id"),
            "manifest": manifest,
        }

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
        exact_project_match: bool = False,
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
            project_values = resolve_project_filter_values(
                self.ledger,
                project,
                exact=exact_project_match,
            )
            filters["project"] = project_values if len(project_values) > 1 else project_values[0]
        if domain:
            filters["domain"] = domain
        if canonical_only:
            filters["canonical"] = True
        if not include_stale:
            filters["status"] = CURRENT_MEMORY_STATUSES
        search = (
            self.retrieval.hybrid_search(search_text, filters=filters, limit=max(int(limit), 1))
            if retrieval_mode == "hybrid"
            else self.retrieval.search(search_text, filters=filters, limit=max(int(limit), 1))
        )
        requested_tags = set(_string_list(tags))
        query_context = {
            "query": search_text,
            "project": filters.get("project"),
            "domain": filters.get("domain"),
            "retrieval_mode": retrieval_mode,
        }
        results = [
            self._activated_search_result_payload(result, query_context=query_context)
            for result in search.get("results", [])
            if _result_has_tags(result, requested_tags)
        ]
        results.sort(
            key=lambda item: (
                -float(item.get("score") or 0.0),
                -float((item.get("activation") or {}).get("activation_score") or 0.0),
            )
        )
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

    def _activated_search_result_payload(
        self,
        result: dict[str, Any],
        *,
        query_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Return one search payload annotated with rank-only activation metadata."""
        payload = _search_result_payload(result)
        key = str(payload.get("key") or "")
        memory = read_record(self.ledger, "memories", key) if key else None
        if memory is None:
            memory = {
                **dict(result.get("metadata") or {}),
                "key": key,
                "project": payload.get("project"),
                "domain": payload.get("domain"),
            }
        payload["activation"] = score_activation(memory, query_context=query_context)
        return payload

    def query_knowledge(self, request: dict[str, Any]) -> dict[str, Any]:
        """Return an EKC v0 typed project capsule response without writing memory."""
        return self.knowledge_service.query_knowledge(request)

    def discover_memory_capabilities(
        self,
        *,
        query: str = "",
        budget_chars: int = 4000,
    ) -> dict[str, Any]:
        """Return a read-only, budgeted capability catalog for agents."""
        return build_capability_catalog(self, query=query, budget_chars=budget_chars)

    def store_activation_receipt(
        self,
        *,
        query_context: dict[str, Any],
        selected_refs: list[dict[str, Any]],
        omitted_refs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Store one compact activation receipt for opt-in high-level/audit flows."""
        return store_activation_receipt_record(
            self.ledger,
            query_context=query_context,
            selected_refs=selected_refs,
            omitted_refs=omitted_refs,
        )

    def materialize_project_capsule_artifact(self, request: dict[str, Any]) -> dict[str, Any]:
        """Explicitly persist a project capsule artifact for later read-only EKC serving."""
        return self.knowledge_service.materialize_project_capsule_artifact(request)

    def prepare_document_artifact_store(
        self,
        review_packet: dict[str, Any],
        *,
        artifact_family: str = "document_evidence",
    ) -> dict[str, Any]:
        """Prepare an explicit document evidence artifact transaction."""
        return self.document_artifacts.prepare_document_artifact_store(
            review_packet,
            artifact_family=artifact_family,
        )

    def store_document_artifact(
        self,
        prepared_transaction_id: str,
        *,
        accept: bool = False,
        review_packet: dict[str, Any] | None = None,
        ingestion_id: str | None = None,
        window_index: int | None = None,
        project: str | None = None,
        domain: str | None = None,
    ) -> dict[str, Any]:
        """Store prepared document evidence artifacts only after acceptance."""
        return self.document_artifacts.store_document_artifact(
            prepared_transaction_id,
            accept=accept,
            review_packet=review_packet,
            ingestion_id=ingestion_id,
            window_index=window_index,
            project=project,
            domain=domain,
        )

    def prepare_document_ingestion_plan(self, **kwargs: Any) -> dict[str, Any]:
        """Prepare a resumable document ingestion plan."""
        return self.document_ingestion.prepare_document_ingestion_plan(**kwargs)

    def run_document_ingestion(self, **kwargs: Any) -> dict[str, Any]:
        """Run or continue a document ingestion job."""
        return self.document_ingestion.run_document_ingestion(**kwargs)

    def resume_document_ingestion(self, **kwargs: Any) -> dict[str, Any]:
        """Resume a document ingestion job from the latest checkpoint."""
        return self.document_ingestion.resume_document_ingestion(**kwargs)

    def enqueue_document_ingestion_run(self, **kwargs: Any) -> dict[str, Any]:
        """Queue accepted document ingestion work for daemon-local background execution."""
        return self.document_ingestion.enqueue_document_ingestion_run(**kwargs)

    def enqueue_document_ingestion_resume(self, **kwargs: Any) -> dict[str, Any]:
        """Queue accepted document ingestion resume work for daemon-local background execution."""
        return self.document_ingestion.enqueue_document_ingestion_run(resume=True, **kwargs)

    def run_queued_document_ingestion(self, **kwargs: Any) -> dict[str, Any]:
        """Acquire and process one queued document ingestion execution job."""
        return self.document_ingestion.run_queued_document_ingestion(**kwargs)

    def inspect_document_ingestion(self, **kwargs: Any) -> dict[str, Any]:
        """Inspect document ingestion status without writing."""
        return self.document_ingestion.inspect_document_ingestion(**kwargs)

    def prepare_document_coverage_pass(self, **kwargs: Any) -> dict[str, Any]:
        """Prepare automatic image/OCR/table coverage evidence without active writes."""
        return self.document_coverage_pass.prepare_document_coverage_pass(**kwargs)

    def prepare_knowledge_branch(self, **kwargs: Any) -> dict[str, Any]:
        """Prepare a reviewable Knowledge Branch record."""
        return self.knowledge_prs.prepare_knowledge_branch(**kwargs)

    def prepare_knowledge_pr(self, **kwargs: Any) -> dict[str, Any]:
        """Prepare a no-active-write Knowledge PR review packet."""
        return self.knowledge_prs.prepare_knowledge_pr(**kwargs)

    def run_memory_ci(self, **kwargs: Any) -> dict[str, Any]:
        """Run deterministic Memory CI gates for a Knowledge PR."""
        return self.knowledge_prs.run_memory_ci(**kwargs)

    def list_memory_benchmark_suites(self, **kwargs: Any) -> dict[str, Any]:
        """List deterministic Memory CI benchmark suites without writing."""
        return list_memory_benchmark_suites()

    def run_memory_benchmark(self, **kwargs: Any) -> dict[str, Any]:
        """Run a reproducible Memory CI benchmark suite."""
        return run_memory_benchmark_suite(self, **kwargs)

    def inspect_benchmark_run(self, **kwargs: Any) -> dict[str, Any]:
        """Inspect one persisted Memory CI benchmark run."""
        return inspect_memory_benchmark_run(self, **kwargs)

    def merge_knowledge_pr(self, **kwargs: Any) -> dict[str, Any]:
        """Merge a reviewed Knowledge PR through accepted runtime write services."""
        return self.knowledge_prs.merge_knowledge_pr(**kwargs)

    def inspect_knowledge_pr(self, **kwargs: Any) -> dict[str, Any]:
        """Inspect Knowledge PR status without writing."""
        return self.knowledge_prs.inspect_knowledge_pr(**kwargs)

    def prepare_document_ingestion_completion(
        self,
        *,
        document_id: str,
        artifact_id: str | None = None,
        visual_request: dict[str, Any] | None = None,
        visual_preview: dict[str, Any] | None = None,
        understanding_packet: dict[str, Any] | None = None,
        document_promotion_transaction: dict[str, Any] | None = None,
        coverage_waivers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Validate whether staged document evidence is ready to become usable."""
        return self.document_completion.prepare_document_ingestion_completion(
            document_id=document_id,
            artifact_id=artifact_id,
            visual_request=visual_request,
            visual_preview=visual_preview,
            understanding_packet=understanding_packet,
            document_promotion_transaction=document_promotion_transaction,
            coverage_waivers=coverage_waivers,
        )

    def complete_document_ingestion(
        self,
        *,
        document_id: str,
        artifact_id: str | None = None,
        visual_request: dict[str, Any] | None = None,
        visual_preview: dict[str, Any] | None = None,
        understanding_packet: dict[str, Any] | None = None,
        document_promotion_transaction: dict[str, Any] | None = None,
        coverage_waivers: list[dict[str, Any]] | None = None,
        accept: bool = False,
        approved_by: str | None = None,
        selected_operation_indexes: list[int] | None = None,
    ) -> dict[str, Any]:
        """Complete reviewed document ingestion and mark the document usable."""
        return self.document_completion.complete_document_ingestion(
            document_id=document_id,
            artifact_id=artifact_id,
            visual_request=visual_request,
            visual_preview=visual_preview,
            understanding_packet=understanding_packet,
            document_promotion_transaction=document_promotion_transaction,
            coverage_waivers=coverage_waivers,
            accept=accept,
            approved_by=approved_by,
            selected_operation_indexes=selected_operation_indexes,
        )

    def apply_document_promotion_transaction(
        self,
        document_promotion_transaction: dict[str, Any],
        *,
        accept: bool = False,
        approved_by: str | None = None,
        selected_operation_indexes: list[int] | None = None,
    ) -> dict[str, Any]:
        """Apply reviewed document draft promotion writes after explicit acceptance."""
        return apply_reviewed_document_promotion(
            self.ledger,
            self,
            document_promotion_transaction,
            accept=accept,
            approved_by=approved_by,
            selected_operation_indexes=selected_operation_indexes,
        )

    def prepare_graph_readiness_report(
        self,
        *,
        scope: str = "memory_os",
        project: str | None = None,
        exact_project_match: bool = False,
        domain: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return a no-write graphability inventory for Memory OS records."""
        return self.graph_pipeline.prepare_graph_readiness_report(
            scope=scope,
            project=project,
            exact_project_match=exact_project_match,
            domain=domain,
            limit=limit,
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
        """Prepare bounded evidence context and validate graph proposals without writing."""
        return self.graph_pipeline.prepare_graph_proposal_batch(
            scope=scope,
            project=project,
            domain=domain,
            source_refs=source_refs,
            limit=limit,
            budget_chars=budget_chars,
            candidate_graph_edges=candidate_graph_edges,
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
        """Promote reviewed graph proposals after explicit acceptance."""
        return self.graph_pipeline.apply_graph_proposal_batch(
            scope=scope,
            project=project,
            domain=domain,
            source_refs=source_refs,
            candidate_graph_edges=candidate_graph_edges,
            accept=accept,
            approved_by=approved_by,
            limit=limit,
            budget_chars=budget_chars,
        )

    def repair_graph_edge_refs(
        self,
        *,
        source: str | None = None,
        limit: int = 1000,
        accept: bool = False,
        approved_by: str | None = None,
    ) -> dict[str, Any]:
        """Add compact key/id ref identities to graph edges without changing meaning."""
        return self.graph_ref_repair.repair_graph_edge_refs(
            source=source,
            limit=limit,
            accept=accept,
            approved_by=approved_by,
        )

    def repair_graph_store_reconciliation(
        self,
        *,
        repair_mode: str = "upsert_missing",
        limit: int = 5000,
        accept: bool = False,
        approved_by: str | None = None,
    ) -> dict[str, Any]:
        """Replay reviewed ledger graph edges into the graph store when it drifts."""
        with self.write_lock:
            result = self.graph.repair_store_from_ledger(
                repair_mode=repair_mode,
                limit=limit,
                accept=accept,
                approved_by=approved_by,
            )
            if not result.get("graph_write_performed"):
                return result

            repaired_count = int(result.get("repaired_count") or 0)
            repaired_sample = list(result.get("repaired_edge_id_sample") or [])
            receipt = self.transactions.promote(
                operation_kind="repair_graph_store_reconciliation",
                proposed_writes=[
                    {
                        "table": "graph_store",
                        "repair_mode": repair_mode,
                        "repaired_count": repaired_count,
                        "repaired_edge_id_sample": repaired_sample,
                    }
                ],
                idempotency_key=(
                    "repair_graph_store_reconciliation:"
                    f"{repair_mode}:{hash_payload(result.get('before') or {})}:"
                    f"{hash_payload(result.get('after') or {})}"
                ),
                affected_refs=[
                    {"kind": "graph_edge", "edge_id": edge_id}
                    for edge_id in repaired_sample
                ],
            )
            return {**result, "transaction_receipt": receipt}

    def retrieve_chunk(self, key: str, chunk_id: int) -> dict[str, Any]:
        """Retrieve one Memory OS chunk by memory key and chunk id."""
        normalized_key = _required_text(key, "key")
        requested_chunk_id = int(chunk_id)
        record = read_record(self.ledger, "chunks", f"{normalized_key}:chunk:{requested_chunk_id}")
        if record is None:
            record = read_chunk_by_lookup(
                self.ledger,
                memory_key=normalized_key,
                document_id=normalized_key,
                chunk_id=requested_chunk_id,
            )
        if record is None:
            matches = [
                candidate
                for candidate in list_records(self.ledger, "chunks")
                if candidate.get("document_id") == normalized_key
                and candidate.get("chunk_id") == requested_chunk_id
            ]
            if matches:
                record = sorted(matches, key=lambda item: str(item.get("chunk_record_id") or ""))[0]
        if record is None:
            return {"key": normalized_key, "chunk_id": requested_chunk_id, "found": False, "chunk": None, "error": None}
        return {
            "key": normalized_key,
            "chunk_id": requested_chunk_id,
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
        """Update selected Memory OS memory metadata without re-embedding inline."""
        normalized_key = _required_text(key, "key")
        memory = read_record(self.ledger, "memories", normalized_key)
        if memory is None:
            return {"key": normalized_key, "updated": False, "memory": None, "error": {"code": "not_found", "message": f"Memory not found: {normalized_key}"}}
        now = now_iso()
        updated_memory = {
            **memory,
            "title": changes.get("title", memory.get("title") or normalized_key),
            "tags": _string_list(changes["tags"]) if "tags" in changes else _string_list(memory.get("tags")),
            "related_to": (
                _string_list(changes["related_to"])
                if "related_to" in changes
                else _string_list(memory.get("related_to"))
            ),
            "project": changes.get("project", memory.get("project")),
            "domain": changes.get("domain", memory.get("domain")),
            "status": changes.get("status", memory.get("status") or "active"),
            "canonical": (
                bool(changes["canonical"])
                if "canonical" in changes
                else bool(memory.get("canonical", False))
            ),
            "memory_type": changes.get("memory_type", memory.get("memory_type")),
            "scope": changes.get("scope", memory.get("scope")),
            "trust_state": changes.get("trust_state", memory.get("trust_state")),
            "retention_policy": changes.get("retention_policy", memory.get("retention_policy")),
            "sync_policy": changes.get("sync_policy", memory.get("sync_policy")),
            "updated_at": now,
            "write_state": "complete",
            "retrieval_state": "metadata_refresh_pending",
            "graph_state": "pending",
            "repair_required": False,
        }
        updated_memory = normalize_memory_payload(updated_memory)
        chunk_records = []
        for chunk in self._read_chunk_records_for_memory(normalized_key, memory=memory):
            updated_chunk = {
                **chunk,
                "title": updated_memory["title"],
                "tags": list(updated_memory["tags"]),
                "project": updated_memory["project"],
                "domain": updated_memory["domain"],
                "status": updated_memory["status"],
                "canonical": updated_memory["canonical"],
                "memory_type": updated_memory["memory_type"],
                "scope": updated_memory["scope"],
                "trust_state": updated_memory["trust_state"],
                "retention_policy": updated_memory["retention_policy"],
                "sync_policy": updated_memory["sync_policy"],
                "updated_at": now,
                "write_state": "complete",
                "retrieval_state": "metadata_refresh_pending",
                "graph_state": "pending",
                "repair_required": False,
            }
            chunk_records.append(updated_chunk)
        upsert_record(self.ledger, "memories", normalized_key, updated_memory)
        for chunk in chunk_records:
            upsert_record(self.ledger, "chunks", str(chunk["chunk_record_id"]), chunk)

        retrieval_job = self._enqueue_memory_retrieval_refresh(normalized_key)
        retrieval_treatment = {
            "source": "memory_retrieval_metadata_refresh",
            "status": "queued",
            "memory_key": normalized_key,
            "job_kind": MEMORY_RETRIEVAL_REFRESH_JOB_KIND,
            "job": _job_summary(retrieval_job),
            "indexed_inline": False,
            "manifest_refresh_required": True,
        }
        try:
            graph_treatment = graph_memory_metadata(
                ledger=self.ledger,
                graph=self.graph,
                memory=updated_memory,
                chunks=chunk_records,
            )
            semantic_graph_treatment = graph_memory_semantics(
                ledger=self.ledger,
                graph=self.graph,
                memory=updated_memory,
                chunks=chunk_records,
            )
        except Exception as exc:  # noqa: BLE001 - durable memory update already succeeded
            error = {
                "code": "memory_metadata_graph_degraded",
                "failed_gate": "metadata_graph",
                "exception_type": type(exc).__name__,
                "message": str(exc),
            }
            updated_memory.update(
                {
                    "graph_state": "repair_pending",
                    "repair_required": True,
                    "failed_gate": "metadata_graph",
                    "last_error": error,
                    "repair_guidance": (
                        f"Repair metadata graph coverage for '{normalized_key}' by retrying "
                        "the metadata update or running targeted graph repair."
                    ),
                    "updated_at": now_iso(),
                }
            )
            upsert_record(self.ledger, "memories", normalized_key, updated_memory)
            for chunk in chunk_records:
                degraded_chunk = {
                    **chunk,
                    "graph_state": "repair_pending",
                    "repair_required": True,
                    "failed_gate": "metadata_graph",
                    "updated_at": updated_memory["updated_at"],
                }
                upsert_record(self.ledger, "chunks", str(degraded_chunk["chunk_record_id"]), degraded_chunk)
            receipt = self.transactions.degraded(
                operation_kind="update_memory_metadata",
                proposed_writes=[{"table": "memories", "id": normalized_key}],
                idempotency_key=f"update_memory_metadata:{normalized_key}:{hash_payload(changes)}",
                affected_refs=[{"kind": "memory", "key": normalized_key}],
                failed_gate="metadata_graph",
                error=error,
                repair_guidance=updated_memory["repair_guidance"],
            )
            return {
                "key": normalized_key,
                "updated": True,
                "memory": {
                    **updated_memory,
                    "transaction_id": receipt["transaction_id"],
                    "transaction_receipt": receipt,
                    "retrieval_treatment": retrieval_treatment,
                    "graph_treatment": None,
                    "semantic_graph_treatment": None,
                },
                "error": error,
            }

        updated_memory["graph_state"] = "complete"
        updated_memory["metadata_graph_edge_ids"] = list(graph_treatment.get("graph_edges_written") or [])
        updated_memory["metadata_graph_concept_ids"] = list(graph_treatment.get("concepts_written") or [])
        updated_memory["metadata_graph_entity_ids"] = list(graph_treatment.get("entities_written") or [])
        updated_memory["metadata_graph_missing_related_to"] = list(
            graph_treatment.get("missing_related_to") or []
        )
        updated_memory["semantic_graph_edge_ids"] = list(
            semantic_graph_treatment.get("graph_edges_written") or []
        )
        updated_memory["semantic_graph_job_id"] = semantic_graph_treatment.get("job_id")
        upsert_record(self.ledger, "memories", normalized_key, updated_memory)
        for chunk in chunk_records:
            chunk["graph_state"] = "complete"
            upsert_record(self.ledger, "chunks", str(chunk["chunk_record_id"]), chunk)

        receipt = self.transactions.promote(
            operation_kind="update_memory_metadata",
            proposed_writes=[{"table": "memories", "id": normalized_key}],
            idempotency_key=f"update_memory_metadata:{normalized_key}:{hash_payload(changes)}",
            affected_refs=[{"kind": "memory", "key": normalized_key}],
        )
        return {
            "key": normalized_key,
            "updated": True,
            "memory": {
                **updated_memory,
                "transaction_id": receipt["transaction_id"],
                "transaction_receipt": receipt,
                "retrieval_treatment": retrieval_treatment,
                "graph_treatment": graph_treatment,
                "semantic_graph_treatment": semantic_graph_treatment,
            },
            "error": None,
        }

    def repair_memory_metadata(self, keys: list[str], *, dry_run: bool = True) -> dict[str, Any]:
        """Return simple Memory OS metadata repair receipts."""
        return self.metadata_repair.repair_memory_metadata(keys, dry_run=dry_run)

    def repair_document_metadata(
        self,
        *,
        project: str | None = None,
        document_ids: list[str] | None = None,
        accept: bool = False,
        approved_by: str | None = None,
    ) -> dict[str, Any]:
        """Review or apply project/domain/catalog metadata repairs for documents."""
        return self.metadata_repair.repair_document_metadata(
            project=project,
            document_ids=document_ids,
            accept=accept,
            approved_by=approved_by,
        )

    def delete_memory(self, key: str) -> dict[str, Any]:
        """Delete one Memory OS memory and its retrieval chunks."""
        normalized_key = _required_text(key, "key")
        memory = read_record(self.ledger, "memories", normalized_key)
        if memory is None:
            return {"key": normalized_key, "deleted": False, "error": None}
        deleted_count = self.retrieval.vector_index.delete_by_parent_key(normalized_key)
        self._delete_chunks(normalized_key, memory=memory)
        self._delete_record("memories", normalized_key)
        manifest = self.retrieval.mark_incremental_manifest_refresh_required(
            reason="delete_memory",
            parent_key=normalized_key,
            indexed_count=0,
            deleted_count=deleted_count,
        )
        manifest_job = self._mark_retrieval_manifest_refresh_pending(
            {"manifest": manifest},
            reason="delete_memory",
            memory_key=normalized_key,
        )
        receipt = self.transactions.promote(
            operation_kind="delete_memory",
            proposed_writes=[{"table": "memories", "id": normalized_key, "delete": True}],
            idempotency_key=f"delete_memory:{normalized_key}:{now_iso()}",
            affected_refs=[{"kind": "memory", "key": normalized_key}],
        )
        return {
            "key": normalized_key,
            "deleted": True,
            "retrieval_treatment": {
                "source": "delete_memory_retrieval_cleanup",
                "deleted_count": deleted_count,
                "manifest_refresh_required": True,
                "manifest_refresh_job": _job_summary(manifest_job),
            },
            "transaction_receipt": receipt,
            "error": None,
        }

    def _read_chunk_records_for_memory(
        self,
        key: str,
        *,
        memory: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        normalized_key = _required_text(key, "key")
        known_memory = memory if isinstance(memory, dict) else read_record(self.ledger, "memories", normalized_key)
        chunk_count = _optional_int((known_memory or {}).get("chunk_count"))
        records: list[dict[str, Any]] = []
        if chunk_count is not None:
            for index in range(max(chunk_count, 0)):
                record = read_record(self.ledger, "chunks", f"{normalized_key}:chunk:{index}")
                if isinstance(record, dict):
                    records.append(record)
            if len(records) == max(chunk_count, 0):
                return records
        return [
            record
            for record in list_records(self.ledger, "chunks")
            if record.get("memory_key") == normalized_key and record.get("chunk_record_id")
        ]

    def _delete_chunks(self, key: str, *, memory: dict[str, Any] | None = None) -> None:
        for record in self._read_chunk_records_for_memory(key, memory=memory):
            if record.get("chunk_record_id"):
                self._delete_record("chunks", str(record["chunk_record_id"]))

    def _delete_record(self, table: str, record_id: str) -> None:
        self.ledger.initialize()
        with self.ledger.connect() as conn:
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))  # nosec B608
            conn.commit()


def _job_summary(job: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(job, dict):
        return None
    return {
        "job_id": job.get("job_id"),
        "job_kind": job.get("job_kind"),
        "status": job.get("status"),
        "attempt": job.get("attempt"),
        "max_attempts": job.get("max_attempts"),
        "lease_owner": job.get("lease_owner"),
        "lease_expires_at": job.get("lease_expires_at"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }


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


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _compact_guardrail_treatment(treatment: dict[str, Any]) -> dict[str, Any]:
    guardrail = treatment.get("guardrail") if isinstance(treatment.get("guardrail"), dict) else {}
    receipt = treatment.get("receipt") if isinstance(treatment.get("receipt"), dict) else {}
    firewall_event = treatment.get("firewall_event") if isinstance(treatment.get("firewall_event"), dict) else {}
    return {
        "schema_version": guardrail.get("schema_version"),
        "decision": guardrail.get("decision") or "allow",
        "highest_severity": guardrail.get("highest_severity") or "none",
        "issue_codes": list(guardrail.get("issue_codes") or []),
        "receipt_id": receipt.get("receipt_id") or guardrail.get("receipt_id"),
        "firewall_event_id": firewall_event.get("event_id") or guardrail.get("firewall_event_id"),
        "reviewed_by": guardrail.get("reviewed_by"),
        "write_performed": bool(receipt or firewall_event),
        "active_memory_write_performed": False,
    }


def _complete_store_state(record: dict[str, Any]) -> bool:
    return (
        record.get("write_state") == "complete"
        and record.get("retrieval_state") == "indexed"
        and record.get("graph_state") == "complete"
        and record.get("repair_required") is not True
    )


def _matches_store_memory_request(
    record: dict[str, Any],
    *,
    content_hash: str,
    title: str,
    tags: list[str],
    related_to: list[str],
    project: str | None,
    domain: str | None,
    status: str,
    canonical: bool,
    memory_type: str,
    scope: str,
    trust_state: str,
    retention_policy: str,
    sync_policy: str,
    document_id: str | None,
    source_id: str | None,
    source_document: dict[str, Any] | None,
) -> bool:
    return (
        record.get("content_hash") == content_hash
        and record.get("title") == title
        and list(record.get("tags") or []) == tags
        and list(record.get("related_to") or []) == related_to
        and record.get("project") == project
        and record.get("domain") == domain
        and (record.get("status") or "active") == status
        and bool(record.get("canonical")) == canonical
        and record.get("memory_type") == memory_type
        and record.get("scope") == scope
        and record.get("trust_state") == trust_state
        and record.get("retention_policy") == retention_policy
        and record.get("sync_policy") == sync_policy
        and record.get("document_id") == document_id
        and record.get("source_id") == source_id
        and record.get("source_document") == source_document
    )


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
        "activation": result.get("activation"),
        "citation": result.get("citation"),
    }
