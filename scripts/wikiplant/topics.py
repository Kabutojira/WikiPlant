"""Authoritative topic registry. Semantic justifications are inputs, never inferred truth."""
from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .errors import ValidationError
from .authorization import validate_user_authorization
from .util import canonical_json, require_timestamp


SECTIONS = {"user": "User topics and interests", "adjacent": "Adjacent topics", "peripheral": "Peripheral topics"}
LIFECYCLES = {"active", "provisional", "archived", "retired"}
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def validate_topic_authorization(value: dict[str, Any], *, instance_id: str, topic_id: str) -> None:
    if value.get("source_role") == "approved_configuration_history":
        if not value.get("approval_record_ref"):
            raise ValidationError("historical tracking authorization needs a preserved approval record")
        value = value.get("original_authorization", {})
    validate_user_authorization(value, instance_id=instance_id, operation="track", target=topic_id)


def _ids(values: list[str], name: str) -> None:
    if not isinstance(values, list) or any(not isinstance(v, str) or not ID.fullmatch(v) for v in values) or len(set(values)) != len(values):
        raise ValidationError(f"{name} must contain unique stable IDs")


def _readable(topic: "Topic") -> str:
    def escape(value: str) -> str:
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("`", "&#96;").replace("\n", " ").replace("\r", " ")
    explanation = topic.direct_contribution or topic.classification_reason
    return f"### {escape(topic.label)}\n\n{escape(explanation)} ({topic.lifecycle})\n\n"


def next_weekly_checkpoint(created_at: str, *, weekday: str, local_time: str, timezone_name: str) -> str:
    """Strictly future occurrence; a topic created in maintenance lasts until next week."""
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    if weekday.casefold() not in days:
        raise ValidationError("weekly weekday is invalid")
    zone = ZoneInfo(timezone_name)
    created = require_timestamp(created_at).astimezone(zone)
    clock = time.fromisoformat(local_time)
    if clock.tzinfo is not None:
        raise ValidationError("weekly local_time must be a local clock time")
    day = created.date() + timedelta(days=(days.index(weekday.casefold()) - created.weekday()) % 7)
    result = datetime.combine(day, clock, zone)
    if result.astimezone(timezone.utc) <= created.astimezone(timezone.utc):
        result += timedelta(days=7)
    # Resolve nonexistent local times forward with the zone's observed round trip.
    return result.astimezone(timezone.utc).isoformat()


@dataclass
class Topic:
    id: str
    label: str
    classification: str
    user_anchor_ids: list[str]
    parent_ids: list[str]
    direct_contribution: str
    classification_reason: str
    added_at: str
    reviewed_at: str
    scope_revision: int
    aliases: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    lifecycle: str = "active"
    authorization: dict[str, Any] = field(default_factory=dict)
    expires_at: str = ""
    may_spawn_research: bool = True
    expansion_priority: int = 20
    research_parent_ids: list[str] = field(default_factory=list)
    lineage_root_ids: list[str] = field(default_factory=list)
    related_page_ids: list[str] = field(default_factory=list)
    schema_version: int = 2
    extra: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.schema_version != 2 or not ID.fullmatch(self.id) or not self.label.strip():
            raise ValidationError("topic schema, stable ID and label are required")
        if self.classification not in SECTIONS or self.lifecycle not in LIFECYCLES:
            raise ValidationError("invalid topic classification/lifecycle")
        for name in ("user_anchor_ids", "parent_ids", "research_parent_ids", "lineage_root_ids", "related_page_ids"):
            _ids(getattr(self, name), name)
        if not isinstance(self.aliases, list) or any(not isinstance(a, str) for a in self.aliases):
            raise ValidationError("topic aliases must be strings")
        if not self.classification_reason.strip() or type(self.scope_revision) is not int or self.scope_revision < 1:
            raise ValidationError("classification reason and scope revision required")
        if type(self.expansion_priority) is not int or not 0 <= self.expansion_priority <= 100:
            raise ValidationError("topic expansion priority must be in [0,100]")
        require_timestamp(self.added_at)
        require_timestamp(self.reviewed_at)
        if self.classification == "user":
            auth = self.authorization
            instance_id = auth.get("original_authorization", auth).get("instance_id", "")
            validate_topic_authorization(auth, instance_id=instance_id, topic_id=self.id)
            if self.user_anchor_ids != [self.id]:
                raise ValidationError("user anchor must reference itself")
        if self.lifecycle == "provisional" and self.may_spawn_research:
            raise ValidationError("unresolved provisional topics cannot expand")
        if self.classification == "adjacent" and self.lifecycle == "active" and (not self.direct_contribution.strip() or not self.evidence_refs):
            raise ValidationError("adjacent topic requires recorded direct contribution and supporting reason/evidence")
        if self.classification == "peripheral":
            if self.may_spawn_research or not self.expires_at:
                raise ValidationError("peripheral topic must be terminal with fixed expiry")
            if require_timestamp(self.expires_at) <= require_timestamp(self.added_at):
                raise ValidationError("peripheral expiry must be a distinct future checkpoint")
        elif self.expires_at:
            require_timestamp(self.expires_at)

    def automatic_eligible(self, now: datetime) -> bool:
        return self.lifecycle == "active" and not (self.classification == "peripheral" and require_timestamp(self.expires_at) <= now)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        value = asdict(self)
        extra = value.pop("extra")
        if set(extra) & set(value):
            raise ValidationError("unknown topic fields cannot override canonical fields")
        return {**extra, **value}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Topic":
        names = set(cls.__dataclass_fields__) - {"extra"}
        try:
            topic = cls(**{k: v for k, v in value.items() if k in names}, extra={k: v for k, v in value.items() if k not in names})
            topic.validate()
            return topic
        except (TypeError, KeyError) as exc:
            raise ValidationError("invalid topic record") from exc


