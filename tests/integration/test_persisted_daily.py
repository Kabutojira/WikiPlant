"""Synthetic Drive tests reconstruct every cycle from raw persisted artifacts."""
import json
import unittest
from dataclasses import asdict
from datetime import datetime, timezone, timedelta

from wikiplant.admission import AdmissionCandidate, AdmissionGate
from wikiplant.authorization import UserAuthorization, request_digest
from wikiplant.fake_drive import FakeDrive
from wikiplant.monitoring import MonitoringRecord
from wikiplant.orchestrator import DailyRunStore, run_daily, run_weekly
from wikiplant.queue import DailyBudget, QueueItem, read_queue, write_queue
from wikiplant.records import ResearchResult, SourceRecord, Claim
from wikiplant.reporting import ReportPublisher
from wikiplant.storage import Binding, SafeWriter
from wikiplant.topics import Topic, TopicRegistry
from wikiplant.storage import create_artifact
from wikiplant.util import pretty_json


NOW = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)


class PersistedDailyTests(unittest.TestCase):
    def setUp(self):
        self.drive = FakeDrive()
        self.root = self.drive.create_folder(None, "synthetic", idempotency_key="root")
        self.ops = self.drive.create_folder(self.root.id, "operations", idempotency_key="ops")
        self.inbox = self.drive.create_folder(self.root.id, "inbox", idempotency_key="inbox")
        self.evidence = self.drive.create_folder(self.root.id, "evidence", idempotency_key="evidence")
        self.reports = self.drive.create_folder(self.root.id, "reports", idempotency_key="reports")
        self.state = self.file("state.json", "application/json", b"{}")
        self.queue = self.file("queue.csv", "text/csv", write_queue([]).encode())
        source = SourceRecord("synthetic-source", "https://example.invalid/fixture", "Synthetic source", None, None, None,
            NOW.isoformat(), None, "primary", ["Synthetic observed finding"], [],
            inspected_passages={"section-1": "Synthetic observed finding"}, retrieval_status="inspected")
        self.proof = self.file("source.json", "application/json", pretty_json(source.to_dict()).encode())
        self.wiki = self.file("wiki.md", "text/markdown", b"Manual note remains here")
        grant = UserAuthorization("synthetic-user-turn", "wp-test", "track", "topic-a", request_digest("Track fixture"), True, "Explicit fixture scope").to_dict()
        topic = Topic("topic-a", "Synthetic topic", "user", ["topic-a"], [], "User goal", "Explicit tracking",
                      NOW.isoformat(), NOW.isoformat(), 1, authorization=grant)
        self.registry = TopicRegistry("wp-test", 1, [topic])
        self.gate = AdmissionGate(self.registry)
        self.calls = []

    def file(self, name, mime, content):
        return self.drive.create_file(self.root.id, name, mime, content, idempotency_key=name)

    def binding(self, file):
        return Binding("data/" + file.name, file.id, file.mime_type, self.root.id)

    def add_items(self, count=7, priority=30):
        items = []
        for i in range(count):
            identifier = f"q{i}"
            item = QueueItem(priority, identifier, 30, "investigation", f"Synthetic distinct question {i}?", "topic-a", [], [],
                identifier, "discovery", "synthetic-event", NOW.isoformat(), priority_reason="User relevance",
                urgency_reason="Synthetic imminent deadline" if priority == 0 else "")
            candidate = AdmissionCandidate(item, "user", ["topic-a"], f"Answer useful goal question {i}", self.proof.id,
                f"new-evidence-{i}", [self.proof.id], root_reason="independent_external_event")
            self.gate.candidates[item.id] = candidate
            items.append(item)
        self.drive.external_edit(self.queue.id, write_queue(items).encode())

    def monitor(self, topic):
        record = MonitoringRecord("wp-test", "2026-01-15", topic["id"], "2026-01-14T00:00:00Z", NOW.isoformat(), 4, 8)
        record.reserve_query()
        record.record_query(1, status="success", query="Synthetic current topic", result_reference="synthetic-search-result")
        record.finish("no_material_update")
        self.calls.append("monitor")
        return record

    def investigate(self, item, reservation):
        self.calls.append(item.id)
        persisted = json.loads(self.drive.read_exact(self.state.id).content)
        self.assertEqual(persisted["reservations"][-1]["reservation_id"], reservation)
        claim = Claim("claim-" + item.id, "synthetic fixture", "reported finding", "Synthetic observed finding", None, None,
            ["synthetic-source"], "uncertain", "uncertain", assessment_reason="Inspected lead with no independently established empirical support")
        assessment = dict(schema_version=2, kind="research_assessment", instance_id="wp-test", item_id=item.id,
            attempt_id=reservation, run_id="wp-test:2026-01-15", source_files={"synthetic-source": {"file_id": self.proof.id, "sha256": self.proof.sha256}},
            claims=[claim.to_dict()], findings=[{"text": "Synthetic observed finding", "claim_id": claim.id}], challenges=[])
        ref = create_artifact(self.drive, self.root.id, self.evidence.id, item.id + "-assessment.json", assessment, reservation + ":assessment")
        return ResearchResult("result-" + item.id, item.question, item.id, reservation, "wp-test:2026-01-15", item.origin,
            ["synthetic-source"], ["Synthetic observed finding"], "uncertain", [], [], [self.wiki.id], ["unknown applicability"], [], "complete",
            evidence_assessment_ref=ref.id, claim_ids=[claim.id])

    def run_cycle(self, **kwargs):
        writer = SafeWriter(self.drive, self.root.id, self.ops.id, self.inbox.id, instance_id="wp-test")
        store = DailyRunStore(writer, self.binding(self.state), self.binding(self.queue), self.evidence.id,
                              execution_guard=lambda: "synthetic-host-serialization-receipt")
        publisher = ReportPublisher(self.drive, self.root.id, self.reports.id, self.ops.id)
        options = dict(topics=[{"id": "topic-a"}], queue_items=[], budget=DailyBudget("wp-test", "2026-01-15", "UTC"),
            now=NOW, calendar_step=lambda: ["Synthetic event today"], monitor_topic=self.monitor, investigate=self.investigate,
            store=store, admission_gate=AdmissionGate.from_dict(self.gate.to_dict(), self.registry), config_revision="synthetic-config-v2",
            report_publisher=publisher, commit_research=self.commit,
            publish_result=lambda payload, key: "synthetic-native-result")
        options.update(kwargs)
        return run_daily(**options)

    def commit(self, result):
        from wikiplant.storage import find_artifact
        from wikiplant.util import sha256_text
        writer = SafeWriter(self.drive, self.root.id, self.ops.id, self.inbox.id, instance_id="wp-test")
        operation_id = "commit:" + result.id
        completed = find_artifact(self.drive, self.root.id, self.ops.id, "operation-" + sha256_text(operation_id) + ".complete.json")
        if completed:
            completion = json.loads(completed.content)
            return [dict(page_id=self.wiki.id, file_id=self.wiki.id, sha256=completion["output_sha256"], operation_reference=completed.id)]
        base = self.drive.read_exact(self.wiki.id)
        context = dict(workflow="research", result_id=result.id, item_id=result.item_id, attempt_id=result.attempt_id, page_id=self.wiki.id)
        receipt = writer.replace(self.binding(self.wiki), base.content + ("\n" + result.id + ": Synthetic finding saved").encode(), operation_id, base=base, authorization=context)
        return [dict(page_id=self.wiki.id, file_id=receipt.target_id, sha256=receipt.verified_sha256, operation_reference=receipt.completion_reference)]

    def test_five_attempts_monitoring_report_and_replay_from_fresh_objects(self):
        self.add_items()
        result = self.run_cycle()
        self.assertEqual(len(result.research), 5, result.gaps)
        self.assertEqual(len(result.monitoring), 1)
        self.assertEqual(len(read_queue(self.drive.read_exact(self.queue.id).content.decode())), 2)
        self.assertIn(b"Synthetic observed finding", self.drive.read_exact(result.report_reference).content)
        self.assertIn(b"Synthetic event today", self.drive.read_exact(result.report_reference).content)
        self.assertTrue(self.drive.read_exact(self.wiki.id).content.startswith(b"Manual note remains here"))
        self.assertIn(b"result-q4: Synthetic finding saved", self.drive.read_exact(self.wiki.id).content)
        before = list(self.calls)
        second = self.run_cycle()
        self.assertEqual(second.report_reference, result.report_reference)
        self.assertEqual(self.calls, before)
        state = json.loads(self.drive.read_exact(self.state.id).content)
        self.assertEqual(len(state["reservations"]), 5)
        self.assertEqual(state["metrics"]["queued_attempts"], 5)
        self.assertEqual(state["metrics"]["primary_topic_completions"], 1)
        self.assertIsNone(state["metrics"]["external_fetched_bytes"])
        self.assertIn(b"Queued attempts: 5", self.drive.read_exact(result.report_reference).content)

    def test_failed_item_has_future_backoff_and_other_work_runs(self):
        self.add_items(3)
        def investigate(item, reservation):
            if item.id == "q0":
                self.calls.append("failed")
                raise RuntimeError("synthetic research outage")
            return self.investigate(item, reservation)
        outcome = self.run_cycle(investigate=investigate)
        self.assertEqual(len(outcome.research), 2, outcome.gaps)
        queue = read_queue(self.drive.read_exact(self.queue.id).content.decode())
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0].attempts, 1)
        self.assertGreater(datetime.fromisoformat(queue[0].not_before), NOW)
        self.assertEqual(self.calls.count("failed"), 1)
        self.assertIsNotNone(outcome.report_reference)

    def test_bad_queue_and_topic_do_not_suppress_other_monitoring_or_report(self):
        self.drive.external_edit(self.queue.id, b"invalid CSV")
        def monitor(topic):
            if topic["id"] == "bad":
                raise RuntimeError("topic provider failed")
            return self.monitor(topic)
        result = self.run_cycle(topics=[{"id": "bad"}, {"id": "topic-a"}], monitor_topic=monitor)
        self.assertEqual(len(result.monitoring), 1)
        self.assertIsNotNone(result.report_reference, result.gaps)
        self.assertIn(b"topic provider failed", self.drive.read_exact(result.report_reference).content)
        self.assertEqual(self.drive.read_exact(self.queue.id).content, b"invalid CSV")

    def test_report_failure_resume_does_not_repeat_finished_research(self):
        self.add_items(2)
        first = self.run_cycle(publish_result=lambda *args: (_ for _ in ()).throw(RuntimeError("lost native response")))
        self.assertIsNotNone(first.report_reference)
        before = list(self.calls)
        second = self.run_cycle(reconcile_result=lambda key: "synthetic-observed-result")
        self.assertEqual(self.calls, before)
        self.assertTrue(any(p.status == "published" for p in second.phases))

    def test_overlapping_invocation_cannot_get_an_unobserved_guard(self):
        writer = SafeWriter(self.drive, self.root.id, self.ops.id, self.inbox.id)
        store = DailyRunStore(writer, self.binding(self.state), self.binding(self.queue), self.evidence.id, execution_guard=lambda: None)
        result = self.run_cycle(store=store)
        self.assertEqual(self.calls, [])
        self.assertIn("serialization", result.gaps[0])

    def test_weekly_release_notice_survives_audit_failure(self):
        saved = []
        phases = run_weekly(check_updates=lambda: ["synthetic-saved-update-notice"],
            structural_review=lambda: (_ for _ in ()).throw(RuntimeError("audit offline")),
            archive_expired=lambda: ["synthetic-archive-receipt"], semantic_review=lambda: ["synthetic-review"], save_result=saved.append)
        self.assertEqual(phases[0].artifact_refs, ["synthetic-saved-update-notice"])
        self.assertEqual(phases[1].status, "partial")
        self.assertEqual(len(saved[0]), 4)

    def material_monitor(self):
        record = MonitoringRecord("wp-test", "2026-01-15", "topic-a", "2026-01-14T00:00:00+00:00", NOW.isoformat(), 4, 8)
        record.record_query(record.reserve_query(), status="success", query="Synthetic material topic", result_reference="synthetic-search-result")
        record.record_source(record.reserve_source(), source_id="synthetic-source", status="inspected", locator="section-1")
        record.findings = ["Synthetic observed finding"]
        record.affected_page_ids = [self.wiki.id]
        claim = Claim("monitor-claim", "synthetic fixture", "finding", "Synthetic observed finding", None, None,
            ["synthetic-source"], "uncertain", "uncertain", assessment_reason="Inspected lead, not independently measured")
        record.claim_ids = [claim.id]
        assessment = dict(schema_version=2, kind="monitoring_assessment", instance_id="wp-test", topic_id=record.topic_id,
            local_date=record.local_date, monitoring_key=record.key, coverage_start=record.coverage_start, coverage_end=record.coverage_end,
            source_files={"synthetic-source": {"file_id": self.proof.id, "sha256": self.proof.sha256}},
            claims=[claim.to_dict()], challenges=[], findings=[dict(text=record.findings[0], claim_id=claim.id)])
        record.evidence_assessment_ref = create_artifact(self.drive, self.root.id, self.evidence.id,
            "monitor-assessment.json", assessment, record.key + ":assessment").id
        record.finish("complete")
        return record

    def commit_monitor(self, record):
        writer = SafeWriter(self.drive, self.root.id, self.ops.id, self.inbox.id, instance_id="wp-test")
        base = self.drive.read_exact(self.wiki.id)
        context = dict(workflow="monitoring", monitoring_key=record.key, assessment_reference=record.evidence_assessment_ref, page_id=self.wiki.id)
        receipt = writer.replace(self.binding(self.wiki), base.content + b"\nMonitored finding [uncertain] saved", "monitor-commit", base=base, authorization=context)
        return [dict(page_id=self.wiki.id, file_id=self.wiki.id, sha256=receipt.verified_sha256, operation_reference=receipt.completion_reference)]

    def test_material_monitoring_requires_bound_assessment_and_verified_wiki_write(self):
        record = self.material_monitor()
        first = self.run_cycle(monitor_topic=lambda topic: record, commit_monitoring=lambda record: [self.evidence.id])
        self.assertEqual(first.monitoring[0].status, "partial")
        self.assertIsNone(first.monitoring[0].successful_watermark)
        self.assertIn(b"PENDING evidence/wiki persistence", self.drive.read_exact(first.report_reference).content)
        self.assertEqual(self.drive.read_exact(self.wiki.id).content, b"Manual note remains here")
        def resume(topic):
            record.finish("complete")  # Resume saved evidence; no new tool invocation.
            return record
        second = self.run_cycle(monitor_topic=resume, commit_monitoring=self.commit_monitor)
        self.assertEqual(second.monitoring[0].status, "complete", second.gaps)
        self.assertEqual(second.monitoring[0].queries_used, 1)
        self.assertIn(b"Monitored finding [uncertain] saved", self.drive.read_exact(self.wiki.id).content)
        self.assertNotEqual(first.report_reference, second.report_reference)
        self.assertIn(b"[uncertain]", self.drive.read_exact(second.report_reference).content)
        self.assertEqual(json.loads(self.drive.read_exact(self.state.id).content)["reservations"], [])

    def test_material_monitoring_unresolved_source_does_not_become_verified_development(self):
        record = self.material_monitor()
        record.source_results["1"]["locator"] = "invented-section"
        outcome = self.run_cycle(monitor_topic=lambda topic: record, commit_monitoring=self.commit_monitor)
        self.assertEqual(outcome.monitoring[0].status, "partial")
        markdown = self.drive.read_exact(outcome.report_reference).content
        self.assertIn(b"unassessed; not a verified development", markdown)
        self.assertIn(b"inspection locator was not saved", markdown)
        self.assertEqual(self.drive.read_exact(self.wiki.id).content, b"Manual note remains here")

    def test_report_preserves_assessed_status_over_result_confidence(self):
        self.add_items(1)
        def misleading(item, reservation):
            result = self.investigate(item, reservation)
            result.confidence = "high confidence proven"
            return result
        outcome = self.run_cycle(investigate=misleading)
        markdown = self.drive.read_exact(outcome.report_reference).content
        self.assertIn(b"[uncertain]", markdown)
        self.assertNotIn(b"high confidence proven", markdown)

    def test_material_ledger_finalizes_after_independent_wiki_receipts(self):
        from wikiplant.monitoring import PersistentMonitoringLedger
        raw = self.file("material-ledger.json", "application/json", b"{}")
        writer = SafeWriter(self.drive, self.root.id, self.ops.id, self.inbox.id, instance_id="wp-test")
        ledger = PersistentMonitoringLedger(writer, self.binding(raw), execution_guard=lambda: "synthetic-exclusive-host")
        prepared = self.material_monitor()
        record, _ = ledger.begin(instance_id="wp-test", local_date="2026-01-15", topic_id="topic-a",
            last_successful_end=prepared.coverage_start, scheduled_end=prepared.coverage_end,
            overlap_hours=0, max_queries=4, max_sources=8)
        ledger.search(record, "Synthetic material topic", lambda query: {"reference": "synthetic-search-result"})
        ledger.inspect(record, "synthetic-source", lambda source: {"locator": "section-1"})
        for name in ("findings", "affected_page_ids", "claim_ids", "evidence_assessment_ref"):
            setattr(record, name, getattr(prepared, name))
        ledger.finish(record, "complete")
        self.assertEqual(record.status, "partial")
        outcome = self.run_cycle(monitor_topic=lambda topic: record, commit_monitoring=self.commit_monitor,
            finalize_monitoring=lambda value, receipts: ledger.finish(value, "complete", commit_receipts=receipts))
        self.assertEqual(outcome.monitoring[0].status, "complete", outcome.gaps)
        saved = json.loads(self.drive.read_exact(raw.id).content)[record.key]
        self.assertEqual(saved["status"], "complete")
        self.assertEqual(saved["successful_watermark"], prepared.coverage_end)
        self.assertEqual((saved["queries_used"], saved["sources_used"]), (1, 1))
