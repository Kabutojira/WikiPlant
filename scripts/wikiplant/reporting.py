from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Iterable

from .records import DeliveryState
from .errors import ConflictError, ValidationError
from .storage import create_artifact, create_raw_file, find_artifact, validate_scope
from .util import sha256_text


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
    represented_record_ids: list[str] = field(default_factory=list)
    deferred_record_ids: list[str] = field(default_factory=list)
    saved: bool = False
    report_reference: str | None = None
    schema_version: int = 2

    @property
    def included_record_ids(self) -> list[str]:
        return self.represented_record_ids


def pending_evidence(records: Iterable[EvidenceSummary], prior_reports: Iterable[ReportState]) -> list[EvidenceSummary]:
    included = {record_id for report in prior_reports if report.saved for record_id in report.represented_record_ids}
    return [record for record in records if record.id not in included]


def render_daily_report(
    *, local_date: str, coverage_window: str, evidence: Iterable[EvidenceSummary], events: Iterable[str],
    pending_queue: Iterable[str], operational_gaps: Iterable[str], report_key: str,
    metrics: dict | None = None,
) -> tuple[str, ReportState]:
    records = sorted(evidence, key=lambda item: (-item.importance, item.id))
    if len({item.id for item in records}) != len(records):
        raise ValidationError("duplicate evidence record IDs in report")
    deferred = [item.id for item in records if not item.summary.strip()]
    records = [item for item in records if item.summary.strip()]
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
    if metrics is not None:
        body.extend(["", "## Resource and coverage accounting", "",
            f"- Queued attempts: {metrics['queued_attempts']} (ordinary-eligible slots: {metrics['ordinary_slots_used']}; urgent-only slots: {metrics['urgent_only_slots_used']}).",
            f"- Primary-topic passes: {metrics['primary_topic_passes']}; completed: {metrics['primary_topic_completions']}. These do not consume queue slots.",
            f"- Pending queue: {metrics['queue_size']}; oldest age (seconds): {metrics['oldest_queue_age_seconds']}; deferred decisions observed this cycle: {metrics['deferred_decisions']}.",
            f"- Current TOPICS inventory: {metrics['active_topics']} active; {metrics['archived_topics']} archived. This is not a full historical page audit.",
            f"- Assessed consequential claims in this cycle: {metrics['consequential_claims']}; completed bounded challenges: {metrics['searched_challenges']}.",
            "- External fetched bytes/latency/cost: unknown (not exposed by the bridge); no estimate presented."])
        body.extend(f"- Topic {topic}: queries {counts['queries_used']}/{counts['max_queries']}; inspected-source attempts {counts['sources_used']}/{counts['max_sources']}; {counts['status']}."
                    for topic, counts in metrics["monitoring"].items())
    body.extend(["", "## Evidence coverage appendix"])
    for item in records:
        body.extend([f"- `{item.id}` — {item.title} [{item.evidence_class}; {item.confidence}]: {item.summary}",
                     *[f"  Evidence: {ref}" for ref in item.source_refs]])
    body.extend(f"- Deferred `{identifier}`: no substantive summary available; remains reportable." for identifier in deferred)
    body.append("")
    return "\n".join(body), ReportState(report_key, [item.id for item in records], deferred)


