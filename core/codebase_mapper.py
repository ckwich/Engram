from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).parent.parent
CODEBASE_MAPPING_DIR = PROJECT_ROOT / "data" / "codebase_mapping_jobs"
CODEBASE_MAPPING_SCHEMA_VERSION = "2026-04-29.agent-native-codebase-mapping.v1"
JOB_ID_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
DEFAULT_MAX_FILE_SIZE_KB = 100
DEFAULT_PLANNING_PATHS = ["PROJECT.md", "ROADMAP.md", "AGENTS.md"]
DEFAULT_DRAFT_PLANNING_PATHS = [
    "PROJECT.md",
    "ROADMAP.md",
    "AGENTS.md",
    "README.md",
    "ARCHITECTURE.md",
    "CONTRIBUTING.md",
    "DEVELOPING.md",
    "CHANGELOG.md",
    "docs",
]
DEFAULT_QUESTIONS = [
    "What is the architecture of this domain?",
    "What key decisions were made and why?",
    "What patterns are established and reused?",
    "What should a developer watch out for?",
]
MAPPING_MODES = {"bootstrap", "evolve", "full"}
HOOK_FILE_MODE = 0o700
DRAFT_DOMAIN_FILE_SOFT_LIMIT = 80
DRAFT_SPINE_STEM_HINTS = {
    "adapter",
    "app",
    "application",
    "config",
    "controller",
    "factory",
    "index",
    "layout",
    "loader",
    "main",
    "manager",
    "manifest",
    "platform",
    "provider",
    "registry",
    "router",
    "schema",
    "service",
    "settings",
    "shell",
    "store",
    "system",
}
CODEBASE_SOURCE_SUFFIXES = {
    ".cs",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".gd",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".json",
    ".kt",
    ".lua",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".swift",
    ".ts",
    ".tsx",
    ".uplugin",
    ".uproject",
    ".yaml",
    ".yml",
}
CODEBASE_CONFIG_SUFFIXES = {".gradle", ".ini", ".kts", ".properties", ".toml", ".xml"}
HOOK_TEMPLATE = """\
#!{hook_shebang}
\"\"\"Engram post-commit hook: run evolve mode in background after each commit.\"\"\"
import subprocess
import sys
from pathlib import Path

VENV_PYTHON = r"{venv_python}"
ENGRAM_INDEX = r"{engram_index}"
PROJECT_ROOT = r"{project_root}"
ENGRAM_DIR = Path(PROJECT_ROOT) / ".engram"
ENGRAM_DIR.mkdir(exist_ok=True)
LOG_FILE = str(ENGRAM_DIR / "last_evolve.log")

CREATE_NO_WINDOW = 0x08000000

try:
    popen_kwargs = dict(stderr=subprocess.STDOUT, close_fds=True)
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = CREATE_NO_WINDOW
    with open(LOG_FILE, "a", encoding="utf-8") as log:
        popen_kwargs["stdout"] = log
        subprocess.Popen(
            [VENV_PYTHON, ENGRAM_INDEX, "--mode", "evolve", "--project", PROJECT_ROOT],
            **popen_kwargs,
        )
    sys.exit(0)
except Exception as exc:
    with open(LOG_FILE, "a", encoding="utf-8") as log:
        log.write(f"Hook spawn error: {{exc}}\\n")
    sys.exit(0)
"""
DEFAULT_EXCLUDED_DIR_NAMES = {
    ".git",
    ".engram",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "env",
    "node_modules",
    "venv",
}
DEFAULT_SECRET_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    ".env.test",
    "credentials.properties",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
    "local.properties",
    "secrets.properties",
}
DEFAULT_SECRET_NAME_PARTS = {"credential", "credentials", "password", "secret", "secrets", "token", "tokens"}
DEFAULT_SECRET_FILE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
DEFAULT_SECRET_NAME_PART_SUFFIXES = CODEBASE_CONFIG_SUFFIXES | {".json", ".yaml", ".yml"}


class SourceDriftError(RuntimeError):
    def __init__(self, drift: dict[str, Any]):
        super().__init__(
            "source files changed after this mapping job was prepared; "
            "read fresh context or pass force=True to store anyway"
        )
        self.drift = drift


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _job_path(job_id: str) -> Path:
    normalized_id = _normalize_job_id(job_id)
    safe_id = normalized_id.replace(":", "_")
    return CODEBASE_MAPPING_DIR / f"{safe_id}.json"


