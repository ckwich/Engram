from core.graph_store import JsonGraphStore, empty_graph
from core.memory_os.graph import MemoryOSGraph
from core.memory_os._records import read_record, upsert_record
from core.memory_os.ledger import MemoryOSLedger


def _edge(edge_id, from_ref, to_ref, edge_type, evidence):
    return {
        "edge_id": edge_id,
        "from_ref": from_ref,
        "to_ref": to_ref,
        "edge_type": edge_type,
        "confidence": 0.86,
        "evidence": evidence,
        "source": "book_import",
        "status": "active",
        "created_by": "agent",
        "created_at": "2026-05-13T00:00:00-07:00",
        "updated_at": "2026-05-13T00:00:00-07:00",
    }


def test_graph_import_preserves_edge_ids_and_returns_evidence_paths(tmp_path):
    graph = MemoryOSGraph(
        MemoryOSLedger(tmp_path / "engram.sqlite"),
        graph_store=JsonGraphStore(tmp_path / "edges.json"),
    )
    edges = [
        _edge(
            "sha256:book-a",
            {"kind": "book", "key": "book_a"},
            {"kind": "concept", "key": "visual_hierarchy"},
            "defines",
            "Book A defines visual hierarchy.",
        ),
        _edge(
            "sha256:book-b",
            {"kind": "concept", "key": "visual_hierarchy"},
            {"kind": "book", "key": "book_b"},
            "applies_to",
            "Book B applies visual hierarchy.",
        ),
    ]

    report = graph.import_edges(edges)
    paths = graph.find_paths(
        {"kind": "book", "key": "book_a"},
        {"kind": "book", "key": "book_b"},
        max_hops=2,
    )

    assert report["imported_count"] == 2
    assert [edge["edge_id"] for edge in graph.load_edges()] == ["sha256:book-a", "sha256:book-b"]
    assert paths["count"] == 1
    assert [edge["edge_id"] for edge in paths["paths"][0]["edges"]] == [
        "sha256:book-a",
        "sha256:book-b",
    ]
    assert all("content" not in edge for edge in paths["paths"][0]["edges"])
    assert "Book A defines visual hierarchy." in paths["paths"][0]["evidence"][0]


def test_graph_reconciliation_reports_reconciled_ledger_and_store(tmp_path):
    graph = MemoryOSGraph(
        MemoryOSLedger(tmp_path / "engram.sqlite"),
        graph_store=JsonGraphStore(tmp_path / "edges.json"),
    )
    graph.import_edges(
        [
            _edge(
                "sha256:book-a",
                {"kind": "book", "key": "book_a"},
                {"kind": "concept", "key": "visual_hierarchy"},
                "defines",
                "Book A defines visual hierarchy.",
            )
        ]
    )

    state = graph.reconciliation_state()

    assert state["status"] == "reconciled"
    assert state["trusted_for_evidence"] is True
    assert state["repair_required"] is False
    assert state["ledger"]["edge_count"] == 1
    assert state["graph_store"]["edge_count"] == 1
    assert state["ledger"]["edge_hash"] == state["graph_store"]["edge_hash"]
    assert state["drift"]["missing_in_store_count"] == 0


def test_graph_reconciliation_reports_store_drift_without_inventing_evidence(tmp_path):
    store = JsonGraphStore(tmp_path / "edges.json")
    graph = MemoryOSGraph(MemoryOSLedger(tmp_path / "engram.sqlite"), graph_store=store)
    ledger_edge = _edge(
        "sha256:book-a",
        {"kind": "book", "key": "book_a"},
        {"kind": "concept", "key": "visual_hierarchy"},
        "defines",
        "Book A defines visual hierarchy.",
    )
    graph.import_edges([ledger_edge])
    store.save_graph(empty_graph())

    state = graph.reconciliation_state()

    assert state["status"] == "drift"
    assert state["trusted_for_evidence"] is False
    assert state["repair_required"] is True
    assert state["ledger"]["edge_count"] == 1
    assert state["graph_store"]["edge_count"] == 0
    assert state["ledger"]["edge_hash"] != state["graph_store"]["edge_hash"]
    assert state["drift"]["missing_in_store_count"] == 1
    assert state["drift"]["missing_in_store_sample"] == ["sha256:book-a"]
    assert state["repair_guidance"]["can_repair_automatically"] is False
    assert "do not synthesize" in state["repair_guidance"]["message"]


