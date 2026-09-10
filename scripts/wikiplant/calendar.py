from __future__ import annotations

import calendar as month_calendar
import copy
import csv
import io
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from .errors import ValidationError
from .queue import QueueItem, semantic_dedup_key
from .util import ensure_single_line, require_timestamp, sha256_text


CALENDAR_HEADER = [
    "id", "kind", "title", "start_date", "start_at", "end_at", "timezone", "date_precision", "status",
    "related_page_ids", "source_refs", "refresh_question", "priority", "expansion_priority", "recurrence",
    "lead_days", "origin_ref", "updated_at",
]


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

    def validate(self) -> None:
        if self.kind not in {"event", "research_refresh"}:
            raise ValidationError("calendar kind is invalid")
        if self.status not in {"scheduled", "tentative", "completed", "cancelled", "unsupported"}:
            raise ValidationError("calendar status is invalid")
        if self.date_precision not in {"date", "time", "month", "year", "unknown"}:
            raise ValidationError("calendar date precision is invalid")
        try:
            date.fromisoformat(self.start_date)
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
        if self.kind == "research_refresh" and not self.refresh_question:
            raise ValidationError("research refresh requires a question")
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
        if int(self.recurrence.get("interval", 1)) < 1:
            raise ValidationError("recurrence interval must be positive")
        require_timestamp(self.updated_at, "calendar updated_at")
        for field_name in ("id", "title", "refresh_question", "origin_ref"):
            ensure_single_line(getattr(self, field_name), field_name)

    def to_row(self) -> dict[str, str]:
        self.validate()
        values = asdict(self)
        for name in ("related_page_ids", "source_refs", "recurrence"):
            values[name] = json.dumps(values[name], ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return {name: str(values[name]) for name in CALENDAR_HEADER}

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "CalendarItem":
        if list(row) != CALENDAR_HEADER:
            raise ValidationError("calendar header/order mismatch")
        try:
            item = cls(
                id=row["id"], kind=row["kind"], title=row["title"], start_date=row["start_date"],
                start_at=row["start_at"], end_at=row["end_at"], timezone=row["timezone"], date_precision=row["date_precision"],
                status=row["status"], related_page_ids=json.loads(row["related_page_ids"]), source_refs=json.loads(row["source_refs"]),
                refresh_question=row["refresh_question"], priority=int(row["priority"]), expansion_priority=int(row["expansion_priority"]),
                recurrence=json.loads(row["recurrence"]), lead_days=int(row["lead_days"]), origin_ref=row["origin_ref"], updated_at=row["updated_at"],
            )
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ValidationError("invalid calendar row") from exc
        item.validate()
        return item


def read_calendar(text: str) -> list[CalendarItem]:
    if "\r" in text:
        raise ValidationError("calendar must use LF line endings")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames != CALENDAR_HEADER:
        raise ValidationError("calendar header/order mismatch")
    return [CalendarItem.from_row(row) for row in reader]


def write_calendar(items: Iterable[CalendarItem]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CALENDAR_HEADER, lineterminator="\n")
    writer.writeheader()
    for item in sorted(items, key=lambda item: (item.start_date, item.id)):
        writer.writerow(item.to_row())
    return output.getvalue()


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, month_calendar.monthrange(year, month)[1])
    return date(year, month, day)


def occurrences(item: CalendarItem, through: date) -> list[date]:
    item.validate()
    current = date.fromisoformat(item.start_date)
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
            current = _add_months(current, interval)
        if len(result) > 10000:
            raise ValidationError("calendar recurrence exceeds bounded expansion")
    return result


def occurrence_id(item: CalendarItem, when: date) -> str:
    return f"occ-{sha256_text(f'{item.id}\0{when.isoformat()}')[:20]}"


def due_refreshes(items: Iterable[CalendarItem], today: date, occurrence_state: dict[str, str], created_at: str) -> list[QueueItem]:
    queued: list[QueueItem] = []
    for item in items:
        if item.kind != "research_refresh" or item.status in {"cancelled", "completed", "unsupported"}:
            continue
        due_through = today + timedelta(days=item.lead_days)
        for when in occurrences(item, due_through):
            oid = occurrence_id(item, when)
            if occurrence_state.get(oid) in {"queued", "completed", "cancelled"}:
                continue
            lineage = f"calendar-{item.id}"
            queued.append(QueueItem(
                priority=item.priority, id=f"q-{oid}", expansion_priority=item.expansion_priority, kind="refresh",
                question=item.refresh_question, topic_id=item.id, related_page_ids=item.related_page_ids,
                parent_ids=[], lineage_root_id=lineage, origin="calendar", origin_ref=item.id, created_at=created_at,
                due_at=when.isoformat() + "T23:59:59+00:00", priority_reason=f"Calendar refresh due {when.isoformat()}",
                urgency_reason="Calendar deadline requires same-day attention" if item.priority == 0 else "",
                dedup_key=semantic_dedup_key(item.refresh_question, item.id, oid), refresh_occurrence_id=oid,
            ))
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
    revised.status = "scheduled"
    revised.origin_ref = item.id
    revised.updated_at = updated_at
    old.validate()
    revised.validate()
    return old, revised
