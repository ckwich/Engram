"""Lazy compatibility access to the legacy JSON/Chroma memory manager.

New daemon-owned Memory OS behavior should not import core.memory_manager
directly. Direct-mode compatibility code can enter through this adapter so the
legacy dependency stays explicit and lazy.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "get_memory_manager",
    "search_memories_legacy",
    "retrieve_memory_legacy",
    "retrieve_chunk_legacy",
    "store_memory_legacy",
    "delete_memory_legacy",
    "is_duplicate_memory_error",
    "is_chroma_availability_error",
    "get_config_value",
    "memory_manager",
]


def _load_memory_manager_module() -> Any:
    return import_module("core.memory_manager")


def get_memory_manager() -> Any:
    return _load_memory_manager_module().memory_manager


def search_memories_legacy(*args: Any, **kwargs: Any) -> Any:
    return get_memory_manager().search_memories(*args, **kwargs)


def retrieve_memory_legacy(*args: Any, **kwargs: Any) -> Any:
    return get_memory_manager().retrieve_memory(*args, **kwargs)


def retrieve_chunk_legacy(*args: Any, **kwargs: Any) -> Any:
    return get_memory_manager().retrieve_chunk(*args, **kwargs)


def store_memory_legacy(*args: Any, **kwargs: Any) -> Any:
    return get_memory_manager().store_memory(*args, **kwargs)


def delete_memory_legacy(*args: Any, **kwargs: Any) -> Any:
    return get_memory_manager().delete_memory(*args, **kwargs)


def is_duplicate_memory_error(error: BaseException) -> bool:
    duplicate_error = _load_memory_manager_module().DuplicateMemoryError
    return isinstance(error, duplicate_error)


def is_chroma_availability_error(error: Exception) -> bool:
    return bool(_load_memory_manager_module().is_chroma_availability_error(error))


def get_config_value(key: str, default: Any = None) -> Any:
    return _load_memory_manager_module()._config.get(key, default)


class _LegacyMemoryManagerProxy:
    def __getattr__(self, name: str) -> Any:
        return getattr(get_memory_manager(), name)

    def __repr__(self) -> str:
        return "<legacy memory_manager proxy>"


memory_manager = _LegacyMemoryManagerProxy()

