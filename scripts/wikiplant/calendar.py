from __future__ import annotations

import calendar as month_calendar
import copy
import csv
import io
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, TYPE_CHECKING
from zoneinfo import ZoneInfo

from .errors import ValidationError
from .queue import QueueItem, semantic_dedup_key
from .util import ensure_single_line, require_timestamp, sha256_text
if TYPE_CHECKING:
    from .admission import AdmissionGate


LEGACY_CALENDAR_HEADER = [
    "id", "kind", "title", "start_date", "start_at", "end_at", "timezone", "date_precision", "status",
    "related_page_ids", "source_refs", "refresh_question", "priority", "expansion_priority", "recurrence",
    "lead_days", "origin_ref", "updated_at",
]
CALENDAR_HEADER = LEGACY_CALENDAR_HEADER + ["schema_version", "topic_id", "parent_ids", "lineage_root_id", "root_reason"]


@dataclass
class CalendarItem:
    id: str
    kind: str
    title: str
    start_date: str
    start_at: str
    end_at: str
    timezone: str
    date_precision: str
    status: str
    related_page_ids: list[str]
    source_refs: list[str]
    refresh_question: str
    priority: int
    expansion_priority: int
    recurrence: dict
    lead_days: int
    origin_ref: str
    updated_at: str
    schema_version: int = 1  # Explicit legacy input; new workflow authors must supply 2.
    topic_id: str = ""
    parent_ids: list[str] = field(default_factory=list)
    lineage_root_id: str = ""
    root_reason: str = ""

    def validate(self) -> None:
        if not self.id or not self.title or self.schema_version not in {1, 2}:
            raise ValidationError("calendar stable identity/title/schema required")
        if self.schema_version == 2 and self.kind == "research_refresh" and (not self.topic_id or not self.lineage_root_id):
            raise ValidationError("v2 refresh requires topic and original lineage binding")
        if not isinstance(self.parent_ids, list) or len(set(self.parent_ids)) != len(self.parent_ids):
            raise ValidationError("calendar causal parents must be unique IDs")
        if self.kind not in {"event", "research_refresh"}:
            raise ValidationError("calendar kind is invalid")
        if self.status not in {"scheduled", "tentative", "completed", "cancelled", "unsupported"}:
            raise ValidationError("calendar status is invalid")
        if self.date_precision not in {"date", "time", "month", "year", "unknown"}:
            raise ValidationError("calendar date precision is invalid")
        try:
            _start_day(self)
        except ValueError as exc:
            raise ValidationError("calendar start_date must be YYYY-MM-DD") from exc
        try:
            ZoneInfo(self.timezone)
        except Exception as exc:
            raise ValidationError("calendar timezone must be an IANA name") from exc
        if self.start_at:
            require_timestamp(self.start_at, "calendar start_at")
        if self.end_at:
            require_timestamp(self.end_at, "calendar end_at")
        if self.date_precision == "time" and not self.start_at:
            raise ValidationError("time-precision calendar items require start_at")
        if self.start_at and self.date_precision == "time" and require_timestamp(self.start_at).astimezone(ZoneInfo(self.timezone)).date() != _start_day(self):
            raise ValidationError("calendar date and actual local start time disagree")
        if self.kind == "research_refresh" and not self.refresh_question:
            raise ValidationError("research refresh requires a question")
        if self.kind == "research_refresh" and self.date_precision not in {"date", "time"}:
            raise ValidationError("executable refresh needs known date/time precision")
        if self.start_at and self.end_at and require_timestamp(self.end_at) < require_timestamp(self.start_at):
            raise ValidationError("calendar end precedes start")
        if type(self.priority) is not int or not 0 <= self.priority <= 100:
            raise ValidationError("calendar priority must be in [0,100]")
        if type(self.expansion_priority) is not int or not 0 <= self.expansion_priority <= 100:
            raise ValidationError("calendar expansion priority must be in [0,100]")
        if type(self.lead_days) is not int or self.lead_days < 0:
            raise ValidationError("lead_days must be nonnegative")
        frequency = self.recurrence.get("frequency", "none")
        if frequency not in {"none", "daily", "weekly", "monthly"}:
            raise ValidationError("unsupported recurrence")
        if any(key not in {"frequency", "interval", "until"} for key in self.recurrence):
            raise ValidationError("unsupported recurrence field")
        if type(self.recurrence.get("interval", 1)) is not int or self.recurrence.get("interval", 1) < 1:
            raise ValidationError("recurrence interval must be positive")
        if self.recurrence.get("until"):
            date.fromisoformat(self.recurrence["until"])
        if self.date_precision in {"unknown", "month", "year"} and frequency != "none":
            raise ValidationError("partial-date recurrence is unsupported")
        require_timestamp(self.updated_at, "calendar updated_at")
        for field_name in ("id", "title", "refresh_question", "origin_ref"):
            ensure_single_line(getattr(self, field_name), field_name)

    def to_row(self) -> dict[str, str]:
        self.validate()
        values = asdict(self)
        for name in ("related_page_ids", "source_refs", "recurrence", "parent_ids"):
            values[name] = json.dumps(values[name], ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return {name: str(values[name]) for name in CALENDAR_HEADER}

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "CalendarItem":
        if list(row) not in (CALENDAR_HEADER, LEGACY_CALENDAR_HEADER):
            raise ValidationError("calendar header/order mismatch")
        try:
            item = cls(
                id=row["id"], kind=row["kind"], title=row["title"], start_date=row["start_date"],
                start_at=row["start_at"], end_at=row["end_at"], timezone=row["timezone"], date_precision=row["date_precision"],
                status=row["status"], related_page_ids=json.loads(row["related_page_ids"]), source_refs=json.loads(row["source_refs"]),
                refresh_question=row["refresh_question"], priority=int(row["priority"]), expansion_priority=int(row["expansion_priority"]),
                recurrence=json.loads(row["recurrence"]), lead_days=int(row["lead_days"]), origin_ref=row["origin_ref"], updated_at=row["updated_at"],
                schema_version=int(row.get("schema_version", 1)), topic_id=row.get("topic_id", ""), parent_ids=json.loads(row.get("parent_ids", "[]")),
                lineage_root_id=row.get("lineage_root_id", ""), root_reason=row.get("root_reason", ""),
            )
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ValidationError("invalid calendar row") from exc
        item.validate()
        return item


def read_calendar(text: str) -> list[CalendarItem]:
    if "\r" in text:
        raise ValidationError("calendar must use LF line endings")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames not in (CALENDAR_HEADER, LEGACY_CALENDAR_HEADER):
        raise ValidationError("calendar header/order mismatch")
    items = [CalendarItem.from_row(row) for row in reader]
    _unique_ids(items)
    return items


def write_calendar(items: Iterable[CalendarItem]) -> str:
    items = list(items)
    _unique_ids(items)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CALENDAR_HEADER, lineterminator="\n")
    writer.writeheader()
    for item in sorted(items, key=lambda item: (item.start_date, item.id)):
        writer.writerow(item.to_row())
    return output.getvalue()


