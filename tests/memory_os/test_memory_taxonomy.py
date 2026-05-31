from core.memory_os._records import read_record
from core.graph_store import JsonGraphStore
from core.memory_os.memory_taxonomy import (
    MemoryClassification,
    classify_memory_request,
    normalize_memory_payload,
    normalize_memory_type,
    normalize_scope,
    normalize_trust_state,
)
from core.memory_os.runtime import MemoryOSRuntime
from core.memory_os.schema import (
    MEMORY_SCOPES,
    MEMORY_TYPES,
    RETENTION_POLICIES,
    SYNC_CONDITIONAL_TABLES,
    SYNC_ELIGIBLE_TABLES,
    SYNC_LOCAL_ONLY_TABLES,
    SYNC_POLICIES,
    TABLES,
    TRUST_STATES,
)
from core.vector_index import InMemoryVectorIndex


def _runtime(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path / "memory_os",
        embed_text=lambda text: [0.1, 0.2],
        vector_index=InMemoryVectorIndex(),
        graph_store=JsonGraphStore(tmp_path / "edges.json"),
    )
    runtime.initialize(rebuild_retrieval=False)
    return runtime


def test_schema_declares_native_taxonomy_and_sync_contracts():
    assert "decision" in MEMORY_TYPES
    assert "document_claim" in MEMORY_TYPES
    assert "project" in MEMORY_SCOPES
    assert "workspace" in MEMORY_SCOPES
    assert "source_backed" in TRUST_STATES
    assert "quarantined" in TRUST_STATES
    assert "local_only" in RETENTION_POLICIES
    assert "ephemeral" in RETENTION_POLICIES
    assert "sync" in SYNC_POLICIES
    assert "quarantined" in SYNC_POLICIES
    assert "memories" in SYNC_ELIGIBLE_TABLES
    assert "drafts" in SYNC_CONDITIONAL_TABLES
    assert "firewall_events" in SYNC_LOCAL_ONLY_TABLES
    assert "memory_type_receipts" in TABLES
    assert "sync_transport_receipts" in TABLES


def test_normalize_known_memory_type_scope_and_trust_state():
    assert normalize_memory_type("Decision") == "decision"
    assert normalize_scope("Project") == "project"
    assert normalize_trust_state("Source Backed") == "source_backed"


def test_unknown_memory_type_is_rejected():
    try:
        normalize_memory_type("vibes")
    except ValueError as exc:
        assert "unknown memory_type" in str(exc)
    else:
        raise AssertionError("unknown memory_type must fail")


def test_unknown_scope_and_trust_state_are_rejected():
    for normalizer, value, expected in (
        (normalize_scope, "planet", "unknown memory scope"),
        (normalize_trust_state, "maybe", "unknown trust_state"),
    ):
        try:
            normalizer(value)
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError(f"{value} must fail")


def test_classify_memory_request_defaults_to_fact_and_project_scope():
    classification = classify_memory_request(
        {
            "key": "engram_runtime_choice",
            "content": "Use engramd as the single writer.",
            "project": "/Users/example/Projects/Engram",
            "domain": "runtime",
            "tags": ["decision"],
        }
    )

    assert isinstance(classification, MemoryClassification)
    assert classification.memory_type == "decision"
    assert classification.scope == "project"
    assert classification.trust_state == "reviewed"
    assert classification.retention_policy == "standard"
    assert classification.sync_policy == "sync"


def test_classify_document_source_memory_as_document_claim_and_scope():
    classification = classify_memory_request(
        {
            "key": "doc_mem_game_design",
            "content": "The document argues that feedback loops shape game feel.",
            "tags": ["document-intelligence"],
            "project": "/Users/example/Projects/Engram",
            "source_document": {
                "document_id": "doc_advanced_game_design",
                "source_uri": "/projects/Design Books/PDF/Advanced Game Design.pdf",
            },
        }
    )

    assert classification.memory_type == "document_claim"
    assert classification.scope == "document"
    assert classification.trust_state == "reviewed"
    assert classification.sync_policy == "sync"


def test_normalize_memory_payload_preserves_callers_and_defaults_missing_fields():
    normalized = normalize_memory_payload(
        {
            "key": "device-local-note",
            "content": "Local device state.",
            "memory_type": "Project State",
            "scope": "Device",
            "trust_state": "Unreviewed",
            "retention_policy": "local_only",
        }
    )

    assert normalized["memory_type"] == "project_state"
    assert normalized["scope"] == "device"
    assert normalized["trust_state"] == "unreviewed"
    assert normalized["retention_policy"] == "local_only"
    assert normalized["sync_policy"] == "local_only"


def test_runtime_store_memory_writes_taxonomy_defaults_for_old_callers(tmp_path):
    runtime = _runtime(tmp_path)

    stored = runtime.store_memory(
        key="runtime-choice",
        content="Use engramd as the single writer.",
        tags=["decision"],
        project="/Users/example/Projects/Engram",
    )
    memory = read_record(runtime.ledger, "memories", "runtime-choice")
    chunks = runtime._read_chunk_records_for_memory("runtime-choice", memory=memory)

    assert stored["memory_type"] == "decision"
    assert memory["scope"] == "project"
    assert memory["trust_state"] == "reviewed"
    assert memory["retention_policy"] == "standard"
    assert memory["sync_policy"] == "sync"
    assert chunks
    assert chunks[0]["memory_type"] == "decision"
    assert chunks[0]["scope"] == "project"


def test_runtime_store_memory_accepts_explicit_taxonomy_fields(tmp_path):
    runtime = _runtime(tmp_path)

    stored = runtime.store_memory(
        key="workspace-procedure",
        content="Run the focused gate before claiming Task 1.",
        memory_type="procedure",
        scope="workspace",
        trust_state="source_backed",
        retention_policy="pinned",
    )

    assert stored["memory_type"] == "procedure"
    assert stored["scope"] == "workspace"
    assert stored["trust_state"] == "source_backed"
    assert stored["retention_policy"] == "pinned"
    assert stored["sync_policy"] == "sync"


def test_document_promotion_preserves_document_taxonomy_evidence(tmp_path):
    runtime = _runtime(tmp_path)
    transaction = {
        "record_type": "document_promotion_transaction",
        "transaction_id": "doc_promote_taxonomy",
        "operations": [
            {
                "kind": "memory",
                "payload": {
                    "key": "doc_mem_feedback_loops",
                    "title": "Document Draft: Advanced Game Design",
                    "content": "The document argues that feedback loops shape game feel.",
                    "tags": ["document-intelligence"],
                    "project": "/Users/example/Projects/Engram",
                    "source_document": {
                        "document_id": "doc_advanced_game_design",
                        "source_uri": "/projects/Design Books/PDF/Advanced Game Design.pdf",
                    },
                },
            }
        ],
    }

    result = runtime.apply_document_promotion_transaction(
        transaction,
        accept=True,
        approved_by="tester",
    )
    stored = read_record(runtime.ledger, "memories", "doc_mem_feedback_loops")

    assert result["status"] == "ok"
    assert stored["memory_type"] == "document_claim"
    assert stored["scope"] == "document"
    assert stored["source_document"]["document_id"] == "doc_advanced_game_design"
