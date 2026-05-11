from __future__ import annotations

from core.vector_index import InMemoryVectorIndex, VectorIndexDocument, VectorIndexQuery


def test_in_memory_vector_index_returns_ranked_cited_chunks_with_filters():
    index = InMemoryVectorIndex()
    index.rebuild(
        [
            VectorIndexDocument(
                document_id="alpha-0",
                parent_key="alpha",
                chunk_id=0,
                text="Alpha migration notes",
                embedding=[1.0, 0.0],
                metadata={"project": "Engram", "domain": "migration"},
                citation={"source": "memory", "key": "alpha", "chunk_id": 0},
            ),
            VectorIndexDocument(
                document_id="beta-0",
                parent_key="beta",
                chunk_id=0,
                text="Beta design notes",
                embedding=[0.0, 1.0],
                metadata={"project": "Engram", "domain": "design"},
                citation={"source": "memory", "key": "beta", "chunk_id": 0},
            ),
            VectorIndexDocument(
                document_id="external-0",
                parent_key="external",
                chunk_id=0,
                text="External migration notes",
                embedding=[1.0, 0.0],
                metadata={"project": "Other", "domain": "migration"},
                citation={"source": "memory", "key": "external", "chunk_id": 0},
            ),
        ]
    )

    results = index.search(
        VectorIndexQuery(
            query_text="migration",
            query_embedding=[1.0, 0.0],
            limit=5,
            filters={"project": "Engram"},
        )
    )

    assert [result.document_id for result in results] == ["alpha-0", "beta-0"]
    assert results[0].score > results[1].score
    assert results[0].parent_key == "alpha"
    assert results[0].chunk_id == 0
    assert results[0].citation == {"source": "memory", "key": "alpha", "chunk_id": 0}


def test_in_memory_vector_index_rebuild_replaces_prior_documents():
    index = InMemoryVectorIndex()
    index.rebuild(
        [
            VectorIndexDocument(
                document_id="old-0",
                parent_key="old",
                chunk_id=0,
                text="Old text",
                embedding=[1.0],
            )
        ]
    )

    index.rebuild(
        [
            VectorIndexDocument(
                document_id="new-0",
                parent_key="new",
                chunk_id=0,
                text="New text",
                embedding=[1.0],
            )
        ]
    )

    results = index.search(VectorIndexQuery(query_text="new", query_embedding=[1.0], limit=10))

    assert [result.document_id for result in results] == ["new-0"]
    assert index.stats() == {"document_count": 1}


def test_in_memory_vector_index_delete_by_parent_key_removes_all_chunks():
    index = InMemoryVectorIndex()
    index.rebuild(
        [
            VectorIndexDocument(
                document_id="alpha-0",
                parent_key="alpha",
                chunk_id=0,
                text="Alpha chunk 0",
                embedding=[1.0],
            ),
            VectorIndexDocument(
                document_id="alpha-1",
                parent_key="alpha",
                chunk_id=1,
                text="Alpha chunk 1",
                embedding=[1.0],
            ),
            VectorIndexDocument(
                document_id="beta-0",
                parent_key="beta",
                chunk_id=0,
                text="Beta chunk 0",
                embedding=[1.0],
            ),
        ]
    )

    deleted = index.delete_by_parent_key("alpha")
    results = index.search(VectorIndexQuery(query_text="all", query_embedding=[1.0], limit=10))

    assert deleted == 2
    assert [result.document_id for result in results] == ["beta-0"]
    assert index.stats() == {"document_count": 1}


def test_in_memory_vector_index_hybrid_mode_promotes_exact_identifiers():
    index = InMemoryVectorIndex()
    index.rebuild(
        [
            VectorIndexDocument(
                document_id="semantic-0",
                parent_key="semantic",
                chunk_id=0,
                text="General mapping guidance without the exact tool name.",
                embedding=[1.0, 0.0],
            ),
            VectorIndexDocument(
                document_id="identifier-0",
                parent_key="identifier",
                chunk_id=0,
                text="Use prepare_codebase_mapping before storing mapped repo context.",
                embedding=[0.7, 0.7],
                metadata={"tool": "prepare_codebase_mapping"},
            ),
        ]
    )

    semantic_results = index.search(
        VectorIndexQuery(
            query_text="prepare_codebase_mapping",
            query_embedding=[1.0, 0.0],
            limit=2,
        )
    )
    hybrid_results = index.search(
        VectorIndexQuery(
            query_text="prepare_codebase_mapping",
            query_embedding=[1.0, 0.0],
            limit=2,
            retrieval_mode="hybrid",
        )
    )

    assert [result.document_id for result in semantic_results] == ["semantic-0", "identifier-0"]
    assert [result.document_id for result in hybrid_results] == ["identifier-0", "semantic-0"]
