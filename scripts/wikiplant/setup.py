from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .errors import ValidationError
from .util import slugify


REQUIRED_SETUP_FIELDS = (
    "instance_name",
    "primary_topics",
    "purpose",
    "exclusions",
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
    storage_provider: str | None = "google-drive"
    github_repository_url: str | None = None
    language: str = "en"
    timezone: str = "UTC"
    daily_time: str | None = None
    weekly_day: str | None = None
    weekly_time: str | None = None
    storage_consistency_mode: str = "strict"
    best_effort_risk_acknowledged: bool = False
    confirmed_at: str | None = None
    topic_authorizations: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # `strict` is the historical Drive default. Selecting GitHub resolves it
        # to that provider's sole supported consistency contract.
        if self.storage_provider == "github" and self.storage_consistency_mode == "strict":
            self.storage_consistency_mode = "git-fast-forward"

    def missing_fields(self) -> list[str]:
        missing: list[str] = []
        for name in REQUIRED_SETUP_FIELDS:
            value = getattr(self, name)
            if value is None or value == "" or (value == [] and name != "exclusions"):
                missing.append(name)
        if self.storage_provider is None:
            missing.append("storage_provider")
        elif self.storage_provider == "google-drive" and not self.drive_parent_id:
            missing.append("drive_parent_id")
        elif self.storage_provider == "github" and not self.github_repository_url:
            missing.append("github_repository_url")
        if self.storage_provider == "google-drive" and self.storage_consistency_mode == "best-effort-personal" and not self.best_effort_risk_acknowledged:
            missing.append("best_effort_risk_acknowledged")
        return missing

    def validate_complete(self) -> None:
        if self.storage_provider not in {"google-drive", "github"}:
            raise ValidationError("storage provider must be google-drive or github")
        if self.storage_provider == "google-drive" and self.github_repository_url is not None:
            raise ValidationError("Drive setup cannot contain a GitHub destination")
        if self.storage_provider == "github" and self.drive_parent_id is not None:
            raise ValidationError("GitHub setup cannot contain a Drive destination")
        if self.storage_provider == "google-drive" and self.storage_consistency_mode not in {"strict", "best-effort-personal"}:
            raise ValidationError("storage consistency mode must be strict or best-effort-personal")
        if self.storage_provider == "github" and self.storage_consistency_mode != "git-fast-forward":
            raise ValidationError("GitHub setup requires git-fast-forward consistency")
        missing = self.missing_fields()
        if missing:
            raise ValidationError("missing setup fields: " + ", ".join(missing))
        if not self.primary_topics or any(not p.get("name") for p in self.primary_topics):
            raise ValidationError("at least one named primary topic is required")
        if self.storage_provider == "github" and not re.fullmatch(
            r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?/?", self.github_repository_url or ""
        ):
            raise ValidationError("GitHub destination must be a normal https://github.com/owner/repository link")


def consolidated_interview(setup: SetupInput) -> str | None:
    missing = setup.missing_fields()
    if not missing:
        return None
    labels = {
        "instance_name": "instance name",
        "primary_topics": "primary topic(s) and useful aliases",
        "purpose": "purpose/projects/constraints",
        "exclusions": "semantic exclusions (say none if none)",
        "storage_provider": "storage provider (Google Drive recommended; GitHub remains experimental)",
        "drive_parent_id": "approved Google Drive destination",
        "github_repository_url": "dedicated private GitHub repository link (not a token or copied repository ID)",
        "daily_time": "daily start time",
        "weekly_day": "weekly maintenance day",
        "weekly_time": "weekly maintenance start time",
        "best_effort_risk_acknowledged": "approval for the non-atomic personal-instance lock and its concurrency risk",
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
        f"- Storage provider: {setup.storage_provider}\n"
        f"- Storage destination: {setup.drive_parent_id if setup.storage_provider == 'google-drive' else setup.github_repository_url}\n"
        f"- Storage consistency: {'git-fast-forward' if setup.storage_provider == 'github' else setup.storage_consistency_mode}"
        + (" (permanent Drive lock; expires after 20 hours; non-atomic and best-effort only)\n"
           if setup.storage_provider == "google-drive" and setup.storage_consistency_mode == "best-effort-personal" else "\n")
        + "- Initialization: up to 5 separately accounted investigations\n"
        "- Daily: every primary topic receives a finite refresh outside 5 normal / urgent-only maximum 10 queue attempts\n"
        + ("- Storage/runtime: private Google Drive raw files and an immutable pinned snapshot\n"
           if setup.storage_provider == "google-drive"
           else "- Storage/runtime: dedicated private GitHub repository, canonical non-force ref, and immutable pinned snapshot; Git history retains prior content\n")
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
