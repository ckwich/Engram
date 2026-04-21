from __future__ import annotations

import json
import threading
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_SESSION_PINS_PATH = PROJECT_ROOT / "data" / "session_pins.json"


class SessionPinStore:
    """Persist lightweight session-scoped pinned memory keys."""

    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_SESSION_PINS_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def pin(self, session_id: str, key: str) -> list[str]:
        """Add a key to a session pin list without creating duplicates."""
        normalized_session = self._normalize_session_id(session_id)
        normalized_key = self._normalize_key(key)

        with self._lock:
            data = self._load()
            pins = data.setdefault(normalized_session, [])
            if normalized_key not in pins:
                pins.append(normalized_key)
                self._save(data)
            return list(pins)

    def unpin(self, session_id: str, key: str) -> list[str]:
        """Remove a key from a session pin list if present."""
        normalized_session = self._normalize_session_id(session_id)
        normalized_key = self._normalize_key(key)

        with self._lock:
            data = self._load()
            pins = data.get(normalized_session, [])
            updated = [pin for pin in pins if pin != normalized_key]

            if updated:
                data[normalized_session] = updated
            else:
                data.pop(normalized_session, None)

            if updated != pins or normalized_session in data or self.path.exists():
                self._save(data)

            return updated

    def list_pins(self, session_id: str) -> list[str]:
        """Return the ordered pin list for a session."""
        normalized_session = self._normalize_session_id(session_id)

        with self._lock:
            data = self._load()
            return list(data.get(normalized_session, []))

    def clear(self, session_id: str) -> list[str]:
        """Remove all pins for a session and return the empty list."""
        normalized_session = self._normalize_session_id(session_id)

        with self._lock:
            data = self._load()
            if normalized_session in data:
                data.pop(normalized_session, None)
                self._save(data)
            return []

    @staticmethod
    def _normalize_session_id(session_id: str) -> str:
        text = str(session_id).strip()
        if not text:
            raise ValueError("session_id is required")
        return text

    @staticmethod
    def _normalize_key(key: str) -> str:
        text = str(key).strip()
        if not text:
            raise ValueError("key is required")
        return text

    def _load(self) -> dict[str, list[str]]:
        if not self.path.exists():
            return {}

        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {}

        if not isinstance(payload, dict):
            return {}

        normalized: dict[str, list[str]] = {}
        for raw_session_id, raw_pins in payload.items():
            try:
                session_id = self._normalize_session_id(raw_session_id)
            except ValueError:
                continue

            pins: list[str] = []
            seen: set[str] = set()
            for raw_key in raw_pins if isinstance(raw_pins, list) else []:
                try:
                    key = self._normalize_key(raw_key)
                except ValueError:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                pins.append(key)

            if pins:
                normalized[session_id] = pins

        return normalized

    def _save(self, data: dict[str, list[str]]) -> None:
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=True)
        temp_path.replace(self.path)