def _unique_ids(items: list[CalendarItem]) -> None:
    if len({item.id for item in items}) != len(items):
        raise ValidationError("duplicate stable calendar ID")


def _start_day(item: CalendarItem) -> date:
    if item.date_precision == "unknown" and not item.start_date:
        return date.max
    if item.date_precision == "month" and len(item.start_date) == 7:
        return date.fromisoformat(item.start_date + "-01")
    if item.date_precision == "year" and len(item.start_date) == 4:
        return date.fromisoformat(item.start_date + "-01-01")
    return date.fromisoformat(item.start_date)


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, month_calendar.monthrange(year, month)[1])
    return date(year, month, day)


def occurrences(item: CalendarItem, through: date) -> list[date]:
    item.validate()
    current = _start_day(item)
    anchor = current
    occurrence_index = 0
    frequency = item.recurrence.get("frequency", "none")
    interval = int(item.recurrence.get("interval", 1))
    until = date.fromisoformat(item.recurrence["until"]) if item.recurrence.get("until") else through
    end = min(through, until)
    result: list[date] = []
    while current <= end:
        result.append(current)
        if frequency == "none":
            break
        if frequency == "daily":
            current += timedelta(days=interval)
        elif frequency == "weekly":
            current += timedelta(weeks=interval)
        else:
            occurrence_index += 1
            current = _add_months(anchor, interval * occurrence_index)
        if len(result) > 10000:
            raise ValidationError("calendar recurrence exceeds bounded expansion")
    return result


def occurrence_id(item: CalendarItem, when: date) -> str:
    return f"occ-{sha256_text(f'{item.id}\0{when.isoformat()}')[:20]}"


