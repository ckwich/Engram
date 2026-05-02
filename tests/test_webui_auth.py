from __future__ import annotations

from pathlib import Path
import re


ACCESS_TOKEN = "a" * 32
WRITE_TOKEN = "b" * 32
WRONG_TOKEN = "c" * 32
ROTATED_ACCESS_TOKEN = "d" * 32
REMOTE_HOST = "engram.tailnet.test"
REMOTE_ORIGIN = f"http://{REMOTE_HOST}:5000"
INLINE_HTML_ATTR_PATTERN = re.compile(r"\s(?:on[a-z]+|style)=", re.IGNORECASE)


def test_loopback_mutation_is_allowed_without_write_token(monkeypatch):
    import webui

    calls = []

    class FakeMemoryManager:
        def store_memory(self, **kwargs):
            calls.append(kwargs)
            return {"stored": True, "key": kwargs["key"]}

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "127.0.0.1")
    monkeypatch.delenv("ENGRAM_WEBUI_WRITE_TOKEN", raising=False)
    monkeypatch.setattr(webui, "memory_manager", FakeMemoryManager())

    response = webui.app.test_client().post(
        "/api/memory",
        json={"key": "local", "content": "Local writes stay frictionless."},
    )

    assert response.status_code == 201
    assert response.get_json() == {"stored": True, "key": "local"}
    assert calls[0]["key"] == "local"


def test_public_host_blocks_mutation_without_configured_write_token(monkeypatch):
    import webui

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.delenv("ENGRAM_WEBUI_WRITE_TOKEN", raising=False)

    response = webui.app.test_client().post(
        "/api/memory",
        headers={"X-Engram-Access-Token": ACCESS_TOKEN},
        json={"key": "blocked", "content": "This write should not reach storage."},
    )

    assert response.status_code == 503
    assert "ENGRAM_WEBUI_WRITE_TOKEN" in response.get_json()["error"]


def test_public_host_rejects_wrong_write_token(monkeypatch):
    import webui

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)

    response = webui.app.test_client().post(
        "/api/memory",
        headers={
            "X-Engram-Access-Token": ACCESS_TOKEN,
            "X-Engram-Write-Token": WRONG_TOKEN,
        },
        json={"key": "blocked", "content": "Wrong token should fail."},
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "invalid write token"


def test_public_host_accepts_matching_write_token(monkeypatch):
    import webui

    calls = []

    class FakeMemoryManager:
        def store_memory(self, **kwargs):
            calls.append(kwargs)
            return {"stored": True, "key": kwargs["key"]}

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)
    monkeypatch.setattr(webui, "memory_manager", FakeMemoryManager())

    response = webui.app.test_client().post(
        "/api/memory",
        headers={
            "X-Engram-Access-Token": ACCESS_TOKEN,
            "X-Engram-Write-Token": WRITE_TOKEN,
        },
        json={"key": "remote", "content": "Public writes need a matching token."},
    )

    assert response.status_code == 201
    assert response.get_json() == {"stored": True, "key": "remote"}
    assert calls[0]["key"] == "remote"


def test_index_renders_write_token_panel_for_exposed_host(monkeypatch):
    import webui

    class FakeMemoryManager:
        def list_memories(self):
            return []

        def get_stats(self):
            return {
                "total_memories": 0,
                "total_chunks": 0,
                "storage_size": "0 B",
                "json_size": "0 B",
                "chroma_size": "0 B",
            }

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)
    monkeypatch.setattr(webui, "memory_manager", FakeMemoryManager())

    client = webui.app.test_client()
    client.post("/login", data={"access_token": ACCESS_TOKEN})
    response = client.get("/")

    assert response.status_code == 200
    assert b"Remote writes require a token" in response.data


def test_auth_status_reports_remote_posture_without_token_values(monkeypatch):
    import webui

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGRAM_WEBUI_PORT", "5055")
    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_ALLOWED_HOSTS", REMOTE_HOST)
    monkeypatch.setenv("ENGRAM_WEBUI_TRUSTED_ORIGINS", REMOTE_ORIGIN)

    status = webui.webui_auth_status()
    rendered_status = repr(status)

    assert status["bind_host"] == "0.0.0.0"
    assert status["bind_port"] == 5055
    assert status["exposed_mode"] is True
    assert status["allowed_hosts_configured"] is True
    assert status["trusted_origins_configured"] is True
    assert status["minimum_token_chars"] == 32
    assert status["access_token_env"] == "ENGRAM_WEBUI_ACCESS_TOKEN"
    assert status["write_token_env"] == "ENGRAM_WEBUI_WRITE_TOKEN"
    assert ACCESS_TOKEN not in rendered_status
    assert WRITE_TOKEN not in rendered_status


