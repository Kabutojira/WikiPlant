"""Synthetic deterministic scope/archive regressions; these are not cloud evidence."""
from __future__ import annotations

import copy
import json
import unittest
from datetime import date, datetime, timezone

from wikiplant.admission import AdmissionCandidate, AdmissionGate, AdmissionPolicy, LineageRecord, decide_admission
from wikiplant.archive import ArchiveCapsule, build_archive_partitions, compact_recovery_snapshot, compact_research_dossier, execute_archive, plan_archive, resume_archive, retrieve_archives
from wikiplant.authorization import UserAuthorization
from wikiplant.calendar import CalendarItem, due_refreshes, occurrence_id, occurrences, read_calendar, reschedule, write_calendar
from wikiplant.errors import ConflictError, ValidationError
from wikiplant.fake_drive import FakeDrive
from wikiplant.queue import DailyBudget, QueueItem, read_queue, select_next, write_queue
from wikiplant.storage import Binding, SafeWriter
from wikiplant.topics import Topic, TopicRegistry, migrate_approved_topics, next_weekly_checkpoint
from wikiplant.wiki import WikiPage, render_page, update_index


STAMP = "2026-01-15T10:00:00+00:00"
NOW = datetime.fromisoformat(STAMP)


def auth(operation="track", target="anchor"):
    return UserAuthorization("synthetic-user-turn", "wp-test", operation, target, "a" * 64, True, "Synthetic affirmative directive").to_dict()


def registry():
    anchor = Topic("anchor", "Synthetic pump goal", "user", ["anchor"], [], "", "Explicit synthetic tracking directive", STAMP, STAMP, 1, authorization=auth())
    adjacent = Topic("adjacent", "Synthetic numerical method", "adjacent", ["anchor"], ["anchor"], "Tests numerical stability of the user's pump simulation", "Recorded direct contribution", STAMP, STAMP, 1, evidence_refs=["assessment-synthetic"])
    peripheral = Topic("peripheral", "Synthetic implementation curiosity", "peripheral", ["anchor"], ["adjacent"], "", "Useful only through adjacent method", STAMP, STAMP, 1, expires_at="2026-01-18T04:00:00+00:00", may_spawn_research=False, expansion_priority=60)
    return TopicRegistry("wp-test", 1, [anchor, adjacent, peripheral])


def item(identifier="q1", topic="adjacent", origin="discovery", priority=20):
    return QueueItem(priority, identifier, priority, "investigation", f"Synthetic question {identifier}?", topic, [], [], identifier, origin, "synthetic-source", STAMP, priority_reason="Direct contribution to user goal", urgency_reason="Synthetic deadline" if priority == 0 else "")


def candidate(identifier="q1", topic="adjacent", origin="discovery"):
    result = AdmissionCandidate(item(identifier, topic, origin), "peripheral" if topic == "peripheral" else "adjacent", ["anchor"], "Tests a named user goal assumption", "assessment-question", "new-evidence-" + identifier, ["synthetic-inspected-source"], root_reason="independent_external_event")
    if origin == "user":
        result.authorization = auth("investigate", identifier)
    return result


