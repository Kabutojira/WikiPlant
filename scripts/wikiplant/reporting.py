from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .records import DeliveryState


@dataclass
class EvidenceSummary:
    id: str
    evidence_class: str
    title: str
    summary: str
    importance: int
    confidence: str
    implications: list[str] = field(default_factory=list)
    changed_assumptions: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


@dataclass
class ReportState:
    report_key: str
    included_record_ids: list[str] = field(default_factory=list)


def pending_evidence(records: Iterable[EvidenceSummary], prior_reports: Iterable[ReportState]) -> list[EvidenceSummary]:
    included = {record_id for report in prior_reports for record_id in report.included_record_ids}
    return [record for record in records if record.id not in included]


def render_daily_report(
    *, local_date: str, coverage_window: str, evidence: Iterable[EvidenceSummary], events: Iterable[str],
    pending_queue: Iterable[str], operational_gaps: Iterable[str], report_key: str,
) -> tuple[str, ReportState]:
    records = sorted(evidence, key=lambda item: (-item.importance, item.id))
    critical = [item for item in records if item.importance >= 80]
    monitored = [item for item in records if item.evidence_class == "monitoring"]
    body = [f"# WikiPlant daily report — {local_date}", "", f"Coverage window: {coverage_window}", "", "## Executive assessment"]
    if records:
        body.extend(f"- {item.title}: {item.summary}" for item in records[:3])
    else:
        body.append("- Quiet report: no newly completed evidence records were available.")
    body.extend(["", "## Critical and time-sensitive findings"])
    body.extend((f"- {item.title}: {item.summary}" for item in critical),)
    if not critical:
        body.append("- None identified in the checked evidence.")
    body.extend(["", "## Main-topic developments"])
    body.extend((f"- {item.title} [{item.confidence}]: {item.summary}" for item in monitored),)
    if not monitored:
        body.append("- No completed main-topic record; see coverage gaps.")
    body.extend(["", "## Implications and changed assumptions"])
    implications = [f"{item.title}: {value}" for item in records for value in item.implications + item.changed_assumptions]
    body.extend((f"- {value}" for value in implications),)
    if not implications:
        body.append("- No supported change to an existing assumption was recorded.")
    body.extend(["", "## Events today and upcoming"])
    event_list = list(events)
    body.extend((f"- {value}" for value in event_list),)
    if not event_list:
        body.append("- None in the configured lookahead.")
    body.extend(["", "## Completed and pending research"])
    body.append(f"- Completed records included: {len(records)}")
    pending = list(pending_queue)
    body.extend(f"- Pending: {value}" for value in pending)
    if not pending:
        body.append("- No eligible pending items were listed.")
    body.extend(["", "## Coverage, operations, and provenance"])
    gaps = list(operational_gaps) + [gap for item in records for gap in item.limitations]
    body.extend((f"- {value}" for value in gaps),)
    if not gaps:
        body.append("- No operational gap was recorded; coverage remains bounded by configured source limits.")
    refs = list(dict.fromkeys(ref for item in records for ref in item.source_refs))
    body.extend(f"- Evidence: {ref}" for ref in refs)
    body.append("")
    return "\n".join(body), ReportState(report_key, [item.id for item in records])


def reconcile_delivery(delivery: DeliveryState, save_report, publish_result) -> DeliveryState:
    """Retry report delivery stages independently from completed research."""
    if not delivery.saved:
        save_report()
        delivery.mark_saved()
    if not delivery.result_published:
        publish_result()
        delivery.mark_published()
    return delivery
