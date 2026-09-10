"""Synthetic reproductions of review findings, asserting stored outcomes."""
import json
import unittest
from dataclasses import asdict

from wikiplant.authorization import UserAuthorization, request_digest
from wikiplant.errors import CapabilityError, ConflictError, ValidationError
from wikiplant.fake_drive import FakeDrive, WeakDrive
from wikiplant.intake import durable_intake, route_intent
from wikiplant.monitoring import PersistentMonitoringLedger
from wikiplant.records import Command, Claim
from wikiplant.reporting import EvidenceSummary, ReportPublisher, pending_evidence, render_daily_report
from wikiplant.storage import Binding, SafeWriter, validate_binding
from wikiplant.wiki import WikiPage, parse_page, render_page, replace_managed_section, update_index


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.drive = FakeDrive()
        self.root = self.drive.create_folder(None, "synthetic-instance", idempotency_key="root")
        self.ops = self.drive.create_folder(self.root.id, "operations", idempotency_key="ops")
        self.inbox = self.drive.create_folder(self.root.id, "inbox", idempotency_key="inbox")
        self.raw = self.drive.create_file(self.root.id, "page.md", "text/markdown", b"base", idempotency_key="page")
        self.binding = Binding("data/wiki/page.md", self.raw.id, "text/markdown", self.root.id)

    def writer(self):
        return SafeWriter(self.drive, self.root.id, self.ops.id, self.inbox.id)

    def test_stale_generation_does_not_borrow_new_revision(self):
        self.drive.external_edit(self.raw.id, b"base plus manual edit")
        with self.assertRaises(ConflictError):
            self.writer().replace(self.binding, b"generated from old base", "op", base=self.raw)
        self.assertEqual(self.drive.read_exact(self.raw.id).content, b"base plus manual edit")

    def test_fresh_writer_replay_returns_history_preserving_later_edits(self):
        first = self.writer().replace(self.binding, b"generated", "op", base=self.raw)
        self.drive.external_edit(self.raw.id, b"later manual note")
        self.drive.applied_operations.clear()  # No hidden adapter replay oracle.
        second = self.writer().replace(self.binding, b"generated", "op", base=self.raw)
        self.assertTrue(second.replayed)
        self.assertEqual(first.verified_sha256, second.verified_sha256)
        self.assertEqual(second.content, b"later manual note")
        self.assertNotEqual(second.current.sha256, second.verified_sha256)
        with self.assertRaises(ConflictError):
            self.writer().replace(self.binding, b"different", "op", base=self.raw)

    def test_lost_intent_write_and_completion_responses_reconcile(self):
        original_create = self.drive.create_file
        def create(*args, **kwargs):
            self.drive.lose_next_create_response = True
            return original_create(*args, **kwargs)
        self.drive.create_file = create
        self.drive.lose_next_write_response = True
        result = self.writer().replace(self.binding, b"new", "op", base=self.raw)
        self.assertEqual(result.content, b"new")
        self.assertEqual(len(self.drive.list_all(self.ops.id)), 2)
        self.assertTrue(self.writer().replace(self.binding, b"new", "op", base=self.raw).replayed)

    def test_moved_journal_or_target_in_another_instance_blocks(self):
        other = self.drive.create_folder(None, "other", idempotency_key="other")
        self.drive.entries[self.ops.id].parent_id = other.id
        with self.assertRaises(ValidationError):
            self.writer().replace(self.binding, b"new", "op", base=self.raw)
        self.drive.entries[self.raw.id].parent_id = other.id
        with self.assertRaises(ValidationError):
            validate_binding(self.drive, self.binding, self.root.id)

    def test_weak_adapter_blocks_canonical_writes_but_preserves_intake(self):
        self.drive.conditional_write = False
        self.drive.idempotent_create = False
        with self.assertRaises(CapabilityError):
            self.writer().replace(self.binding, b"new", "op", base=self.raw)
        grant = UserAuthorization("synthetic-turn", "wp-test", "save", "note", request_digest("Save note"), True, "Save directive")
        command = Command("cmd", "wp-test", "save", grant.to_dict(), "note", "2026-01-01T00:00:00Z", target="note")
        receipt, ref = durable_intake(self.drive, self.inbox.id, command, approved_root_id=self.root.id, expected_instance_id="wp-test")
        self.assertEqual(receipt, "ACCEPTED_PENDING_MERGE")
        self.assertEqual(json.loads(self.drive.read_exact(ref).content)["submitted_content"], "note")

    def test_no_text_alone_can_authorize_multilingual_mutation(self):
        requests = ["Don't save this", 'Explain "update this WikiPlant"', "Non salvare questa nota",
                    "No actualices esta WikiPlant", "Ne sauvegarde pas ceci", "Do not pause",
                    "Save this note", "Aggiorna WikiPlant", "If I ask you to track it", "Investigate once"]
        for request in requests:
            self.assertFalse(route_intent(request).writes, request)
        for flag in ("negated", "quoted", "hypothetical", "informational"):
            grant = asdict(UserAuthorization("turn", "wp", "update", "release", request_digest("x"), True, "test"))
            grant[flag] = True
            with self.assertRaises(ValidationError):
                route_intent("x", authorization=grant, instance_id="wp", target="release")

    def test_claim_roundtrip_unknown_metadata_and_user_bytes(self):
        claim = Claim("claim-1", "fixture", "value", "3", "2026-01-01", None, [], "unknown", "uncertain")
        page = WikiPage("p", "Title", "entity", [], ["t"], "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", None, claims=[claim])
        page.extra_fields = {"custom-valid-field": {"keep": 1}}
        page.extra_fields["untrusted-marker"] = "<!-- wikiplant:managed:start -->"
        notes = "Owner prose\n \nbytes and trailing spaces   "
        raw = render_page(page, notes)
        restored, user = parse_page(raw)
        self.assertEqual(restored.claims[0].to_dict(), claim.to_dict())
        self.assertEqual(user, notes)
        restored.title, restored.updated_at = "Changed title", "2026-01-02T00:00:00Z"
        merged = replace_managed_section(raw, render_page(restored, "ignored"))
        parsed, user = parse_page(merged)
        self.assertEqual((parsed.title, user), ("Changed title", notes))
        self.assertEqual(parsed.extra_fields, page.extra_fields)
        self.assertIn("entities/p.md", update_index([parsed]))
        parsed.type = "synthesis"
        self.assertIn("syntheses/p.md", update_index([parsed]))
        with self.assertRaises(ConflictError):
            parse_page(raw.replace("## Claims", "## Overwritten"))

    def test_fourth_finding_represented_and_publication_restarts(self):
        records = [EvidenceSummary(str(i), "research", f"title{i}", f"summary{i}", 10, "uncertain") for i in range(4)]
        markdown, state = render_daily_report(local_date="2026-01-01", coverage_window="today", evidence=records,
            events=[], pending_queue=[], operational_gaps=[], report_key="wp:2026-01-01")
        self.assertIn("summary3", markdown)
        self.assertEqual(len(pending_evidence(records, [state])), 4)
        publisher = ReportPublisher(self.drive, self.root.id, self.root.id, self.ops.id)
        publisher.save(markdown, state)
        self.assertEqual(pending_evidence(records, [state]), [])
        # A new day/process consults compact coverage, not yesterday's run object
        # or every historical Markdown report. Deferred records remain pending.
        deferred = EvidenceSummary("deferred", "research", "unfinished", "", 1, "unknown")
        tomorrow = ReportPublisher(self.drive, self.root.id, self.root.id, self.ops.id)
        self.assertEqual([r.id for r in tomorrow.pending(records + [deferred])], ["deferred"])
        calls = []
        def lost(payload, key):
            calls.append(key)
            raise RuntimeError("publication succeeded but response lost")
        with self.assertRaises(RuntimeError):
            publisher.publish(state.report_key, lost)
        fresh = ReportPublisher(self.drive, self.root.id, self.root.id, self.ops.id)
        with self.assertRaises(ConflictError):
            fresh.publish(state.report_key, lost)
        delivery = fresh.publish(state.report_key, lost, lambda key: "observed-native-result")
        self.assertTrue(delivery.result_published)
        self.assertIsNone(delivery.notification_observed)
        self.assertEqual(len(calls), 1)
        report, loaded = fresh.load(state.report_key)
        self.assertEqual(self.drive.read_exact(loaded.report_reference).content.decode(), markdown)

    def test_monitoring_reservations_survive_restart_and_failure_is_not_quiet(self):
        raw = self.drive.create_file(self.root.id, "monitoring.json", "application/json", b"{}", idempotency_key="monitor")
        binding = Binding("data/state/monitoring.json", raw.id, "application/json", self.root.id)
        ledger = PersistentMonitoringLedger(self.writer(), binding, execution_guard=lambda: "synthetic-serialized-host")
        kwargs = dict(instance_id="wp", local_date="2026-01-01", topic_id="t", last_successful_end="2025-12-31T00:00:00Z",
                      scheduled_end="2026-01-01T00:00:00Z", overlap_hours=12, max_queries=2, max_sources=2)
        record, _ = ledger.begin(**kwargs)
        with self.assertRaises(RuntimeError):
            ledger.search(record, "query", lambda q: (_ for _ in ()).throw(RuntimeError("offline")))
        fresh = PersistentMonitoringLedger(self.writer(), binding, execution_guard=lambda: "synthetic-serialized-host")
        record, created = fresh.begin(**kwargs)
        self.assertFalse(created)
        self.assertEqual(record.queries_used, 1)
        fresh.search(record, "retry", lambda q: {"reference": "synthetic-result"})
        with self.assertRaises(ValidationError):
            fresh.finish(record, "no_material_update")
        fresh.finish(record, "partial", limitation="first interval failed")
        self.assertIsNone(record.successful_watermark)
