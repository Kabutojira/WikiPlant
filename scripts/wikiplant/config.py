from __future__ import annotations

from datetime import time
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ValidationError


WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
DRIVE_PROVIDER = "google-drive"
GITHUB_PROVIDER = "github"
_DRIVE_ONLY_FIELDS = {"root_folder_id", "personal_lock"}
_GITHUB_ONLY_FIELDS = {
    "repository_id", "repository", "canonical_ref", "root_prefix", "limits",
}


def _nonempty_string(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        raise ValidationError(f"{field} must be a non-empty single-line string")


def _validate_storage(storage: Any, *, version: int, activated: bool) -> str:
    if not isinstance(storage, dict):
        raise ValidationError("storage must be a mapping")
    # schema v1 predates the provider tag. Its Drive-shaped binding remains valid.
    provider = storage.get("provider", DRIVE_PROVIDER if version == 1 else None)
    if provider not in {DRIVE_PROVIDER, GITHUB_PROVIDER}:
        raise ValidationError("storage.provider must be google-drive or github")

    foreign = _GITHUB_ONLY_FIELDS if provider == DRIVE_PROVIDER else _DRIVE_ONLY_FIELDS
    mixed = sorted(field for field in foreign if field in storage)
    if mixed:
        raise ValidationError(f"{provider} storage cannot contain fields for another provider: {', '.join(mixed)}")

    if provider == DRIVE_PROVIDER:
        if activated:
            _nonempty_string(storage.get("root_folder_id"), "storage.root_folder_id")
        consistency_mode = storage.get("consistency_mode", "strict")
        if consistency_mode not in {"strict", "best-effort-personal"}:
            raise ValidationError("Drive storage.consistency_mode must be strict or best-effort-personal")
        personal_lock = storage.get("personal_lock")
        if consistency_mode == "best-effort-personal":
            if (not isinstance(personal_lock, dict) or not personal_lock.get("file_id")
                    or personal_lock.get("logical_path") != "data/state/research.lock.json"
                    or personal_lock.get("stale_after_hours") != 20):
                raise ValidationError("best-effort personal storage requires the mapped permanent 20-hour lock")
        elif personal_lock is not None:
            raise ValidationError("strict storage cannot declare a best-effort personal lock")
        return provider

    for field in ("repository_id", "repository", "canonical_ref"):
        if activated or storage.get(field) is not None:
            _nonempty_string(storage.get(field), f"storage.{field}")
    repository = storage.get("repository")
    if repository is not None and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValidationError("storage.repository must be an owner/name locator")
    canonical_ref = storage.get("canonical_ref")
    if canonical_ref is not None and not re.fullmatch(
        r"refs/heads/(?![./])(?!.*(?:\.\.|//|@\{|\.lock$))[A-Za-z0-9._/-]*[A-Za-z0-9_-]", canonical_ref
    ):
        raise ValidationError("storage.canonical_ref must be a safe full branch ref")
    if storage.get("root_prefix", "") != "":
        raise ValidationError("storage.root_prefix is reserved and must currently be empty")
    if storage.get("consistency_mode") != "git-fast-forward":
        raise ValidationError("GitHub storage requires git-fast-forward consistency")
    limits = storage.get("limits")
    if not isinstance(limits, dict):
        raise ValidationError("GitHub storage requires bounded repository limits")
    required_limits = ("max_file_bytes", "max_transaction_bytes", "max_repository_bytes", "max_paths_per_transaction")
    for field in required_limits:
        value = limits.get(field)
        if type(value) is not int or value < 1:
            raise ValidationError(f"storage.limits.{field} must be a positive integer")
    if limits["max_file_bytes"] > limits["max_transaction_bytes"]:
        raise ValidationError("max_file_bytes cannot exceed max_transaction_bytes")
    if limits["max_transaction_bytes"] > limits["max_repository_bytes"]:
        raise ValidationError("max_transaction_bytes cannot exceed max_repository_bytes")
    return provider


def _time(value: Any, field: str, activated: bool) -> None:
    if value is None and not activated:
        return
    if not isinstance(value, str):
        raise ValidationError(f"{field} is required")
    try:
        time.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"{field} must be HH:MM[:SS]") from exc


