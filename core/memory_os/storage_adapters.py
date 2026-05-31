"""Local storage adapter facades for Memory OS runtime seams."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from core.memory_os._records import list_records, read_record, upsert_record
from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.schema import TABLES


@dataclass(frozen=True)
class RecordWriteReceipt:
    table: str
    record_id: str
    status: str = "upserted"


@dataclass(frozen=True)
class RecordDeleteReceipt:
    table: str
    record_id: str
    deleted: bool


@dataclass(frozen=True)
class ArtifactDescriptor:
    artifact_id: str
    digest: str
    size_bytes: int
    local_path: Path | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "local_path": str(self.local_path) if self.local_path is not None else None,
        }


class RecordLedger(Protocol):
    """Minimal record-ledger contract for runtime adapter seams."""

    def initialize(self) -> None:
        ...

    def upsert_record(
        self,
        table: str,
        record_id: str,
        payload: dict[str, Any],
    ) -> RecordWriteReceipt:
        ...

    def read_record(self, table: str, record_id: str) -> dict[str, Any] | None:
        ...

    def list_records(
        self,
        table: str,
        *,
        filters: Mapping[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        ...

    def delete_record(self, table: str, record_id: str) -> RecordDeleteReceipt:
        ...


class ArtifactStore(Protocol):
    """Minimal content-addressed artifact contract for runtime adapter seams."""

    def put_bytes(self, data: bytes, *, suffix: str = "") -> str:
        ...

    def read_bytes(self, artifact_id: str) -> bytes:
        ...

    def describe(self, artifact_id: str) -> ArtifactDescriptor:
        ...

    def verify(self, artifact_id: str) -> ArtifactDescriptor:
        ...


class LocalRecordLedger:
    """RecordLedger facade over the current SQLite JSON-record helpers."""

    def __init__(self, ledger: MemoryOSLedger | str | Path) -> None:
        self.ledger = ledger if isinstance(ledger, MemoryOSLedger) else MemoryOSLedger(ledger)

    @property
    def path(self) -> Path:
        return self.ledger.path

    def initialize(self) -> None:
        self.ledger.initialize()

    def upsert_record(
        self,
        table: str,
        record_id: str,
        payload: dict[str, Any],
    ) -> RecordWriteReceipt:
        table = _validate_table(table)
        upsert_record(self.ledger, table, record_id, payload)
        return RecordWriteReceipt(table=table, record_id=record_id)

    def read_record(self, table: str, record_id: str) -> dict[str, Any] | None:
        return read_record(self.ledger, _validate_table(table), record_id)

    def list_records(
        self,
        table: str,
        *,
        filters: Mapping[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        records = list_records(self.ledger, _validate_table(table))
        if filters:
            records = [
                record
                for record in records
                if all(record.get(key) == value for key, value in filters.items())
            ]
        if limit is not None:
            if limit < 0:
                raise ValueError("limit must be non-negative")
            records = records[:limit]
        return records

    def delete_record(self, table: str, record_id: str) -> RecordDeleteReceipt:
        table = _validate_table(table)
        self.ledger.initialize()
        with self.ledger.connect() as conn:
            cursor = conn.execute(
                f"DELETE FROM {table} WHERE id = ?",  # nosec B608
                (record_id,),
            )
            conn.commit()
        return RecordDeleteReceipt(
            table=table,
            record_id=record_id,
            deleted=cursor.rowcount > 0,
        )


class LocalArtifactStore:
    """ArtifactStore facade over the current content-addressed filesystem store."""

    def __init__(self, store: ContentAddressedStore | str | Path) -> None:
        self.store = store if isinstance(store, ContentAddressedStore) else ContentAddressedStore(store)

    @property
    def root(self) -> Path:
        return self.store.root

    def put_bytes(self, data: bytes, *, suffix: str = "") -> str:
        return self.store.put_bytes(data, suffix=suffix)

    def write_bytes(self, data: bytes, *, suffix: str = "") -> ArtifactDescriptor:
        artifact_id = self.put_bytes(data, suffix=suffix)
        return self.describe(artifact_id)

    def read_bytes(self, artifact_id: str) -> bytes:
        return self.store.read_bytes(artifact_id)

    def path_for(self, artifact_id: str) -> Path:
        return self.store.path_for(artifact_id)

    def describe(self, artifact_id: str) -> ArtifactDescriptor:
        path = self.path_for(artifact_id)
        digest = _digest_from_artifact_id(artifact_id)
        size_bytes = path.stat().st_size
        return ArtifactDescriptor(
            artifact_id=artifact_id,
            digest=f"sha256:{digest}",
            size_bytes=size_bytes,
            local_path=path,
        )

    def verify(self, artifact_id: str) -> ArtifactDescriptor:
        data = self.read_bytes(artifact_id)
        expected = _digest_from_artifact_id(artifact_id)
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise ValueError("artifact digest mismatch")
        return self.describe(artifact_id)


def _validate_table(table: str) -> str:
    table = str(table)
    if table not in TABLES:
        raise ValueError(f"unknown Memory OS table: {table}")
    return table


def _digest_from_artifact_id(artifact_id: str) -> str:
    text = str(artifact_id)
    if not text.startswith("sha256:"):
        raise ValueError("invalid artifact id")
    digest = text.removeprefix("sha256:")[:64]
    if len(digest) != 64 or not all(char in "0123456789abcdef" for char in digest):
        raise ValueError("invalid artifact id")
    return digest
