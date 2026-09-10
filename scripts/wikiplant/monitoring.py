from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from .errors import ValidationError
from .storage import validate_binding
from .util import pretty_json, sha256_text
import json


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
    query_results: dict[str, dict] = field(default_factory=dict)
    source_results: dict[str, dict] = field(default_factory=dict)
    successful_watermark: str | None = None
    evidence_assessment_ref: str | None = None
    claim_ids: list[str] = field(default_factory=list)
    challenge_ids: list[str] = field(default_factory=list)
    affected_page_ids: list[str] = field(default_factory=list)
    schema_version: int = 2

    @property
    def key(self) -> str:
        return f"{self.instance_id}:{self.local_date}:{self.topic_id}"

    def validate(self) -> None:
        from datetime import date
        from .util import require_timestamp
        if not all(isinstance(v, str) and v for v in (self.instance_id, self.local_date, self.topic_id)):
            raise ValidationError("monitoring identity is required")
        date.fromisoformat(self.local_date)
        if require_timestamp(self.coverage_start) > require_timestamp(self.coverage_end):
            raise ValidationError("monitoring coverage interval is reversed")
        for used, maximum in ((self.queries_used, self.max_queries), (self.sources_used, self.max_sources)):
            if type(used) is not int or type(maximum) is not int or maximum < 1 or not 0 <= used <= maximum:
                raise ValidationError("invalid monitoring resource counters")
        for results, used in ((self.query_results, self.queries_used), (self.source_results, self.sources_used)):
            if any(not key.isdigit() or not 1 <= int(key) <= used for key in results):
                raise ValidationError("unreserved monitoring result")

    def reserve_query(self) -> int | None:
        self.validate()
        if self.status in {"complete", "no_material_update"} or self.queries_used >= self.max_queries:
            return None
        self.queries_used += 1
        return self.queries_used

    def reserve_source(self) -> int | None:
        self.validate()
        if self.status in {"complete", "no_material_update"} or self.sources_used >= self.max_sources:
            return None
        self.sources_used += 1
        return self.sources_used

    def finish(self, status: CoverageStatus, *, limitation: str = "") -> None:
        self.validate()
        if status not in {"complete", "no_material_update", "partial", "blocked"}:
            raise ValidationError("invalid final monitoring status")
        if status in {"complete", "no_material_update"}:
            if not self.query_results or not any(r["status"] == "success" for r in self.query_results.values()):
                raise ValidationError("successful coverage requires observed successful search results")
            recovered = {str(r["replaces_reservation"]) for r in self.query_results.values() if r["status"] == "success" and r.get("replaces_reservation")}
            if len(self.query_results) != self.queries_used or any(r["status"] != "success" and key not in recovered for key, r in self.query_results.items()):
                raise ValidationError("failed or unresolved searches require partial coverage")
            if len(self.source_results) != self.sources_used or any(r["status"] != "inspected" for r in self.source_results.values()):
                raise ValidationError("uninspected/failed sources require partial coverage")
            if self.findings and not self.source_results:
                raise ValidationError("material findings require inspected sources")
            if status == "no_material_update" and self.findings:
                raise ValidationError("no-update cannot contain material findings")
            self.successful_watermark = self.coverage_end
        if status in {"partial", "blocked"} and limitation:
            if limitation not in self.limitations:
                self.limitations.append(limitation)
        if status in {"partial", "blocked"}:
            self.successful_watermark = None
        self.status = status

    def record_query(self, reservation: int, *, status: str, query: str, result_reference: str = "", limitation: str = "", replaces_reservation: int | None = None) -> None:
        if reservation < 1 or reservation > self.queries_used or status not in {"success", "failed", "blocked"}:
            raise ValidationError("query result must correspond to a reserved invocation")
        if status == "success" and not result_reference:
            raise ValidationError("successful query requires an observed result reference")
        value = {"status": status, "query": query, "result_reference": result_reference, "limitation": limitation}
        if replaces_reservation is not None:
            prior = self.query_results.get(str(replaces_reservation), {})
            if status != "success" or replaces_reservation >= reservation or prior.get("status") not in {"failed", "blocked"} or prior.get("query") != query:
                raise ValidationError("successful retry must cover the same failed query and interval")
            value["replaces_reservation"] = replaces_reservation
        key = str(reservation)
        if key in self.query_results and self.query_results[key] != value:
            raise ValidationError("query attempt outcome cannot be rewritten")
        self.query_results[key] = value

    def record_source(self, reservation: int, *, source_id: str, status: str, locator: str = "") -> None:
        if reservation < 1 or reservation > self.sources_used or status not in {"inspected", "failed", "blocked"}:
            raise ValidationError("source result must correspond to its reserved invocation")
        if status == "inspected" and (not source_id or not locator):
            raise ValidationError("source inspection requires source identity and locator")
        value = {"status": status, "source_id": source_id, "locator": locator}
        key = str(reservation)
        if key in self.source_results and self.source_results[key] != value:
            raise ValidationError("source outcome cannot be rewritten")
        self.source_results[key] = value


