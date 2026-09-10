from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from .errors import ValidationError
from .util import ensure_single_line, normalize_question, require_timestamp, sha256_text


QUEUE_HEADER = [
    "priority", "id", "expansion_priority", "kind", "question", "topic_id", "related_page_ids",
    "parent_ids", "lineage_root_id", "origin", "origin_ref", "created_at", "not_before", "due_at",
    "status", "attempts", "priority_reason", "urgency_reason", "dedup_key", "refresh_occurrence_id",
]
KINDS = {"investigation", "refresh", "contradiction", "validation"}
ORIGINS = {"user", "initialization", "main-topic", "discovery", "research", "calendar", "maintenance"}
STATUSES = {"pending", "in_progress", "retry_wait", "blocked"}


@dataclass
class QueueItem:
    priority: int
    id: str
    expansion_priority: int
    kind: str
    question: str
    topic_id: str
    related_page_ids: list[str]
    parent_ids: list[str]
    lineage_root_id: str
    origin: str
    origin_ref: str
    created_at: str
    not_before: str = ""
    due_at: str = ""
    status: str = "pending"
    attempts: int = 0
    priority_reason: str = ""
    urgency_reason: str = ""
    dedup_key: str = ""
    refresh_occurrence_id: str = ""

    def validate(self) -> None:
        for name in ("priority", "expansion_priority"):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 100:
                raise ValidationError(f"{name} must be an integer in [0,100]")
        if not self.id or not self.question or not self.topic_id or not self.lineage_root_id:
            raise ValidationError("queue identity, question, topic, and lineage root are required")
        for field_name in ("id", "question", "topic_id", "lineage_root_id", "origin_ref", "priority_reason", "urgency_reason", "dedup_key", "refresh_occurrence_id"):
            ensure_single_line(str(getattr(self, field_name)), field_name)
        if self.kind not in KINDS or self.origin not in ORIGINS or self.status not in STATUSES:
            raise ValidationError("queue enum value is invalid")
        require_timestamp(self.created_at, "created_at")
        for name in ("not_before", "due_at"):
            if getattr(self, name):
                require_timestamp(getattr(self, name), name)
        if type(self.attempts) is not int or self.attempts < 0:
            raise ValidationError("attempts must be a nonnegative integer")
        if self.priority == 0 and not self.urgency_reason.strip():
            raise ValidationError("priority 0 requires a nonempty urgency reason")
        if not isinstance(self.related_page_ids, list) or not isinstance(self.parent_ids, list):
            raise ValidationError("queue list fields must be arrays")
        if not self.dedup_key:
            self.dedup_key = normalized_question_key(self.question, self.topic_id, self.refresh_occurrence_id)

    def to_row(self) -> dict[str, str]:
        self.validate()
        values = asdict(self)
        values["related_page_ids"] = json.dumps(self.related_page_ids, ensure_ascii=False, separators=(",", ":"))
        values["parent_ids"] = json.dumps(self.parent_ids, ensure_ascii=False, separators=(",", ":"))
        return {name: str(values[name]) for name in QUEUE_HEADER}

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "QueueItem":
        if list(row) != QUEUE_HEADER:
            raise ValidationError("research queue header/order mismatch")
        try:
            item = cls(
                priority=int(row["priority"]), id=row["id"], expansion_priority=int(row["expansion_priority"]),
                kind=row["kind"], question=row["question"], topic_id=row["topic_id"],
                related_page_ids=json.loads(row["related_page_ids"]), parent_ids=json.loads(row["parent_ids"]),
                lineage_root_id=row["lineage_root_id"], origin=row["origin"], origin_ref=row["origin_ref"],
                created_at=row["created_at"], not_before=row["not_before"], due_at=row["due_at"],
                status=row["status"], attempts=int(row["attempts"]), priority_reason=row["priority_reason"],
                urgency_reason=row["urgency_reason"], dedup_key=row["dedup_key"], refresh_occurrence_id=row["refresh_occurrence_id"],
            )
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ValidationError("invalid research queue row") from exc
        item.validate()
        return item


def normalized_question_key(question: str, topic_id: str, occurrence_id: str = "") -> str:
    """Lexical normalization only; semantic comparison belongs to recorded admission review."""
    return sha256_text("\0".join((normalize_question(question), topic_id.casefold(), occurrence_id)))[:24]


# Explicit legacy import compatibility, not a claim of semantic equivalence.
semantic_dedup_key = normalized_question_key


