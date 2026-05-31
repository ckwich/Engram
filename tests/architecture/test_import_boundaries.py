from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

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


def test_memory_os_legacy_compatibility_imports_stay_policy_contained():
    from core.legacy.compatibility_policy import (
        BANNED_MEMORY_OS_LEGACY_IMPORTS,
        MEMORY_OS_LEGACY_COMPATIBILITY_MODULES,
    )

    offenders: dict[str, list[str]] = {}
    for path in _python_files("core/memory_os"):
        rel = _relative(path)
        module = rel[:-3].replace("/", ".")
        if module in MEMORY_OS_LEGACY_COMPATIBILITY_MODULES:
            continue
        bad = _banned_imports(_imports(path), set(BANNED_MEMORY_OS_LEGACY_IMPORTS))
        if bad:
            offenders[rel] = bad

    assert offenders == {}


def test_legacy_migration_kernel_imports_stay_policy_contained():
    from core.legacy.compatibility_policy import LEGACY_MIGRATION_KERNEL_IMPORTERS

    offenders: dict[str, list[str]] = {}
    for path in _python_files("core"):
        rel = _relative(path)
        module = rel[:-3].replace("/", ".")
        if module in LEGACY_MIGRATION_KERNEL_IMPORTERS:
            continue
        bad = _banned_imports(_imports(path), {"core.memory_os_migration"})
        if bad:
            offenders[rel] = bad

    assert offenders == {}


def test_legacy_memory_manager_imports_stay_allowlisted():
    from core.legacy.compatibility_policy import DIRECT_LEGACY_MEMORY_MANAGER_IMPORTERS

    offenders: dict[str, list[str]] = {}
    for path in _python_files("server.py", "webui.py", "engramd.py", "engram_index.py", "core", "hooks"):
        rel = _relative(path)
        if rel.startswith("tests/") or rel in DIRECT_LEGACY_MEMORY_MANAGER_IMPORTERS:
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


def test_focused_mcp_handler_modules_are_plain_helpers():
    candidates = [
        "core/mcp/document_tools.py",
        "core/mcp/knowledge_tools.py",
        "core/mcp/backend_tools.py",
    ]
    banned = {"server", "server_daemon_client", "fastmcp", "mcp"}
    offenders: dict[str, list[str]] = {}
    missing: list[str] = []
    for candidate in candidates:
        path = ROOT / candidate
        if not path.exists():
            missing.append(candidate)
            continue
        bad = _banned_imports(_imports(path), banned)
        if bad:
            offenders[candidate] = bad

    assert missing == []
    assert offenders == {}


def test_server_cli_bulk_lives_outside_mcp_tool_module():
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")
    cli_source = (ROOT / "core" / "server_cli.py").read_text(encoding="utf-8")

    assert "from core.server_cli import ServerCliDependencies, run_server_cli" in server_source
    assert "def main(" in server_source
    assert "async def _run_self_test" not in server_source
    assert "argparse.ArgumentParser" not in server_source
    assert "async def _run_self_test" in cli_source
    assert "argparse.ArgumentParser" in cli_source


def test_server_cli_module_is_plain_operator_helper():
    path = ROOT / "core" / "server_cli.py"
    imports = _imports(path)
    banned = {"server", "server_daemon_client", "fastmcp", "mcp", "core.memory_manager"}

    assert _banned_imports(imports, banned) == []