def _normalize_job_id(job_id: str) -> str:
    normalized = str(job_id)
    if not JOB_ID_PATTERN.fullmatch(normalized):
        raise ValueError("invalid codebase mapping job_id")
    return normalized


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="codebase-map.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with open(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _resolve_project_root(project_root: str | Path) -> Path:
    root = Path(project_root).resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"project_root does not exist or is not a directory: {root}")
    return root


def load_project_config(project_root: Path) -> dict[str, Any] | None:
    config_path = project_root / ".engram" / "config.json"
    if not config_path.exists():
        return None
    return json.loads(config_path.read_text(encoding="utf-8"))


def save_project_config(project_root: Path, config: dict[str, Any]) -> None:
    engram_dir = project_root / ".engram"
    engram_dir.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(engram_dir / "config.json", config)


def _hook_status(project_root: Path) -> dict[str, Any]:
    hook_path = project_root / ".git" / "hooks" / "post-commit"
    installed = hook_path.exists()
    try:
        hook_text = hook_path.read_text(encoding="utf-8", errors="replace") if installed else ""
    except OSError:
        hook_text = ""
    return {
        "installed": installed,
        "path": str(hook_path),
        "engram_managed": installed and "Engram post-commit hook" in hook_text,
    }


def load_manifest(engram_dir: Path) -> dict[str, Any]:
    manifest_path = engram_dir / "index.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    return {"files": {}, "last_run": None, "memories": {}}


def save_manifest(engram_dir: Path, manifest: dict[str, Any]) -> None:
    manifest["last_run"] = _now()
    engram_dir.mkdir(parents=True, exist_ok=True)
    (engram_dir / "index.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _domain_file_hashes(
    project_root: Path,
    domain_config: dict[str, Any],
    max_file_size_kb: int,
) -> dict[str, str]:
    return {
        path.relative_to(project_root).as_posix(): sha256_file(path)
        for path in collect_mapping_files(project_root, domain_config, max_file_size_kb)
    }


def source_drift(
    project_root: Path,
    domain_config: dict[str, Any],
    expected_hashes: dict[str, str] | None,
    max_file_size_kb: int,
) -> dict[str, Any]:
    if expected_hashes is None:
        return {
            "changed": False,
            "unknown": True,
            "changed_files": [],
            "new_files": [],
            "missing_files": [],
        }
    current_hashes = _domain_file_hashes(project_root, domain_config, max_file_size_kb)
    changed_files = sorted(
        relative
        for relative, current_hash in current_hashes.items()
        if relative in expected_hashes and expected_hashes[relative] != current_hash
    )
    new_files = sorted(relative for relative in current_hashes if relative not in expected_hashes)
    missing_files = sorted(relative for relative in expected_hashes if relative not in current_hashes)
    return {
        "changed": bool(changed_files or new_files or missing_files),
        "unknown": False,
        "changed_files": changed_files,
        "new_files": new_files,
        "missing_files": missing_files,
    }


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _should_skip_mapping_path(path: Path, project_root: Path) -> bool:
    try:
        relative_path = path.relative_to(project_root)
    except ValueError:
        return True
    if any(part in DEFAULT_EXCLUDED_DIR_NAMES for part in relative_path.parts[:-1]):
        return True
    name = path.name.lower()
    if name in DEFAULT_SECRET_FILE_NAMES or name.startswith(".env."):
        return True
    suffix = path.suffix.lower()
    stem_parts = set(re.split(r"[^a-z0-9]+", path.stem.lower()))
    if suffix in DEFAULT_SECRET_NAME_PART_SUFFIXES and stem_parts & DEFAULT_SECRET_NAME_PARTS:
        return True
    return suffix in DEFAULT_SECRET_FILE_SUFFIXES


def _is_safe_relative_pattern(value: str) -> bool:
    path = Path(value)
    if path.is_absolute():
        return False
    return ".." not in path.parts


