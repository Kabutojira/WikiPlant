from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from .errors import CapabilityError, ValidationError
from .monitoring import MonitoringRecord
from .queue import AttemptReservation, DailyBudget, QueueItem, read_queue, select_next, write_queue
from .records import ResearchResult
from .reporting import EvidenceSummary, ReportState, pending_evidence, render_daily_report
from .storage import SafeWriter, create_artifact, find_artifact, validate_binding, validate_scope
from .util import pretty_json, sha256_text


@dataclass
class PhaseResult:
    phase: str
    status: str
    artifact_refs: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class DailyOutcome:
    order: list[str] = field(default_factory=list)
    monitoring: list[MonitoringRecord] = field(default_factory=list)
    research: list[ResearchResult] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    phases: list[PhaseResult] = field(default_factory=list)
    report_reference: str | None = None
    simulated: bool = False


class DailyRunStore:
    """Work bridge for a cycle, requiring observed exclusion of whole executions.

    execution_guard must observe a host guarantee, never a mutable Drive lock.
    Callbacks execute provider operations; these helpers have no credentials.
    """

    def __init__(self, writer: SafeWriter, state_binding, queue_binding, evidence_folder_id,
                 *, execution_guard: Callable[[], str | None]):
        self.writer, self.state_binding, self.queue_binding = writer, state_binding, queue_binding
        self.evidence_folder_id, self.execution_guard = evidence_folder_id, execution_guard
        self.snapshot = self.queue_snapshot = None
        self.state = {}
        self.queue_error = ""

    def load(self, budget, config_revision, scope_revision):
        if not self.execution_guard():
            raise CapabilityError("No observed serialization; preserve intake and block canonical work")
        if self.writer.instance_id != budget.instance_id:
            raise ValidationError("run store belongs to another instance")
        self.snapshot = validate_binding(self.writer.adapter, self.state_binding, self.writer.root_id)
        self.state = json.loads(self.snapshot.content)
        if self.state:
            if (self.state["cycle_key"], self.state["instance_id"]) != (budget.cycle_key, budget.instance_id):
                raise ValidationError("Run/budget binding mismatch; allowance reset forbidden")
            budget.reservations = [AttemptReservation(**r) for r in self.state["reservations"]]
            if len({r.reservation_id for r in budget.reservations}) != len(budget.reservations) or len(budget.reservations) > 10:
                raise ValidationError("Invalid persisted reservation ledger")
        else:
            self.state = dict(schema_version=2, cycle_key=budget.cycle_key, instance_id=budget.instance_id,
                config_revision=config_revision, scope_revision=scope_revision,
                reservations=[], attempts={}, monitoring={}, errors=[], complete=False)
        try:
            self.queue_snapshot = validate_binding(self.writer.adapter, self.queue_binding, self.writer.root_id)
            return read_queue(self.queue_snapshot.content.decode())
        except Exception as exc:
            self.queue_error = str(exc)
            return []

    def checkpoint(self, budget):
        if not self.execution_guard():
            raise CapabilityError("Execution serialization evidence expired")
        self.state["reservations"] = [asdict(r) for r in budget.reservations]
        payload = pretty_json(self.state).encode()
        op = f"{budget.cycle_key}:state:{self.snapshot.revision}:{sha256_text(payload.decode())}"
        self.snapshot = self.writer.replace(self.state_binding, payload, op, base=self.snapshot).current

    def save_queue(self, items, budget):
        payload = write_queue(items).encode()
        if payload != self.queue_snapshot.content:
            op = f"{budget.cycle_key}:queue:{self.queue_snapshot.revision}:{sha256_text(payload.decode())}"
            self.queue_snapshot = self.writer.replace(self.queue_binding, payload, op, base=self.queue_snapshot).current

    def save_evidence(self, identifier, payload):
        return create_artifact(self.writer.adapter, self.writer.root_id, self.evidence_folder_id,
            "evidence-" + sha256_text(identifier) + ".json", payload,
            f"{self.writer.instance_id}:evidence:{identifier}").id


