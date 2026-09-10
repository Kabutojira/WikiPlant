"""One origin-independent admission policy; semantic assessments must be recorded inputs."""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .errors import ValidationError
from .authorization import validate_user_authorization
from .queue import QueueItem, normalized_question_key
from .topics import TopicRegistry
from .util import require_timestamp, sha256_text, canonical_json


DISPOSITIONS = {"admit", "merge", "defer_capacity", "archive_candidate", "reject_scope", "needs_user_scope_decision"}


@dataclass
class AdmissionPolicy:
    max_active_adjacent_topics: int = 30
    max_active_peripheral_topics: int = 15
    max_active_automatic_items: int = 50
    max_new_automatic_roots_per_day: int = 5
    revalidate_pending_after_days: int = 14
    automatic_candidate_deferral_days: int = 30
    child_priority_increment: int = 20
    max_semantic_comparisons: int = 20

    def validate(self) -> None:
        if any(type(v) is not int or v < 1 for v in asdict(self).values()):
            raise ValidationError("admission limits must be positive integers")

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "AdmissionPolicy":
        values = {**config.get("topic_governance", {}), **config.get("queue_admission", {}), **config.get("expansion", {})}
        policy = cls(**{key: value for key, value in values.items() if key in cls.__dataclass_fields__})
        policy.validate()
        return policy


@dataclass
class LineageRecord:
    id: str
    topic_id: str
    parent_ids: list[str]
    root_ids: list[str]
    anchor_ids: list[str]
    expansion_priority: int
    terminal: bool
    novelty_key: str
    question_key: str
    status: str = "pending"
    evidence_refs: list[str] = field(default_factory=list)
    explicit_user: bool = False


@dataclass
class AdmissionCandidate:
    item: QueueItem
    classification: str
    original_anchor_ids: list[str]
    contribution: str
    assessment_ref: str
    novelty_key: str
    novelty_evidence_refs: list[str]
    question_conditions: str = ""
    entity_version: str = ""
    time_window: str = ""
    root_reason: str = ""
    authorization: dict[str, Any] = field(default_factory=dict)
    recurring: bool = False
    excluded: bool = False
    semantic_matches: list[dict[str, Any]] = field(default_factory=list)
    validated_independent_parent_ids: list[str] = field(default_factory=list)
    relationship: str = "direct_anchor"
    independent_parent_assessments: dict[str, dict[str, Any]] = field(default_factory=dict)
    current_anchor_ids: list[str] = field(default_factory=list)

    @property
    def question_key(self) -> str:
        # Topic relabeling cannot turn an old question into a fresh root.
        return sha256_text(canonical_json([normalized_question_key(self.item.question, ""), self.question_conditions, self.entity_version, self.time_window, self.item.refresh_occurrence_id]))[:24]


@dataclass
class AdmissionDecision:
    candidate_id: str
    disposition: str
    reason: str
    scope_revision: int
    original_anchor_ids: list[str]
    contribution: str
    classification: str
    parent_ids: list[str]
    root_ids: list[str]
    expansion_priority: int
    terminal: bool
    novelty_key: str
    novelty_evidence_refs: list[str]
    priority: int
    priority_reason: str
    urgency_reason: str
    capacity: dict[str, int]
    decided_at: str
    merge_target_id: str = ""
    defer_until: str = ""
    execution_revalidation: bool = False
    schema_version: int = 2
    local_cycle_date: str = ""

    def to_dict(self) -> dict[str, Any]:
        if self.disposition not in DISPOSITIONS:
            raise ValidationError("invalid admission disposition")
        return asdict(self)


def _user_exception(candidate: AdmissionCandidate, instance_id: str) -> bool:
    try:
        validate_user_authorization(candidate.authorization, instance_id=instance_id, operation="investigate", target=candidate.item.id)
        return True
    except ValidationError:
        return False