class TopicTests(unittest.TestCase):
    def test_roundtrip_exact_sections_unknown_fields_and_notes(self):
        state = registry()
        state.topics[1].extra["user_custom_field"] = {"alpha": 3}
        state.notes["adjacent"] = "User-authored explanatory note."
        restored = TopicRegistry.parse(state.render())
        self.assertEqual([t.to_dict() for t in restored.topics], [t.to_dict() for t in state.topics])
        self.assertIn("User-authored explanatory note.", restored.render())
        self.assertEqual(restored.monitored_topics({"primary_topic_ids": ["anchor"]})[0]["name"], "Synthetic pump goal")

    def test_anchors_require_affirmative_current_bound_authorization(self):
        for change in ({"negated": True}, {"quoted": True}, {"hypothetical": True}, {"informational": True}, {"instance_id": "another"}, {"operation": "save"}, {"target": "other"}):
            state = registry()
            state.topics[0].authorization.update(change)
            with self.subTest(change=change), self.assertRaises(ValidationError):
                state.validate()

    def test_maintenance_cannot_edit_anchor_or_promote_without_new_direct_evidence(self):
        state = registry()
        changed = copy.deepcopy(state.topics[0]); changed.label = "Changed anchor"
        with self.assertRaises(ValidationError):
            state.transition(changed)
        changed = copy.deepcopy(state.topics[2]); changed.classification = "adjacent"; changed.may_spawn_research = True
        with self.assertRaises(ValidationError):
            state.transition(changed)
        changed.direct_contribution = "New finding tests a pump constraint directly"
        changed.evidence_refs = ["new-inspected-direct-evidence"]
        self.assertEqual(state.transition(changed).by_id["peripheral"].classification, "adjacent")

    def test_expiry_is_next_distinct_future_and_cannot_be_extended(self):
        result = next_weekly_checkpoint("2026-01-18T04:00:00+00:00", weekday="sunday", local_time="04:00", timezone_name="UTC")
        self.assertEqual(result, "2026-01-25T04:00:00+00:00")
        state = registry(); changed = copy.deepcopy(state.topics[2]); changed.expires_at = result
        with self.assertRaises(ValidationError):
            state.transition(changed)
        self.assertFalse(state.topics[2].automatic_eligible(datetime(2026, 1, 19, tzinfo=timezone.utc)))

    def test_duplicate_unknown_and_cyclic_topic_references_rejected(self):
        for mutate in (lambda s: s.topics.append(copy.deepcopy(s.topics[0])), lambda s: s.topics[1].parent_ids.append("missing"), lambda s: s.topics[0].parent_ids.append("adjacent")):
            state = registry(); mutate(state)
            with self.assertRaises(ValidationError): state.validate()

    def test_topic_capacity_and_legacy_provenance(self):
        state = registry(); extra = copy.deepcopy(state.topics[1]); extra.id = "new-topic"
        with self.assertRaises(ValidationError): state.transition(extra, policy=AdmissionPolicy(max_active_adjacent_topics=1))
        old = {"schema_version": 1, "primary_topics": [{"id": "anchor", "name": "Approved"}, {"id": "guess", "name": "Unproven"}], "queue": {"attempts": 4}}
        migrated, config, unresolved = migrate_approved_topics(old, instance_id="wp-test", authorization_history={"anchor": auth()}, created_at=STAMP)
        self.assertEqual(config["primary_topic_ids"], ["anchor"])
        self.assertEqual(unresolved, ["guess"])
        self.assertEqual(migrated.by_id["guess"].lifecycle, "provisional")
        self.assertFalse(migrated.by_id["guess"].may_spawn_research)
        self.assertEqual(config["queue"], old["queue"])
        self.assertEqual(old["schema_version"], 1)


