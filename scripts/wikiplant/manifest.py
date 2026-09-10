from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .errors import ValidationError
from .util import pretty_json, safe_relative_path, sha256_bytes


MAX_FILE_BYTES = 512_000
MAX_RUNTIME_BYTES = 8_000_000
MAX_RUNTIME_FILES = 4096
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
RUNTIME_PREFIXES = (
    "skills/init/",
    "skills/query/",
    "skills/research/",
    "skills/main-topic-refresh/",
    "skills/discover/",
    "skills/calendar/",
    "skills/synthesize/",
    "skills/create-report/",
    "skills/wiki-maintenance/",
    "skills/upgrade/",
    "skills/check-updates/",
    "skills/topic-governance/",
    "skills/archive/",
    "skills/evidence-review/",
    "skills/adversarial-review/",
    "skills/daily-operation/",
    "skills/instance/",
    "schemas/",
    "scripts/wikiplant/",
    "cron/",
    "templates/data/",
)
EXCLUDED_NAMES = {"__pycache__", ".DS_Store", ".gitkeep"}
DEVELOPMENT_ONLY_PATHS = {
    "scripts/wikiplant/cli.py",
    "scripts/wikiplant/fake_drive.py",
    "scripts/wikiplant/host.py",
    "scripts/wikiplant/installer.py",
}


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    sha256: str
    size: int
    encoding: str = "utf-8"


def runtime_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for prefix in RUNTIME_PREFIXES:
        base = root / prefix
        if not base.exists():
            continue
        for path in base.rglob("*"):
            relative = path.relative_to(root).as_posix()
            if path.is_file() and relative not in DEVELOPMENT_ONLY_PATHS and not any(part in EXCLUDED_NAMES for part in path.parts) and path.suffix != ".pyc":
                paths.append(path)
    return sorted(set(paths), key=lambda p: p.relative_to(root).as_posix())


def build_manifest(root: Path, release_id: str, source_commit: str, *, status: str = "released",
                   repository: str = "Kabutojira/WikiPlant", read_schemas: tuple[int, ...] = (2,),
                   write_schema: int = 2, migrations: tuple[str, ...] = ("1_to_2",),
                   required_capabilities: tuple[str, ...] = ("raw_create", "raw_full_read", "raw_content_update", "paginated_inventory", "conditional_write", "idempotent_create", "serialized_execution", "private_skill_update", "task_inspect", "writer_drain")) -> dict[str, Any]:
    from .releases import Version
    Version.parse(release_id)
    if status == "released" and not COMMIT_RE.fullmatch(source_commit):
        raise ValidationError("released manifests require an immutable 40-hex source commit")
    entries: list[dict[str, Any]] = []
    total = 0
    for path in runtime_paths(root):
        if path.is_symlink():
            raise ValidationError(f"runtime symlink is not allowed: {path}")
        payload = path.read_bytes()
        try:
            payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError(f"runtime file is not UTF-8: {path}") from exc
        if len(payload) > MAX_FILE_BYTES:
            raise ValidationError(f"runtime file exceeds size limit: {path}")
        total += len(payload)
        entries.append({
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256_bytes(payload),
            "size": len(payload),
            "encoding": "utf-8",
        })
    if total > MAX_RUNTIME_BYTES:
        raise ValidationError("runtime payload exceeds total size limit")
    if len(entries) > MAX_RUNTIME_FILES:
        raise ValidationError("runtime file inventory exceeds limit")
    return {
        "schema_version": 2,
        "release_id": release_id,
        "source_commit": source_commit,
        "status": status,
        "repository": repository,
        "distribution": "detached-release-asset",
        "compatibility": {"read_schemas": list(read_schemas), "write_schema": write_schema},
        "required_capabilities": list(required_capabilities),
        "migrations": list(migrations),
        "rollback": "Previous runtime must read the current schema; otherwise remain paused for validated repair. Never restore over later data.",
        "max_file_bytes": MAX_FILE_BYTES,
        "max_total_bytes": MAX_RUNTIME_BYTES,
        "files": entries,
    }


def manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return pretty_json(manifest).encode("utf-8")


