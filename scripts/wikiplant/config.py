from __future__ import annotations

from datetime import time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ValidationError


WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}


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
    if config.get("storage", {}).get("provider") != "google-drive":
        raise ValidationError("Google Drive is the only supported operational storage provider")
    storage = config.get("storage", {})
    consistency_mode = storage.get("consistency_mode", "strict")
    if consistency_mode not in {"strict", "best-effort-personal"}:
        raise ValidationError("storage.consistency_mode must be strict or best-effort-personal")
    personal_lock = storage.get("personal_lock")
    if consistency_mode == "best-effort-personal":
        if (not isinstance(personal_lock, dict) or not personal_lock.get("file_id")
                or personal_lock.get("logical_path") != "data/state/research.lock.json"
                or personal_lock.get("stale_after_hours") != 20):
            raise ValidationError("best-effort personal storage requires the mapped permanent 20-hour lock")
    elif personal_lock is not None:
        raise ValidationError("strict storage cannot declare a best-effort personal lock")
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
