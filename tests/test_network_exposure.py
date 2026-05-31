from __future__ import annotations

import os
import subprocess
import sys

import engramd
from core.network_exposure import PublicBindDenied, validate_raw_service_bind


def test_raw_service_bind_allows_loopback_without_ack(monkeypatch):
    monkeypatch.delenv("ENGRAM_ALLOW_PUBLIC_BIND", raising=False)

    validate_raw_service_bind("127.0.0.1", surface="test daemon")
    validate_raw_service_bind("localhost", surface="test daemon")


def test_raw_service_bind_blocks_public_host_without_ack(monkeypatch):
    monkeypatch.delenv("ENGRAM_ALLOW_PUBLIC_BIND", raising=False)

    try:
        validate_raw_service_bind("0.0.0.0", surface="test daemon")
    except PublicBindDenied as exc:
        assert "ENGRAM_ALLOW_PUBLIC_BIND" in str(exc)
    else:
        raise AssertionError("public bind should be denied")


def test_raw_service_bind_blocks_blank_and_unspecified_hosts_without_ack(monkeypatch):
    monkeypatch.delenv("ENGRAM_ALLOW_PUBLIC_BIND", raising=False)

    for host in ("", None, "::", "0.0.0.0"):
        try:
            validate_raw_service_bind(host, surface="test daemon")
        except PublicBindDenied:
            continue
        raise AssertionError(f"public bind should be denied for host {host!r}")


def test_raw_service_bind_rejects_casual_truthy_ack(monkeypatch):
    monkeypatch.setenv("ENGRAM_ALLOW_PUBLIC_BIND", "true")

    try:
        validate_raw_service_bind("0.0.0.0", surface="test daemon")
    except PublicBindDenied:
        return
    raise AssertionError("generic truthy public-bind acknowledgement should be denied")


def test_raw_service_bind_allows_explicit_ack(monkeypatch):
    monkeypatch.setenv("ENGRAM_ALLOW_PUBLIC_BIND", "loopback-published")

    validate_raw_service_bind("0.0.0.0", surface="test daemon")


def test_engramd_main_blocks_public_bind_before_start(monkeypatch, capsys):
    called = False

    def fake_run_daemon(host, port):
        nonlocal called
        called = True

    monkeypatch.delenv("ENGRAM_ALLOW_PUBLIC_BIND", raising=False)
    monkeypatch.setattr(engramd, "run_daemon", fake_run_daemon)

    result = engramd.main(["--host", "0.0.0.0", "--port", "9876"])

    captured = capsys.readouterr()
    assert result == 2
    assert called is False
    assert "ENGRAM_ALLOW_PUBLIC_BIND" in captured.err


def test_server_sse_blocks_public_bind_before_runtime_start(monkeypatch):
    env = os.environ.copy()
    env.pop("ENGRAM_ALLOW_PUBLIC_BIND", None)
    env.pop("ENGRAM_DAEMON_URL", None)

    result = subprocess.run(
        [
            sys.executable,
            "server.py",
            "--transport",
            "sse",
            "--host",
            "0.0.0.0",
            "--port",
            "9876",
        ],
        cwd=".",
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 2
    assert "ENGRAM_ALLOW_PUBLIC_BIND" in result.stderr
    assert "Pre-loading embedding model" not in result.stderr