def _unique_ids(items: list[QueueItem]) -> None:
    if len({item.id for item in items}) != len(items):
        raise ValidationError("duplicate stable queue ID")


def read_queue(text: str) -> list[QueueItem]:
    if "\r" in text:
        raise ValidationError("queue must use LF line endings")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames != QUEUE_HEADER:
        raise ValidationError("research queue header/order mismatch")
    items = [QueueItem.from_row(row) for row in reader]
    _unique_ids(items)
    if items != sort_queue(items):
        raise ValidationError("research queue must be in canonical numeric order")
    return items


def write_queue(items: Iterable[QueueItem]) -> str:
    sorted_items = sort_queue(list(items))
    _unique_ids(sorted_items)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=QUEUE_HEADER, lineterminator="\n")
    writer.writeheader()
    for item in sorted_items:
        writer.writerow(item.to_row())
    return output.getvalue()


def _deadline(value: str) -> tuple[int, datetime]:
    return (0, require_timestamp(value, "due_at")) if value else (1, datetime.max.replace(tzinfo=timezone.utc))


def sort_queue(items: list[QueueItem]) -> list[QueueItem]:
    return sorted(items, key=lambda item: (item.priority, _deadline(item.due_at), require_timestamp(item.created_at, "created_at"), item.id))


def merge_duplicate(existing: QueueItem, incoming: QueueItem) -> QueueItem:
    existing.validate()
    incoming.validate()
    if existing.dedup_key != incoming.dedup_key:
        raise ValidationError("cannot merge non-equivalent queue items")
    existing.priority = min(existing.priority, incoming.priority)
    # An unvalidated low score must never replenish depth. Admission records can
    # establish a genuine independent path before a separate explicit migration.
    existing.expansion_priority = max(existing.expansion_priority, incoming.expansion_priority)
    existing.related_page_ids = list(dict.fromkeys(existing.related_page_ids + incoming.related_page_ids))
    existing.parent_ids = list(dict.fromkeys(existing.parent_ids + incoming.parent_ids))
    if incoming.due_at and (not existing.due_at or require_timestamp(incoming.due_at) < require_timestamp(existing.due_at)):
        existing.due_at = incoming.due_at
    if incoming.priority == 0 and incoming.urgency_reason:
        existing.urgency_reason = incoming.urgency_reason
    if incoming.priority_reason and incoming.priority_reason not in existing.priority_reason:
        existing.priority_reason = "; ".join(filter(None, (existing.priority_reason, incoming.priority_reason)))
    return existing


def deduplicate(items: Iterable[QueueItem]) -> list[QueueItem]:
    items = list(items)
    identities: dict[str, str] = {}
    by_key: dict[str, QueueItem] = {}
    for item in items:
        item.validate()
        identity = json.dumps(item.to_row(), sort_keys=True)
        if item.id in identities:
            if identities[item.id] != identity:
                raise ValidationError("stable queue ID reused for different content")
            continue
        identities[item.id] = identity
        if item.dedup_key in by_key:
            merge_duplicate(by_key[item.dedup_key], item)
        else:
            by_key[item.dedup_key] = item
    return sort_queue(list(by_key.values()))


def derived_child(
    *, child_id: str, question: str, topic_id: str, parents: list[QueueItem], created_at: str,
    increment: int = 20, priority_reason: str, related_page_ids: list[str] | None = None,
) -> QueueItem | None:
    if not parents:
        raise ValidationError("derived research requires causal parents")
    if type(increment) is not int or increment < 1:
        raise ValidationError("child increment must be a positive integer")
    _unique_ids(parents)
    if child_id in {p.id for p in parents}:
        raise ValidationError("child cannot be its own causal parent")
    for parent in parents:
        parent.validate()
    inherited = min(parent.expansion_priority for parent in parents) + increment
    if inherited > 100:
        return None
    root_parent = min(parents, key=lambda p: (p.expansion_priority, p.id))
    child = QueueItem(
        priority=inherited, id=child_id, expansion_priority=inherited, kind="investigation", question=question,
        topic_id=topic_id, related_page_ids=related_page_ids or [], parent_ids=[p.id for p in parents],
        lineage_root_id=root_parent.lineage_root_id, origin="research", origin_ref=root_parent.id,
        created_at=created_at, priority_reason=priority_reason,
        dedup_key=semantic_dedup_key(question, topic_id),
    )
    child.validate()
    return child