class ReportPublisher:
    """Persist immutable generation, Markdown readback, and publication separately.

    Host publication must accept a stable key or expose reconciliation. An
    uncertain publication remains pending until a host observation resolves it.
    """

    def __init__(self, adapter, root_id: str, reports_folder_id: str, state_folder_id: str):
        self.adapter, self.root_id = adapter, root_id
        self.reports_folder_id, self.state_folder_id = reports_folder_id, state_folder_id

    def _find(self, stem, stage):
        return find_artifact(self.adapter, self.root_id, self.state_folder_id, f"{stem}.{stage}.json")

    def _save(self, stem, stage, value):
        return create_artifact(self.adapter, self.root_id, self.state_folder_id, f"{stem}.{stage}.json", value, f"{self.root_id}:{stem}:{stage}")

    def save(self, markdown: str, state: ReportState) -> ReportState:
        stem = "report-" + sha256_text(state.report_key)
        # Membership and full per-record representation are frozen before archive
        # or report writes. Fresh processes use the same generation artifact.
        for identifier in state.represented_record_ids:
            if f"`{identifier}` — " not in markdown:
                raise ValidationError("represented evidence lacks a per-record summary")
        if set(state.represented_record_ids) & set(state.deferred_record_ids):
            raise ValidationError("report evidence cannot be both represented and deferred")
        generation = {"schema_version": 2, "report_key": state.report_key, "markdown": markdown,
                      "represented_record_ids": state.represented_record_ids, "deferred_record_ids": state.deferred_record_ids}
        self._save(stem, "generated", generation)
        observed = create_raw_file(self.adapter, self.root_id, self.reports_folder_id,
                                   stem + ".md", "text/markdown", markdown.encode(), f"{self.root_id}:{stem}:markdown")
        state.saved, state.report_reference = True, observed.id
        self._save(stem, "saved", {**asdict(state), "sha256": observed.sha256})
        self._save(stem, "publication-payload", {"report_key": state.report_key, "report_reference": observed.id,
                                                "report_sha256": observed.sha256, "result": markdown})
        for identifier in state.represented_record_ids:
            # Rebuildable per-record lookup avoids reading historical Markdown.
            name = "coverage-" + sha256_text(identifier) + ".json"
            existing = find_artifact(self.adapter, self.root_id, self.state_folder_id, name)
            if existing:
                if json.loads(existing.content)["record_id"] != identifier:
                    raise ConflictError("report coverage identity mismatch")
                continue
            create_artifact(self.adapter, self.root_id, self.state_folder_id, name,
                {"schema_version": 2, "record_id": identifier, "report_key": state.report_key,
                 "saved_state_reference": self._find(stem, "saved").id}, f"{self.root_id}:coverage:{identifier}")
        return state

    def pending(self, records: Iterable[EvidenceSummary]) -> list[EvidenceSummary]:
        pending = []
        for record in records:
            coverage = find_artifact(self.adapter, self.root_id, self.state_folder_id, "coverage-" + sha256_text(record.id) + ".json")
            if coverage is None:
                pending.append(record)
                continue
            value = json.loads(coverage.content)
            saved = validate_scope(self.adapter, value["saved_state_reference"], self.root_id)
            receipt = json.loads(saved.content)
            if value["record_id"] != record.id or not receipt.get("saved") or record.id not in receipt.get("represented_record_ids", []):
                raise ConflictError("coverage index lacks a matching saved representation")
        return pending

    def load(self, report_key: str) -> tuple[str, ReportState] | None:
        stem = "report-" + sha256_text(report_key)
        generated = self._find(stem, "generated")
        if not generated:
            return None
        value = json.loads(generated.content)
        state = ReportState(report_key, value["represented_record_ids"], value["deferred_record_ids"])
        saved = self._find(stem, "saved")
        if saved:
            saved_value = json.loads(saved.content)
            current = validate_scope(self.adapter, saved_value["report_reference"], self.root_id)
            if current.sha256 != saved_value["sha256"]:
                raise ConflictError("saved report changed; preserve membership and reconcile")
            state.saved, state.report_reference = True, current.id
        return value["markdown"], state

    def publish(self, report_key: str, publish_result, reconcile_result=None) -> DeliveryState:
        stem = "report-" + sha256_text(report_key)
        loaded = self.load(report_key)
        if not loaded or not loaded[1].saved:
            raise ValidationError("publication requires independent saved report readback")
        delivery = DeliveryState(report_key, saved=True)
        published = self._find(stem, "published")
        if not published:
            attempted = self._find(stem, "publication-attempt")
            observed = reconcile_result(report_key) if attempted and reconcile_result else None
            known_absent = isinstance(observed, dict) and observed.get("status") == "not_published" and observed.get("observation_reference")
            if attempted and not observed:
                raise ConflictError("native publication outcome pending reconciliation; research is already saved")
            payload = json.loads(self._find(stem, "publication-payload").content)
            if not attempted or known_absent:
                self._save(stem, "publication-attempt", {"report_key": report_key, "payload_sha256": sha256_text(json.dumps(payload, sort_keys=True))})
                observed = publish_result(payload, report_key)
            if not isinstance(observed, str) or not observed:
                raise ValidationError("publication needs an observed native result reference")
            self._save(stem, "published", {"report_key": report_key, "native_result_reference": observed})
        delivery.mark_published()
        return delivery


def reconcile_delivery(delivery: DeliveryState, save_report, publish_result) -> DeliveryState:
    """Retry report delivery stages independently from completed research."""
    if not delivery.saved:
        save_report()
        delivery.mark_saved()
    if not delivery.result_published:
        publish_result()
        delivery.mark_published()
    return delivery
