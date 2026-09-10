from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .errors import ValidationError
from .util import slugify


REQUIRED_SETUP_FIELDS = (
    "instance_name",
    "primary_topics",
    "purpose",
    "exclusions",
    "drive_parent_id",
    "daily_time",
    "weekly_day",
    "weekly_time",
)


@dataclass
class SetupInput:
    instance_name: str | None = None
    primary_topics: list[dict[str, Any]] = field(default_factory=list)
    purpose: str | None = None
    projects: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    exclusions: list[str] | None = None
    initial_material: list[str] = field(default_factory=list)
    drive_parent_id: str | None = None
    language: str = "en"
    timezone: str = "UTC"
    daily_time: str | None = None
    weekly_day: str | None = None
    weekly_time: str | None = None

    def missing_fields(self) -> list[str]:
        missing: list[str] = []
        for name in REQUIRED_SETUP_FIELDS:
            value = getattr(self, name)
            if value is None or value == [] or value == "":
                missing.append(name)
        return missing

    def validate_complete(self) -> None:
        missing = self.missing_fields()
        if missing:
            raise ValidationError("missing setup fields: " + ", ".join(missing))
        if not self.primary_topics or any(not p.get("name") for p in self.primary_topics):
            raise ValidationError("at least one named primary topic is required")


def consolidated_interview(setup: SetupInput) -> str | None:
    missing = setup.missing_fields()
    if not missing:
        return None
    labels = {
        "instance_name": "instance name",
        "primary_topics": "primary topic(s) and useful aliases",
        "purpose": "purpose/projects/constraints",
        "exclusions": "semantic exclusions (say none if none)",
        "drive_parent_id": "approved Google Drive destination",
        "daily_time": "daily start time",
        "weekly_day": "weekly maintenance day",
        "weekly_time": "weekly maintenance start time",
    }
    requested = ", ".join(labels[name] for name in missing)
    return (
        "Please provide the remaining setup details in one reply: " + requested + ". "
        f"Current defaults are language={setup.language or 'en'} and timezone={setup.timezone or 'UTC'}; "
        "times are local start times, not report-delivery guarantees. Include initial links/documents only if useful."
    )


def setup_summary(setup: SetupInput) -> str:
    setup.validate_complete()
    topic_names = ", ".join(topic["name"] for topic in setup.primary_topics)
    return (
        f"# WikiPlant setup: {setup.instance_name}\n\n"
        f"- Primary topics: {topic_names}\n"
        f"- Purpose: {setup.purpose}\n"
        f"- Projects: {', '.join(setup.projects) or 'None supplied'}\n"
        f"- Constraints: {', '.join(setup.constraints) or 'None supplied'}\n"
        f"- Exclusions: {', '.join(setup.exclusions or []) or 'None'}\n"
        f"- Language/timezone: {setup.language} / {setup.timezone}\n"
        f"- Daily start: {setup.daily_time}; weekly: {setup.weekly_day} {setup.weekly_time}\n"
        "- Initialization: up to 5 separately accounted investigations\n"
        "- Daily: every primary topic receives a finite refresh outside 5 normal / urgent-only maximum 10 queue attempts\n"
        "- Storage/runtime: private Google Drive raw files and an immutable pinned snapshot\n"
    )


def topic_records(setup: SetupInput) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, supplied in enumerate(setup.primary_topics, 1):
        name = str(supplied["name"]).strip()
        topic_id = str(supplied.get("id") or f"topic-{slugify(name)}")
        if topic_id in seen:
            raise ValidationError("primary topic identifiers must be unique")
        seen.add(topic_id)
        records.append({
            "id": topic_id,
            "name": name,
            "aliases": list(dict.fromkeys(str(v).strip() for v in supplied.get("aliases", []) if str(v).strip())),
            "related_page_ids": list(supplied.get("related_page_ids", [])),
            "preferred_sources": list(supplied.get("preferred_sources", [])),
            "search_terms": list(supplied.get("search_terms", [])),
        })
    return records