def admit_children(candidates: Iterable[QueueItem | None], persisted_ids: list[str], max_children: int = 3) -> tuple[list[QueueItem], list[str]]:
    if max_children < 0:
        raise ValidationError("max_children must be nonnegative")
    admitted: list[QueueItem] = []
    ids = list(persisted_ids)
    for child in candidates:
        if child is None or child.id in ids:
            continue
        if len(ids) >= max_children:
            break
        child.validate()
        admitted.append(child)
        ids.append(child.id)
    return admitted, ids


@dataclass
class AttemptReservation:
    reservation_id: str
    item_id: str
    slot: int
    cycle_key: str
    status: str = "reserved"


@dataclass
class DailyBudget:
    instance_id: str
    local_date: str
    timezone: str
    reservations: list[AttemptReservation] = field(default_factory=list)

    @property
    def cycle_key(self) -> str:
        return f"{self.instance_id}:{self.local_date}"

    def reserve(self, item: QueueItem, *, resume_reservation_id: str | None = None) -> AttemptReservation | None:
        if resume_reservation_id:
            found = next((r for r in self.reservations if r.reservation_id == resume_reservation_id and r.item_id == item.id), None)
            if not found:
                raise ValidationError("resume reservation does not match item/cycle")
            return found
        used = len(self.reservations)
        if used >= 10 or (used >= 5 and item.priority != 0):
            return None
        if item.priority == 0 and not item.urgency_reason:
            raise ValidationError("urgent extension requires an urgency reason")
        reservation = AttemptReservation(f"{self.cycle_key}:slot-{used + 1}", item.id, used + 1, self.cycle_key)
        self.reservations.append(reservation)
        return reservation

    def transition_timezone(self, new_timezone: str) -> None:
        """Change display/scheduling timezone without changing this cycle's budget key."""
        self.timezone = new_timezone


def eligible(item: QueueItem, now: datetime) -> bool:
    if item.status not in {"pending", "retry_wait"}:
        return False
    return not item.not_before or require_timestamp(item.not_before) <= now


def select_next(items: Iterable[QueueItem], budget: DailyBudget, now: datetime, *, validation_lane_slot: int = 5,
                service_counts: dict[str, int] | None = None, ageing_days: int = 14,
                selection_log: list[dict] | None = None, anchor_ids_by_topic: dict[str, list[str]] | None = None) -> QueueItem | None:
    if type(validation_lane_slot) is not int or not 1 <= validation_lane_slot <= 5:
        raise ValidationError("validation lane must occupy one of the first five slots")
    if type(ageing_days) is not int or ageing_days < 1:
        raise ValidationError("ageing interval must be positive")
    candidates = [item for item in items if eligible(item, now)]
    _unique_ids(candidates)
    next_slot = len(budget.reservations) + 1
    if next_slot > 10 or not candidates:
        return None
    if len(budget.reservations) >= 5:
        candidates = [item for item in candidates if item.priority == 0 and item.urgency_reason]
    urgent = sort_queue([item for item in candidates if item.priority == 0 and item.urgency_reason])
    overdue = sort_queue([item for item in candidates if item.kind in {"validation", "contradiction"} and item.due_at and require_timestamp(item.due_at) <= now])
    selected = None
    reason = "numeric priority and stable deadline order"
    if urgent:
        selected = urgent[0]
        reason = "genuinely urgent work takes precedence"
        if next_slot == validation_lane_slot and overdue:
            reason += "; overdue validation deferred by urgency"
    elif next_slot == validation_lane_slot and overdue:
        selected = overdue[0]
        reason = "reserved ordinary slot serves overdue validation"
    elif candidates:
        # Ageing can serve old work without rewriting its research priority.
        aged = [item for item in candidates if (now - require_timestamp(item.created_at)).days >= ageing_days]
        if aged and service_counts is not None:
            def served(item):
                anchors = (anchor_ids_by_topic or {}).get(item.topic_id, [item.topic_id])
                return max((service_counts.get(anchor, 0) for anchor in anchors), default=0)
            selected = min(aged, key=lambda item: (served(item), require_timestamp(item.created_at), item.priority, item.id))
            reason = "ageing and per-anchor service fairness"
        else:
            selected = sort_queue(candidates)[0]
    if selection_log is not None:
        selection_log.append({"slot": next_slot, "selected_id": selected.id if selected else None, "reason": reason,
                              "overdue_validation_ids": [i.id for i in overdue], "validation_deferred_by_urgency": bool(urgent and overdue and next_slot == validation_lane_slot)})
    return selected
