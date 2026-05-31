"""Cryptographic helpers for Memory OS sync identities and bundles."""
from __future__ import annotations

import base64
import getpass
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


LOCAL_SYNC_IDENTITY_FILE = "local_sync_identity.json"


@dataclass(frozen=True)
class LocalSyncKeys:
    signing_private_key: str
    signing_public_key: str
    exchange_private_key: str
    exchange_public_key: str


def load_or_create_local_sync_keys(keys_dir: str | Path) -> LocalSyncKeys:
    """Load local sync keys from disk, creating them with owner-only permissions."""
    path = Path(keys_dir) / LOCAL_SYNC_IDENTITY_FILE
    if path.exists():
        _repair_key_file_permissions(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _keys_from_payload(payload)
    keys = generate_local_sync_keys()
    _write_key_file(path, keys)
    return keys


def load_local_sync_keys(keys_dir: str | Path) -> LocalSyncKeys:
    """Load existing local sync keys without creating key material."""
    path = Path(keys_dir) / LOCAL_SYNC_IDENTITY_FILE
    if not path.exists():
        raise FileNotFoundError(f"local sync key file is missing: {path}")
    _repair_key_file_permissions(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _keys_from_payload(payload)


def rotate_local_sync_key_file(keys_dir: str | Path) -> LocalSyncKeys:
    """Generate and persist fresh local sync keys."""
    keys = generate_local_sync_keys()
    _write_key_file(Path(keys_dir) / LOCAL_SYNC_IDENTITY_FILE, keys)
    return keys


def generate_local_sync_keys() -> LocalSyncKeys:
    """Generate a fresh Ed25519 signing key and X25519 exchange key."""
    signing_private = ed25519.Ed25519PrivateKey.generate()
    exchange_private = x25519.X25519PrivateKey.generate()
    return LocalSyncKeys(
        signing_private_key=_b64(
            signing_private.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )
        ),
        signing_public_key=_b64(
            signing_private.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ),
        exchange_private_key=_b64(
            exchange_private.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            )
        ),
        exchange_public_key=_b64(
            exchange_private.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ),
    )


def sign_payload(payload_bytes: bytes, signing_private_key: str) -> str:
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(_unb64(signing_private_key))
    return "ed25519:" + _b64(private_key.sign(payload_bytes))


def verify_payload(payload_bytes: bytes, signature: str, public_key: str) -> bool:
    signature_bytes = _unprefixed_b64(signature, "ed25519")
    public_key_bytes = _unprefixed_b64(public_key, "ed25519")
    try:
        ed25519.Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
            signature_bytes,
            payload_bytes,
        )
    except InvalidSignature:
        return False
    return True


def encrypt_for_peer(
    payload_bytes: bytes,
    local_exchange_private_key: str,
    peer_exchange_public_key: str,
    *,
    aad: bytes | None = None,
) -> dict[str, Any]:
    """Encrypt bytes for a peer using X25519, HKDF, and AES-GCM."""
    local_private = x25519.X25519PrivateKey.from_private_bytes(_unb64(local_exchange_private_key))
    peer_public = x25519.X25519PublicKey.from_public_bytes(
        _unprefixed_b64(peer_exchange_public_key, "x25519")
    )
    key = _derive_shared_key(local_private.exchange(peer_public))
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, payload_bytes, aad)
    return {
        "schema_version": "2026-05-26.sync-encryption.v1",
        "algorithm": "x25519-hkdf-sha256-aesgcm",
        "nonce": _b64(nonce),
        "ciphertext": _b64(ciphertext),
    }


def decrypt_from_peer(
    envelope: dict[str, Any],
    local_exchange_private_key: str,
    source_exchange_public_key: str,
    *,
    aad: bytes | None = None,
) -> bytes:
    local_private = x25519.X25519PrivateKey.from_private_bytes(_unb64(local_exchange_private_key))
    source_public = x25519.X25519PublicKey.from_public_bytes(
        _unprefixed_b64(source_exchange_public_key, "x25519")
    )
    key = _derive_shared_key(local_private.exchange(source_public))
    return AESGCM(key).decrypt(
        _unb64(str(envelope.get("nonce") or "")),
        _unb64(str(envelope.get("ciphertext") or "")),
        aad,
    )


