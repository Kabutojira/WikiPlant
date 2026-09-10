from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from .errors import ValidationError


CoverageStatus = Literal["in_progress", "complete", "no_material_update", "partial", "blocked"]


@dataclass
class MonitoringRecord:
    instance_id: str
    local_date: str
    topic_id: str
    coverage_start: str
    coverage_end: str
    max_queries: int
    max_sources: int
    queries_used: int = 0
    sources_used: int = 0
    status: CoverageStatus = "in_progress"
    findings: list[str] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)
    wiki_change_ids: list[str] = field(default_factory=list)
    deeper_question_ids: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.instance_id}:{self.local_date}:{self.topic_id}"

    def reserve_query(self) -> int | None:
        if self.status in {"complete", "no_material_update"} or self.queries_used >= self.max_queries:
            return None
        self.queries_used += 1
        return self.queries_used

    def reserve_source(self) -> int | None:
        if self.status in {"complete", "no_material_update"} or self.sources_used >= self.max_sources:
            return None
        self.sources_used += 1
        return self.sources_used

    def finish(self, status: CoverageStatus, *, limitation: str = "") -> None:
        if status not in {"complete", "no_material_update", "partial", "blocked"}:
            raise ValidationError("invalid final monitoring status")
        if status == "no_material_update" and self.queries_used == 0:
            raise ValidationError("no-update requires at least one successful search")
        if status in {"partial", "blocked"} and limitation:
            self.limitations.append(limitation)
        self.status = status


class MonitoringLedger:
    def __init__(self) -> None:
        self.records: dict[str, MonitoringRecord] = {}

    def begin(
        self, *, instance_id: str, local_date: str, topic_id: str, last_successful_end: str,
        scheduled_end: str, overlap_hours: int, max_queries: int, max_sources: int,
    ) -> tuple[MonitoringRecord, bool]:
        key = f"{instance_id}:{local_date}:{topic_id}"
        if key in self.records:
            return self.records[key], False
        start = datetime.fromisoformat(last_successful_end.replace("Z", "+00:00")) - timedelta(hours=overlap_hours)
        record = MonitoringRecord(instance_id, local_date, topic_id, start.isoformat(), scheduled_end, max_queries, max_sources)
        self.records[key] = record
        return record, True


def is_new_event(*, publication_at: datetime | None, event_at: datetime | None, coverage_start: datetime) -> bool:
    relevant = event_at or publication_at
    return relevant is not None and relevant >= coverage_start