def validate_config(config: dict[str, Any], *, activated: bool = True, topic_registry=None) -> None:
    version = config.get("schema_version")
    if version not in {1, 2}:
        raise ValidationError("unsupported config schema_version")
    instance = config.get("instance", {})
    if activated and (not instance.get("id") or not instance.get("name")):
        raise ValidationError("active config requires instance id and name")
    timezone = instance.get("timezone", "UTC")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, TypeError) as exc:
        raise ValidationError("instance.timezone must be an IANA timezone") from exc
    storage = config.get("storage", {})
    _validate_storage(storage, version=version, activated=activated)
    if version == 2 and "primary_topics" in config:
        raise ValidationError("TOPICS.md is authoritative; v2 config cannot contain primary_topics")
    topics = config.get("primary_topics", []) if version == 1 else config.get("primary_topic_ids", [])
    if activated and not topics:
        raise ValidationError("active config requires at least one primary topic")
    ids: set[str] = set()
    for topic in topics:
        if version == 2:
            if not isinstance(topic, str) or not topic or topic in ids:
                raise ValidationError("primary_topic_ids must be unique stable IDs")
            ids.add(topic)
            continue
        if not isinstance(topic, dict) or not topic.get("id") or not topic.get("name"):
            raise ValidationError("each primary topic requires id and name")
        if topic["id"] in ids:
            raise ValidationError("primary topic ids must be unique")
        ids.add(topic["id"])
        if not isinstance(topic.get("aliases", []), list):
            raise ValidationError("topic aliases must be a list")
    if version == 2:
        if activated and topic_registry is None:
            raise ValidationError("active v2 validation requires the authoritative topic registry")
        if topic_registry is not None:
            if topic_registry.instance_id != instance.get("id"):
                raise ValidationError("topic registry belongs to another instance")
            topic_registry.monitored_topics(config)
        from .admission import AdmissionPolicy
        AdmissionPolicy.from_config(config).validate()
        governance = config.get("topic_governance", {})
        if governance.get("peripheral_expiry") != "next_weekly_maintenance":
            raise ValidationError("peripheral expiry must be the next distinct weekly checkpoint")
        retention_days = governance.get("archive_recovery_retention_days", 7)
        if type(retention_days) is not int or retention_days < 1:
            raise ValidationError("archive recovery retention must be positive integer days")
        target = governance.get("archive_summary_target_words", [100, 200])
        if not isinstance(target, list) or len(target) != 2 or any(type(v) is not int or v < 1 for v in target) or target[0] > target[1]:
            raise ValidationError("archive summary target must be an increasing positive word range")
    schedules = config.get("schedules", {})
    _time(schedules.get("daily", {}).get("local_time"), "daily local_time", activated)
    _time(schedules.get("weekly", {}).get("local_time"), "weekly local_time", activated)
    weekday = schedules.get("weekly", {}).get("weekday")
    if activated and (not isinstance(weekday, str) or weekday.casefold() not in WEEKDAYS):
        raise ValidationError("weekly weekday is invalid")
    queue = config.get("queue", {})
    normal = queue.get("normal_daily_attempts")
    urgent = queue.get("urgent_daily_attempts_total")
    if normal != 5 or urgent != 10:
        raise ValidationError("v1 active queue policy requires normal 5 and urgent total 10")
    if queue.get("urgent_priority") != 0:
        raise ValidationError("urgent priority must be 0")
    expansion = config.get("expansion", {})
    if type(expansion.get("child_priority_increment")) is not int or expansion.get("child_priority_increment", 0) <= 0:
        raise ValidationError("expansion increment must be positive")
    if type(expansion.get("max_children_per_research")) is not int or expansion.get("max_children_per_research", 0) < 1:
        raise ValidationError("maximum children per research must be positive")
    if expansion.get("preserve_expansion_priority") is not True:
        raise ValidationError("expansion score must survive urgency changes")
    monitoring = config.get("main_topic_refresh", {})
    if not monitoring.get("enabled") or not monitoring.get("outside_queue_budget"):
        raise ValidationError("active WikiPlant requires outside-budget main-topic refresh")
    if monitoring.get("max_search_queries_per_topic", 0) < 1:
        raise ValidationError("main-topic search allowance must permit a real search")
    if monitoring.get("max_source_fetches_per_topic", 0) < 1:
        raise ValidationError("main-topic source allowance must permit evidence inspection")