def test_graph_store_reconciliation_repair_replays_exact_missing_ledger_edges(tmp_path):
    store = JsonGraphStore(tmp_path / "edges.json")
    graph = MemoryOSGraph(MemoryOSLedger(tmp_path / "engram.sqlite"), graph_store=store)
    ledger_edge = _edge(
        "sha256:book-a",
        {"kind": "book", "key": "book_a"},
        {"kind": "concept", "key": "visual_hierarchy"},
        "defines",
        "Book A defines visual hierarchy.",
    )
    graph.import_edges([ledger_edge])
    store.save_graph(empty_graph())

    prepared = graph.repair_store_from_ledger()
    assert prepared["status"] == "prepared"
    assert prepared["candidate_count"] == 1
    assert prepared["write_performed"] is False
    assert graph.load_edges() == []

    denied = graph.repair_store_from_ledger(accept=True)
    assert denied["status"] == "policy_denied"
    assert denied["write_performed"] is False
    assert graph.load_edges() == []

    repaired = graph.repair_store_from_ledger(accept=True, approved_by="agent-review")
    replay = graph.repair_store_from_ledger()

    assert repaired["status"] == "ok"
    assert repaired["repaired_count"] == 1
    assert repaired["graph_write_performed"] is True
    assert repaired["after"]["status"] == "reconciled"
    assert graph.load_edges() == [ledger_edge]
    assert replay["status"] == "noop"


def test_graph_store_reconciliation_rebuild_can_clear_extra_store_edges(tmp_path):
    store = JsonGraphStore(tmp_path / "edges.json")
    graph = MemoryOSGraph(MemoryOSLedger(tmp_path / "engram.sqlite"), graph_store=store)
    store.save_graph(
        {
            "edges": [
                _edge(
                    "sha256:extra",
                    {"kind": "book", "key": "store_only"},
                    {"kind": "concept", "key": "orphaned"},
                    "mentions",
                    "Store-only edge should be discarded by reviewed rebuild.",
                )
            ]
        }
    )

    blocked = graph.repair_store_from_ledger(
        repair_mode="upsert_missing",
        accept=True,
        approved_by="agent-review",
    )
    rebuilt = graph.repair_store_from_ledger(
        repair_mode="rebuild_from_ledger",
        accept=True,
        approved_by="agent-review",
    )

    assert blocked["status"] == "blocked"
    assert "extra_store_edges" in blocked["blocking_reasons"]
    assert rebuilt["status"] == "ok"
    assert rebuilt["graph_write_performed"] is True
    assert rebuilt["after"]["status"] == "reconciled"
    assert rebuilt["after"]["graph_store"]["edge_count"] == 0
    assert graph.load_edges() == []


def test_graph_reconciliation_reports_mismatched_and_extra_store_edges(tmp_path):
    store = JsonGraphStore(tmp_path / "edges.json")
    graph = MemoryOSGraph(MemoryOSLedger(tmp_path / "engram.sqlite"), graph_store=store)
    ledger_edge = _edge(
        "sha256:book-a",
        {"kind": "book", "key": "book_a"},
        {"kind": "concept", "key": "visual_hierarchy"},
        "defines",
        "Book A defines visual hierarchy.",
    )
    extra_edge = _edge(
        "sha256:book-b",
        {"kind": "book", "key": "book_b"},
        {"kind": "concept", "key": "feedback_loops"},
        "defines",
        "Book B defines feedback loops.",
    )
    graph.import_edges([ledger_edge])
    store.save_graph(
        {
            "edges": [
                {**ledger_edge, "evidence": "Store evidence drifted."},
                extra_edge,
            ]
        }
    )

    state = graph.reconciliation_state()

    assert state["status"] == "drift"
    assert state["drift"]["mismatched_edge_count"] == 1
    assert state["drift"]["mismatched_edge_sample"] == ["sha256:book-a"]
    assert state["drift"]["extra_in_store_count"] == 1
    assert state["drift"]["extra_in_store_sample"] == ["sha256:book-b"]


