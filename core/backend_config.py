"""Backend selection policy for Engram's optional backend candidates.

This module records operator intent only. It must not instantiate ChromaDB,
LanceDB, Kuzu, or graph storage. Live backend switching remains blocked until
the readiness gates prove migration, parity, persistence, and daemon ownership.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_RETRIEVAL_BACKEND = "chroma"
DEFAULT_GRAPH_BACKEND = "json"
SUPPORTED_RETRIEVAL_BACKENDS = {DEFAULT_RETRIEVAL_BACKEND, "lancedb"}
SUPPORTED_GRAPH_BACKENDS = {DEFAULT_GRAPH_BACKEND, "kuzu"}


@dataclass(frozen=True)
class BackendConfig:
    """Operator-requested backend policy with safe legacy defaults."""

    retrieval_backend: str = DEFAULT_RETRIEVAL_BACKEND
    graph_backend: str = DEFAULT_GRAPH_BACKEND

    @property
    def retrieval_candidate_requested(self) -> bool:
        return self.retrieval_backend != DEFAULT_RETRIEVAL_BACKEND

    @property
    def graph_candidate_requested(self) -> bool:
        return self.graph_backend != DEFAULT_GRAPH_BACKEND

    @property
    def live_backend_switch_requested(self) -> bool:
        return self.retrieval_candidate_requested or self.graph_candidate_requested

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.update(
            {
                "retrieval_candidate_requested": self.retrieval_candidate_requested,
                "graph_candidate_requested": self.graph_candidate_requested,
                "live_backend_switch_requested": self.live_backend_switch_requested,
                "live_switch_performed": False,
                "policy": (
                    "Configuration records operator intent only; live backend "
                    "promotion remains blocked until readiness gates pass."
                ),
            }
        )
        return payload


def load_backend_config(env: dict[str, str] | None = None) -> BackendConfig:
    """Load backend policy from environment variables without side effects."""
    source = os.environ if env is None else env
    retrieval_backend = _normalize_backend(
        source.get("ENGRAM_RETRIEVAL_BACKEND"),
        default=DEFAULT_RETRIEVAL_BACKEND,
        supported=SUPPORTED_RETRIEVAL_BACKENDS,
        env_name="ENGRAM_RETRIEVAL_BACKEND",
    )
    graph_backend = _normalize_backend(
        source.get("ENGRAM_GRAPH_BACKEND"),
        default=DEFAULT_GRAPH_BACKEND,
        supported=SUPPORTED_GRAPH_BACKENDS,
        env_name="ENGRAM_GRAPH_BACKEND",
    )
    return BackendConfig(
        retrieval_backend=retrieval_backend,
        graph_backend=graph_backend,
    )


def _normalize_backend(
    value: str | None,
    *,
    default: str,
    supported: set[str],
    env_name: str,
) -> str:
    normalized = (value or default).strip().lower()
    if not normalized:
        normalized = default
    if normalized not in supported:
        options = ", ".join(sorted(supported))
        raise ValueError(f"Unsupported {env_name}: {normalized}. Expected one of: {options}")
    return normalized