def decide_admission(candidate: AdmissionCandidate, registry: TopicRegistry, obligations: Iterable[QueueItem], lineage: dict[str, LineageRecord], *, now: datetime, policy: AdmissionPolicy | None = None, roots_admitted_today: int = 0, execution: bool = False, local_cycle_date: str = "") -> AdmissionDecision:
    policy = policy or AdmissionPolicy()
    policy.validate()
    registry.validate()
    item = candidate.item
    item.validate()
    obligations = list(obligations)
    if len({i.id for i in obligations}) != len(obligations):
        raise ValidationError("duplicate active queue identity")
    counts = {"active_automatic_items": sum(not (i.id in lineage and lineage[i.id].explicit_user) and i.status in {"pending", "in_progress", "retry_wait", "blocked"} for i in obligations),
              "active_adjacent_topics": sum(t.classification == "adjacent" and t.lifecycle == "active" for t in registry.topics),
              "active_peripheral_topics": sum(t.classification == "peripheral" and t.lifecycle == "active" for t in registry.topics),
              "new_roots_today": roots_admitted_today}
    roots = [item.lineage_root_id]
    terminal = candidate.classification == "peripheral"
    def decision(disposition: str, reason: str, *, target: str = "") -> AdmissionDecision:
        return AdmissionDecision(item.id, disposition, reason, registry.scope_revision, list(candidate.original_anchor_ids), candidate.contribution,
            candidate.classification, list(item.parent_ids), list(roots), item.expansion_priority, terminal, candidate.novelty_key,
            list(candidate.novelty_evidence_refs), item.priority, item.priority_reason, item.urgency_reason, counts, now.isoformat(),
            merge_target_id=target, defer_until=(now + timedelta(days=policy.automatic_candidate_deferral_days)).isoformat() if disposition == "defer_capacity" else "",
            execution_revalidation=execution, local_cycle_date=local_cycle_date or now.date().isoformat())

    explicit = _user_exception(candidate, registry.instance_id)
    if item.origin == "user" and not explicit:
        return decision("needs_user_scope_decision", "Explicit user work requires current bound research-once authority")
    if candidate.excluded:
        return decision("needs_user_scope_decision" if explicit else "reject_scope", "Actual question conflicts with current semantic exclusions")
    if not candidate.assessment_ref or not candidate.contribution.strip():
        return decision("needs_user_scope_decision", "Actual question lacks recorded relevance assessment")
    if len(set(candidate.original_anchor_ids)) != len(candidate.original_anchor_ids) or any(a not in registry.by_id or registry.by_id[a].classification != "user" for a in candidate.original_anchor_ids):
        return decision("reject_scope", "Original anchors must remain known unique user interests")
    topic = registry.by_id.get(item.topic_id)
    if not topic or not topic.automatic_eligible(now):
        if not explicit:
            return decision("archive_candidate", "Topic is missing, provisional, archived, retired or expired")
        terminal = True
    elif candidate.classification != topic.classification:
        return decision("reject_scope", "Question classification must be reconciled with the authoritative topic registry")
    if not explicit:
        current_anchors = candidate.current_anchor_ids or candidate.original_anchor_ids
        if candidate.relationship not in {"direct_anchor", "via_adjacent"} or (candidate.classification in {"user", "adjacent"} and candidate.relationship != "direct_anchor"):
            return decision("reject_scope", "Actual question is locally adjacent without direct anchor contribution")
        if not current_anchors or any(a not in registry.by_id or registry.by_id[a].classification != "user" or registry.by_id[a].lifecycle != "active" for a in current_anchors):
            return decision("reject_scope", "Actual question has no direct active user-anchor relationship")
        if topic and not set(current_anchors).issubset(topic.user_anchor_ids):
            return decision("reject_scope", "Question assessment invents unrecorded topic anchor relationships")
        if candidate.classification == "adjacent" and (not topic.direct_contribution or not topic.evidence_refs):
            return decision("reject_scope", "Adjacent chains do not establish direct anchor contribution")
    if explicit:
        # A scoped one-off request is always terminal, even when its topic is an anchor.
        terminal = True
    if candidate.recurring and (terminal or (topic and not topic.may_spawn_research)):
        return decision("reject_scope", "Terminal questions cannot create recurring obligations")

    parents: list[LineageRecord] = []
    visiting: set[str] = set()
    visited: set[str] = set()
    def walk(identifier: str) -> str | None:
        if identifier == item.id or identifier in visiting:
            return "Lineage cycle or self-parent"
        if identifier in visited:
            return None
        record = lineage.get(identifier)
        if record is None:
            return "Unknown causal parent"
        if record.terminal:
            return "Terminal peripheral or one-off ancestry cannot be relabeled into descendants"
        parent_topic = registry.by_id.get(record.topic_id)
        if (record.status == "archived" or parent_topic is None or not parent_topic.automatic_eligible(now) or
                not parent_topic.may_spawn_research):
            return "Archived, retired, provisional, expired or terminal parent cannot anchor graph expansion"
        if type(record.expansion_priority) is not int or not 0 <= record.expansion_priority <= 100:
            return "Invalid inherited expansion score"
        visiting.add(identifier)
        for ref in record.parent_ids:
            failure = walk(ref)
            if failure:
                return failure
        visiting.remove(identifier)
        visited.add(identifier)
        return None
    for identifier in item.parent_ids:
        failure = walk(identifier)
        if failure:
            return decision("reject_scope", failure)
        parents.append(lineage[identifier])
    if parents:
        roots = sorted({root for parent in parents for root in parent.root_ids})
        if not {anchor for parent in parents for anchor in parent.anchor_ids}.issubset(candidate.original_anchor_ids):
            return decision("reject_scope", "Derived question must retain every original user anchor")
        expected = max(parent.expansion_priority for parent in parents) + policy.child_priority_increment
        # A lower genuine independent path requires an explicit, auditable assessment.
        approved = set(candidate.validated_independent_parent_ids)
        if approved:
            if not approved.issubset(item.parent_ids):
                return decision("reject_scope", "Independent ancestry assessment references a non-parent")
            if any(not candidate.independent_parent_assessments.get(identifier, {}).get("reason") or not candidate.independent_parent_assessments.get(identifier, {}).get("evidence_refs") for identifier in approved):
                return decision("reject_scope", "Lower inherited path needs recorded independent-parent evidence and reason")
            expected = min(parent.expansion_priority for parent in parents if parent.id in approved) + policy.child_priority_increment
        if expected > 100 or item.expansion_priority != expected:
            return decision("reject_scope", "Inherited expansion score overflow/reset or unvalidated lower parent path")
        if item.lineage_root_id not in roots:
            return decision("reject_scope", "Original lineage root was replaced")
    elif item.origin in {"research", "maintenance", "calendar"} and not explicit and candidate.root_reason != "independent_external_event":
        return decision("reject_scope", "Workflow origin cannot manufacture a fresh causal root")
    if not candidate.novelty_key or (not candidate.novelty_evidence_refs and not explicit):
        return decision("archive_candidate", "No recorded new evidence or explicit user request")
    if not parents and not explicit and candidate.root_reason not in {"independent_external_event", "approved_initialization"}:
        return decision("reject_scope", "Automatic root needs new independent evidence provenance")

    prior = lineage.get(item.id)
    if prior and (prior.novelty_key != candidate.novelty_key or prior.question_key != candidate.question_key or prior.parent_ids != item.parent_ids or prior.expansion_priority != item.expansion_priority):
        return decision("reject_scope", "Stable investigation ID reused for different question or lineage")
    for existing in lineage.values():
        if existing.id == item.id:
            continue
        if existing.novelty_key == candidate.novelty_key and existing.question_key == candidate.question_key:
            if existing.id in item.parent_ids:
                return decision("reject_scope", "Duplicate merge would create a self-parent lineage cycle")
            return decision("merge" if existing.status in {"pending", "in_progress", "retry_wait", "blocked"} else "archive_candidate", "Known question/evidence identity; rediscovery is not new research", target=existing.id)
        if existing.question_key == candidate.question_key and existing.parent_ids and not explicit:
            if existing.terminal or not set(existing.parent_ids).issubset(item.parent_ids) or item.expansion_priority < existing.expansion_priority:
                return decision("reject_scope", "New evidence cannot erase the existing question's derived or terminal ancestry")
    if len(candidate.semantic_matches) > policy.max_semantic_comparisons:
        raise ValidationError("semantic comparison exceeds configured bound")
    for match in candidate.semantic_matches:
        existing = lineage.get(match.get("target_id", ""))
        # Semantic equivalence is supplied by the bounded review and remains auditable.
        if not existing or not match.get("assessment_ref") or not match.get("reason"):
            raise ValidationError("semantic comparison requires an existing target and recorded reasoning")
        if match.get("equivalent") and not match.get("new_evidence"):
            if match.get("occurrence_id", "") != item.refresh_occurrence_id:
                continue
            if existing.terminal and parents:
                return decision("reject_scope", "Duplicate merge cannot launder terminal ancestry")
            if existing.id in item.parent_ids:
                return decision("reject_scope", "Semantic merge would create a lineage cycle")
            return decision("merge" if existing.status in {"pending", "in_progress", "retry_wait", "blocked"} else "archive_candidate", "Recorded semantic duplicate without new evidence; preserve existing ancestry", target=existing.id)

    already_active = any(i.id == item.id for i in obligations)
    capacity_full = counts["active_automatic_items"] >= policy.max_active_automatic_items
    over_topics = counts["active_adjacent_topics"] > policy.max_active_adjacent_topics or counts["active_peripheral_topics"] > policy.max_active_peripheral_topics
    if not already_active and (capacity_full or over_topics or (not parents and not explicit and roots_admitted_today >= policy.max_new_automatic_roots_per_day)):
        return decision("defer_capacity", "Preserved inactive candidate; active capacity or daily root admission limit reached")
    if execution and not already_active and not explicit:
        return decision("reject_scope", "Execution requires an admitted active obligation")
    return decision("admit", "Current question relevance, ancestry, novelty and capacity checks passed")