def due_refreshes(items: Iterable[CalendarItem], today: date, occurrence_state: dict[str, str], created_at: str, *,
                  admission_gate: "AdmissionGate | None" = None, obligations: Iterable[QueueItem] = (),
                  coverage_log: list[dict] | None = None) -> list[QueueItem]:
    items = list(items)
    _unique_ids(items)
    queued: list[QueueItem] = []
    for item in items:
        if item.kind != "research_refresh" or item.status in {"cancelled", "completed", "unsupported"}:
            continue
        due_through = today + timedelta(days=item.lead_days)
        dates = occurrences(item, due_through)
        processed = [when for when in dates if occurrence_state.get(occurrence_id(item, when)) in {"queued", "completed", "cancelled"}]
        pending = [when for when in dates if (not processed or when > max(processed)) and occurrence_state.get(occurrence_id(item, when)) not in {"queued", "completed", "cancelled"}]
        # A refresh asks for current observations; one latest occurrence covers
        # missed equivalent checks. Persist coverage only with the resulting queue receipt.
        for when in pending[-1:]:
            oid = occurrence_id(item, when)
            if occurrence_state.get(oid) in {"queued", "completed", "cancelled"}:
                continue
            lineage = item.lineage_root_id or f"calendar-{item.id}"
            topic_id = item.topic_id or item.id  # Legacy rows only; v2 validation forbids this.
            candidate_item = QueueItem(
                priority=item.priority, id=f"q-{oid}", expansion_priority=item.expansion_priority, kind="refresh",
                question=item.refresh_question, topic_id=topic_id, related_page_ids=item.related_page_ids,
                parent_ids=list(item.parent_ids), lineage_root_id=lineage, origin="calendar", origin_ref=item.id, created_at=created_at,
                due_at=datetime.combine(when, time(23, 59, 59), ZoneInfo(item.timezone)).isoformat(), priority_reason=f"Calendar refresh due {when.isoformat()}",
                urgency_reason="Calendar deadline requires same-day attention" if item.priority == 0 else "",
                dedup_key=semantic_dedup_key(item.refresh_question, topic_id, oid), refresh_occurrence_id=oid,
            )
            if item.schema_version == 2:
                if admission_gate is None:
                    raise ValidationError("v2 calendar intake requires shared admission")
                assessment = admission_gate.candidates.get(candidate_item.id)
                if assessment is None:
                    raise ValidationError("calendar occurrence needs a recorded question-specific assessment")
                assessment.recurring = item.recurrence.get("frequency", "none") != "none"
                result = admission_gate.evaluate(candidate_item, list(obligations) + queued, require_timestamp(created_at))
                if result.disposition != "admit":
                    if coverage_log is not None:
                        coverage_log.append({"calendar_id": item.id, "disposition": result.disposition, "reason": result.reason})
                    continue
            queued.append(candidate_item)
            if coverage_log is not None:
                coverage_log.append({"calendar_id": item.id, "occurrence_id": oid, "coalesced_occurrence_ids": [occurrence_id(item, day) for day in pending[:-1]]})
    return queued


def mark_occurrence_queued(occurrence_state: dict[str, str], queue_item: QueueItem) -> None:
    if not queue_item.refresh_occurrence_id:
        raise ValidationError("queue item is not tied to a calendar occurrence")
    occurrence_state[queue_item.refresh_occurrence_id] = "queued"


def visible_events(items: Iterable[CalendarItem], today: date, upcoming_days: int = 7) -> list[tuple[CalendarItem, date]]:
    end = today + timedelta(days=upcoming_days)
    visible: list[tuple[CalendarItem, date]] = []
    for item in items:
        if item.kind != "event" or item.status in {"cancelled", "unsupported"}:
            continue
        if item.date_precision == "unknown":
            continue
        if item.date_precision in {"month", "year"}:
            start = _start_day(item)
            stop = date(start.year, 12, 31) if item.date_precision == "year" else date(start.year, start.month, month_calendar.monthrange(start.year, start.month)[1])
            if start <= end and stop >= today:
                visible.append((item, max(start, today)))
            continue
        for when in occurrences(item, end):
            if today <= when <= end:
                visible.append((item, when))
    return sorted(visible, key=lambda pair: (pair[1], pair[0].priority, pair[0].id))


def reschedule(item: CalendarItem, *, new_id: str, new_start_date: str, updated_at: str) -> tuple[CalendarItem, CalendarItem]:
    """Return a cancelled historical row and a new linked live row."""
    item.validate()
    old = copy.deepcopy(item)
    old.status = "cancelled"
    old.updated_at = updated_at
    revised = copy.deepcopy(item)
    revised.id = new_id
    revised.start_date = new_start_date
    if item.start_at:
        zone = ZoneInfo(item.timezone)
        previous_start = require_timestamp(item.start_at)
        clock = previous_start.astimezone(zone).time().replace(tzinfo=None)
        new_start = datetime.combine(date.fromisoformat(new_start_date), clock, zone)
        revised.start_at = new_start.isoformat()
        if item.end_at:
            duration = require_timestamp(item.end_at).astimezone(timezone.utc) - previous_start.astimezone(timezone.utc)
            revised.end_at = (new_start.astimezone(timezone.utc) + duration).astimezone(zone).isoformat()
    revised.status = "scheduled"
    revised.origin_ref = item.id
    revised.updated_at = updated_at
    old.validate()
    revised.validate()
    return old, revised
