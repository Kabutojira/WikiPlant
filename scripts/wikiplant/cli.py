from __future__ import annotations

import argparse
import json
import subprocess
import tomllib
from pathlib import Path

from .calendar import read_calendar
from .authorization import UserAuthorization, request_digest
from .config import validate_config
from .fake_drive import FakeDrive
from .host import CapabilityProfile, FakeHost
from .installer import InstallPhase, Installer
from .manifest import COMMIT_RE, build_manifest, load_manifest, manifest_bytes, runtime_paths, verify_dependency_closure, verify_manifest, write_manifest
from .queue import read_queue
from .setup import SetupInput, topic_records
from .util import sha256_text
from .yamlio import loads as yaml_loads


REQUIRED_PATHS = [
    "README.md", "INSTALL.md", "VERSION", "config.example.yml", "release/runtime-manifest.schema.json",
    "cron/daily.prompt.md.template", "cron/weekly.prompt.md.template", "skills/bootstrap/BOOTSTRAP.md",
    "skills/instance/SKILL.md.template", "templates/data/research_queue.csv", "templates/data/calendar.csv",
]


def validate_repository(root: Path, *, require_released: bool = False, detached_manifest: Path | None = None) -> list[str]:
    errors: list[str] = []
    for relative in REQUIRED_PATHS:
        if not (root / relative).is_file():
            errors.append(f"missing required file: {relative}")
    try:
        import ast
        release_version = (root / "VERSION").read_text(encoding="utf-8").strip()
        project_version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        initializer = ast.parse((root / "scripts/wikiplant/__init__.py").read_text(encoding="utf-8"))
        package_version = next(node.value.value for node in initializer.body if isinstance(node, ast.Assign)
                               and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
                               and isinstance(node.value, ast.Constant))
        if not release_version == project_version == package_version:
            errors.append("VERSION, pyproject.toml and package __version__ disagree")
    except (OSError, KeyError, ValueError, StopIteration) as exc:
        errors.append(f"invalid development version metadata: {exc}")
    for path in sorted((root / "schemas").glob("*.json")) + sorted((root / "release").glob("*.schema.json")) + sorted((root / "cron").glob("*.schema.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("type") != "object":
                errors.append(f"schema root is not an object schema: {path.relative_to(root)}")
        except Exception as exc:
            errors.append(f"invalid JSON schema {path.relative_to(root)}: {exc}")
    try:
        config = yaml_loads((root / "config.example.yml").read_text(encoding="utf-8"))
        validate_config(config, activated=False)
    except Exception as exc:
        errors.append(f"invalid config template: {exc}")
    try:
        read_queue((root / "templates/data/research_queue.csv").read_text(encoding="utf-8"))
        read_calendar((root / "templates/data/calendar.csv").read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"invalid CSV template: {exc}")
    manifest_path = detached_manifest or root / "release/runtime-manifest.json"
    if manifest_path.exists():
        try:
            manifest = load_manifest(manifest_path)
            if manifest["release_id"] != (root / "VERSION").read_text(encoding="utf-8").strip():
                errors.append("runtime manifest release differs from VERSION")
            rebuilt = build_manifest(root, manifest["release_id"], manifest["source_commit"], status=manifest["status"])
            if manifest_bytes(rebuilt) != manifest_bytes(manifest):
                errors.append("runtime manifest is stale; regenerate it")
            if require_released:
                if detached_manifest is None:
                    errors.append("released verification requires --manifest pointing to a detached release asset")
                verify_manifest(root, manifest, resolved_commit=manifest["source_commit"])
        except Exception as exc:
            errors.append(f"invalid runtime manifest: {exc}")
    elif require_released:
        errors.append("released runtime manifest is missing")
    try:
        verify_dependency_closure(root, {p.relative_to(root).as_posix() for p in runtime_paths(root)})
    except Exception as exc:
        errors.append(f"runtime dependency closure: {exc}")
    forbidden = [root / ".github/workflows", root / "AGENT.md"]
    for path in forbidden:
        if path.exists():
            errors.append(f"obsolete/forbidden active path exists: {path.relative_to(root)}")
    private_markers = ("drive.google.com/drive/folders/", "ya29.", "AIza", "-----BEGIN PRIVATE KEY-----")
    for path in runtime_paths(root):
        text = path.read_text(encoding="utf-8")
        if any(marker in text for marker in private_markers):
            errors.append(f"possible private credential/Drive reference in runtime: {path.relative_to(root)}")
    return errors


def resolve_git_commit(root: Path) -> str | None:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=False)
    value = result.stdout.strip()
    return value if result.returncode == 0 and len(value) == 40 else None


def package(root: Path, source_commit: str | None, *, draft: bool = False, output: Path | None = None) -> Path:
    commit = source_commit or resolve_git_commit(root)
    if draft:
        commit = commit or "uncommitted-worktree"
    elif not commit:
        raise SystemExit("a committed 40-hex source revision is required")
    if not draft and not COMMIT_RE.fullmatch(commit):
        raise SystemExit("a committed 40-hex source revision is required")
    release_id = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not draft:
        # Verify payloads against an already-existing immutable source commit. The
        # detached asset is generated afterwards and never hashes itself.
        for path in [root / "VERSION", *runtime_paths(root)]:
            relative = path.relative_to(root).as_posix()
            result = subprocess.run(["git", "show", f"{commit}:{relative}"], cwd=root, capture_output=True, check=False)
            if result.returncode or result.stdout != path.read_bytes():
                raise SystemExit(f"source bytes differ from pinned commit: {relative}")
    manifest = build_manifest(root, release_id, commit, status="draft" if draft else "released")
    target = output or (root / "release/runtime-manifest.json" if draft else root / "dist" / f"wikiplant-{release_id}.manifest.json")
    if not draft:
        if target.resolve() == (root / "release/runtime-manifest.json").resolve():
            raise SystemExit("released manifests must be detached build/release assets")
        verify_manifest(root, manifest, resolved_commit=commit)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_manifest(target, manifest)
    return target


def run_e2e(root: Path) -> dict:
    commit = "a" * 40
    manifest = build_manifest(root, (root / "VERSION").read_text().strip(), commit, status="released")
    drive = FakeDrive()
    parent = drive.create_folder(None, "Approved private sandbox", idempotency_key="e2e-parent")
    capabilities = CapabilityProfile(
        google_drive_raw_create=True, google_drive_full_read=True, google_drive_content_update=True,
        google_drive_paginated_list=True, private_skill_install=True, scheduled_task_create=True,
        scheduled_task_inspect=True, conditional_write=True, idempotent_create=True, serialized_task_runs=True,
        observed_surface="synthetic-local", observed_at="2026-01-15T00:00:00+00:00",
    )
    host = FakeHost(capabilities)
    setup = SetupInput(
        instance_name="Synthetic Materials", primary_topics=[{"name": "Synthetic materials", "aliases": ["test composites"]}],
        purpose="Exercise the domain-neutral installer", exclusions=["real-world conclusions"],
        drive_parent_id=parent.id, daily_time="06:15", weekly_day="sunday", weekly_time="04:30",
    )
    installer = Installer(root, drive, host, parent.id)
    setup.confirmed_at = "2026-01-15T00:00:00+00:00"
    instance_id = "wp-" + sha256_text(parent.id + "\0" + setup.instance_name)[:16]
    setup.topic_authorizations = {topic["id"]: UserAuthorization(
        "synthetic-e2e-setup-turn", instance_id, "track", topic["id"], request_digest("Track this synthetic test topic"),
        True, "Synthetic fixture setup authorization").to_dict() for topic in topic_records(setup)}
    seed = [{"id": "seed-1", "question": "What baseline concepts are needed?", "source_ids": ["fixture-source"], "findings": ["Synthetic fixture only"]}]
    first = installer.run(setup, manifest, commit, seed_results=seed)
    resumed = installer.run(setup, manifest, commit, seed_results=seed, verify_first_run=True)
    ok = (
        first.phase == InstallPhase.ACTIVE_AWAITING_FIRST_RUN.name
        and resumed.phase == InstallPhase.ACTIVE_VERIFIED.name
        and len(host.skills) == 1 and len(host.tasks) == 2
        and resumed.initialization_allowance_consumed == 1
    )
    return {
        "ok": ok, "first_status": first.phase, "resumed_status": resumed.phase,
        "skills": len(host.skills), "tasks": len(host.tasks),
        "seed_attempts": resumed.initialization_allowance_consumed, "drive_objects": len(drive.entries),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wikiplant")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--root", default=".")
    validate_parser.add_argument("--require-released", action="store_true")
    validate_parser.add_argument("--manifest", type=Path, help="detached release manifest asset")
    package_parser = subparsers.add_parser("package")
    package_parser.add_argument("--root", default=".")
    package_parser.add_argument("--source-commit")
    package_parser.add_argument("--draft", action="store_true", help="write a non-installable development manifest")
    package_parser.add_argument("--output", type=Path, help="detached manifest output path")
    e2e_parser = subparsers.add_parser("e2e")
    e2e_parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "validate":
        errors = validate_repository(root, require_released=args.require_released, detached_manifest=args.manifest)
        if errors:
            for error in errors:
                print(f"FAIL {error}")
            return 1
        print("PASS repository schemas, templates, policies, and runtime manifest")
        return 0
    if args.command == "package":
        print(package(root, args.source_commit, draft=args.draft, output=args.output))
        return 0
    result = run_e2e(root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