def decrypt_sync_bundle(runtime: Any, bundle_bytes: bytes) -> dict[str, Any]:
    """Decrypt and verify a sync bundle for this runtime."""
    from core.memory_os._records import read_record
    from core.memory_os.sync_identity import LOCAL_DEVICE_RECORD_ID

    bundle = json.loads(bundle_bytes.decode("utf-8"))
    envelope = bundle.get("envelope") if isinstance(bundle, dict) else None
    if not isinstance(envelope, dict) or envelope.get("encrypted") is not True:
        raise ValueError("invalid sync bundle envelope")
    source_device_id = str(envelope.get("source_device_id") or "")
    source_peer = read_record(runtime.ledger, "sync_devices", f"sync_device:peer:{source_device_id}")
    if not source_peer or source_peer.get("status") != "active":
        raise ValueError("sync bundle source peer is not registered")
    local_device = read_record(runtime.ledger, "sync_devices", LOCAL_DEVICE_RECORD_ID)
    if local_device and envelope.get("target_device_id") != local_device.get("device_id"):
        raise ValueError("sync bundle target does not match local device")
    if envelope.get("source_signing_key_fingerprint") != source_peer.get("signing_key_fingerprint"):
        raise ValueError("sync bundle signing key fingerprint mismatch")
    if envelope.get("source_exchange_key_fingerprint") != source_peer.get("exchange_key_fingerprint"):
        raise ValueError("sync bundle exchange key fingerprint mismatch")

    local_keys = load_local_sync_keys(runtime.root / "keys")
    aad = {
        "schema_version": envelope.get("schema_version"),
        "source_device_id": envelope.get("source_device_id"),
        "target_device_id": envelope.get("target_device_id"),
        "source_signing_public_key": envelope.get("source_signing_public_key"),
        "source_exchange_public_key": envelope.get("source_exchange_public_key"),
        "source_signing_key_fingerprint": envelope.get("source_signing_key_fingerprint"),
        "source_exchange_key_fingerprint": envelope.get("source_exchange_key_fingerprint"),
        "target_exchange_key_fingerprint": envelope.get("target_exchange_key_fingerprint"),
        "signature": envelope.get("signature"),
    }
    signed_bytes = decrypt_from_peer(
        envelope,
        local_keys.exchange_private_key,
        str(source_peer["exchange_public_key"]),
        aad=_canonical_json_bytes(aad),
    )
    signed_payload = json.loads(signed_bytes.decode("utf-8"))
    payload = signed_payload.get("payload")
    signature = str(signed_payload.get("signature") or "")
    if signature != envelope.get("signature"):
        raise ValueError("sync bundle signature mismatch")
    if not verify_payload(_canonical_json_bytes(payload), signature, str(source_peer["signing_public_key"])):
        raise ValueError("sync bundle signature verification failed")
    if not isinstance(payload, dict):
        raise ValueError("sync bundle payload is invalid")
    return payload


def _derive_shared_key(shared_secret: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"engram-memory-os-sync-v1",
    ).derive(shared_secret)


def _write_key_file(path: Path, keys: LocalSyncKeys) -> None:
    if path.is_symlink():
        raise PermissionError(f"refusing to write sync key file through symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "2026-05-26.sync-local-keys.v1",
        "signing_private_key": keys.signing_private_key,
        "signing_public_key": keys.signing_public_key,
        "exchange_private_key": keys.exchange_private_key,
        "exchange_public_key": keys.exchange_public_key,
    }
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        if os.name == "posix":
            os.chmod(temp_path, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _repair_key_file_permissions(temp_path)
        temp_path.replace(path)
        _repair_key_file_permissions(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _repair_key_file_permissions(path: Path) -> None:
    if path.is_symlink():
        raise PermissionError(f"refusing to load sync key file through symlink: {path}")
    if os.name == "posix":
        os.chmod(path, 0o600)
    elif os.name == "nt":
        _repair_windows_key_file_acl(path)


def _repair_windows_key_file_acl(path: Path) -> None:
    user = getpass.getuser()
    completed = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(F)"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise PermissionError(f"failed to harden sync key ACL: {completed.stderr.strip()}")


def _keys_from_payload(payload: dict[str, Any]) -> LocalSyncKeys:
    return LocalSyncKeys(
        signing_private_key=str(payload["signing_private_key"]),
        signing_public_key=str(payload["signing_public_key"]),
        exchange_private_key=str(payload["exchange_private_key"]),
        exchange_public_key=str(payload["exchange_public_key"]),
    )


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    text = str(value or "").strip()
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))


def _unprefixed_b64(value: str, expected_prefix: str) -> bytes:
    prefix = expected_prefix + ":"
    text = str(value or "")
    if text.startswith(prefix):
        text = text[len(prefix) :]
    return _unb64(text)


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
