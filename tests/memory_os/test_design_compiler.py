import json

from core.memory_os.design_compiler import compile_design_knowledge, export_skill_pack
from core.memory_os.ledger import MemoryOSLedger


def _scope():
    return {
        "scope_id": "frontend-design",
        "concepts": [
            {
                "label": "Visual Hierarchy",
                "definition": "Arrange interface elements so attention follows importance.",
                "review_state": "reviewed",
                "source_refs": ["book_a:section_visual_hierarchy", "book_b:figure_attention"],
                "critique_prompts": ["Identify the dominant focal point."],
                "checklist_items": ["Verify the primary action is visually dominant."],
                "anti_patterns": ["Competing focal points"],
                "eval_pack_refs": ["design-mini"],
            }
        ],
    }


def test_design_compiler_produces_source_backed_skill_material(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")

    compilation = compile_design_knowledge(_scope(), ledger=ledger)

    assert compilation["compilation_id"].startswith("design_compilation:")
    assert compilation["principles"][0]["name"] == "Visual Hierarchy"
    assert compilation["principles"][0]["citation_refs"] == [
        "book_a:section_visual_hierarchy",
        "book_b:figure_attention",
    ]
    assert compilation["critique_rubrics"][0]["prompt"] == "Identify the dominant focal point."
    assert compilation["checklist"][0]["text"] == "Verify the primary action is visually dominant."
    assert compilation["anti_patterns"][0]["name"] == "Competing focal points"
    assert compilation["quote_safety"] == {
        "direct_excerpt_policy": "short_quotes_only",
        "raw_source_exported": False,
    }
    assert compilation["eval_pack_refs"] == ["design-mini"]


def test_skill_pack_export_reads_compilation_from_ledger(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    compilation = compile_design_knowledge(_scope(), ledger=ledger)

    manifest = export_skill_pack(compilation["compilation_id"], tmp_path / "skill", ledger=ledger)
    exported = json.loads((tmp_path / "skill" / "skill_pack.json").read_text(encoding="utf-8"))

    assert manifest["skill_pack_path"] == str(tmp_path / "skill" / "skill_pack.json")
    assert exported["compilation_id"] == compilation["compilation_id"]
    assert exported["principles"][0]["name"] == "Visual Hierarchy"
    assert exported["quote_safety"]["raw_source_exported"] is False
