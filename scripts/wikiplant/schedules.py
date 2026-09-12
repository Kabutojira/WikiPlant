from __future__ import annotations

from dataclasses import asdict
import json
import re
from .skillgen import SkillBinding


def render_task_prompt(template: str, *, operation: str, skill_name: str, binding: SkillBinding, scope_summary: str) -> str:
    if binding.storage_provider == "google-drive":
        storage_binding = {
            "root_folder_id": binding.drive_root_id,
            "config_file_id": binding.config_file_id,
            "map_file_id": binding.drive_map_file_id,
        }
    elif binding.storage_provider == "github":
        storage_binding = {
            "repository_id": binding.repository_id,
            "repository": binding.repository,
            "canonical_ref": binding.canonical_ref,
            "root_prefix": binding.root_prefix,
            "config_path": binding.config_path,
            "first_verified_commit": binding.first_verified_commit,
        }
    else:  # SkillBinding validation should make this unreachable.
        raise ValueError("unsupported storage provider")
    values = {
        "operation": operation,
        "skill_name": skill_name,
        "instance_id": binding.instance_id,
        "storage_provider": binding.storage_provider,
        "storage_binding_json": json.dumps(storage_binding, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "drive_root_id": binding.drive_root_id,
        "config_file_id": binding.config_file_id,
        "drive_map_file_id": binding.drive_map_file_id,
        "release_id": binding.release_id,
        "manifest_sha256": binding.runtime_manifest_sha256,
        "scope_summary": json.dumps(scope_summary, ensure_ascii=False),
    }
    if not re.fullmatch(r"wikiplant-[a-z0-9-]+", skill_name) or operation not in {"daily", "weekly"}:
        raise ValueError("invalid task operation/skill binding")
    def substitute(match):
        if match.group(1) not in values:
            raise ValueError("unresolved schedule template placeholder")
        return values[match.group(1)]
    # Substitute once: topic strings cannot introduce new operational bindings.
    return re.sub(r"\{\{([a-z_]+)\}\}", substitute, template)


def task_to_record(task: object) -> dict:
    return asdict(task)