class AdmissionTests(unittest.TestCase):
    def test_distant_direct_connection_admitted_but_local_chain_rejected(self):
        proposal = candidate()
        self.assertEqual(decide_admission(proposal, registry(), [], {}, now=NOW).disposition, "admit")
        proposal.relationship = "via_adjacent"
        self.assertEqual(decide_admission(proposal, registry(), [], {}, now=NOW).disposition, "reject_scope")

    def test_all_origins_obey_terminal_ancestry_even_relabelled_urgent(self):
        for origin in ("main-topic", "discovery", "research", "calendar", "maintenance", "initialization"):
            proposal = candidate(origin=origin); proposal.item.parent_ids = ["parent"]; proposal.item.expansion_priority = 80
            proposal.item.priority = 0; proposal.item.urgency_reason = "Synthetic urgent deadline"
            proposal.item.lineage_root_id = "root"
            parents = {"parent": LineageRecord("parent", "peripheral", [], ["root"], ["anchor"], 60, True, "prior", "prior")}
            with self.subTest(origin=origin):
                decision = decide_admission(proposal, registry(), [], parents, now=NOW)
                self.assertEqual(decision.disposition, "reject_scope")
                self.assertIn("Terminal", decision.reason)

    def test_recurring_peripheral_and_expired_work_rejected(self):
        proposal = candidate(topic="peripheral"); proposal.recurring = True
        self.assertEqual(decide_admission(proposal, registry(), [], {}, now=NOW).disposition, "reject_scope")
        proposal.recurring = False
        self.assertEqual(decide_admission(proposal, registry(), [], {}, now=datetime(2026, 1, 19, tzinfo=timezone.utc)).disposition, "archive_candidate")

    def test_merged_ancestry_cannot_take_unvalidated_minimum(self):
        proposal = candidate(); proposal.item.parent_ids = ["low", "high"]; proposal.item.expansion_priority = 40; proposal.item.lineage_root_id = "low"
        parents = {p: LineageRecord(p, "adjacent", [], [p], ["anchor"], score, False, p, p) for p, score in (("low", 20), ("high", 60))}
        self.assertEqual(decide_admission(proposal, registry(), [], parents, now=NOW).disposition, "reject_scope")
        proposal.validated_independent_parent_ids = ["low"]
        proposal.independent_parent_assessments = {"low": {"reason": "Independent original evidence supports this actual question", "evidence_refs": ["inspected-independent-origin"]}}
        self.assertEqual(decide_admission(proposal, registry(), [], parents, now=NOW).disposition, "admit")

    def test_stable_replay_and_semantic_duplicate_do_not_create_roots(self):
        proposal = candidate()
        gate = AdmissionGate(registry(), {proposal.item.id: proposal})
        accepted = gate.evaluate(proposal.item, [], NOW); gate.record(accepted)
        restored = AdmissionGate.from_dict(json.loads(json.dumps(gate.to_dict())), registry())
        other = candidate("paraphrase"); other.semantic_matches = [{"target_id": "q1", "equivalent": True, "new_evidence": False, "assessment_ref": "review", "reason": "same entity, conditions and evidence", "occurrence_id": ""}]
        self.assertEqual(decide_admission(other, registry(), [proposal.item], restored.lineage, now=NOW).disposition, "merge")
        restored.lineage["q1"].status = "completed"
        self.assertEqual(decide_admission(other, registry(), [], restored.lineage, now=NOW).disposition, "archive_candidate")

    def test_sustained_automatic_overload_is_bounded_and_explicit_work_preserved(self):
        state = registry(); gate = AdmissionGate(state, policy=AdmissionPolicy(max_active_automatic_items=3, max_new_automatic_roots_per_day=100))
        queue = []
        for index in range(40):
            proposal = candidate(f"q{index}"); gate.candidates[proposal.item.id] = proposal
            result = gate.evaluate(proposal.item, queue, NOW); gate.record(result)
            if result.disposition == "admit": queue.append(proposal.item)
        self.assertEqual(len(queue), 3)
        self.assertEqual(sum(d.disposition == "defer_capacity" for d in gate.decisions), 37)
        user = candidate("explicit", topic="outside", origin="user")
        result = decide_admission(user, state, queue, gate.lineage, now=NOW, policy=gate.policy)
        self.assertEqual(result.disposition, "defer_capacity")
        self.assertTrue(result.terminal)
        self.assertTrue(result.defer_until)
        self.assertNotIn("outside", state.by_id)

    def test_scope_change_before_execution_revalidates_and_counterevidence_is_in_scope(self):
        proposal = candidate(); proposal.contribution = "Counterevidence challenges the user's preferred mechanism"
        gate = AdmissionGate(registry(), {proposal.item.id: proposal})
        self.assertEqual(gate.evaluate(proposal.item, [proposal.item], NOW, execution=True).disposition, "admit")
        gate.registry.topics[1].lifecycle = "retired"
        self.assertEqual(gate.evaluate(proposal.item, [proposal.item], NOW, execution=True).disposition, "archive_candidate")

    def test_archived_parent_cannot_support_another_active_topic_or_regain_depth(self):
        state = registry()
        old_topic = copy.deepcopy(state.topics[1]); old_topic.id = "archived-adjacent"; old_topic.lifecycle = "archived"
        state.topics.append(old_topic)
        proposal = candidate(); proposal.item.parent_ids = ["old-parent"]; proposal.item.lineage_root_id = "old-root"; proposal.item.expansion_priority = 40
        lineage = {"old-parent": LineageRecord("old-parent", old_topic.id, [], ["old-root"], ["anchor"], 20, False, "old", "old")}
        self.assertEqual(decide_admission(proposal, state, [], lineage, now=NOW).disposition, "reject_scope")
        old_topic.lifecycle = "active"
        lineage["old-parent"].status = "archived"
        self.assertEqual(decide_admission(proposal, state, [], lineage, now=NOW).disposition, "reject_scope")

    def test_local_root_budget_is_not_recharged_by_execution_revalidation(self):
        gate = AdmissionGate(registry(), policy=AdmissionPolicy(max_new_automatic_roots_per_day=1), timezone_name="Pacific/Auckland")
        late = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
        proposal = candidate(); gate.candidates["q1"] = proposal
        gate.record(gate.evaluate(proposal.item, [], late))
        gate.record(gate.evaluate(proposal.item, [proposal.item], late, execution=True))
        second = candidate("q2"); gate.candidates["q2"] = second
        decision = gate.evaluate(second.item, [proposal.item], late)
        self.assertEqual(decision.disposition, "defer_capacity")
        self.assertEqual(decision.capacity["new_roots_today"], 1)
        self.assertEqual(decision.local_cycle_date, "2026-01-16")
        gate.lineage["q1"].status = "completed"
        gate.record(gate.evaluate(proposal.item, [proposal.item], late, execution=True))
        self.assertEqual(gate.lineage["q1"].status, "completed")


