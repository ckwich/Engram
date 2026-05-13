from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ALLOWED_MEMORY_MANAGER_IMPORTERS = {
    "server.py",
    "webui.py",
    "engramd.py",
    "engram_index.py",
    "core/engramd_api.py",
    "hooks/engram_evaluator.py",
}


def _python_files(*roots: str) -> list[Path]:
    paths: list[Path] = []
    for root in roots:
        base = ROOT / root
        if base.is_file():
            paths.append(base)
            continue
        paths.extend(
            path
            for path in base.rglob("*.py")
            if "__pycache__" not in path.parts
        )
    return sorted(paths)


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _matches(import_name: str, banned: str) -> bool:
    return import_name == banned or import_name.startswith(f"{banned}.")


def _banned_imports(imports: set[str], banned: set[str]) -> list[str]:
    return sorted(
        import_name
        for import_name in imports
        for banned_name in banned
        if _matches(import_name, banned_name)
    )


def test_thin_daemon_client_stays_thin():
    imports = _imports(ROOT / "server_daemon_client.py")
    banned = {
        "server",
        "core.memory_manager",
        "core.embedder",
        "core.document_extractors",
        "core.document_intelligence",
        "chromadb",
        "lancedb",
        "kuzu",
        "sentence_transformers",
    }

    assert _banned_imports(imports, banned) == []


def test_memory_os_does_not_import_mcp_or_server_modules():
    banned = {"server", "server_daemon_client", "fastmcp", "mcp"}
    offenders: dict[str, list[str]] = {}
    for path in _python_files("core/memory_os"):
        bad = _banned_imports(_imports(path), banned)
        if bad:
            offenders[_relative(path)] = bad

    assert offenders == {}


def test_memory_os_does_not_import_legacy_memory_manager_directly():
    offenders: dict[str, list[str]] = {}
    for path in _python_files("core/memory_os"):
        bad = _banned_imports(_imports(path), {"core.memory_manager"})
        if bad:
            offenders[_relative(path)] = bad

    assert offenders == {}


def test_legacy_memory_manager_imports_stay_allowlisted():
    offenders: dict[str, list[str]] = {}
    for path in _python_files("server.py", "webui.py", "engramd.py", "engram_index.py", "core", "hooks"):
        rel = _relative(path)
        if rel.startswith("tests/") or rel in ALLOWED_MEMORY_MANAGER_IMPORTERS:
            continue
        bad = _banned_imports(_imports(path), {"core.memory_manager"})
        if bad:
            offenders[rel] = bad

    assert offenders == {}


def test_document_preview_modules_do_not_import_legacy_memory_manager():
    candidates = [
        "core/document_intelligence.py",
        "core/document_extractors.py",
        "core/document_artifacts.py",
        "core/document_quality.py",
        "core/memory_os/document_pipeline.py",
    ]
    offenders: dict[str, list[str]] = {}
    for path in _python_files(*candidates):
        bad = _banned_imports(_imports(path), {"core.memory_manager"})
        if bad:
            offenders[_relative(path)] = bad

    assert offenders == {}


def test_graph_services_do_not_import_mcp_server_modules():
    candidates = [
        "core/graph_manager.py",
        "core/graph_store.py",
        "core/kuzu_graph_store.py",
        "core/memory_os/graph.py",
    ]
    banned = {"server", "server_daemon_client", "fastmcp", "mcp"}
    offenders: dict[str, list[str]] = {}
    for path in _python_files(*candidates):
        bad = _banned_imports(_imports(path), banned)
        if bad:
            offenders[_relative(path)] = bad

    assert offenders == {}