@dataclass
class TopicRegistry:
    instance_id: str
    scope_revision: int
    topics: list[Topic] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)

    @property
    def by_id(self) -> dict[str, Topic]:
        return {t.id: t for t in self.topics}

    def validate(self) -> None:
        if not self.instance_id or type(self.scope_revision) is not int or self.scope_revision < 1:
            raise ValidationError("registry identity/revision required")
        if len(self.by_id) != len(self.topics):
            raise ValidationError("duplicate stable topic ID")
        for topic in self.topics:
            topic.validate()
            if topic.scope_revision > self.scope_revision:
                raise ValidationError("topic revision exceeds registry")
            if topic.classification == "user":
                validate_topic_authorization(topic.authorization, instance_id=self.instance_id, topic_id=topic.id)
            for ref in topic.parent_ids + topic.user_anchor_ids:
                if ref not in self.by_id:
                    raise ValidationError(f"unknown topic reference: {ref}")
            if topic.classification != "user" and topic.lifecycle != "provisional" and not topic.user_anchor_ids:
                raise ValidationError("non-user topic requires original user anchors")
            for anchor_id in topic.user_anchor_ids:
                anchor = self.by_id[anchor_id]
                if anchor.classification != "user":
                    raise ValidationError("adjacent chains cannot replace user anchors")
                if topic.lifecycle == "active" and anchor.lifecycle != "active":
                    raise ValidationError("active topic needs active user anchors")
            if topic.classification == "peripheral" and not topic.parent_ids:
                raise ValidationError("peripheral topic requires its adjacent relationship")
        visiting: set[str] = set()
        visited: set[str] = set()
        def walk(identifier: str) -> None:
            if identifier in visiting:
                raise ValidationError("topic ancestry cycle")
            if identifier in visited:
                return
            visiting.add(identifier)
            for parent in self.by_id[identifier].parent_ids:
                walk(parent)
            visiting.remove(identifier)
            visited.add(identifier)
        for identifier in self.by_id:
            walk(identifier)

    def render(self) -> str:
        self.validate()
        header = canonical_json({"schema_version": 2, "instance_id": self.instance_id, "scope_revision": self.scope_revision})
        parts = [f"# Topics\n\n<!-- wikiplant:registry {header} -->\n"]
        for kind, heading in SECTIONS.items():
            parts.append(f"\n## {heading}\n")
            if self.notes.get(kind):
                parts.append(self.notes[kind])
            for topic in self.topics:
                if topic.classification != kind:
                    continue
                # JSON data cannot escape into Markdown delimiters.
                data = canonical_json(topic.to_dict()).replace("<", "\\u003c").replace(">", "\\u003e")
                parts.append(f"\n<!-- wikiplant:topic -->\n{_readable(topic)}```json\n{data}\n```\n<!-- /wikiplant:topic -->\n")
        return "".join(parts)

    @classmethod
    def parse(cls, text: str) -> "TopicRegistry":
        header = re.search(r"^<!-- wikiplant:registry (\{.*\}) -->$", text, re.M)
        if not header or not text.startswith("# Topics\n"):
            raise ValidationError("TOPICS registry header missing")
        try:
            meta = json.loads(header.group(1))
            if meta.get("schema_version") != 2:
                raise ValidationError("unsupported registry schema")
            registry = cls(meta["instance_id"], meta["scope_revision"])
            headings = list(re.finditer(r"^## (.+)$", text, re.M))
            if [h.group(1) for h in headings] != list(SECTIONS.values()):
                raise ValidationError("TOPICS requires the exact three sections")
            for index, (kind, _) in enumerate(SECTIONS.items()):
                segment = text[headings[index].end()+1:headings[index+1].start() if index + 1 < len(headings) else len(text)]
                pattern = r"\n?<!-- wikiplant:topic -->\n(.*?)```json\n(.*?)\n```\n<!-- /wikiplant:topic -->\n?"
                blocks = list(re.finditer(pattern, segment, re.S))
                remainder = re.sub(pattern, "", segment, flags=re.S)
                if "wikiplant:topic" in remainder:
                    raise ValidationError("malformed topic managed block")
                registry.notes[kind] = remainder.strip("\n")
                for block in blocks:
                    topic = Topic.from_dict(json.loads(block.group(2)))
                    if topic.classification != kind:
                        raise ValidationError("topic classification disagrees with section")
                    if block.group(1) != _readable(topic):
                        raise ValidationError("topic readable explanation and canonical metadata disagree")
                    registry.topics.append(topic)
            registry.validate()
            return registry
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValidationError("invalid TOPICS metadata") from exc

    def transition(self, topic: Topic, *, authority: dict[str, Any] | None = None, policy=None) -> "TopicRegistry":
        """Validate updates without inferring authorization from text or current state."""
        previous = self.by_id.get(topic.id)
        if policy is None:
            from .admission import AdmissionPolicy
            policy = AdmissionPolicy()
        policy.validate()
        if topic.classification == "user" or (previous and previous.classification == "user"):
            auth = authority or {}
            validate_user_authorization(auth, instance_id=self.instance_id, operation="track", target=topic.id)
            topic = copy.deepcopy(topic)
            topic.authorization = dict(auth)
        if previous and previous.classification == topic.classification == "peripheral" and previous.expires_at != topic.expires_at:
            raise ValidationError("mentions, retries and maintenance cannot renew peripheral expiry")
        if previous and topic.classification != "user":
            if previous.expansion_priority != topic.expansion_priority or previous.research_parent_ids != topic.research_parent_ids or previous.lineage_root_ids != topic.lineage_root_ids:
                raise ValidationError("classification/reactivation cannot reset research lineage")
            if previous.classification == "peripheral" and topic.classification == "adjacent" and (not topic.direct_contribution or not set(topic.evidence_refs) - set(previous.evidence_refs)):
                raise ValidationError("promotion needs newly recorded direct anchor contribution evidence")
            if previous.lifecycle in {"archived", "retired"} and topic.lifecycle == "active" and (not topic.direct_contribution or not set(topic.evidence_refs) - set(previous.evidence_refs)):
                raise ValidationError("automatic reactivation needs new direct-relevance evidence and admission")
        if topic.lifecycle == "active" and topic.classification != "user" and not (previous and previous.lifecycle == "active" and previous.classification == topic.classification):
            count = sum(t.id != topic.id and t.classification == topic.classification and t.lifecycle == "active" for t in self.topics)
            maximum = policy.max_active_adjacent_topics if topic.classification == "adjacent" else policy.max_active_peripheral_topics
            if count >= maximum:
                raise ValidationError("active topic capacity reached; preserve candidate as inactive deferral")
        updated = copy.deepcopy(self)
        updated.scope_revision += 1
        topic = copy.deepcopy(topic)
        topic.scope_revision = updated.scope_revision
        updated.topics = [t for t in updated.topics if t.id != topic.id] + [topic]
        updated.validate()
        return updated

    def monitored_topics(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Read-only projection for existing monitoring/skill renderers, never a second taxonomy."""
        self.validate()
        identifiers = config.get("primary_topic_ids", [])
        _ids(identifiers, "primary_topic_ids")
        result = []
        for identifier in identifiers:
            topic = self.by_id.get(identifier)
            if not topic or topic.classification != "user" or topic.lifecycle != "active":
                raise ValidationError("monitored topic must reference an active user anchor")
            result.append({"id": topic.id, "name": topic.label, "aliases": topic.aliases,
                           "related_page_ids": topic.related_page_ids,
                           "preferred_sources": topic.extra.get("preferred_sources", []),
                           "search_terms": topic.extra.get("search_terms", [])})
        return result


def migrate_approved_topics(config: dict[str, Any], *, instance_id: str, authorization_history: dict[str, dict[str, Any]], created_at: str) -> tuple[TopicRegistry, dict[str, Any], list[str]]:
    """Pure conservative v1 migration; unproven anchors remain unresolved, never invented."""
    if config.get("schema_version") == 2:
        raise ValidationError("v2 topic registry must be loaded, not recreated from config")
    result = copy.deepcopy(config)
    registry = TopicRegistry(instance_id, 1)
    unresolved: list[str] = []
    for old in config.get("primary_topics", []):
        identifier = old["id"]
        auth = authorization_history.get(identifier, {})
        try:
            validate_topic_authorization(auth, instance_id=instance_id, topic_id=identifier)
        except ValidationError:
            unresolved.append(identifier)
            registry.topics.append(Topic(identifier, old["name"], "adjacent", [], [], "", "Legacy classification unresolved; no evidence of user tracking authorization", created_at, created_at, 1, aliases=old.get("aliases", []), lifecycle="provisional", may_spawn_research=False, extra={"legacy_topic": copy.deepcopy(old)}))
            continue
        registry.topics.append(Topic(identifier, old["name"], "user", [identifier], [], "", "Migrated demonstrably approved configuration", created_at, created_at, 1, aliases=old.get("aliases", []), authorization=auth, related_page_ids=old.get("related_page_ids", []), extra={k: copy.deepcopy(v) for k, v in old.items() if k not in {"id", "name", "aliases", "related_page_ids"}}))
    registry.validate()
    result["schema_version"] = 2
    result["primary_topic_ids"] = [t.id for t in registry.topics if t.classification == "user"]
    result.pop("primary_topics", None)
    if unresolved:
        result["migration_unresolved_topics"] = [copy.deepcopy(t) for t in config["primary_topics"] if t["id"] in unresolved]
    return registry, result, unresolved
