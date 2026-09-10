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


def validate_config(config: dict[str, Any], *, activated: bool = True) -> None:
    if config.get("schema_version") != 1:
        raise ValidationError("config schema_version must be 1")
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
    topics = config.get("primary_topics", [])
    if activated and not topics:
        raise ValidationError("active config requires at least one primary topic")
    ids: set[str] = set()
    for topic in topics:
        if not isinstance(topic, dict) or not topic.get("id") or not topic.get("name"):
            raise ValidationError("each primary topic requires id and name")
        if topic["id"] in ids:
            raise ValidationError("primary topic ids must be unique")
        ids.add(topic["id"])
        if not isinstance(topic.get("aliases", []), list):
            raise ValidationError("topic aliases must be a list")
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
    if expansion.get("child_priority_increment", 0) <= 0:
        raise ValidationError("expansion increment must be positive")
    if expansion.get("max_children_per_research") != 3:
        raise ValidationError("v1 maximum children per research must be 3")
    monitoring = config.get("main_topic_refresh", {})
    if not monitoring.get("enabled") or not monitoring.get("outside_queue_budget"):
        raise ValidationError("active WikiPlant requires outside-budget main-topic refresh")
    if monitoring.get("max_search_queries_per_topic", 0) < 1:
        raise ValidationError("main-topic search allowance must permit a real search")
    if monitoring.get("max_source_fetches_per_topic", 0) < 1:
        raise ValidationError("main-topic source allowance must permit evidence inspection")