def test_index_renders_security_status_without_token_values(monkeypatch):
    import webui

    class FakeMemoryManager:
        def list_memories(self):
            return []

        def get_stats(self):
            return {
                "total_memories": 0,
                "total_chunks": 0,
                "storage_size": "0 B",
                "json_size": "0 B",
                "chroma_size": "0 B",
            }

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_ALLOWED_HOSTS", REMOTE_HOST)
    monkeypatch.setattr(webui, "memory_manager", FakeMemoryManager())

    client = webui.app.test_client()
    client.post("/login", data={"access_token": ACCESS_TOKEN})
    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Security status" in html
    assert "Exposed mode" in html
    assert "ENGRAM_WEBUI_ALLOWED_HOSTS" in html
    assert ACCESS_TOKEN not in html
    assert WRITE_TOKEN not in html


def test_startup_validation_requires_write_token_for_public_host(monkeypatch):
    import pytest
    import webui

    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.delenv("ENGRAM_WEBUI_WRITE_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="ENGRAM_WEBUI_WRITE_TOKEN"):
        webui.validate_webui_security("0.0.0.0")


def test_startup_validation_requires_access_token_for_public_host(monkeypatch):
    import pytest
    import webui

    monkeypatch.delenv("ENGRAM_WEBUI_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)

    with pytest.raises(RuntimeError, match="ENGRAM_WEBUI_ACCESS_TOKEN"):
        webui.validate_webui_security("0.0.0.0")


def test_startup_validation_rejects_weak_public_tokens(monkeypatch):
    import pytest
    import webui

    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", "short")
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)

    with pytest.raises(RuntimeError, match="at least 32 characters"):
        webui.validate_webui_security("0.0.0.0")


def test_startup_validation_requires_allowed_hosts_for_wildcard_public_host(monkeypatch):
    import pytest
    import webui

    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)
    monkeypatch.delenv("ENGRAM_WEBUI_ALLOWED_HOSTS", raising=False)

    with pytest.raises(RuntimeError, match="ENGRAM_WEBUI_ALLOWED_HOSTS"):
        webui.validate_webui_security("0.0.0.0")


def test_startup_validation_accepts_allowed_hosts_for_wildcard_public_host(monkeypatch):
    import webui

    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_ALLOWED_HOSTS", REMOTE_HOST)

    webui.validate_webui_security("0.0.0.0")


def test_public_host_redirects_dashboard_to_login_without_access_session(monkeypatch):
    import webui

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)

    response = webui.app.test_client().get("/")

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")
    assert "next=/" in response.headers["Location"]


def test_public_host_blocks_read_api_without_access_session(monkeypatch):
    import webui

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)

    response = webui.app.test_client().get("/api/stats")

    assert response.status_code == 401
    assert response.get_json()["error"] == "access token required for exposed WebUI"


def test_remote_client_fails_closed_when_host_env_is_left_loopback(monkeypatch):
    import webui

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "127.0.0.1")
    monkeypatch.delenv("ENGRAM_WEBUI_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("ENGRAM_WEBUI_WRITE_TOKEN", raising=False)

    response = webui.app.test_client().get(
        "/",
        environ_base={"REMOTE_ADDR": "100.64.0.2"},
    )

    assert response.status_code == 503
    assert "ENGRAM_WEBUI_ACCESS_TOKEN" in response.get_json()["error"]


def test_remote_client_requires_auth_when_host_env_is_left_loopback(monkeypatch):
    import webui

    class FakeMemoryManager:
        def get_stats(self):
            return {"total_memories": 1}

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "127.0.0.1")
    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)
    monkeypatch.setattr(webui, "memory_manager", FakeMemoryManager())

    client = webui.app.test_client()
    blocked = client.get("/api/stats", environ_base={"REMOTE_ADDR": "100.64.0.2"})
    allowed = client.get(
        "/api/stats",
        headers={"X-Engram-Access-Token": ACCESS_TOKEN},
        environ_base={"REMOTE_ADDR": "100.64.0.2"},
    )

    assert blocked.status_code == 401
    assert allowed.status_code == 200
    assert allowed.get_json() == {"total_memories": 1}