class QueueCalendarHardeningTests(unittest.TestCase):
    def test_duplicate_ids_fail_csv_read_and_write(self):
        one = item()
        with self.assertRaises(ValidationError): write_queue([one, copy.deepcopy(one)])
        text = write_queue([one]); row = text.splitlines()[1]
        with self.assertRaises(ValidationError): read_queue(text + row + "\n")

    def test_validation_lane_does_not_override_urgent_or_expand_budget(self):
        budget = DailyBudget("wp-test", "2026-01-15", "UTC")
        for index in range(4): budget.reserve(item(f"used-{index}"))
        validation = item("validation", priority=80); validation.kind = "validation"; validation.due_at = "2026-01-14T00:00:00+00:00"
        ordinary = item("ordinary", priority=10)
        self.assertEqual(select_next([validation, ordinary], budget, NOW).id, "validation")
        urgent = item("urgent", priority=0); log = []
        self.assertEqual(select_next([validation, urgent], budget, NOW, selection_log=log).id, "urgent")
        self.assertTrue(log[0]["validation_deferred_by_urgency"])
        budget.reserve(urgent)
        self.assertIsNone(select_next([validation, ordinary], budget, NOW))

    def test_calendar_monthly_anchor_non_utc_deadlines_and_bounded_catchup(self):
        event = CalendarItem("event", "research_refresh", "Synthetic refresh", "2026-01-31", "", "", "Europe/Rome", "date", "scheduled", [], [], "Refresh?", 20, 20, {"frequency": "monthly", "interval": 1}, 0, "fixture", STAMP)
        self.assertEqual([d.isoformat() for d in occurrences(event, date(2026, 3, 31))], ["2026-01-31", "2026-02-28", "2026-03-31"])
        results = due_refreshes([event], date(2026, 3, 31), {}, STAMP)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].due_at.endswith("+02:00"))
        state = {results[0].refresh_occurrence_id: "queued"}
        self.assertEqual(due_refreshes([event], date(2026, 3, 31), state, STAMP), [])
        with self.assertRaises(ValidationError): write_calendar([event, copy.deepcopy(event)])

    def test_v2_calendar_routes_terminal_scope_through_shared_admission(self):
        event = CalendarItem("event", "research_refresh", "Synthetic peripheral refresh", "2026-01-15", "", "", "UTC", "date", "scheduled", [], [], "Refresh?", 60, 60, {"frequency": "weekly", "interval": 1}, 0, "fixture", STAMP, schema_version=2, topic_id="peripheral", lineage_root_id="root", root_reason="independent_external_event")
        identifier = "q-" + occurrence_id(event, date(2026, 1, 15))
        proposal = candidate(identifier, topic="peripheral", origin="calendar")
        gate = AdmissionGate(registry(), {identifier: proposal})
        coverage = []
        self.assertEqual(due_refreshes([event], date(2026, 1, 15), {}, STAMP, admission_gate=gate, coverage_log=coverage), [])
        self.assertEqual(coverage[0]["disposition"], "reject_scope")
        with self.assertRaises(ValidationError): due_refreshes([event], date(2026, 1, 15), {}, STAMP)

    def test_timed_reschedule_preserves_local_clock_and_duration_across_dst(self):
        event = CalendarItem("event", "event", "Synthetic meeting", "2026-03-28", "2026-03-28T10:00:00+01:00", "2026-03-28T11:30:00+01:00", "Europe/Rome", "time", "scheduled", [], [], "", 20, 20, {"frequency": "none"}, 0, "fixture", STAMP)
        previous, revised = reschedule(event, new_id="rescheduled", new_start_date="2026-03-30", updated_at=STAMP)
        self.assertEqual(previous.status, "cancelled")
        self.assertEqual(revised.start_at, "2026-03-30T10:00:00+02:00")
        self.assertEqual(revised.end_at, "2026-03-30T11:30:00+02:00")


def capsule():
    return ArchiveCapsule("peripheral", "Synthetic curiosity", ["curiosity"], "peripheral", ["anchor"], ["adjacent"], 1, STAMP, STAMP,
        "2026-01-18T04:00:00+00:00", "Peripheral checkpoint expired", "The synthetic exploration found no applicable improvement. Research stopped at its fixed peripheral checkpoint; measured support remains absent.", [], [], ["No supported improvement"], ["Measurement missing"], ["Conditions differ"], [], [], 60, ["New direct contribution evidence or explicit user request"], user_notes="Private manual note α\n")


