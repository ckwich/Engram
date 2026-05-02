from __future__ import annotations

import json
import sys
from pathlib import Path


def _write_project(tmp_path):
    project = tmp_path / "example_game_0"
    (project / ".engram").mkdir(parents=True)
    (project / "src").mkdir()
    (project / "AGENTS.md").write_text(
        "# Agent Notes\n\nPreserve the isometric ARPG direction.\n",
        encoding="utf-8",
    )
    (project / "src" / "player.py").write_text(
        "class PlayerController:\n    pass\n",
        encoding="utf-8",
    )
    (project / ".env").write_text("SECRET=do-not-index\n", encoding="utf-8")
    config = {
        "project_name": "example_game_0",
        "planning_paths": ["AGENTS.md"],
        "max_file_size_kb": 100,
        "domains": {
            "gameplay": {
                "file_globs": ["src/**/*.py", ".env"],
                "questions": ["What is the gameplay architecture?"],
            }
        },
    }
    (project / ".engram" / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return project


def _write_unconfigured_project(tmp_path):
    project = tmp_path / "example_game_0"
    (project / "Source" / "ExampleGame").mkdir(parents=True)
    (project / "Config").mkdir()
    (project / "Tests").mkdir()
    (project / "README.md").write_text("# ExampleGame\n", encoding="utf-8")
    (project / "Source" / "ExampleGame" / "Player.cpp").write_text(
        "class AExampleGamePlayer {};\n",
        encoding="utf-8",
    )
    (project / "Config" / "DefaultGame.ini").write_text("[Project]\n", encoding="utf-8")
    (project / "Tests" / "test_player.py").write_text("def test_player(): pass\n", encoding="utf-8")
    (project / ".env").write_text("SECRET=do-not-draft\n", encoding="utf-8")
    return project


def _write_gradle_plugin_project(tmp_path):
    project = tmp_path / "LegacyPluginFork"
    (project / "docs").mkdir(parents=True)
    (project / "src" / "main" / "java" / "com" / "example").mkdir(parents=True)
    (project / "src" / "main" / "resources").mkdir(parents=True)
    (project / "build" / "generated").mkdir(parents=True)
    (project / "README.md").write_text("# Legacy Plugin Fork\n", encoding="utf-8")
    (project / "CHANGELOG.md").write_text("## Fork notes\n", encoding="utf-8")
    (project / "docs" / "migration.md").write_text("# Migration\n", encoding="utf-8")
    (project / "settings.gradle.kts").write_text('rootProject.name = "legacy-plugin"\n', encoding="utf-8")
    (project / "build.gradle").write_text("plugins { id 'java' }\n", encoding="utf-8")
    (project / "gradle.properties").write_text("pluginGroup=com.example\n", encoding="utf-8")
    (project / "local.properties").write_text("sdk.dir=C:/private/sdk\n", encoding="utf-8")
    (project / "src" / "main" / "java" / "com" / "example" / "Plugin.java").write_text(
        "package com.example;\nclass Plugin {}\n",
        encoding="utf-8",
    )
    (project / "src" / "main" / "resources" / "messages.properties").write_text(
        "welcome.message=Welcome back\n",
        encoding="utf-8",
    )
    (project / "build" / "generated" / "Generated.java").write_text("class Generated {}\n", encoding="utf-8")
    return project


def _write_fanout_game_project(tmp_path):
    project = tmp_path / "FanoutGame"
    (project / "items" / "potions").mkdir(parents=True)
    (project / "items" / "scrolls").mkdir(parents=True)
    (project / "items" / "system").mkdir(parents=True)
    (project / "UI" / "components").mkdir(parents=True)
    (project / "platform" / "helpers").mkdir(parents=True)
    (project / "items" / "schema.json").write_text('{"type":"object"}\n', encoding="utf-8")
    (project / "items" / "registry.ts").write_text("export const itemRegistry = {};\n", encoding="utf-8")
    (project / "items" / "system" / "ItemRegistry.ts").write_text(
        "export class ItemRegistry {}\n",
        encoding="utf-8",
    )
    (project / "items" / "system" / "MappingHelper.ts").write_text(
        "export class MappingHelper {}\n",
        encoding="utf-8",
    )
    (project / "UI" / "index.tsx").write_text("export { AppShell } from './AppShell';\n", encoding="utf-8")
    (project / "UI" / "AppShell.tsx").write_text("export function AppShell() { return null; }\n", encoding="utf-8")
    (project / "platform" / "main.ts").write_text("export function bootPlatform() {}\n", encoding="utf-8")
    (project / "platform" / "PlatformAdapter.ts").write_text("export class PlatformAdapter {}\n", encoding="utf-8")
    for index in range(90):
        (project / "items" / "potions" / f"potion_{index:03}.json").write_text(
            f'{{"id":"potion_{index:03}"}}\n',
            encoding="utf-8",
        )
        (project / "items" / "scrolls" / f"scroll_{index:03}.json").write_text(
            f'{{"id":"scroll_{index:03}"}}\n',
            encoding="utf-8",
        )
        (project / "UI" / "components" / f"LeafWidget{index:03}.tsx").write_text(
            f"export function LeafWidget{index:03}() {{ return null; }}\n",
            encoding="utf-8",
        )
        (project / "platform" / "helpers" / f"helper_{index:03}.ts").write_text(
            f"export const helper{index:03} = true;\n",
            encoding="utf-8",
        )
    return project


def test_prepare_codebase_mapping_creates_agent_job_without_synthesis(tmp_path, monkeypatch):
    import core.codebase_mapper as mapper_module

    monkeypatch.setattr(mapper_module, "CODEBASE_MAPPING_DIR", tmp_path / "mapping_jobs")
    project = _write_project(tmp_path)

    manager = mapper_module.CodebaseMappingManager()
    payload = manager.prepare_mapping(
        project_root=project,
        mode="bootstrap",
        domain=None,
        budget_chars=400,
    )

    assert payload["error"] is None
    job = payload["job"]
    assert job["status"] == "prepared"
    assert job["mode"] == "bootstrap"
    assert job["project_root"] == str(project.resolve())
    assert job["domains"][0]["domain"] == "gameplay"
    assert job["domains"][0]["memory_key"] == "codebase_example_game_0_gameplay_architecture"
    assert job["domains"][0]["context_part_count"] >= 1
    assert "synthesize" in " ".join(job["agent_steps"]).lower()

    rendered = json.dumps(job)
    assert "PlayerController" not in rendered
    assert "do-not-index" not in rendered


def test_read_codebase_mapping_context_returns_bounded_secret_safe_context(tmp_path, monkeypatch):
    import core.codebase_mapper as mapper_module

    monkeypatch.setattr(mapper_module, "CODEBASE_MAPPING_DIR", tmp_path / "mapping_jobs")
    project = _write_project(tmp_path)

    manager = mapper_module.CodebaseMappingManager()
    job = manager.prepare_mapping(project_root=project, mode="bootstrap", budget_chars=160)["job"]

    payload = manager.read_context(job["job_id"], "gameplay", part_index=0)

    assert payload["error"] is None
    assert payload["job_id"] == job["job_id"]
    assert payload["domain"] == "gameplay"
    assert payload["part_index"] == 0
    assert payload["total_parts"] >= 1
    assert len(payload["context"]) <= 160
    assert "PlayerController" in payload["context"]
    assert "do-not-index" not in payload["context"]
    assert payload["memory_key"] == "codebase_example_game_0_gameplay_architecture"
    assert "store_codebase_mapping_result" in payload["agent_steps"][-1]


def test_store_codebase_mapping_result_writes_with_current_memory_manager(tmp_path, monkeypatch):
    import core.codebase_mapper as mapper_module

    monkeypatch.setattr(mapper_module, "CODEBASE_MAPPING_DIR", tmp_path / "mapping_jobs")
    project = _write_project(tmp_path)

    class FakeMemoryManager:
        def __init__(self):
            self.calls = []

        def store_memory(self, **kwargs):
            self.calls.append(kwargs)
            return {"key": kwargs["key"], "chunk_count": 1}

    manager = mapper_module.CodebaseMappingManager()
    job = manager.prepare_mapping(project_root=project, mode="bootstrap", budget_chars=400)["job"]
    fake_memory_manager = FakeMemoryManager()

    payload = manager.store_result(
        job_id=job["job_id"],
        domain="gameplay",
        content="## Architecture\n\nAgent-authored gameplay architecture.",
        memory_manager=fake_memory_manager,
        force=False,
    )

    assert payload["error"] is None
    assert payload["stored"]["key"] == "codebase_example_game_0_gameplay_architecture"
    call = fake_memory_manager.calls[0]
    assert call["key"] == "codebase_example_game_0_gameplay_architecture"
    assert call["content"].startswith("## Architecture")
    assert call["tags"] == ["example_game_0", "gameplay", "architecture", "codebase"]
    assert call["project"] == str(project.resolve())
    assert call["domain"] == "gameplay"
    assert call["canonical"] is True
    assert call["force"] is False

    manifest = json.loads((project / ".engram" / "index.json").read_text(encoding="utf-8"))
    assert manifest["memories"]["gameplay"] == "codebase_example_game_0_gameplay_architecture"
    assert "src/player.py" in manifest["files"]


def test_mapping_file_collection_dedupes_overlapping_globs_and_skips_secrets(tmp_path):
    from core.codebase_mapper import collect_mapping_files

    project = _write_project(tmp_path)

    files = collect_mapping_files(
        project,
        {"file_globs": ["src/**/*.py", "**/*.py", ".env"]},
        max_file_size_kb=100,
    )

    relative_files = [path.relative_to(project).as_posix() for path in files]
    assert relative_files == ["src/player.py"]


def test_mapping_file_collection_keeps_source_files_with_secret_like_names(tmp_path):
    from core.codebase_mapper import collect_mapping_files

    project = _write_project(tmp_path)
    (project / "src" / "token.py").write_text("TOKEN_KIND = 'parser token, not credential'\n", encoding="utf-8")

    files = collect_mapping_files(
        project,
        {"file_globs": ["src/**/*.py"]},
        max_file_size_kb=100,
    )

    relative_files = [path.relative_to(project).as_posix() for path in files]
    assert relative_files == ["src/player.py", "src/token.py"]


def test_memory_key_normalizes_agent_facing_identifiers():
    from core.codebase_mapper import memory_key

    assert (
        memory_key("Example Game 0!", "Gameplay/Combat Systems")
        == "codebase_example_game_0_gameplay_combat_systems_architecture"
    )


def test_draft_codebase_mapping_config_is_agent_safe_and_does_not_write(tmp_path):
    import core.codebase_mapper as mapper_module

    project = _write_unconfigured_project(tmp_path)

    payload = mapper_module.CodebaseMappingManager().draft_config(project_root=project)

    assert payload["error"] is None
    assert payload["config"]["project_name"] == "example_game_0"
    assert "README.md" in payload["config"]["planning_paths"]
    assert "source" in payload["config"]["domains"]
    assert "config" in payload["config"]["domains"]
    assert "tests" in payload["config"]["domains"]
    assert ".env" not in json.dumps(payload["config"])
    assert payload["receipt"]["existing_config"] is False
    assert not (project / ".engram" / "config.json").exists()


def test_draft_codebase_mapping_config_captures_gradle_docs_and_message_assets(tmp_path):
    import core.codebase_mapper as mapper_module

    project = _write_gradle_plugin_project(tmp_path)

    payload = mapper_module.CodebaseMappingManager().draft_config(project_root=project)

    assert payload["error"] is None
    config = payload["config"]
    rendered_config = json.dumps(config)
    assert {"README.md", "CHANGELOG.md", "docs"}.issubset(set(config["planning_paths"]))
    assert {"*.gradle", "*.kts", "*.properties"}.issubset(set(config["domains"]["project"]["file_globs"]))
    assert {"src/**/*.java", "src/**/*.properties"}.issubset(set(config["domains"]["src"]["file_globs"]))
    assert "local.properties" not in rendered_config
    assert "build" not in rendered_config


def test_preview_codebase_mapping_counts_drafted_gradle_and_message_assets(tmp_path, monkeypatch):
    import core.codebase_mapper as mapper_module

    monkeypatch.setattr(mapper_module, "CODEBASE_MAPPING_DIR", tmp_path / "mapping_jobs")
    project = _write_gradle_plugin_project(tmp_path)
    manager = mapper_module.CodebaseMappingManager()
    config = manager.draft_config(project_root=project)["config"]
    manager.store_config(project_root=project, config=config, overwrite=False)

    payload = manager.preview_mapping(project_root=project, mode="bootstrap")

    assert payload["error"] is None
    domains = {entry["domain"]: entry for entry in payload["preview"]["domains"]}
    assert domains["project"]["file_count"] == 3
    assert domains["src"]["file_count"] == 2


def test_draft_codebase_mapping_config_prunes_high_fanout_domains_to_spine_files(tmp_path):
    import core.codebase_mapper as mapper_module

    project = _write_fanout_game_project(tmp_path)

    payload = mapper_module.CodebaseMappingManager().draft_config(project_root=project)

    assert payload["error"] is None
    domains = payload["config"]["domains"]
    assert domains["items"]["file_globs"] == [
        "items/registry.ts",
        "items/schema.json",
        "items/system/ItemRegistry.ts",
    ]
    assert domains["ui"]["file_globs"] == ["UI/AppShell.tsx", "UI/index.tsx"]
    assert domains["platform"]["file_globs"] == ["platform/PlatformAdapter.ts", "platform/main.ts"]
    pruned_domains = {entry["domain"]: entry for entry in payload["receipt"]["fanout_pruned_domains"]}
    assert pruned_domains["items"]["candidate_file_count"] == 184
    assert pruned_domains["items"]["draft_file_count"] == 3


def test_preview_codebase_mapping_keeps_high_fanout_draft_bounded(tmp_path, monkeypatch):
    import core.codebase_mapper as mapper_module

    monkeypatch.setattr(mapper_module, "CODEBASE_MAPPING_DIR", tmp_path / "mapping_jobs")
    project = _write_fanout_game_project(tmp_path)
    manager = mapper_module.CodebaseMappingManager()
    config = manager.draft_config(project_root=project)["config"]
    manager.store_config(project_root=project, config=config, overwrite=False)

    payload = manager.preview_mapping(project_root=project, mode="bootstrap")

    assert payload["error"] is None
    domains = {entry["domain"]: entry for entry in payload["preview"]["domains"]}
    assert domains["items"]["file_count"] == 3
    assert domains["ui"]["file_count"] == 2
    assert domains["platform"]["file_count"] == 2


def test_store_codebase_mapping_config_writes_validated_config_and_blocks_overwrite(tmp_path):
    import core.codebase_mapper as mapper_module

    project = _write_unconfigured_project(tmp_path)
    manager = mapper_module.CodebaseMappingManager()
    config = manager.draft_config(project_root=project)["config"]

    first = manager.store_config(project_root=project, config=config, overwrite=False)
    second = manager.store_config(project_root=project, config=config, overwrite=False)
    third = manager.store_config(project_root=project, config=config, overwrite=True)

    assert first["error"] is None
    assert Path(first["stored"]["config_path"]).name == "config.json"
    assert Path(first["stored"]["config_path"]).parent.name == ".engram"
    assert json.loads((project / ".engram" / "config.json").read_text(encoding="utf-8")) == config
    assert second["stored"] is None
    assert second["error"]["code"] == "already_exists"
    assert third["error"] is None


def test_store_codebase_mapping_config_rejects_unsafe_globs(tmp_path):
    import core.codebase_mapper as mapper_module

    project = _write_unconfigured_project(tmp_path)
    config = {
        "project_name": "example_game_0",
        "planning_paths": ["README.md"],
        "max_file_size_kb": 100,
        "domains": {
            "escape": {
                "file_globs": ["../outside/**/*.py"],
                "questions": ["What is outside?"],
            }
        },
    }

    payload = mapper_module.CodebaseMappingManager().store_config(
        project_root=project,
        config=config,
        overwrite=False,
    )

    assert payload["stored"] is None
    assert payload["error"]["code"] == "invalid_config"
    assert "parent traversal" in payload["error"]["message"]


def test_read_codebase_mapping_config_reports_missing_and_existing(tmp_path):
    import core.codebase_mapper as mapper_module

    project = _write_unconfigured_project(tmp_path)
    manager = mapper_module.CodebaseMappingManager()

    missing = manager.read_config(project_root=project)
    config = manager.draft_config(project_root=project)["config"]
    manager.store_config(project_root=project, config=config, overwrite=False)
    existing = manager.read_config(project_root=project)

    assert missing["exists"] is False
    assert missing["config"] is None
    assert existing["exists"] is True
    assert existing["config"] == config
    assert existing["hook"]["installed"] is False


def test_preview_codebase_mapping_targets_returns_dry_run_without_job(tmp_path, monkeypatch):
    import core.codebase_mapper as mapper_module

    monkeypatch.setattr(mapper_module, "CODEBASE_MAPPING_DIR", tmp_path / "mapping_jobs")
    project = _write_unconfigured_project(tmp_path)
    manager = mapper_module.CodebaseMappingManager()
    config = manager.draft_config(project_root=project)["config"]
    manager.store_config(project_root=project, config=config, overwrite=False)

    payload = manager.preview_mapping(project_root=project, mode="bootstrap", domain="source")

    assert payload["error"] is None
    assert payload["preview"]["mode"] == "bootstrap"
    assert payload["preview"]["domains"][0]["domain"] == "source"
    assert payload["preview"]["domains"][0]["file_count"] == 1
    assert list((tmp_path / "mapping_jobs").glob("*.json")) == []


def test_install_codebase_mapping_hook_is_overwrite_protected(tmp_path):
    import core.codebase_mapper as mapper_module

    project = _write_unconfigured_project(tmp_path)
    (project / ".git" / "hooks").mkdir(parents=True)
    manager = mapper_module.CodebaseMappingManager()

    first = manager.install_hook(
        project_root=project,
        overwrite=False,
        python_path=sys.executable,
        engram_index_path=tmp_path / "engram_index.py",
    )
    second = manager.install_hook(
        project_root=project,
        overwrite=False,
        python_path=sys.executable,
        engram_index_path=tmp_path / "engram_index.py",
    )

    hook_path = project / ".git" / "hooks" / "post-commit"
    hook_text = hook_path.read_text(encoding="utf-8")
    assert first["error"] is None
    assert first["hook"]["installed"] is True
    assert first["hook"]["overwrote"] is False
    assert hook_text.splitlines()[0] == f"#!{mapper_module._path_for_hook_shebang(Path(sys.executable).resolve())}"
    assert str(project) in hook_text
    assert second["hook"] is None
    assert second["error"]["code"] == "already_exists"


def test_install_codebase_mapping_hook_requires_git_hooks(tmp_path):
    import core.codebase_mapper as mapper_module

    project = _write_unconfigured_project(tmp_path)

    payload = mapper_module.CodebaseMappingManager().install_hook(project_root=project)

    assert payload["hook"] is None
    assert payload["error"]["code"] == "not_git_repository"


def test_read_context_reports_source_drift_since_prepare(tmp_path, monkeypatch):
    import core.codebase_mapper as mapper_module

    monkeypatch.setattr(mapper_module, "CODEBASE_MAPPING_DIR", tmp_path / "mapping_jobs")
    project = _write_project(tmp_path)

    manager = mapper_module.CodebaseMappingManager()
    job = manager.prepare_mapping(project_root=project, mode="bootstrap", budget_chars=400)["job"]
    (project / "src" / "player.py").write_text(
        "class PlayerController:\n    def tick(self):\n        pass\n",
        encoding="utf-8",
    )

    payload = manager.read_context(job["job_id"], "gameplay", part_index=0)

    assert payload["error"] is None
    assert payload["source_drift"]["changed"] is True
    assert payload["source_drift"]["changed_files"] == ["src/player.py"]


def test_store_result_rejects_stale_prepare_without_force(tmp_path, monkeypatch):
    import core.codebase_mapper as mapper_module

    monkeypatch.setattr(mapper_module, "CODEBASE_MAPPING_DIR", tmp_path / "mapping_jobs")
    project = _write_project(tmp_path)

    class FakeMemoryManager:
        def __init__(self):
            self.calls = []

        def store_memory(self, **kwargs):
            self.calls.append(kwargs)
            return {"key": kwargs["key"], "chunk_count": 1}

    manager = mapper_module.CodebaseMappingManager()
    job = manager.prepare_mapping(project_root=project, mode="bootstrap", budget_chars=400)["job"]
    (project / "src" / "player.py").write_text("class Changed:\n    pass\n", encoding="utf-8")

    payload = manager.store_result(
        job_id=job["job_id"],
        domain="gameplay",
        content="## Architecture\n\nThis was synthesized from an older snapshot.",
        memory_manager=FakeMemoryManager(),
        force=False,
    )

    assert payload["stored"] is None
    assert payload["error"]["code"] == "source_drift"


def test_mapping_job_ids_cannot_escape_mapping_dir(tmp_path, monkeypatch):
    import core.codebase_mapper as mapper_module

    monkeypatch.setattr(mapper_module, "CODEBASE_MAPPING_DIR", tmp_path / "mapping_jobs")
    project = _write_project(tmp_path)
    outside_job = {
        "job_id": "../outside",
        "project_root": str(project),
        "project_name": "example_game_0",
        "budget_chars": 400,
        "domains": [
            {
                "domain": "gameplay",
                "memory_key": "codebase_example_game_0_gameplay_architecture",
                "file_hashes": {},
            }
        ],
        "config": json.loads((project / ".engram" / "config.json").read_text(encoding="utf-8")),
    }
    (tmp_path / "outside.json").write_text(json.dumps(outside_job), encoding="utf-8")

    manager = mapper_module.CodebaseMappingManager()
    payload = manager.read_context("../outside", "gameplay", part_index=0)

    assert payload["context"] == ""
    assert payload["error"]["code"] == "invalid_request"