def validate_commit_receipts(store, result, receipts, *, workflow="research"):
    """Only saved operation completions covering required wiki pages remove work."""
    if not isinstance(receipts, list):
        raise ValidationError("research commit needs structured completion receipts")
    covered = set()
    for proof in receipts:
        if not isinstance(proof, dict) or not {"page_id", "file_id", "sha256", "operation_reference"} <= set(proof):
            raise ValidationError("research commit receipt lacks page/target/hash/operation proof")
        if proof["page_id"] in covered:
            raise ValidationError("duplicate research commit page identity")
        covered.add(proof["page_id"])
        raw = validate_scope(store.writer.adapter, proof["file_id"], store.writer.root_id)
        operation = validate_scope(store.writer.adapter, proof["operation_reference"], store.writer.root_id)
        if raw.mime_type != "text/markdown" or operation.mime_type != "application/json":
            raise ValidationError("research wiki commit is not verified raw Markdown")
        completion = json.loads(operation.content)
        if completion.get("stage") != "COMPLETE" or completion.get("instance_id") != store.writer.instance_id or completion.get("target_id") != raw.id or completion.get("output_sha256") != proof["sha256"]:
            raise ValidationError("research commit completion belongs to another mutation")
        canonical_completion = find_artifact(store.writer.adapter, store.writer.root_id, store.writer.operations_folder_id,
                               "operation-" + sha256_text(completion["operation_id"]) + ".complete.json")
        if canonical_completion is None or canonical_completion.id != operation.id or operation.parent_id != store.writer.operations_folder_id:
            raise ValidationError("completion is not the canonical operation artifact")
        intent = find_artifact(store.writer.adapter, store.writer.root_id, store.writer.operations_folder_id,
                               "operation-" + sha256_text(completion["operation_id"]) + ".intent.json")
        if workflow == "research":
            expected_context = {"workflow": "research", "result_id": result.id, "item_id": result.item_id,
                                "attempt_id": result.attempt_id, "page_id": proof["page_id"]}
        elif workflow == "monitoring":
            expected_context = {"workflow": "monitoring", "monitoring_key": result.key,
                                "assessment_reference": result.evidence_assessment_ref, "page_id": proof["page_id"]}
        else:
            raise ValidationError("unknown wiki commit workflow")
        original = json.loads(intent.content) if intent else {}
        if intent is None or intent.sha256 != completion.get("intent_sha256") or original.get("authorization") != expected_context:
            raise ValidationError("wiki mutation intent is not bound to this research result and page")
        if (any(original.get(key) != completion.get(key) for key in ("schema_version", "operation_id", "instance_id", "target_id", "output_sha256"))
                or original.get("root_id") != store.writer.root_id or original.get("stage") != "INTENT_SAVED"
                or completion.get("schema_version") != 2 or type(completion.get("output_revision")) is not int):
            raise ValidationError("wiki completion contradicts the original mutation identity")
        proof["current_sha256"] = raw.sha256
    if result.findings and not result.affected_page_ids:
        raise ValidationError("material findings need an affected wiki page")
    if set(result.affected_page_ids) != covered:
        raise ValidationError("research wiki commit does not cover every required affected page")
    return receipts