def verify_manifest(root: Path, manifest: dict[str, Any], *, resolved_commit: str, require_released: bool = True) -> None:
    if manifest.get("schema_version") != 2:
        raise ValidationError("unsupported runtime manifest schema")
    from .releases import Version
    Version.parse(str(manifest.get("release_id", "")))
    if manifest.get("distribution") != "detached-release-asset" or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(manifest.get("repository", ""))):
        raise ValidationError("manifest requires detached distribution and repository identity")
    compatibility = manifest.get("compatibility", {})
    if not compatibility.get("read_schemas") or any(type(v) is not int or v < 1 for v in compatibility["read_schemas"]) or type(compatibility.get("write_schema")) is not int or compatibility["write_schema"] not in compatibility["read_schemas"]:
        raise ValidationError("manifest requires explicit schema compatibility")
    for field in ("required_capabilities", "migrations"):
        if not isinstance(manifest.get(field), list) or any(not isinstance(v, str) or not v for v in manifest[field]):
            raise ValidationError(f"manifest requires valid {field}")
    if not manifest.get("rollback"):
        raise ValidationError("manifest must explain rollback limitations")
    for key, limit in (("max_file_bytes", MAX_FILE_BYTES), ("max_total_bytes", MAX_RUNTIME_BYTES)):
        if type(manifest.get(key)) is not int or not 1 <= manifest[key] <= limit:
            raise ValidationError("manifest must declare finite positive file/total limits")
    if require_released and manifest.get("status") != "released":
        raise ValidationError("installation requires a released manifest")
    commit = manifest.get("source_commit")
    if not COMMIT_RE.fullmatch(str(commit)) or commit != resolved_commit:
        raise ValidationError("manifest commit does not match resolved immutable source")
    files = manifest.get("files")
    if not isinstance(files, list) or not files or len(files) > MAX_RUNTIME_FILES:
        raise ValidationError("manifest must list runtime files")
    seen: set[str] = set()
    total = 0
    for item in files:
        if not isinstance(item, dict):
            raise ValidationError("invalid manifest file entry")
        relative = safe_relative_path(str(item.get("path", "")))
        if relative in seen:
            raise ValidationError(f"duplicate manifest path: {relative}")
        seen.add(relative)
        if not any(relative.startswith(prefix) for prefix in RUNTIME_PREFIXES) or relative in DEVELOPMENT_ONLY_PATHS or any(p in EXCLUDED_NAMES for p in Path(relative).parts) or relative.endswith(".pyc"):
            raise ValidationError(f"path is outside the runtime allowlist: {relative}")
        declared_size = item.get("size")
        if type(declared_size) is not int or declared_size < 0 or declared_size > manifest["max_file_bytes"]:
            raise ValidationError(f"invalid file size for {relative}")
        if item.get("encoding") != "utf-8":
            raise ValidationError(f"unsupported encoding for {relative}")
        target = root / relative
        if not target.is_file() or target.is_symlink() or root.resolve() not in target.resolve().parents:
            raise ValidationError(f"missing or unsafe runtime file: {relative}")
        payload = target.read_bytes()
        try:
            payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError(f"runtime file is not UTF-8: {relative}") from exc
        if len(payload) != declared_size or sha256_bytes(payload) != item.get("sha256"):
            raise ValidationError(f"runtime payload mismatch: {relative}")
        total += len(payload)
    if total > min(int(manifest.get("max_total_bytes", MAX_RUNTIME_BYTES)), MAX_RUNTIME_BYTES):
        raise ValidationError("runtime exceeds allowed total size")
    verify_dependency_closure(root, seen)


def verify_dependency_closure(root: Path, paths: set[str]) -> None:
    """Reject missing package imports without importing untrusted release code."""
    verify_payload_dependency_closure({path: (root / path).read_bytes() for path in paths})


def verify_payload_dependency_closure(payloads: dict[str, bytes]) -> None:
    modules = {}
    for path in payloads:
        if path.startswith("scripts/wikiplant/") and path.endswith(".py"):
            name = path[len("scripts/"):-3].replace("/", ".")
            modules[name.removesuffix(".__init__")] = path
    if "wikiplant" not in modules:
        raise ValidationError("runtime package initializer missing")
    for name, path in modules.items():
        tree = ast.parse(payloads[path].decode("utf-8"), filename=path)
        package = name if path.endswith("/__init__.py") else name.rpartition(".")[0]
        for node in ast.walk(tree):
            required = []
            if isinstance(node, ast.Import):
                required = [alias.name for alias in node.names if alias.name.startswith("wikiplant")]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    prefix = package.split(".")[:len(package.split(".")) - node.level + 1]
                    module = ".".join(prefix + ([node.module] if node.module else []))
                else:
                    module = node.module or ""
                if module.startswith("wikiplant"):
                    required = [module]
            for module in required:
                if module not in modules:
                    raise ValidationError(f"runtime import {module} from {path} is absent from manifest")


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read manifest: {path}") from exc
    if not isinstance(value, dict):
        raise ValidationError("manifest root must be an object")
    return value


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_bytes(manifest_bytes(manifest))