def test_graph_reconciliation_reports_malformed_ledger_and_store_records(tmp_path):
    store = JsonGraphStore(tmp_path / "edges.json")
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    graph = MemoryOSGraph(ledger, graph_store=store)
    duplicate = _edge(
        "sha256:duplicate",
        {"kind": "book", "key": "book_a"},
        {"kind": "concept", "key": "visual_hierarchy"},
        "defines",
        "Book A defines visual hierarchy.",
    )
    missing_evidence = dict(duplicate)
    missing_evidence.pop("evidence")
    upsert_record(ledger, "graph_edges", "row:one", duplicate)
    upsert_record(ledger, "graph_edges", "row:two", {**duplicate, "source": "duplicate_source"})
    upsert_record(ledger, "graph_edges", "row:missing", missing_evidence)
    store.save_graph({"edges": [{**duplicate, "edge_id": ""}, duplicate, duplicate]})

    state = graph.reconciliation_state()

    assert state["status"] == "drift"
    assert state["trusted_for_evidence"] is False
    assert state["drift"]["duplicate_ledger_edge_id_count"] == 1
    assert state["drift"]["duplicate_ledger_edge_id_sample"] == ["sha256:duplicate"]
    assert state["drift"]["ledger_malformed_edge_count"] == 1
    assert state["drift"]["ledger_malformed_edge_sample"][0]["edge_id"] == "sha256:duplicate"
    assert state["drift"]["store_missing_edge_id_count"] == 1
    assert state["drift"]["duplicate_store_edge_id_count"] == 1
    assert state["drift"]["duplicate_store_edge_id_sample"] == ["sha256:duplicate"]


def test_graph_reconciliation_reports_read_errors_without_writes(tmp_path):
    class FailingReadStore:
        def __init__(self):
            self.saved = False
            self.upserted = False

        def load_graph(self):
            raise RuntimeError("forced graph read failure")

        def save_graph(self, graph):
            self.saved = True

        def upsert_edges(self, edges):
            self.upserted = True

    store = FailingReadStore()
    graph = MemoryOSGraph(MemoryOSLedger(tmp_path / "engram.sqlite"), graph_store=store)

    state = graph.reconciliation_state()

    assert state["status"] == "error"
    assert state["trusted_for_evidence"] is False
    assert state["repair_required"] is True
    assert state["drift"]["phase"] == "graph_store_read"
    assert store.saved is False
    assert store.upserted is False


def test_graph_conflict_paths_query_contradictions_and_supersessions(tmp_path):
    graph = MemoryOSGraph(
        MemoryOSLedger(tmp_path / "engram.sqlite"),
        graph_store=JsonGraphStore(tmp_path / "edges.json"),
    )
    graph.import_edges(
        [
            _edge(
                "sha256:contradicts",
                {"kind": "claim", "key": "new_claim"},
                {"kind": "claim", "key": "old_claim"},
                "contradicts",
                "New evidence contradicts old claim.",
            ),
            _edge(
                "sha256:supersedes",
                {"kind": "decision", "key": "new_decision"},
                {"kind": "decision", "key": "old_decision"},
                "supersedes",
                "New decision supersedes old decision.",
            ),
        ]
    )

    conflicts = graph.conflict_paths({"kind": "claim", "key": "new_claim"})
    impact = graph.impact_scan({"kind": "decision", "key": "new_decision"})

    assert conflicts["count"] == 1
    assert conflicts["paths"][0]["edges"][0]["edge_type"] == "contradicts"
    assert impact["count"] == 1
    assert impact["edges"][0]["edge_type"] == "supersedes"
    assert "content" not in impact["edges"][0]


def test_graph_import_uses_incremental_store_upsert_when_available(tmp_path):
    class IncrementalStore(JsonGraphStore):
        def __init__(self, edges_path):
            super().__init__(edges_path)
            self.upsert_batches = []
            self.save_called = False

        def save_graph(self, graph):
            self.save_called = True
            super().save_graph(graph)

        def upsert_edges(self, edges):
            self.upsert_batches.append([dict(edge) for edge in edges])
            graph = self.load_graph()
            by_id = {edge["edge_id"]: edge for edge in graph["edges"]}
            for edge in edges:
                by_id[edge["edge_id"]] = edge
            graph["edges"] = [by_id[edge_id] for edge_id in sorted(by_id)]

    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    store = IncrementalStore(tmp_path / "edges.json")
    graph = MemoryOSGraph(ledger, graph_store=store)
    edge = _edge(
        "sha256:incremental",
        {"kind": "document", "key": "book"},
        {"kind": "chunk", "key": "book:1"},
        "contains",
        "Book contains chunk 1.",
    )

    report = graph.import_edges([edge])

    assert report == {"imported_count": 1, "edge_ids": ["sha256:incremental"]}
    assert store.save_called is False
    assert store.upsert_batches == [[edge]]
    assert read_record(ledger, "graph_edges", "sha256:incremental")["edge_id"] == "sha256:incremental"
