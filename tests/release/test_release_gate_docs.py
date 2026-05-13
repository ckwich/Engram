from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_release_gates_document_pre_ekc_and_full_release_lanes() -> None:
    gates = _read("docs/RELEASE_GATES.md")

    assert "Pre-EKC Readiness Gate" in gates
    assert "Full 1.0 Release Gate" in gates
    assert "server_daemon_client.py" in gates
    assert "tests\\architecture" in gates
    assert "tests\\backend_gates" in gates
    assert "test_no_write_tool_contracts.py" in gates
    assert "write_policy" in gates
    assert "prepare_document_disassembly" in gates
    assert "Review-first promotion stays explicit" in gates
    assert "build_retrieval_backend_gate" in gates
    assert "build_graph_backend_gate" in gates
    assert "Skipped parity is a blocker" in gates


def test_user_facing_docs_link_to_release_gates() -> None:
    readme = _read("README.md")
    agents = _read("AGENTS.md")
    checklist = _read("docs/ENGRAM_MEMORY_OS_1_0_RELEASE_CHECKLIST.md")

    assert "docs/RELEASE_GATES.md" in readme
    assert "docs/RELEASE_GATES.md" in agents
    assert "docs/RELEASE_GATES.md" in checklist
    assert "tests/architecture" in readme
    assert "tests\\architecture" in checklist
    assert "tests\\backend_gates" in checklist
    assert "pre-EKC readiness lane" in agents