def test_remote_client_rejects_disallowed_host_before_read(monkeypatch):
    import webui

    class FakeMemoryManager:
        def get_stats(self):
            return {"total_memories": 1}

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_ALLOWED_HOSTS", REMOTE_HOST)
    monkeypatch.setattr(webui, "memory_manager", FakeMemoryManager())

    response = webui.app.test_client().get(
        "/api/stats",
        base_url="http://evil.example:5000",
        headers={"X-Engram-Access-Token": ACCESS_TOKEN},
        environ_base={"REMOTE_ADDR": "100.64.0.2"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "host not allowed for exposed WebUI"


def test_remote_client_accepts_allowed_host_for_read(monkeypatch):
    import webui

    class FakeMemoryManager:
        def get_stats(self):
            return {"total_memories": 1}

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_ALLOWED_HOSTS", REMOTE_HOST)
    monkeypatch.setattr(webui, "memory_manager", FakeMemoryManager())

    response = webui.app.test_client().get(
        "/api/stats",
        base_url=REMOTE_ORIGIN,
        headers={"X-Engram-Access-Token": ACCESS_TOKEN},
        environ_base={"REMOTE_ADDR": "100.64.0.2"},
    )

    assert response.status_code == 200
    assert response.get_json() == {"total_memories": 1}


def test_public_host_accepts_read_api_with_access_header(monkeypatch):
    import webui

    class FakeMemoryManager:
        def get_stats(self):
            return {"total_memories": 1}

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)
    monkeypatch.setattr(webui, "memory_manager", FakeMemoryManager())

    response = webui.app.test_client().get(
        "/api/stats",
        headers={"X-Engram-Access-Token": ACCESS_TOKEN},
    )

    assert response.status_code == 200
    assert response.get_json() == {"total_memories": 1}


def test_login_sets_access_session_for_public_host(monkeypatch):
    import webui

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)

    client = webui.app.test_client()
    response = client.post("/login", data={"access_token": ACCESS_TOKEN})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")

    with client.session_transaction() as session:
        assert session["engram_webui_authenticated"] is True


def test_access_session_is_bound_to_current_token(monkeypatch):
    import webui

    class FakeMemoryManager:
        def get_stats(self):
            return {"total_memories": 1}

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)
    monkeypatch.setattr(webui, "memory_manager", FakeMemoryManager())

    client = webui.app.test_client()
    client.post("/login", data={"access_token": ACCESS_TOKEN})

    assert client.get("/api/stats").status_code == 200

    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ROTATED_ACCESS_TOKEN)

    response = client.get("/api/stats")

    assert response.status_code == 401
    assert response.get_json()["error"] == "access token required for exposed WebUI"


def test_login_throttles_repeated_failed_attempts(monkeypatch):
    import webui

    if hasattr(webui, "_LOGIN_FAILURES"):
        webui._LOGIN_FAILURES.clear()

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_LOGIN_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("ENGRAM_WEBUI_LOGIN_WINDOW_SECONDS", "300")

    client = webui.app.test_client()

    assert client.post("/login", data={"access_token": WRONG_TOKEN}).status_code == 200
    assert client.post("/login", data={"access_token": WRONG_TOKEN}).status_code == 200

    response = client.post("/login", data={"access_token": WRONG_TOKEN})

    assert response.status_code == 429
    assert b"Too many failed attempts" in response.data


