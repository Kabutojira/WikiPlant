from __future__ import annotations

import re
from typing import Any, Mapping

from .errors import ValidationError


INSTANCE_ID = re.compile(r"^wp-[a-f0-9]{16}$")
COMMIT = re.compile(r"^[a-f0-9]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REF = re.compile(
    r"^refs/heads/(?![./])(?!.*(?:\.\.|//|@\{|\.lock$))[A-Za-z0-9._/-]*[A-Za-z0-9_-]$"
)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        raise ValidationError(f"{field} must be a nonempty single-line string")
    return value


def validate_instance_v2(record: Mapping[str, Any], *, expected_instance_id: str | None = None) -> None:
    """Validate the complete provider-tagged v2 INSTANCE identity contract."""
    if not isinstance(record, Mapping) or record.get("schema_version") != 2:
        raise ValidationError("INSTANCE.json must use schema version 2")
    instance_id = _text(record.get("instance_id"), "instance_id")
    if INSTANCE_ID.fullmatch(instance_id) is None or (
        expected_instance_id is not None and instance_id != expected_instance_id
    ):
        raise ValidationError("INSTANCE.json has an invalid or foreign instance ID")
    _text(record.get("runtime_release_id"), "runtime_release_id")
    if COMMIT.fullmatch(str(record.get("source_commit", ""))) is None:
        raise ValidationError("INSTANCE.json source_commit must be immutable 40-hex")
    storage = record.get("storage")
    if not isinstance(storage, Mapping):
        raise ValidationError("INSTANCE.json requires a provider storage binding")
    provider = storage.get("provider")
    if provider == "google-drive":
        for key in ("root_folder_id", "config_file_id", "drive_map_file_id"):
            _text(storage.get(key), f"storage.{key}")
        if any(key in storage for key in (
            "repository_id", "repository", "canonical_ref", "root_prefix",
            "repository_visibility", "app_installation_id", "capability_profile_path",
            "first_verified_commit",
        )):
            raise ValidationError("Drive INSTANCE.json cannot contain GitHub binding fields")
        return
    if provider != "github":
        raise ValidationError("INSTANCE.json storage provider is unsupported")
    for key in ("repository_id", "repository", "canonical_ref", "app_installation_id"):
        _text(storage.get(key), f"storage.{key}")
    if REPOSITORY.fullmatch(storage["repository"]) is None:
        raise ValidationError("INSTANCE.json GitHub repository locator is invalid")
    if REF.fullmatch(storage["canonical_ref"]) is None or storage.get("root_prefix") != "":
        raise ValidationError("INSTANCE.json GitHub ref/root binding is invalid")
    if storage.get("repository_visibility") != "private":
        raise ValidationError("INSTANCE.json GitHub repository must be private")
    if storage.get("capability_profile_path") != "installation/capability-profile.json":
        raise ValidationError("INSTANCE.json GitHub capability profile binding is invalid")
    if COMMIT.fullmatch(str(storage.get("first_verified_commit", ""))) is None:
        raise ValidationError("INSTANCE.json GitHub ancestry anchor must be immutable 40-hex")