class MonitoringLedger:
    def __init__(self) -> None:
        self.records: dict[str, MonitoringRecord] = {}

    def to_dict(self) -> dict:
        return {key: asdict(record) for key, record in self.records.items()}

    @classmethod
    def from_dict(cls, values: dict) -> "MonitoringLedger":
        ledger = cls()
        for key, value in values.items():
            record = MonitoringRecord(**value)
            record.validate()
            if key != record.key:
                raise ValidationError("monitoring ledger identity mismatch")
            ledger.records[key] = record
        return ledger

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


def validate_monitoring_assessment(adapter, root_id, record):
    """Resolve material findings against saved sources; no labels-only receipt."""
    from .storage import validate_scope
    from .evidence import validate_assessment_payload
    from .records import SourceRecord
    if not record.evidence_assessment_ref:
        raise ValidationError("material monitoring needs a saved evidence assessment")
    raw = validate_scope(adapter, record.evidence_assessment_ref, root_id)
    if raw.mime_type != "application/json":
        raise ValidationError("monitoring assessment must be raw JSON")
    assessment = json.loads(raw.content)
    expected = dict(schema_version=2, kind="monitoring_assessment", instance_id=record.instance_id,
        local_date=record.local_date, topic_id=record.topic_id, monitoring_key=record.key,
        coverage_start=record.coverage_start, coverage_end=record.coverage_end)
    if any(assessment.get(key) != value for key, value in expected.items()):
        raise ValidationError("monitoring assessment has another binding or coverage interval")
    assessment = validate_assessment_payload(adapter, root_id, assessment)
    if set(record.claim_ids) != {c["id"] for c in assessment["claims"]} or set(record.challenge_ids) != {c["id"] for c in assessment.get("challenges", [])}:
        raise ValidationError("monitoring assessment inventory mismatch")
    if record.findings != [f["text"] for f in assessment["findings"]]:
        raise ValidationError("monitoring findings differ from assessed findings")
    for observed in record.source_results.values():
        if observed["status"] != "inspected":
            continue
        binding = assessment["source_files"].get(observed["source_id"])
        if binding is None:
            raise ValidationError("monitoring inspection has no saved source artifact")
        source = SourceRecord.from_dict(json.loads(validate_scope(adapter, binding["file_id"], root_id).content))
        if observed["locator"] not in source.inspected_passages:
            raise ValidationError("monitoring inspection locator was not saved")
    if record.findings and (not record.affected_page_ids or not record.claim_ids):
        raise ValidationError("material monitoring must identify its claims and affected wiki pages")
    return assessment


class PersistentMonitoringLedger(MonitoringLedger):
    """Persist each reservation and observed result through the shared writer."""

    def __init__(self, writer, binding, *, execution_guard):
        self.writer, self.binding, self.execution_guard = writer, binding, execution_guard
        self.snapshot = validate_binding(writer.adapter, binding, writer.root_id)
        self.records = MonitoringLedger.from_dict(json.loads(self.snapshot.content)).records

    def save(self):
        if not self.execution_guard():
            raise ValidationError("monitoring requires an observed strict or best-effort execution guard")
        payload = pretty_json(self.to_dict()).encode()
        op = f"monitoring:{self.snapshot.revision}:{sha256_text(payload.decode())}"
        self.snapshot = self.writer.replace(self.binding, payload, op, base=self.snapshot).current

    def begin(self, **kwargs):
        result = super().begin(**kwargs)
        self.save()
        return result

    def search(self, record, query: str, invoke, *, replaces_reservation: int | None = None):
        self._owned(record)
        reservation = record.reserve_query()
        if reservation is None:
            return None
        self.save()
        try:
            result = invoke(query)
            if not isinstance(result, dict) or not result.get("reference"):
                raise ValidationError("search invocation lacks observed reference")
            record.record_query(reservation, status="success", query=query, result_reference=result["reference"], replaces_reservation=replaces_reservation)
        except Exception as exc:
            record.record_query(reservation, status="failed", query=query, limitation=str(exc))
            self.save()
            raise
        self.save()
        return result

    def inspect(self, record, source_id: str, invoke):
        self._owned(record)
        reservation = record.reserve_source()
        if reservation is None:
            return None
        self.save()
        try:
            result = invoke(source_id)
            record.record_source(reservation, source_id=source_id, status="inspected", locator=result["locator"])
        except Exception:
            record.record_source(reservation, source_id=source_id, status="failed")
            self.save()
            raise
        self.save()
        return result

    def finish(self, record, status, *, limitation="", commit_receipts=None):
        self._owned(record)
        if record.findings and status == "complete":
            if commit_receipts is None:
                # The resource ledger must not advertise successful coverage
                # before independent evidence and wiki persistence readbacks.
                record.finish("partial", limitation="Evidence/wiki persistence pending: material commit not verified")
                self.save()
                return
            from types import SimpleNamespace
            from .orchestrator import validate_commit_receipts
            validate_monitoring_assessment(self.writer.adapter, self.writer.root_id, record)
            validate_commit_receipts(SimpleNamespace(writer=self.writer), record, commit_receipts, workflow="monitoring")
        record.finish(status, limitation=limitation)
        self.save()

    def _owned(self, record):
        if self.records.get(record.key) is not record:
            raise ValidationError("monitoring record is detached from this durable ledger")
