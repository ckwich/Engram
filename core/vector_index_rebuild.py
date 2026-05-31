"""Auditable vector-index rebuild helpers for the Engram Memory OS rebuild.

This module consumes already-prepared vector source records and a caller-owned
embedding function. It does not choose an embedding provider or replace live
retrieval behavior.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from core.memory_os_migration import MemoryOSMigrationKernel, _atomic_write, build_vector_index_documents
from core.vector_index import InMemoryVectorIndex, VectorIndex


REBUILD_SCHEMA_VERSION = "2026-05-11.vector_index_rebuild.v1"
DRY_RUN_SCHEMA_VERSION = "2026-05-11.vector_index_rebuild.dry_run.v1"


EmbeddingBatchFn = Callable[[list[str]], list[list[float]]]


def rebuild_vector_index_from_sources(
    index: VectorIndex,
    source_records: list[dict],
    embed_texts: EmbeddingBatchFn,
    *,
    batch_size: int = 128,
) -> dict:
    """Embed source record text in batches, rebuild an index, and return a receipt."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    embeddings_by_document_id: dict[str, list[float]] = {}
    batch_count = 0
    embedding_dimension: int | None = None

    for batch in _batched(source_records, batch_size):
        texts = [str(source["text"]) for source in batch]
        embeddings = embed_texts(texts)
        if len(embeddings) != len(texts):
            raise ValueError(
                f"embedding provider returned {len(embeddings)} embeddings for {len(texts)} texts"
            )

        batch_count += 1
        for source, embedding in zip(batch, embeddings):
            vector = [float(value) for value in embedding]
            if not vector:
                raise ValueError("embedding provider returned an empty embedding")
            if embedding_dimension is None:
                embedding_dimension = len(vector)
            elif len(vector) != embedding_dimension:
                raise ValueError("embedding dimensions must be consistent")
            embeddings_by_document_id[str(source["document_id"])] = vector

    documents = build_vector_index_documents(source_records, embeddings_by_document_id)
    index.rebuild(documents)

    return {
        "schema_version": REBUILD_SCHEMA_VERSION,
        "status": "pass",
        "source_count": len(source_records),
        "embedded_count": len(embeddings_by_document_id),
        "document_count": len(documents),
        "batch_count": batch_count,
        "embedding_dimension": embedding_dimension or 0,
        "document_ids": [document.document_id for document in documents],
        "index_stats": index.stats(),
    }


def run_vector_index_rebuild_dry_run(
    store_root: str | Path,
    *,
    report_path: str | Path | None = None,
    batch_size: int = 128,
) -> dict:
    """Validate rebuild plumbing against a migrated ledger without live backend writes."""
    kernel = MemoryOSMigrationKernel(store_root)
    sources = kernel.read_vector_source_records()
    index = InMemoryVectorIndex()
    receipt = rebuild_vector_index_from_sources(
        index,
        sources,
        _deterministic_dry_run_embeddings,
        batch_size=batch_size,
    )
    report = {
        "schema_version": DRY_RUN_SCHEMA_VERSION,
        "mode": "dry_run",
        "store_root": str(Path(store_root)),
        "embedding_provider": "deterministic_dry_run_stub",
        "source_count": len(sources),
        "rebuild_receipt": receipt,
    }

    if report_path is not None:
        encoded = (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        _atomic_write(Path(report_path), encoded)

    return report


def _batched(items: list[dict], batch_size: int) -> list[list[dict]]:
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def _deterministic_dry_run_embeddings(texts: list[str]) -> list[list[float]]:
    return [
        [
            float(len(text) % 997),
            float(sum(text.encode("utf-8")) % 997),
        ]
        for text in texts
    ]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m core.vector_index_rebuild",
        description="Engram Memory OS vector-index rebuild utilities.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry_run = subparsers.add_parser(
        "dry-run",
        help="Validate vector source rebuild plumbing without writing a live backend.",
    )
    dry_run.add_argument("--store-root", required=True, help="Migrated Memory OS store root.")
    dry_run.add_argument("--report", help="Optional JSON report path.")
    dry_run.add_argument("--batch-size", type=int, default=128, help="Embedding batch size.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "dry-run":
        report = run_vector_index_rebuild_dry_run(
            args.store_root,
            report_path=args.report,
            batch_size=args.batch_size,
        )
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