def run_daily(
    *, topics: list[dict], queue_items: list[QueueItem], budget: DailyBudget, now: datetime,
    calendar_step: Callable[[], list[str]], monitor_topic: Callable[[dict], MonitoringRecord],
    investigate: Callable[[QueueItem, str], ResearchResult], queue_available: bool = True,
    store=None, admission_gate=None, config_revision="", report_publisher=None,
    publish_result=None, reconcile_result=None, commit_research=None, simulate=False,
    retry_base_minutes=60, max_attempts=3, extra_evidence=None, refresh_evidence=None, commit_monitoring=None, finalize_monitoring=None,
) -> DailyOutcome:
    outcome = DailyOutcome(simulated=simulate)
    resume_only = False
    if retry_base_minutes < 1 or max_attempts < 1:
        raise ValidationError("Retry controls must be positive")
    if not simulate and (store is None or admission_gate is None or not config_revision):
        outcome.gaps.append("BLOCKED: durable run store, current admission scope and config revision required")
        return outcome
    if store:
        try:
            queue_items[:] = store.load(budget, config_revision, admission_gate.registry.scope_revision)
            if store.queue_error:
                queue_available = False
                outcome.gaps.append("Queue read/validation blocked: " + store.queue_error)
        except Exception as exc:
            outcome.gaps.append(f"Unsafe run storage: {exc}")
            return outcome
        if store.state["complete"]:
            unfinished_monitoring = any(store.state["monitoring"].get(t["id"], {}).get("record", {}).get("status") not in {"complete", "no_material_update"} for t in topics)
            pending_merge = any(a.get("result", {}).get("status") == "complete" and not a.get("wiki_committed", bool(a.get("commit_refs"))) for a in store.state["attempts"].values())
            report_key = store.state.get("latest_report_key", budget.cycle_key)
            loaded = report_publisher.load(report_key) if report_publisher else None
            if loaded:
                outcome.report_reference = loaded[1].report_reference
                _publish(outcome, report_publisher, report_key, publish_result, reconcile_result)
            if not unfinished_monitoring and not pending_merge:
                return outcome
            resume_only = True  # Retry missing persistence/coverage, no new queue allowance.
        if store.state.get("admission"):
            from .admission import AdmissionGate
            admission_gate = AdmissionGate.from_dict(store.state["admission"], admission_gate.registry)
    outcome.order.append("recover-bindings-config")
    def checkpoint():
        if store:
            store.checkpoint(budget)
    try:
        outcome.events = calendar_step()
    except Exception as exc:
        outcome.gaps.append(f"Calendar partial: {exc}")
    outcome.order.append("calendar")
    for topic in topics:
        try:
            previous = store.state["monitoring"].get(topic["id"]) if store else None
            if previous and previous["record"]["status"] in {"complete", "no_material_update"}:
                record = MonitoringRecord(**previous["record"])
            else:
                # The host callback must checkpoint query/source reservations
                # before each tool invocation, via the MonitoringLedger bridge.
                record = monitor_topic(topic)
                if (record.topic_id, record.instance_id, record.local_date) != (topic["id"], budget.instance_id, budget.local_date):
                    raise ValidationError("Monitoring result topic/instance/cycle mismatch")
                if previous:
                    old = previous["record"]
                    if any(getattr(record, key) != old[key] for key in ("max_queries", "max_sources", "coverage_start", "coverage_end")):
                        raise ValidationError("Monitoring retry cannot reset its interval or allowance")
                    if record.queries_used < old["queries_used"] or record.sources_used < old["sources_used"]:
                        raise ValidationError("Monitoring retry cannot reset consumed reservations")
                    for field in ("query_results", "source_results"):
                        if any(getattr(record, field).get(key) != value for key, value in old.get(field, {}).items()):
                            raise ValidationError("Monitoring retry rewrote prior invocation outcomes")
                material_state = {}
                try:
                    if record.status in {"complete", "no_material_update"}:
                        record.finish(record.status)
                    if store and record.findings:
                        from .monitoring import validate_monitoring_assessment
                        material_state["assessment"] = validate_monitoring_assessment(store.writer.adapter, store.writer.root_id, record)
                        # Save evidence before invoking a separate wiki mutation.
                        material_state["material_reference"] = store.save_evidence(record.key + ":material:" + sha256_text(pretty_json(asdict(record))), asdict(record))
                        if commit_monitoring is None:
                            raise CapabilityError("material monitoring wiki commit bridge unavailable")
                        material_state["commit_refs"] = validate_commit_receipts(store, record, commit_monitoring(record), workflow="monitoring")
                        material_state["wiki_committed"] = True
                        record.wiki_change_ids = [p["operation_reference"] for p in material_state["commit_refs"]]
                        record.finish("complete")
                        if finalize_monitoring:
                            finalize_monitoring(record, material_state["commit_refs"])
                        record.limitations = ["Resolved earlier: " + value if value.startswith("Evidence/wiki persistence pending:") else value for value in record.limitations]
                except Exception as exc:
                    record.finish("partial", limitation=f"Evidence/wiki persistence pending: {exc}")
                    outcome.gaps.append(f"Topic {topic['id']} material evidence pending: {exc}")
                if store:
                    ref = store.save_evidence(record.key + ":" + sha256_text(pretty_json(asdict(record))), asdict(record))
                    store.state["monitoring"][topic["id"]] = dict(record=asdict(record), reference=ref, **material_state)
                    checkpoint()
            outcome.monitoring.append(record)
        except Exception as exc:
            outcome.gaps.append(f"Topic {topic['id']} partial: {exc}")
    outcome.order.extend(["main-topic-refresh", "bounded-discovery"])
    if not queue_available:
        outcome.gaps.append("Queue unavailable; mandatory main-topic results and events retained")
    else:
        if store:
            for item in list(queue_items):
                slots = {r.reservation_id: r.slot for r in budget.reservations}
                prior = max((a for a in store.state["attempts"].values() if a["item_id"] == item.id),
                            key=lambda a: slots[a["reservation_id"]], default=None)
                if prior and prior.get("result"):
                    result = ResearchResult(**prior["result"])
                    if result.status == "complete" and prior.get("wiki_committed", bool(prior.get("commit_refs"))):
                        queue_items.remove(item)
                    elif result.status == "complete":
                        try:
                            if commit_research is None:
                                raise CapabilityError("Wiki/source commit bridge remains unavailable")
                            from .evidence import validate_research_assessment
                            prior["assessment"] = validate_research_assessment(store.writer.adapter, store.writer.root_id, budget.instance_id, result)
                            refs = commit_research(result)
                            validate_commit_receipts(store, result, refs)
                            prior["commit_refs"] = refs
                            prior["wiki_committed"] = True
                            next(r for r in budget.reservations if r.reservation_id == prior["reservation_id"]).status = "complete"
                            if item.id in admission_gate.lineage:
                                admission_gate.lineage[item.id].status = "complete"
                                store.state["admission"] = admission_gate.to_dict()
                            checkpoint()
                            queue_items.remove(item)
                        except Exception as exc:
                            item.status = "blocked"
                            outcome.gaps.append(f"{item.id}: saved evidence pending wiki merge: {exc}; no repeat research")
                    else:
                        item.status, item.not_before, item.attempts = prior["status"], prior["not_before"], prior["attempts"]
                elif prior and prior["status"] == "in_progress":
                    item.status = "blocked"
                    outcome.gaps.append(f"{item.id}: interrupted attempt awaits provider reconciliation; slot retained")
            store.save_queue(queue_items, budget)
        skipped = set()
        while not resume_only:
            service_counts = store.state.setdefault("anchor_service_counts", {}) if store else {}
            selection_log = store.state.setdefault("selection_log", []) if store else []
            anchors = {t.id: t.user_anchor_ids for t in admission_gate.registry.topics} if admission_gate else None
            item = select_next([i for i in queue_items if i.id not in skipped], budget, now,
                               service_counts=service_counts, selection_log=selection_log, anchor_ids_by_topic=anchors)
            if item is None:
                break
            if admission_gate:
                try:
                    decision = admission_gate.evaluate(item, queue_items, now, execution=True, local_cycle_date=budget.local_date)
                except Exception as exc:
                    skipped.add(item.id)
                    outcome.gaps.append(f"{item.id}: admission blocked: {exc}")
                    continue
                if store:
                    store.save_evidence("admission:" + sha256_text(pretty_json(decision.to_dict())), decision.to_dict())
                    store.state.setdefault("admission_outcomes", {})[item.id] = decision.to_dict()
                    checkpoint()
                if decision.disposition != "admit":
                    skipped.add(item.id)
                    outcome.gaps.append(f"{item.id}: {decision.disposition}: {decision.reason}")
                    continue
                admission_gate.record(decision)
                if store:
                    store.state["admission"] = admission_gate.to_dict()
            reservation = budget.reserve(item)
            if reservation is None:
                break
            item.status, item.attempts = "in_progress", item.attempts + 1
            for anchor in (anchors or {}).get(item.topic_id, []):
                service_counts[anchor] = service_counts.get(anchor, 0) + 1
            if store:
                attempt = dict(item_id=item.id, reservation_id=reservation.reservation_id,
                    status=item.status, attempts=item.attempts, not_before=item.not_before)
                store.state["attempts"][reservation.reservation_id] = attempt
                checkpoint()
                store.save_queue(queue_items, budget)
            try:
                result = investigate(item, reservation.reservation_id)
                result.validate()
                if store and result.status == "complete" and not result.evidence_assessment_ref:
                    raise ValidationError("Completed research needs a saved evidence-policy assessment")
                if store and result.evidence_assessment_ref:
                    from .evidence import validate_research_assessment
                    attempt["assessment"] = validate_research_assessment(store.writer.adapter, store.writer.root_id, budget.instance_id, result)
                if (result.item_id, result.attempt_id) != (item.id, reservation.reservation_id):
                    raise ValidationError("Research result does not match reservation")
                outcome.research.append(result)
                if store:
                    attempt.update(result=asdict(result), result_reference=store.save_evidence(result.id, asdict(result)))
                    checkpoint()
                if result.status == "complete":
                    if store:
                        if commit_research is None:
                            raise CapabilityError("Wiki/source commit bridge missing; evidence retained")
                        refs = commit_research(result)
                        validate_commit_receipts(store, result, refs)
                        attempt["commit_refs"] = refs
                        attempt["wiki_committed"] = True
                        reservation.status = "complete"
                        checkpoint()
                    queue_items.remove(item)
                    if admission_gate and item.id in admission_gate.lineage:
                        admission_gate.lineage[item.id].status = "complete"
                else:
                    raise RuntimeError("Research result " + result.status)
            except Exception as exc:
                outcome.gaps.append(f"Research {item.id}: {exc}")
                completed = store and attempt.get("result", {}).get("status") == "complete"
                item.status = "blocked" if completed or item.attempts >= max_attempts else "retry_wait"
                item.not_before = (now + timedelta(minutes=retry_base_minutes * 2 ** min(item.attempts - 1, 10))).isoformat()
                reservation.status = "pending_merge" if completed else "failed"
                if store:
                    attempt.update(status=item.status, not_before=item.not_before, attempts=item.attempts)
                    checkpoint()
            if store:
                store.state["admission"] = admission_gate.to_dict()
                checkpoint()
                store.save_queue(queue_items, budget)
        outcome.order.append("queued-research")
    records = list(extra_evidence or [])
    for record in outcome.monitoring:
        versioned_key = record.key + ":" + sha256_text(pretty_json(asdict(record)))[:16]
        saved = store.state["monitoring"].get(record.topic_id, {}) if store else {}
        assessment = saved.get("assessment", {})
        texts = assessment.get("computed_finding_texts", [])
        summary = "; ".join(texts) if texts else "; ".join("[unassessed; not a verified development] " + text for text in record.findings)
        if record.findings and not saved.get("wiki_committed"):
            summary = "PENDING evidence/wiki persistence: " + summary
        records.append(EvidenceSummary(versioned_key, "monitoring", record.topic_id,
            summary or record.status.replace("_", " "), 30,
            "coverage: " + record.status, limitations=record.limitations,
            source_refs=[r for r in [saved.get("reference"), record.evidence_assessment_ref] if r]))
    results = {r.id: r for r in outcome.research}
    if store:
        for attempt in store.state["attempts"].values():
            if attempt.get("result"):
                r = ResearchResult(**attempt["result"])
                results[r.id] = r
    for result in results.values():
        assessment, limits = {}, list(result.uncertainties)
        if store and result.evidence_assessment_ref:
            try:
                from .evidence import validate_research_assessment
                assessment = validate_research_assessment(store.writer.adapter, store.writer.root_id, budget.instance_id, result)
            except Exception as exc:
                limits.append(f"Assessment no longer verifies: {exc}")
        texts = assessment.get("computed_finding_texts", [])
        summary = "; ".join(texts) if texts else "; ".join("[unassessed] " + text for text in result.findings)
        statuses = sorted({c["status"] for c in assessment.get("computed_claim_assessments", {}).values()})
        limits.extend(value for c in assessment.get("computed_claim_assessments", {}).values() for value in c["limitations"])
        source_refs = [binding["file_id"] for binding in assessment.get("source_files", {}).values()]
        if result.evidence_assessment_ref:
            source_refs.append(result.evidence_assessment_ref)
        if store:
            attempt = next((a for a in store.state["attempts"].values() if a.get("result", {}).get("id") == result.id), {})
            if attempt.get("result_reference"):
                source_refs.append(attempt["result_reference"])
            if not attempt.get("wiki_committed", bool(attempt.get("commit_refs"))):
                limits.append("Saved research is pending verified wiki merge")
        records.append(EvidenceSummary(result.id, "research", result.question, summary or result.status,
            50, "assessed claims: " + ", ".join(statuses) if statuses else "unassessed",
            implications=["Proposed implication (applicability must be established): " + value for value in result.applicability],
            changed_assumptions=["Proposed conclusion change: " + value for value in result.changed_conclusions],
            source_refs=source_refs, limitations=list(dict.fromkeys(limits))))
    outcome.order.append("synthesis")
    if store and report_publisher:
        try:
            try:
                outcome.events = calendar_step()
                if refresh_evidence:
                    records = list({r.id: r for r in records + refresh_evidence()}.values())
            except Exception as exc:
                outcome.gaps.append(f"Final evidence/event inventory partial: {exc}")
            assessments = [a.get("assessment", {}) for a in store.state["attempts"].values()] + [a.get("assessment", {}) for a in store.state["monitoring"].values()]
            claims = {c["id"]: c for a in assessments for c in a.get("claims", [])}
            challenges = {c["id"]: c for a in assessments for c in a.get("challenges", [])}
            metrics = dict(schema_version=2, queued_attempts=len(budget.reservations),
                ordinary_slots_used=sum(r.slot <= 5 for r in budget.reservations), urgent_only_slots_used=sum(r.slot > 5 for r in budget.reservations),
                primary_topic_passes=len(outcome.monitoring), primary_topic_completions=sum(r.status in {"complete", "no_material_update"} for r in outcome.monitoring),
                monitoring={r.topic_id: {k: getattr(r, k) for k in ("queries_used", "max_queries", "sources_used", "max_sources", "status")} for r in outcome.monitoring},
                queue_size=len(queue_items) if queue_available else None,
                oldest_queue_age_seconds=max((max(0, (now - datetime.fromisoformat(i.created_at.replace("Z", "+00:00"))).total_seconds()) for i in queue_items), default=None),
                deferred_decisions=sum("defer" in decision["disposition"] for decision in store.state.get("admission_outcomes", {}).values()),
                active_topics=sum(t.lifecycle == "active" for t in admission_gate.registry.topics),
                archived_topics=sum(t.lifecycle == "archived" for t in admission_gate.registry.topics),
                consequential_claims=sum(c.get("impact") == "consequential" for c in claims.values()),
                searched_challenges=sum(c.get("state") == "searched" for c in challenges.values()),
                external_fetched_bytes=None, latency=None, cost=None)
            store.state["metrics"] = metrics
            prior_reports = [ReportState(**r) for r in store.state.get("reports", [])]
            records = pending_evidence(records, prior_reports)
            records = report_publisher.pending(records)
            report_key = budget.cycle_key
            if prior_reports:
                if not records:
                    store.state["complete"] = True
                    checkpoint()
                    return outcome
                report_key += ":supplement:" + sha256_text(pretty_json(sorted(r.id for r in records)))[:16]
            existing = report_publisher.load(report_key)
            if existing:
                markdown, report_state = existing
            else:
                markdown, report_state = render_daily_report(local_date=budget.local_date, coverage_window=budget.local_date,
                    evidence=records, events=outcome.events, pending_queue=[i.question for i in queue_items],
                    operational_gaps=outcome.gaps, report_key=report_key, metrics=metrics)
            report_publisher.save(markdown, report_state)
            outcome.report_reference = report_state.report_reference
            outcome.phases.append(PhaseResult("report-save", "saved", [outcome.report_reference]))
            store.state["complete"], store.state["errors"] = True, outcome.gaps
            store.state["latest_report_key"] = report_key
            if report_key not in {r.report_key for r in prior_reports}:
                store.state.setdefault("reports", []).append(asdict(report_state))
            checkpoint()
            _publish(outcome, report_publisher, report_key, publish_result, reconcile_result)
        except Exception as exc:
            outcome.gaps.append(f"Report pending: {exc}")
    elif not simulate:
        outcome.gaps.append("No report persistence bridge; no saved-report claim")
    outcome.order.extend(["report-save", "native-result"])
    return outcome


def _publish(outcome, publisher, key, publish, reconcile):
    if publish is None:
        outcome.gaps.append("Saved report pending native publication")
        return
    try:
        publisher.publish(key, publish, reconcile)
        outcome.phases.append(PhaseResult("native-result", "published", [outcome.report_reference]))
    except Exception as exc:
        outcome.gaps.append(f"Native publication pending: {exc}")


def run_weekly(*, check_updates, structural_review, archive_expired, semantic_review, save_result):
    phases = []
    for name, callback in (("check-updates", check_updates), ("structural", structural_review),
                           ("archive", archive_expired), ("semantic", semantic_review)):
        try:
            refs = callback()
            if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or not ref for ref in refs):
                raise ValidationError("Phase needs observed artifact references")
            phases.append(PhaseResult(name, "saved", refs))
        except Exception as exc:
            phases.append(PhaseResult(name, "partial", error=str(exc)))
    save_result([asdict(p) for p in phases])
    return phases
