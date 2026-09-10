from __future__ import annotations

import copy
from dataclasses import dataclass, field

from .errors import ValidationError


@dataclass
class InstanceImage:
    instance_id: str
    runtime_release_id: str
    runtime_files: dict[str, bytes]
    data_files: dict[str, bytes]
    config: dict
    skill_binding_release: str
    schedule_binding_release: str
    paused: bool = False


@dataclass
class UpgradeCheckpoint:
    from_release: str
    to_release: str
    stage: str = "planned"
    backup_runtime: dict[str, bytes] = field(default_factory=dict)
    error: str | None = None


def available_update(current: str, published: str) -> dict:
    return {"current": current, "available": published, "update_available": current != published, "adopted": False}


def apply_upgrade(image: InstanceImage, new_release: str, new_runtime: dict[str, bytes], *, explicit_user_request: bool, fail_stage: str | None = None) -> UpgradeCheckpoint:
    if not explicit_user_request:
        raise ValidationError("runtime upgrades require an explicit user request")
    checkpoint = UpgradeCheckpoint(image.runtime_release_id, new_release)
    image.paused = True
    checkpoint.backup_runtime = copy.deepcopy(image.runtime_files)
    checkpoint.stage = "backed_up"
    if fail_stage == checkpoint.stage:
        checkpoint.error = "injected failure"
        return checkpoint
    image.runtime_files = copy.deepcopy(new_runtime)
    checkpoint.stage = "runtime_written"
    if fail_stage == checkpoint.stage:
        image.runtime_files = copy.deepcopy(checkpoint.backup_runtime)
        checkpoint.error = "injected failure; previous runtime restored"
        return checkpoint
    image.runtime_release_id = new_release
    image.skill_binding_release = new_release
    image.schedule_binding_release = new_release
    checkpoint.stage = "bindings_verified"
    if fail_stage == checkpoint.stage:
        image.paused = True
        checkpoint.error = "binding verification failed; manual recovery required"
        return checkpoint
    image.paused = False
    checkpoint.stage = "complete"
    return checkpoint


def rollback_runtime(image: InstanceImage, checkpoint: UpgradeCheckpoint) -> None:
    image.paused = True
    image.runtime_files = copy.deepcopy(checkpoint.backup_runtime)
    image.runtime_release_id = checkpoint.from_release
    image.skill_binding_release = checkpoint.from_release
    image.schedule_binding_release = checkpoint.from_release
    image.paused = False


def export_private_raw(image: InstanceImage) -> dict[str, object]:
    """Return a detached private raw snapshot, never a live synchronization target."""
    return {
        "instance_id": image.instance_id,
        "runtime_release_id": image.runtime_release_id,
        "config": copy.deepcopy(image.config),
        "runtime_files": copy.deepcopy(image.runtime_files),
        "data_files": copy.deepcopy(image.data_files),
    }