class ArchiveTests(unittest.TestCase):
    def setup_plan(self):
        drive = FakeDrive(); root = drive.create_folder(None, "instance", idempotency_key="root")
        ops = drive.create_folder(root.id, "operations", idempotency_key="ops"); inbox = drive.create_folder(root.id, "inbox", idempotency_key="inbox")
        writer = SafeWriter(drive, root.id, ops.id, inbox.id, instance_id="wp-test")
        def raw(name, content, mime):
            snapshot = drive.create_file(root.id, name, mime, content.encode(), idempotency_key=name)
            return Binding(name, snapshot.id, mime, root.id), snapshot
        page = WikiPage("page-peripheral", "Synthetic curiosity", "concept", [], ["peripheral"], STAMP, STAMP, STAMP)
        topic_file = raw("peripheral.md", render_page(page, capsule().user_notes), "text/markdown")
        registry_file = raw("TOPICS.md", registry().render(), "text/markdown")
        queued = item("automatic", "peripheral"); user = item("explicit", "peripheral", "user")
        queue_file = raw("research_queue.csv", write_queue([queued, user]), "text/csv")
        refresh = CalendarItem("retire-refresh", "research_refresh", "Synthetic legacy peripheral refresh", "2026-01-15", "", "", "UTC", "date", "scheduled", [page.id], [], "What changed?", 60, 60, {"frequency": "weekly"}, 0, "fixture", STAMP, schema_version=2, topic_id="peripheral", lineage_root_id="original-root")
        calendar_file = raw("calendar.csv", write_calendar([refresh]), "text/csv")
        index_file = raw("archive-index.json", "{}", "application/json")
        active_index_file = raw("index.md", update_index([page]), "text/markdown")
        admission = AdmissionGate(registry())
        admission.lineage[queued.id] = LineageRecord(queued.id, "peripheral", [], [queued.id], ["anchor"], 60, False, "old", "old")
        admission_file = raw("admission.json", json.dumps(admission.to_dict()), "application/json")
        plan = plan_archive(operation_id="archive-once", instance_id="wp-test", capsule=capsule(), topic_file=topic_file, registry_file=registry_file,
            queue_file=queue_file, calendar_file=calendar_file, index_file=index_file, active_index_file=active_index_file, admission_file=admission_file,
            inventory={"claims": [], "sources": [], "reports": ["historical-report"], "queue": [queued.id, user.id], "calendar": [refresh.id], "user_notes": ["page-peripheral"]},
            complete_inventory=True, unreported_record_ids=["finding"], represented_record_ids=[], deferred_record_ids=["finding"], retained_evidence_ids=[])
        return drive, writer, ops.id, plan

    def test_capsule_roundtrip_preserves_uncertainty_lineage_and_notes(self):
        original = capsule(); original.extra["unknown_field"] = {"note": "retained"}
        self.assertEqual(ArchiveCapsule.parse(original.render()).to_dict(), original.to_dict())

    def test_archive_every_checkpoint_resumes_fresh_writer_and_replay_preserves_later_edits(self):
        stages = ["CAPSULE_VERIFIED", "REDIRECTS_VERIFIED", "ACTIVE_INDEX_RECONCILED", "REGISTRY_ARCHIVED", "ADMISSION_RETIRED", "QUEUE_RETIRED", "CALENDAR_RETIRED"]
        for stage in stages:
            with self.subTest(stage=stage):
                drive, writer, ops, plan = self.setup_plan()
                with self.assertRaises(RuntimeError): execute_archive(writer, ops, plan, interrupt_after=stage)
                restored = SafeWriter(drive, writer.root_id, ops, writer.inbox_folder_id, instance_id="wp-test")
                result = resume_archive(restored, ops, plan.operation_id)
                self.assertEqual(result["status"], "COMPLETE")
                target = plan.mutations[0].binding.file_id
                actual = ArchiveCapsule.parse(drive.read_exact(target).content.decode())
                self.assertEqual(actual.user_notes, capsule().user_notes)
                queue_target = next(m.binding.file_id for m in plan.mutations if m.stage == "QUEUE_RETIRED")
                self.assertEqual([q.id for q in read_queue(drive.read_exact(queue_target).content.decode())], ["explicit"])
                registry_target = next(m.binding.file_id for m in plan.mutations if m.stage == "REGISTRY_ARCHIVED")
                self.assertEqual(TopicRegistry.parse(drive.read_exact(registry_target).content.decode()).by_id["peripheral"].lifecycle, "archived")
                admission_target = next(m.binding.file_id for m in plan.mutations if m.stage == "ADMISSION_RETIRED")
                self.assertTrue(json.loads(drive.read_exact(admission_target).content)["lineage"]["automatic"]["terminal"])
                calendar_target = next(m.binding.file_id for m in plan.mutations if m.stage == "CALENDAR_RETIRED")
                self.assertEqual(read_calendar(drive.read_exact(calendar_target).content.decode())[0].status, "cancelled")
                before = drive.read_exact(target)
                drive.replace_content(target, before.content + b"Later user note", expected_revision=before.revision, operation_id="manual-after")
                self.assertEqual(resume_archive(restored, ops, plan.operation_id), result)
                self.assertTrue(drive.read_exact(target).content.endswith(b"Later user note"))

    def test_archive_conflicting_manual_edit_preserved(self):
        drive, writer, ops, plan = self.setup_plan()
        before = plan.mutations[0].base
        drive.replace_content(before.id, before.content + b"new note", expected_revision=before.revision, operation_id="manual-before")
        with self.assertRaises(ConflictError): execute_archive(writer, ops, plan)
        self.assertTrue(drive.read_exact(before.id).content.endswith(b"new note"))

    def test_recovery_bulk_compacts_only_after_complete_retention_and_replay_survives(self):
        drive, writer, ops, plan = self.setup_plan()
        with self.assertRaises(RuntimeError): execute_archive(writer, ops, plan, interrupt_after="CAPSULE_VERIFIED")
        with self.assertRaises(ValidationError): compact_recovery_snapshot(writer, ops, plan.operation_id, now=datetime(2026, 2, 1, tzinfo=timezone.utc))
        complete = resume_archive(writer, ops, plan.operation_id)
        with self.assertRaises(ValidationError): compact_recovery_snapshot(writer, ops, plan.operation_id, now=datetime(2026, 1, 19, tzinfo=timezone.utc))
        result = compact_recovery_snapshot(writer, ops, plan.operation_id, now=datetime(2026, 2, 1, tzinfo=timezone.utc))
        self.assertTrue(result["compacted"])
        self.assertNotIn("mutations", result)
        self.assertIn("mutation_identities", result)
        self.assertEqual(resume_archive(writer, ops, plan.operation_id), complete)
        self.assertEqual(execute_archive(writer, ops, plan), complete)

    def test_large_archive_fetches_only_bounded_matching_capsules_and_never_reactivates(self):
        entries = [{"topic_id": f"topic-{i}", "file_id": f"file-{i}", "title": f"Synthetic subject{i}", "aliases": []} for i in range(2000)]
        partitions = build_archive_partitions(entries); fetched = []
        def fetch(identifier):
            fetched.append(identifier); record = capsule(); record.topic_id = "topic-120"; return record.render()
        result = retrieve_archives("subject120", lambda key: partitions.get(key, {}), fetch)
        self.assertEqual(fetched, ["file-120"])
        self.assertEqual(result["partitions_fetched"], 1)
        self.assertFalse(result["reactivated"])

    def test_disposable_dossier_compaction_preserves_qualifiers_and_coverage(self):
        record = {"schema_version": 2, "id": "research-one", "topic_ids": ["peripheral"], "status": "complete", "source_ids": ["source-one"], "findings": ["Long generated narrative"], "confidence": "uncertain", "uncertainties": ["Measurement missing"], "applicability": ["Only tested in different conditions"], "parent_ids": ["root"], "manual_extra": "retain user field"}
        with self.assertRaises(ValidationError):
            compact_research_dossier(json.dumps(record), capsule=capsule(), capsule_file_id="capsule-id", represented_record_ids=[], deferred_record_ids=[], retained_evidence_ids=["source-one"])
        compact = compact_research_dossier(json.dumps(record), capsule=capsule(), capsule_file_id="capsule-id", represented_record_ids=[], deferred_record_ids=[record["id"]], retained_evidence_ids=["source-one"])
        self.assertEqual(compact["findings"], [])
        for field in ("source_ids", "confidence", "uncertainties", "applicability", "parent_ids", "manual_extra"):
            self.assertEqual(compact[field], record[field])


if __name__ == "__main__":
    unittest.main()