def validate_mapping_config(project_root: Path, config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(config, dict):
        return ["config must be an object"]
    project_name = config.get("project_name")
    if not isinstance(project_name, str) or not project_name.strip():
        errors.append("project_name must be a non-empty string")
    try:
        max_file_size_kb = int(config.get("max_file_size_kb", DEFAULT_MAX_FILE_SIZE_KB))
        if max_file_size_kb <= 0 or max_file_size_kb > 10000:
            errors.append("max_file_size_kb must be between 1 and 10000")
    except (TypeError, ValueError):
        errors.append("max_file_size_kb must be an integer")

    planning_paths = config.get("planning_paths", DEFAULT_PLANNING_PATHS)
    if not isinstance(planning_paths, list) or not all(isinstance(path, str) and path.strip() for path in planning_paths):
        errors.append("planning_paths must be a list of non-empty strings")
    else:
        unsafe = [path for path in planning_paths if not _is_safe_relative_pattern(path)]
        if unsafe:
            errors.append(f"planning_paths cannot use absolute paths or parent traversal: {unsafe}")

    domains = config.get("domains")
    if not isinstance(domains, dict) or not domains:
        errors.append("domains must be a non-empty object")
        return errors

    for domain_name, domain_config in domains.items():
        if not isinstance(domain_name, str) or not domain_name.strip():
            errors.append("domain names must be non-empty strings")
            continue
        if not isinstance(domain_config, dict):
            errors.append(f"domain '{domain_name}' must be an object")
            continue
        file_globs = domain_config.get("file_globs")
        if not isinstance(file_globs, list) or not all(isinstance(pattern, str) and pattern.strip() for pattern in file_globs):
            errors.append(f"domain '{domain_name}' file_globs must be a list of non-empty strings")
        else:
            unsafe_globs = [pattern for pattern in file_globs if not _is_safe_relative_pattern(pattern)]
            if unsafe_globs:
                errors.append(f"domain '{domain_name}' file_globs cannot use absolute paths or parent traversal: {unsafe_globs}")
        questions = domain_config.get("questions", DEFAULT_QUESTIONS)
        if not isinstance(questions, list) or not all(isinstance(question, str) and question.strip() for question in questions):
            errors.append(f"domain '{domain_name}' questions must be a list of non-empty strings")
    return errors


def _iter_candidate_files(project_root: Path, max_file_size_kb: int) -> list[Path]:
    suffixes = CODEBASE_SOURCE_SUFFIXES | CODEBASE_CONFIG_SUFFIXES
    candidates: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        current_dir = Path(dirpath)
        try:
            relative_dir = current_dir.relative_to(project_root)
        except ValueError:
            continue
        dirnames[:] = [
            name
            for name in dirnames
            if name not in DEFAULT_EXCLUDED_DIR_NAMES
            and not _should_skip_mapping_path(current_dir / name, project_root)
        ]
        if any(part in DEFAULT_EXCLUDED_DIR_NAMES for part in relative_dir.parts):
            continue
        for filename in filenames:
            path = current_dir / filename
            if path.suffix.lower() not in suffixes:
                continue
            if _should_skip_mapping_path(path, project_root):
                continue
            try:
                size_kb = path.stat().st_size / 1024
            except OSError:
                continue
            if size_kb > max_file_size_kb:
                continue
            candidates.append(path)
    return sorted(candidates, key=lambda item: item.relative_to(project_root).as_posix())


def _domain_name_for_path(relative_path: Path) -> str:
    if len(relative_path.parts) == 1:
        return "project"
    first = _safe_key_part(relative_path.parts[0])
    if first in {"test", "tests"}:
        return "tests"
    return first


def _glob_for_group(relative_path: Path, suffix: str) -> str:
    if len(relative_path.parts) == 1:
        return f"*{suffix}"
    return f"{relative_path.parts[0]}/**/*{suffix}"


def _stem_tokens(stem: str) -> set[str]:
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", stem)
    return {token for token in re.split(r"[^a-zA-Z0-9]+", camel_split.lower()) if token}


def _is_spine_mapping_file(relative_path: Path) -> bool:
    if len(relative_path.parts) <= 2:
        return True
    return bool(_stem_tokens(relative_path.stem) & DRAFT_SPINE_STEM_HINTS)


def _draft_file_globs_for_domain(project_root: Path, files: list[Path]) -> list[str]:
    if len(files) <= DRAFT_DOMAIN_FILE_SOFT_LIMIT:
        return sorted({
            _glob_for_group(path.relative_to(project_root), path.suffix.lower())
            for path in files
        })

    # High-fanout domains are usually content catalogs or UI leaf forests.
    # Draft exact spine files so agents get architecture, not every asset.
    return sorted({
        path.relative_to(project_root).as_posix()
        for path in files
        if _is_spine_mapping_file(path.relative_to(project_root))
    })


def _path_for_hook_shebang(path: Path) -> str:
    path_text = str(path).replace("\\", "/")
    if len(path_text) >= 2 and path_text[1] == ":":
        return f"/{path_text[0].lower()}/{path_text[3:]}"
    return path_text


def _draft_planning_paths(project_root: Path) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for candidate in DEFAULT_DRAFT_PLANNING_PATHS:
        path = project_root / candidate
        if path.exists() and not _should_skip_mapping_path(path, project_root):
            paths.append(candidate)
            seen.add(candidate)

    for markdown_file in sorted(project_root.glob("*.md")):
        relative = markdown_file.relative_to(project_root).as_posix()
        if relative in seen or _should_skip_mapping_path(markdown_file, project_root):
            continue
        paths.append(relative)
        seen.add(relative)
    return paths or DEFAULT_PLANNING_PATHS


def draft_mapping_config(project_root: Path, project_name: str | None = None) -> dict[str, Any]:
    max_kb = DEFAULT_MAX_FILE_SIZE_KB
    candidates = _iter_candidate_files(project_root, max_kb)
    grouped_files: dict[str, list[Path]] = {}
    for path in candidates:
        relative = path.relative_to(project_root)
        domain = _domain_name_for_path(relative)
        grouped_files.setdefault(domain, []).append(path)

    domains: dict[str, dict[str, Any]] = {}
    for domain in sorted(grouped_files):
        file_globs = _draft_file_globs_for_domain(project_root, grouped_files[domain])
        if not file_globs:
            continue
        domains[domain] = {
            "file_globs": file_globs,
            "questions": DEFAULT_QUESTIONS,
        }

    if not domains:
        domains["project"] = {
            "file_globs": ["**/*.py"],
            "questions": DEFAULT_QUESTIONS,
        }

    return {
        "project_name": project_name or project_root.name,
        "max_file_size_kb": max_kb,
        "planning_paths": _draft_planning_paths(project_root),
        "domains": domains,
    }


def collect_mapping_files(
    project_root: Path,
    domain_config: dict[str, Any],
    max_file_size_kb: int,
) -> list[Path]:
    project_root = project_root.resolve()
    files_by_relative_path: dict[str, Path] = {}
    for pattern in domain_config.get("file_globs", []):
        for path in sorted(project_root.glob(pattern)):
            if not path.is_file():
                continue
            try:
                resolved_path = path.resolve(strict=True)
            except OSError:
                continue
            if not _is_relative_to(resolved_path, project_root):
                continue
            if _should_skip_mapping_path(path, project_root):
                continue
            size_kb = path.stat().st_size / 1024
            if size_kb > max_file_size_kb:
                continue
            relative = path.relative_to(project_root).as_posix()
            files_by_relative_path.setdefault(relative, path)
    return [files_by_relative_path[key] for key in sorted(files_by_relative_path)]


def memory_key(project_name: str, domain_name: str) -> str:
    safe_project = _safe_key_part(project_name)
    safe_domain = _safe_key_part(domain_name)
    return f"codebase_{safe_project}_{safe_domain}_architecture"


def _safe_key_part(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(value).lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "unnamed"


def assemble_mapping_context(
    project_root: Path,
    config: dict[str, Any],
    domain_name: str,
    domain_config: dict[str, Any],
) -> str:
    parts: list[str] = []
    for rel_path in config.get("planning_paths", DEFAULT_PLANNING_PATHS):
        path = Path(rel_path) if Path(rel_path).is_absolute() else project_root / rel_path
        if path.exists() and path.is_file() and not _should_skip_mapping_path(path, project_root):
            rel = path.relative_to(project_root).as_posix() if _is_relative_to(path, project_root) else str(path)
            parts.append(f"=== {rel} ===\n{path.read_text(encoding='utf-8', errors='replace')}")
        elif path.exists() and path.is_dir():
            for md_file in sorted(path.glob("**/*.md")):
                if _should_skip_mapping_path(md_file, project_root):
                    continue
                rel = md_file.relative_to(project_root).as_posix()
                parts.append(f"=== {rel} ===\n{md_file.read_text(encoding='utf-8', errors='replace')}")

    max_kb = config.get("max_file_size_kb", DEFAULT_MAX_FILE_SIZE_KB)
    for file_path in collect_mapping_files(project_root, domain_config, max_kb):
        rel = file_path.relative_to(project_root).as_posix()
        parts.append(f"=== {rel} ===\n{file_path.read_text(encoding='utf-8', errors='replace')}")
    return "\n\n".join(parts).strip()


def build_synthesis_prompt(project_name: str, domain_name: str, domain_config: dict[str, Any]) -> str:
    questions = domain_config.get("questions", DEFAULT_QUESTIONS)
    question_block = "\n".join(f"- {question}" for question in questions)
    return (
        f"You are the active agent mapping the '{domain_name}' domain of the "
        f"'{project_name}' project. Use the provided context parts to synthesize "
        f"agent-authored markdown for Engram.\n\n"
        f"Answer these questions:\n{question_block}\n\n"
        "Format your response as structured markdown with these sections where relevant:\n"
        "## Architecture\n"
        "## Key Decisions\n"
        "## Patterns\n"
        "## Watch Out For\n\n"
        "Explain why the system is shaped this way, not just what files exist."
    )


def _chunk_text(value: str, budget_chars: int) -> list[str]:
    budget = max(100, min(int(budget_chars), 15000))
    if not value:
        return [""]
    return [value[index:index + budget] for index in range(0, len(value), budget)]


def find_changed_domains(project_root: Path, config: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    max_kb = config.get("max_file_size_kb", DEFAULT_MAX_FILE_SIZE_KB)
    changed_domains: list[str] = []
    stored_hashes = manifest.get("files", {})
    new_hashes: dict[str, str] = {}
    for domain_name, domain_config in config.get("domains", {}).items():
        domain_changed = False
        for file_path in collect_mapping_files(project_root, domain_config, max_kb):
            relative = file_path.relative_to(project_root).as_posix()
            current_hash = sha256_file(file_path)
            new_hashes[relative] = current_hash
            if stored_hashes.get(relative) != current_hash:
                domain_changed = True
        if domain_changed:
            changed_domains.append(domain_name)
    manifest["files"] = new_hashes
    return changed_domains


def _fanout_pruned_domains(
    project_root: Path,
    config: dict[str, Any],
    candidate_files: list[Path],
) -> list[dict[str, Any]]:
    candidate_counts: dict[str, int] = {}
    for path in candidate_files:
        domain = _domain_name_for_path(path.relative_to(project_root))
        candidate_counts[domain] = candidate_counts.get(domain, 0) + 1

    pruned: list[dict[str, Any]] = []
    max_kb = config.get("max_file_size_kb", DEFAULT_MAX_FILE_SIZE_KB)
    for domain, candidate_count in sorted(candidate_counts.items()):
        if candidate_count <= DRAFT_DOMAIN_FILE_SOFT_LIMIT or domain not in config.get("domains", {}):
            continue
        draft_count = len(collect_mapping_files(project_root, config["domains"][domain], max_kb))
        pruned.append({
            "domain": domain,
            "candidate_file_count": candidate_count,
            "draft_file_count": draft_count,
            "soft_limit": DRAFT_DOMAIN_FILE_SOFT_LIMIT,
        })
    return pruned


class CodebaseMappingManager:
    def read_config(self, *, project_root: str | Path) -> dict[str, Any]:
        try:
            root = _resolve_project_root(project_root)
            config = load_project_config(root)
            return {
                "exists": config is not None,
                "project_root": str(root),
                "config_path": str(root / ".engram" / "config.json"),
                "config": config,
                "manifest": load_manifest(root / ".engram"),
                "hook": _hook_status(root),
                "error": None,
            }
        except ValueError as exc:
            return {"exists": False, "config": None, "error": {"code": "invalid_request", "message": str(exc)}}
        except OSError as exc:
            return {"exists": False, "config": None, "error": {"code": "filesystem_error", "message": str(exc)}}
        except RuntimeError as exc:
            return {"exists": False, "config": None, "error": {"code": "runtime_error", "message": str(exc)}}

    def draft_config(self, *, project_root: str | Path, project_name: str | None = None) -> dict[str, Any]:
        try:
            root = _resolve_project_root(project_root)
            config = draft_mapping_config(root, project_name=project_name)
            errors = validate_mapping_config(root, config)
            if errors:
                raise ValueError("; ".join(errors))
            candidate_files = _iter_candidate_files(root, config["max_file_size_kb"])
            return {
                "config": config,
                "receipt": {
                    "project_root": str(root),
                    "config_path": str(root / ".engram" / "config.json"),
                    "existing_config": (root / ".engram" / "config.json").exists(),
                    "domain_count": len(config["domains"]),
                    "candidate_file_count": len(candidate_files),
                    "fanout_pruned_domains": _fanout_pruned_domains(root, config, candidate_files),
                    "excluded_dirs": sorted(DEFAULT_EXCLUDED_DIR_NAMES),
                    "secret_file_names": sorted(DEFAULT_SECRET_FILE_NAMES),
                },
                "error": None,
            }
        except ValueError as exc:
            return {"config": None, "receipt": None, "error": {"code": "invalid_request", "message": str(exc)}}
        except OSError as exc:
            return {"config": None, "receipt": None, "error": {"code": "filesystem_error", "message": str(exc)}}
        except RuntimeError as exc:
            return {"config": None, "receipt": None, "error": {"code": "runtime_error", "message": str(exc)}}

    def store_config(
        self,
        *,
        project_root: str | Path,
        config: dict[str, Any],
        overwrite: bool = False,
    ) -> dict[str, Any]:
        try:
            root = _resolve_project_root(project_root)
            errors = validate_mapping_config(root, config)
            if errors:
                return {
                    "stored": None,
                    "config": None,
                    "error": {"code": "invalid_config", "message": "; ".join(errors)},
                }
            config_path = root / ".engram" / "config.json"
            if config_path.exists() and not overwrite:
                return {
                    "stored": None,
                    "config": load_project_config(root),
                    "error": {
                        "code": "already_exists",
                        "message": f"{config_path} already exists; pass overwrite=True to replace it",
                    },
                }
            existed_before = config_path.exists()
            save_project_config(root, config)
            return {
                "stored": {
                    "project_root": str(root),
                    "config_path": str(config_path),
                    "overwrote": existed_before and overwrite,
                },
                "config": config,
                "error": None,
            }
        except ValueError as exc:
            return {"stored": None, "config": None, "error": {"code": "invalid_request", "message": str(exc)}}
        except OSError as exc:
            return {"stored": None, "config": None, "error": {"code": "filesystem_error", "message": str(exc)}}
        except RuntimeError as exc:
            return {"stored": None, "config": None, "error": {"code": "runtime_error", "message": str(exc)}}

    def preview_mapping(
        self,
        *,
        project_root: str | Path,
        mode: str = "bootstrap",
        domain: str | None = None,
        budget_chars: int = 6000,
    ) -> dict[str, Any]:
        try:
            preview = self._preview_mapping(project_root, mode, domain, budget_chars)
            return {"preview": preview, "error": None}
        except ValueError as exc:
            return {"preview": None, "error": {"code": "invalid_request", "message": str(exc)}}
        except OSError as exc:
            return {"preview": None, "error": {"code": "filesystem_error", "message": str(exc)}}
        except RuntimeError as exc:
            return {"preview": None, "error": {"code": "runtime_error", "message": str(exc)}}

    def install_hook(
        self,
        *,
        project_root: str | Path,
        overwrite: bool = False,
        python_path: str | Path | None = None,
        engram_index_path: str | Path | None = None,
    ) -> dict[str, Any]:
        try:
            root = _resolve_project_root(project_root)
            git_hooks_dir = root / ".git" / "hooks"
            if not git_hooks_dir.exists():
                return {
                    "hook": None,
                    "error": {
                        "code": "not_git_repository",
                        "message": f"{root} does not appear to be a git repository (.git/hooks not found)",
                    },
                }
            hook_path = git_hooks_dir / "post-commit"
            if hook_path.exists() and not overwrite:
                return {
                    "hook": None,
                    "error": {
                        "code": "already_exists",
                        "message": f"{hook_path} already exists; pass overwrite=True to replace it",
                    },
                }

            resolved_python = Path(python_path or sys.executable).resolve()
            resolved_index = Path(engram_index_path or PROJECT_ROOT / "engram_index.py").resolve()
            existed_before = hook_path.exists()
            hook_content = HOOK_TEMPLATE.format(
                hook_shebang=_path_for_hook_shebang(resolved_python),
                venv_python=str(resolved_python),
                engram_index=str(resolved_index),
                project_root=str(root),
            )
            hook_path.write_text(hook_content, encoding="utf-8")
            os.chmod(hook_path, HOOK_FILE_MODE)
            return {
                "hook": {
                    "installed": True,
                    "path": str(hook_path),
                    "python": str(resolved_python),
                    "engram_index": str(resolved_index),
                    "log_path": str(root / ".engram" / "last_evolve.log"),
                    "overwrote": existed_before and overwrite,
                },
                "error": None,
            }
        except ValueError as exc:
            return {"hook": None, "error": {"code": "invalid_request", "message": str(exc)}}
        except OSError as exc:
            return {"hook": None, "error": {"code": "filesystem_error", "message": str(exc)}}
        except RuntimeError as exc:
            return {"hook": None, "error": {"code": "runtime_error", "message": str(exc)}}

    def prepare_mapping(
        self,
        *,
        project_root: str | Path,
        mode: str = "bootstrap",
        domain: str | None = None,
        budget_chars: int = 6000,
    ) -> dict[str, Any]:
        try:
            return {"job": self._prepare_mapping(project_root, mode, domain, budget_chars), "error": None}
        except ValueError as exc:
            return {"job": None, "error": {"code": "invalid_request", "message": str(exc)}}
        except RuntimeError as exc:
            return {"job": None, "error": {"code": "runtime_error", "message": str(exc)}}

    def read_context(self, job_id: str, domain: str, part_index: int = 0) -> dict[str, Any]:
        try:
            job = self._load_job(job_id)
            domain_entry = self._domain_entry(job, domain)
            project_root = Path(job["project_root"])
            config = job["config"]
            domain_config = config["domains"][domain]
            max_kb = config.get("max_file_size_kb", DEFAULT_MAX_FILE_SIZE_KB)
            drift = source_drift(
                project_root,
                domain_config,
                domain_entry.get("file_hashes"),
                max_kb,
            )
            context = assemble_mapping_context(project_root, config, domain, domain_config)
            chunks = _chunk_text(context, job["budget_chars"])
            normalized_part = int(part_index)
            if normalized_part < 0 or normalized_part >= len(chunks):
                raise ValueError(f"part_index must be between 0 and {len(chunks) - 1}")
            return {
                "job_id": job_id,
                "domain": domain,
                "part_index": normalized_part,
                "total_parts": len(chunks),
                "context": chunks[normalized_part],
                "context_chars": len(context),
                "memory_key": domain_entry["memory_key"],
                "source_drift": drift,
                "synthesis_prompt": build_synthesis_prompt(job["project_name"], domain, domain_config),
                "agent_steps": [
                    "Read every context part for this domain.",
                    "Synthesize architecture markdown as the connected agent.",
                    "Call store_codebase_mapping_result with the completed markdown.",
                ],
                "error": None,
            }
        except ValueError as exc:
            return {"context": "", "error": {"code": "invalid_request", "message": str(exc)}}
        except RuntimeError as exc:
            return {"context": "", "error": {"code": "runtime_error", "message": str(exc)}}

    def store_result(
        self,
        *,
        job_id: str,
        domain: str,
        content: str,
        memory_manager: Any,
        force: bool = False,
    ) -> dict[str, Any]:
        try:
            if not content or not content.strip():
                raise ValueError("content is required")
            job = self._load_job(job_id)
            domain_entry = self._domain_entry(job, domain)
            project_root = Path(job["project_root"])
            domain_config = job["config"]["domains"][domain]
            max_kb = job["config"].get("max_file_size_kb", DEFAULT_MAX_FILE_SIZE_KB)
            drift = source_drift(
                project_root,
                domain_config,
                domain_entry.get("file_hashes"),
                max_kb,
            )
            if drift["changed"] and not force:
                raise SourceDriftError(drift)
            manifest = load_manifest(project_root / ".engram")
            related = [value for key, value in manifest.get("memories", {}).items() if key != domain]
            result = memory_manager.store_memory(
                key=domain_entry["memory_key"],
                content=content,
                tags=[job["project_name"].lower(), domain.lower(), "architecture", "codebase"],
                title=f"{job['project_name'].title()} - {domain.title()} Architecture",
                related_to=related[:10],
                force=force,
                project=str(project_root),
                domain=domain,
                status="active",
                canonical=True,
            )
            manifest.setdefault("memories", {})[domain] = domain_entry["memory_key"]
            find_changed_domains(project_root, job["config"], manifest)
            save_manifest(project_root / ".engram", manifest)
            domain_entry["status"] = "stored"
            domain_entry["stored_at"] = _now()
            domain_entry["stored_key"] = domain_entry["memory_key"]
            if all(entry.get("status") == "stored" for entry in job["domains"]):
                job["status"] = "stored"
            job["updated_at"] = _now()
            self._write_job(job)
            return {
                "stored": result,
                "job_id": job_id,
                "domain": domain,
                "memory_key": domain_entry["memory_key"],
                "source_drift": drift,
                "error": None,
            }
        except SourceDriftError as exc:
            return {
                "stored": None,
                "source_drift": exc.drift,
                "error": {"code": "source_drift", "message": str(exc)},
            }
        except ValueError as exc:
            return {"stored": None, "error": {"code": "invalid_request", "message": str(exc)}}
        except RuntimeError as exc:
            return {"stored": None, "error": {"code": "runtime_error", "message": str(exc)}}
        except Exception as exc:
            return {"stored": None, "error": {"code": "store_failed", "message": str(exc)}}

    def _prepare_mapping(
        self,
        project_root: str | Path,
        mode: str,
        domain: str | None,
        budget_chars: int,
    ) -> dict[str, Any]:
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode not in MAPPING_MODES:
            raise ValueError("mode must be one of bootstrap, evolve, or full")
        root = Path(project_root).resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError(f"project_root does not exist or is not a directory: {root}")
        config = load_project_config(root)
        if config is None:
            raise ValueError(f"no .engram/config.json found in {root}")
        domains = config.get("domains", {})
        if not domains:
            raise ValueError("project config has no domains")
        manifest = load_manifest(root / ".engram")
        selected_names = self._selected_domain_names(root, config, manifest, normalized_mode, domain)
        normalized_budget = max(100, min(int(budget_chars), 15000))
        project_name = config.get("project_name", root.name)
        domain_entries = [
            self._build_domain_entry(root, config, project_name, name, domains[name], normalized_budget)
            for name in selected_names
        ]
        status = "no_changes" if normalized_mode == "evolve" and not domain_entries else "prepared"
        timestamp = _now()
        job_id = _sha256_text(f"{root}:{normalized_mode}:{domain or '*'}:{time.time_ns()}")
        job = {
            "schema_version": CODEBASE_MAPPING_SCHEMA_VERSION,
            "job_id": job_id,
            "status": status,
            "mode": normalized_mode,
            "project_root": str(root),
            "project_name": project_name,
            "budget_chars": normalized_budget,
            "domains": domain_entries,
            "agent_steps": [
                "Call read_codebase_mapping_context for each domain and every context part.",
                "Synthesize architecture markdown using the connected agent.",
                "Call store_codebase_mapping_result for each completed domain mapping.",
            ],
            "config": config,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        self._write_job(job)
        return self._public_job(job)

    def _preview_mapping(
        self,
        project_root: str | Path,
        mode: str,
        domain: str | None,
        budget_chars: int,
    ) -> dict[str, Any]:
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode not in MAPPING_MODES:
            raise ValueError("mode must be one of bootstrap, evolve, or full")
        root = _resolve_project_root(project_root)
        config = load_project_config(root)
        if config is None:
            raise ValueError(f"no .engram/config.json found in {root}")
        domains = config.get("domains", {})
        if not domains:
            raise ValueError("project config has no domains")
        manifest = load_manifest(root / ".engram")
        selected_names = self._selected_domain_names(root, config, manifest, normalized_mode, domain)
        normalized_budget = max(100, min(int(budget_chars), 15000))
        project_name = config.get("project_name", root.name)
        domain_entries = [
            self._build_domain_entry(root, config, project_name, name, domains[name], normalized_budget)
            for name in selected_names
        ]
        return {
            "status": "no_changes" if normalized_mode == "evolve" and not domain_entries else "preview",
            "mode": normalized_mode,
            "project_root": str(root),
            "project_name": project_name,
            "budget_chars": normalized_budget,
            "domains": domain_entries,
            "domain_count": len(domain_entries),
            "hook": _hook_status(root),
            "config_path": str(root / ".engram" / "config.json"),
        }

    def _selected_domain_names(
        self,
        project_root: Path,
        config: dict[str, Any],
        manifest: dict[str, Any],
        mode: str,
        domain: str | None,
    ) -> list[str]:
        domains = config.get("domains", {})
        selected = list(domains.keys())
        if mode == "evolve":
            selected = find_changed_domains(project_root, config, manifest)
        if domain:
            if domain not in domains:
                raise ValueError(f"domain not found in config: {domain}")
            selected = [name for name in selected if name == domain]
        return selected

    def _build_domain_entry(
        self,
        project_root: Path,
        config: dict[str, Any],
        project_name: str,
        domain_name: str,
        domain_config: dict[str, Any],
        budget_chars: int,
    ) -> dict[str, Any]:
        files = collect_mapping_files(
            project_root,
            domain_config,
            config.get("max_file_size_kb", DEFAULT_MAX_FILE_SIZE_KB),
        )
        file_hashes = {
            path.relative_to(project_root).as_posix(): sha256_file(path)
            for path in files
        }
        context = assemble_mapping_context(project_root, config, domain_name, domain_config)
        return {
            "domain": domain_name,
            "status": "prepared",
            "memory_key": memory_key(project_name, domain_name),
            "file_count": len(files),
            "files": [path.relative_to(project_root).as_posix() for path in files],
            "file_hashes": file_hashes,
            "context_chars": len(context),
            "context_part_count": max(1, math.ceil(len(context) / budget_chars)),
            "questions": domain_config.get("questions", DEFAULT_QUESTIONS),
        }

    def _write_job(self, job: dict[str, Any]) -> None:
        _write_json_atomic(_job_path(job["job_id"]), job)

    def _load_job(self, job_id: str) -> dict[str, Any]:
        path = _job_path(job_id)
        if not path.exists():
            raise ValueError(f"codebase mapping job not found: {job_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _domain_entry(job: dict[str, Any], domain: str) -> dict[str, Any]:
        for entry in job.get("domains", []):
            if entry.get("domain") == domain:
                return entry
        raise ValueError(f"domain not found in mapping job: {domain}")

    @staticmethod
    def _public_job(job: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in job.items() if key != "config"}


codebase_mapping_manager = CodebaseMappingManager()
