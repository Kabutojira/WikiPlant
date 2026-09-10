"""Fresh final review regressions; all host/storage observations are synthetic."""
import json
from dataclasses import asdict
import unittest

from tests.integration import test_persisted_daily as persisted
from tests.integration import test_installer as installation
from wikiplant.authorization import UserAuthorization, request_digest, validate_user_authorization
from wikiplant.errors import ValidationError
from wikiplant.intake import durable_intake
from wikiplant.installer import InstallPhase
from wikiplant.monitoring import MonitoringRecord, PersistentMonitoringLedger
from wikiplant.queue import read_queue
from wikiplant.records import Command
from wikiplant.storage import SafeWriter
from wikiplant.storage import create_artifact


class ReviewRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = persisted.PersistedDailyTests()
        self.fixture.setUp()

    def test_complete_research_commit_retries_without_new_investigation(self):
        fixture = self.fixture
        fixture.add_items(1)
        commits = []

        def fail_commit(result):
            commits.append(result.id)
            raise RuntimeError("synthetic temporary commit outage")

        first = fixture.run_cycle(commit_research=fail_commit)
        self.assertIsNotNone(first.report_reference)
        self.assertEqual(fixture.calls.count("q0"), 1)

        def recover_commit(result):
            commits.append(result.id)
            return fixture.commit(result)

        fixture.run_cycle(commit_research=recover_commit)
        self.assertEqual(commits, ["result-q0", "result-q0"])
        self.assertEqual(fixture.calls.count("q0"), 1)
        self.assertEqual(read_queue(fixture.drive.read_exact(fixture.queue.id).content.decode()), [])

    def test_folder_reference_cannot_certify_wiki_commit(self):
        fixture = self.fixture
        fixture.add_items(1)
        fixture.run_cycle(commit_research=lambda result: [fixture.root.id])
        queue = read_queue(fixture.drive.read_exact(fixture.queue.id).content.decode())
        self.assertEqual([item.id for item in queue], ["q0"])
        self.assertEqual(queue[0].status, "blocked")
        state = json.loads(fixture.drive.read_exact(fixture.state.id).content)
        self.assertFalse(state["attempts"]["wp-test:2026-01-15:slot-1"].get("commit_refs"))

    def test_historical_commit_receipt_survives_later_same_page_work(self):
        fixture = self.fixture
        fixture.add_items(2)

        def lose_first_result(result):
            receipts = fixture.commit(result)
            if result.item_id == "q0":
                raise RuntimeError("synthetic lost commit callback response")
            return receipts

        fixture.run_cycle(commit_research=lose_first_result)
        before = fixture.drive.read_exact(fixture.wiki.id).content
        self.assertIn(b"result-q0", before)
        self.assertIn(b"result-q1", before)
        fixture.run_cycle()
        self.assertEqual(fixture.drive.read_exact(fixture.wiki.id).content, before)
        self.assertEqual(fixture.calls.count("q0"), 1)
        self.assertEqual(fixture.calls.count("q1"), 1)
        self.assertEqual(read_queue(fixture.drive.read_exact(fixture.queue.id).content.decode()), [])

    def test_saved_partial_report_does_not_disable_same_day_monitoring_retry(self):
        fixture = self.fixture

        def partial(topic):
            record = MonitoringRecord("wp-test", "2026-01-15", topic["id"],
                "2026-01-14T00:00:00Z", "2026-01-15T12:00:00Z", 4, 8)
            record.reserve_query()
            record.record_query(1, status="failed", query="synthetic query", limitation="outage")
            record.finish("partial", limitation="synthetic search unavailable")
            fixture.calls.append("partial")
            return record

        first = fixture.run_cycle(monitor_topic=partial)
        self.assertIsNotNone(first.report_reference)
        def recovered(topic):
            saved = json.loads(fixture.drive.read_exact(fixture.state.id).content)
            record = MonitoringRecord(**saved["monitoring"][topic["id"]]["record"])
            reservation = record.reserve_query()
            self.assertEqual(reservation, 2)
            record.record_query(reservation, status="success", query="synthetic query",
                result_reference="synthetic-recovered-result", replaces_reservation=1)
            record.finish("no_material_update")
            fixture.calls.append("monitor")
            return record

        second = fixture.run_cycle(monitor_topic=recovered)
        self.assertEqual(fixture.calls, ["partial", "monitor"])
        self.assertEqual(second.monitoring[0].status, "no_material_update")

    def test_monitoring_cannot_invoke_with_an_unreserved_detached_record(self):
        fixture = self.fixture
        raw = fixture.file("monitor-ledger.json", "application/json", b"{}")
        writer = SafeWriter(fixture.drive, fixture.root.id, fixture.ops.id, fixture.inbox.id, instance_id="wp-test")
        ledger = PersistentMonitoringLedger(writer, fixture.binding(raw), execution_guard=lambda: "synthetic-exclusive-host")
        record, _ = ledger.begin(instance_id="wp-test", local_date="2026-01-15", topic_id="topic-a",
            last_successful_end="2026-01-14T00:00:00Z", scheduled_end="2026-01-15T12:00:00Z",
            overlap_hours=12, max_queries=2, max_sources=2)
        detached = MonitoringRecord(**asdict(record))
        calls = []

        def invoke(query):
            calls.append(query)
            saved = json.loads(fixture.drive.read_exact(raw.id).content)
            self.assertEqual(saved[record.key]["queries_used"], 1,
                             "Actual provider invocation must follow durable reservation")
            return {"reference": "synthetic-search-result"}

        with self.assertRaises(ValidationError):
            ledger.search(detached, "synthetic query", invoke)
        self.assertEqual(calls, [])

    def test_material_monitoring_ledger_does_not_keep_unverified_success_watermark(self):
        fixture = self.fixture
        raw = fixture.file("material-monitor-ledger.json", "application/json", b"{}")
        writer = SafeWriter(fixture.drive, fixture.root.id, fixture.ops.id, fixture.inbox.id, instance_id="wp-test")
        ledger = PersistentMonitoringLedger(writer, fixture.binding(raw), execution_guard=lambda: "synthetic-exclusive-host")

        def monitor(topic):
            prepared = fixture.material_monitor()
            record, _ = ledger.begin(instance_id="wp-test", local_date="2026-01-15", topic_id="topic-a",
                last_successful_end="2026-01-14T00:00:00Z", scheduled_end=prepared.coverage_end,
                overlap_hours=0, max_queries=4, max_sources=8)
            ledger.search(record, "Synthetic material topic", lambda query: {"reference": "synthetic-search-result"})
            ledger.inspect(record, "synthetic-source", lambda source: {"locator": "section-1"})
            for name in ("findings", "affected_page_ids", "claim_ids", "evidence_assessment_ref"):
                setattr(record, name, getattr(prepared, name))
            ledger.finish(record, "complete")
            return record

        fixture.run_cycle(monitor_topic=monitor, commit_monitoring=lambda record: [fixture.evidence.id])
        durable = json.loads(fixture.drive.read_exact(raw.id).content)["wp-test:2026-01-15:topic-a"]
        self.assertNotEqual(durable["status"], "complete")
        self.assertIsNone(durable["successful_watermark"])

    def test_forged_completion_cannot_rebind_a_real_intent_to_another_page(self):
        fixture = self.fixture
        fixture.add_items(1)
        unrelated = fixture.file("unrelated.md", "text/markdown", b"Unrelated private page")

        def forge(result):
            original = fixture.commit(result)[0]
            completion = json.loads(fixture.drive.read_exact(original["operation_reference"]).content)
            completion["target_id"] = unrelated.id
            completion["output_sha256"] = unrelated.sha256
            forged = create_artifact(fixture.drive, fixture.root.id, fixture.evidence.id,
                "forged-completion.json", completion, "synthetic-forged-completion")
            return [dict(page_id=fixture.wiki.id, file_id=unrelated.id, sha256=unrelated.sha256,
                         operation_reference=forged.id)]

        fixture.run_cycle(commit_research=forge)
        queue = read_queue(fixture.drive.read_exact(fixture.queue.id).content.decode())
        self.assertEqual([item.id for item in queue], ["q0"])
        self.assertEqual(queue[0].status, "blocked")


