from __future__ import annotations

from dataclasses import asdict
from .host import HostTask
from .skillgen import SkillBinding


def render_task_prompt(template: str, *, operation: str, skill_name: str, binding: SkillBinding, scope_summary: str) -> str:
    values = {
        "operation": operation,
        "skill_name": skill_name,
        "instance_id": binding.instance_id,
        "drive_root_id": binding.drive_root_id,
        "config_file_id": binding.config_file_id,
        "drive_map_file_id": binding.drive_map_file_id,
        "release_id": binding.release_id,
        "manifest_sha256": binding.runtime_manifest_sha256,
        "scope_summary": scope_summary,
    }
    output = template
    for key, value in values.items():
        output = output.replace("{{" + key + "}}", value)
    if "{{" in output or "}}" in output:
        raise ValueError("unresolved schedule template placeholder")
    return output


def task_to_record(task: HostTask) -> dict:
    return asdict(task)