@dataclass
class AdmissionGate:
    registry: TopicRegistry
    candidates: dict[str, AdmissionCandidate] = field(default_factory=dict)
    lineage: dict[str, LineageRecord] = field(default_factory=dict)
    policy: AdmissionPolicy = field(default_factory=AdmissionPolicy)
    decisions: list[AdmissionDecision] = field(default_factory=list)
    timezone_name: str = "UTC"

    def evaluate(self, item: QueueItem, obligations: Iterable[QueueItem], now: datetime, *, execution: bool = False, local_cycle_date: str | None = None) -> AdmissionDecision:
        candidate = self.candidates.get(item.id)
        if candidate is None:
            raise ValidationError("Missing persisted question-specific admission assessment")
        candidate = copy.deepcopy(candidate)
        candidate.item = item
        cycle_date = local_cycle_date or now.astimezone(ZoneInfo(self.timezone_name)).date().isoformat()
        roots_today = len({d.candidate_id for d in self.decisions if d.disposition == "admit" and not d.execution_revalidation and not d.parent_ids and not self.candidates[d.candidate_id].authorization and d.local_cycle_date == cycle_date})
        result = decide_admission(candidate, self.registry, obligations, self.lineage, now=now, policy=self.policy, roots_admitted_today=roots_today, execution=execution, local_cycle_date=cycle_date)
        return result

    def record(self, result: AdmissionDecision) -> None:
        """Call only as part of the durable intake/queue commit; serialize before executing."""
        candidate = self.candidates[result.candidate_id]
        if result.scope_revision != self.registry.scope_revision:
            raise ValidationError("scope changed before admission was committed")
        if result.disposition == "admit":
            existing = self.lineage.get(result.candidate_id)
            if existing is None:
                self.lineage[result.candidate_id] = LineageRecord(result.candidate_id, candidate.item.topic_id, result.parent_ids, result.root_ids, result.original_anchor_ids,
                    result.expansion_priority, result.terminal, result.novelty_key, candidate.question_key, evidence_refs=result.novelty_evidence_refs,
                    explicit_user=_user_exception(candidate, self.registry.instance_id))
            elif (existing.question_key, existing.novelty_key, existing.expansion_priority) != (candidate.question_key, result.novelty_key, result.expansion_priority):
                raise ValidationError("revalidation cannot replace original lineage identity")
        elif result.disposition == "merge":
            existing = self.lineage.get(result.merge_target_id)
            if existing is None:
                raise ValidationError("merge decision has no original lineage target")
            existing.parent_ids = sorted(set(existing.parent_ids) | set(result.parent_ids))
            existing.root_ids = sorted(set(existing.root_ids) | set(result.root_ids))
            existing.anchor_ids = sorted(set(existing.anchor_ids) | set(result.original_anchor_ids))
            existing.expansion_priority = max(existing.expansion_priority, result.expansion_priority)
            existing.terminal = existing.terminal or result.terminal
            existing.evidence_refs = sorted(set(existing.evidence_refs) | set(result.novelty_evidence_refs))
        self.decisions.append(result)

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 2, "instance_id": self.registry.instance_id, "scope_revision": self.registry.scope_revision,
                "candidates": {key: asdict(value) for key, value in self.candidates.items()},
                "lineage": {key: asdict(value) for key, value in self.lineage.items()},
                "policy": asdict(self.policy), "decisions": [d.to_dict() for d in self.decisions], "timezone_name": self.timezone_name}

    @classmethod
    def from_dict(cls, value: dict[str, Any], registry: TopicRegistry) -> "AdmissionGate":
        if value.get("schema_version") != 2 or value.get("instance_id") != registry.instance_id:
            raise ValidationError("admission ledger instance/schema mismatch")
        candidates = {}
        for key, record in value["candidates"].items():
            fields = copy.deepcopy(record)
            fields["item"] = QueueItem(**fields["item"])
            candidates[key] = AdmissionCandidate(**fields)
            if candidates[key].item.id != key:
                raise ValidationError("candidate ledger key/identity mismatch")
        return cls(registry, candidates, {key: LineageRecord(**record) for key, record in value["lineage"].items()}, AdmissionPolicy(**value["policy"]), [AdmissionDecision(**record) for record in value["decisions"]], value.get("timezone_name", "UTC"))