class ReviewAuthorizationTests(unittest.TestCase):
    def test_truthy_string_is_not_affirmative_authorization(self):
        grant = UserAuthorization("synthetic-turn", "wp-test", "save", "note",
            request_digest("Do not save this"), True, "Synthetic malformed interpretation").to_dict()
        for value in ("false", "true", 1):
            with self.subTest(value=value):
                grant["affirmative"] = value
                with self.assertRaises(ValidationError):
                    validate_user_authorization(grant, instance_id="wp-test", operation="save", target="note")

    def test_valid_other_instance_grant_cannot_write_this_inbox(self):
        fixture = persisted.PersistedDailyTests()
        fixture.setUp()
        grant = UserAuthorization("synthetic-other-turn", "wp-other", "save", "note",
            request_digest("Save to other wiki"), True, "Synthetic explicit destination").to_dict()
        command = Command("other-cmd", "wp-other", "save", grant, "Synthetic private note for B",
            "2026-01-15T00:00:00Z", target="note")
        with self.assertRaises(ValidationError):
            durable_intake(fixture.drive, fixture.inbox.id, command,
                approved_root_id=fixture.root.id, expected_instance_id="wp-test")
        self.assertEqual(fixture.drive.list_all(fixture.inbox.id), [])


class ReviewInstallerTests(unittest.TestCase):
    def test_resume_does_not_bypass_public_destination_block(self):
        fixture = installation.InstallerTests()
        drive, parent, host, installer = fixture.environment()
        manifest = installation.build_manifest(installation.ROOT, "0.1.0", installation.COMMIT)
        values = installation.setup(parent.id)
        values.purpose = "PRIVATE-FIXTURE-PURPOSE must never enter public Drive"
        drive.public_parents.add(parent.id)
        for _ in range(2):
            result = installer.run(values, manifest, installation.COMMIT)
            self.assertEqual(result.phase, InstallPhase.BLOCKED.name)
            self.assertFalse(any(b"PRIVATE-FIXTURE-PURPOSE" in entry.content for entry in drive.entries.values()))

    def test_resume_cannot_swap_the_pinned_release(self):
        fixture = installation.InstallerTests()
        drive, parent, host, installer = fixture.environment()
        manifest = installation.build_manifest(installation.ROOT, "0.1.0", installation.COMMIT)
        values = installation.setup(parent.id)
        installer.run(values, manifest, installation.COMMIT, stop_after=InstallPhase.RUNTIME_VERIFIED)
        replacement_commit = "c" * 40
        replacement = installation.build_manifest(installation.ROOT, "0.2.0", replacement_commit)
        try:
            state = installer.run(values, replacement, replacement_commit)
        except ValidationError:
            pass
        else:
            self.assertEqual(state.phase, InstallPhase.BLOCKED.name)
        self.assertEqual(host.skills, {})
        self.assertEqual(host.tasks, {})