def test_public_host_rejects_cross_origin_mutation_before_storage(monkeypatch):
    import webui

    calls = []

    class FakeMemoryManager:
        def store_memory(self, **kwargs):
            calls.append(kwargs)
            return {"stored": True, "key": kwargs["key"]}

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_ALLOWED_HOSTS", REMOTE_HOST)
    monkeypatch.setattr(webui, "memory_manager", FakeMemoryManager())

    response = webui.app.test_client().post(
        "/api/memory",
        base_url=REMOTE_ORIGIN,
        headers={
            "Origin": "https://evil.example",
            "X-Engram-Access-Token": ACCESS_TOKEN,
            "X-Engram-Write-Token": WRITE_TOKEN,
        },
        environ_base={"REMOTE_ADDR": "100.64.0.2"},
        json={"key": "blocked", "content": "Cross-origin writes should not reach storage."},
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "origin not allowed for exposed WebUI"
    assert calls == []


def test_public_host_accepts_same_origin_mutation(monkeypatch):
    import webui

    calls = []

    class FakeMemoryManager:
        def store_memory(self, **kwargs):
            calls.append(kwargs)
            return {"stored": True, "key": kwargs["key"]}

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_ALLOWED_HOSTS", REMOTE_HOST)
    monkeypatch.setattr(webui, "memory_manager", FakeMemoryManager())

    response = webui.app.test_client().post(
        "/api/memory",
        base_url=REMOTE_ORIGIN,
        headers={
            "Origin": REMOTE_ORIGIN,
            "X-Engram-Access-Token": ACCESS_TOKEN,
            "X-Engram-Write-Token": WRITE_TOKEN,
        },
        environ_base={"REMOTE_ADDR": "100.64.0.2"},
        json={"key": "remote", "content": "Same-origin writes are allowed with tokens."},
    )

    assert response.status_code == 201
    assert response.get_json() == {"stored": True, "key": "remote"}
    assert calls[0]["key"] == "remote"


def test_public_host_rejects_cross_site_fetch_metadata_before_storage(monkeypatch):
    import webui

    calls = []

    class FakeMemoryManager:
        def store_memory(self, **kwargs):
            calls.append(kwargs)
            return {"stored": True, "key": kwargs["key"]}

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_ALLOWED_HOSTS", REMOTE_HOST)
    monkeypatch.setattr(webui, "memory_manager", FakeMemoryManager())

    response = webui.app.test_client().post(
        "/api/memory",
        base_url=REMOTE_ORIGIN,
        headers={
            "Sec-Fetch-Site": "cross-site",
            "X-Engram-Access-Token": ACCESS_TOKEN,
            "X-Engram-Write-Token": WRITE_TOKEN,
        },
        environ_base={"REMOTE_ADDR": "100.64.0.2"},
        json={"key": "blocked", "content": "Cross-site browser writes should fail."},
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "cross-site request forbidden"
    assert calls == []


def test_webui_sets_security_headers(monkeypatch):
    import webui

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "127.0.0.1")
    monkeypatch.delenv("ENGRAM_WEBUI_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("ENGRAM_WEBUI_WRITE_TOKEN", raising=False)

    response = webui.app.test_client().get("/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_webui_csp_disallows_inline_script_and_style(monkeypatch):
    import webui

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "127.0.0.1")
    monkeypatch.delenv("ENGRAM_WEBUI_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("ENGRAM_WEBUI_WRITE_TOKEN", raising=False)

    response = webui.app.test_client().get("/health")

    csp = response.headers["Content-Security-Policy"]
    assert "'unsafe-inline'" not in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp


def test_index_uses_external_dashboard_script_for_strict_csp(monkeypatch):
    import webui

    class FakeMemoryManager:
        def list_memories(self):
            return []

        def get_stats(self):
            return {
                "total_memories": 0,
                "total_chunks": 0,
                "storage_size": "0 B",
                "json_size": "0 B",
                "chroma_size": "0 B",
            }

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "127.0.0.1")
    monkeypatch.delenv("ENGRAM_WEBUI_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("ENGRAM_WEBUI_WRITE_TOKEN", raising=False)
    monkeypatch.setattr(webui, "memory_manager", FakeMemoryManager())

    client = webui.app.test_client()
    response = client.get("/")
    script_response = client.get("/static/app.js")

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert script_response.status_code == 200
    assert script_response.mimetype == "application/javascript"
    assert '<script src="/static/app.js" defer></script>' in html
    assert "<script>" not in html
    assert INLINE_HTML_ATTR_PATTERN.search(html) is None


def test_dashboard_script_does_not_generate_inline_handlers_or_styles():
    script = Path("static/app.js").read_text(encoding="utf-8")

    assert "onclick=" not in script
    assert "onchange=" not in script
    assert "style=" not in script
    assert ".style" not in script


def test_webui_has_default_request_body_limit():
    import webui

    assert webui.app.config["MAX_CONTENT_LENGTH"] == 1_048_576


def test_logout_clears_access_session(monkeypatch):
    import webui

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGRAM_WEBUI_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("ENGRAM_WEBUI_WRITE_TOKEN", WRITE_TOKEN)

    client = webui.app.test_client()
    client.post("/login", data={"access_token": ACCESS_TOKEN})

    response = client.post("/logout")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
    with client.session_transaction() as session:
        assert "engram_webui_authenticated" not in session
