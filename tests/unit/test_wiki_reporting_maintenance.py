from __future__ import annotations

import unittest

from wikiplant.errors import CapabilityError, ValidationError
from wikiplant.authorization import UserAuthorization, request_digest
from wikiplant.intake import InstanceProfile, observed_receipt, resolve_instance, route_intent, routing_profile_status, select_relevant_pages
from wikiplant.maintenance import MaintenanceState, semantic_audit, structural_lint
from wikiplant.records import Claim, DeliveryState, SourceRecord
from wikiplant.reporting import EvidenceSummary, pending_evidence, reconcile_delivery, render_daily_report
from wikiplant.upgrades import InstanceImage, apply_upgrade, available_update, export_private_raw
from wikiplant.wiki import WikiPage, applicability_analysis, append_change_log, claim_relationship, independent_source_count, render_page, replace_managed_section


def claim(identifier: str, value: str, *, start=None, end=None, status="supported") -> Claim:
    # Historical v1 fixture: source IDs alone do not satisfy the v2 promotion policy.
    return Claim(identifier, "synthetic pump", "rated pressure", value, start, end, ["source-1"] if status != "user_note" else [], "medium", status, schema_version=1)


def page(identifier="page-1", claims=None, page_type="concept") -> WikiPage:
    return WikiPage(
        identifier, "Synthetic page", page_type, ["fixture"], ["topic-a"], "2026-01-01T00:00:00+00:00",
        "2026-01-15T00:00:00+00:00", None, source_ids=["source-1"], claims=claims or [],
    )


class WikiTests(unittest.TestCase):
    def test_manual_text_preserved_across_managed_update(self):
        first = render_page(page(claims=[claim("c1", "10")]), "Owner note: preserve exactly.")
        second = render_page(page(claims=[claim("c2", "12")]), "ignored replacement note")
        merged = replace_managed_section(first, second)
        self.assertIn("Owner note: preserve exactly.", merged)
        self.assertIn("rated pressure: 12", merged)
        self.assertNotIn("ignored replacement note", merged)
        log = append_change_log("# Wiki change log\n", timestamp="2026-01-15T00:00:00+00:00", operation_id="op-1", page_ids=["page-1"], summary="Updated evidence")
        self.assertIn("op-1", log)

    def test_temporal_change_is_not_contradiction(self):
        old = claim("old", "10", end="2025-12-31")
        new = claim("new", "12", start="2026-01-01")
        overlap = claim("overlap", "9")
        self.assertEqual(claim_relationship(old, new), "temporal_change")
        self.assertEqual(claim_relationship(new, overlap), "contradiction")

    def test_user_note_not_upgraded_to_evidence(self):
        note = claim("note", "maybe 20", status="user_note")
        note.validate()
        unsupported = claim("bad", "20")
        unsupported.source_ids = []
        with self.assertRaises(ValidationError):
            unsupported.validate()

    def test_syndication_not_independent_confirmation(self):
        sources = [
            SourceRecord("s1", "https://example.invalid/original", "Original", None, None, None, "2026-01-15T00:00:00+00:00", None, "primary", [], [], "release-x"),
            SourceRecord("s2", "https://mirror.invalid/story", "Copy", None, None, None, "2026-01-15T00:00:00+00:00", None, "reporting", [], [], "release-x"),
        ]
        self.assertEqual(independent_source_count(sources), 1)

    def test_synthetic_breakthrough_only_proposes_validation(self):
        project = page("pump-project", page_type="project")
        project.constraints = ["maximum cost", "minimum reliability"]
        project.assumptions = ["current actuator efficiency"]
        analysis = applicability_analysis("A fictional fluid-dynamics breakthrough was reported", project)
        self.assertTrue(any("Check constraint" in line for line in analysis))
        self.assertTrue(any("Revalidate assumption" in line for line in analysis))
        self.assertTrue(any("No project performance improvement is verified" in line for line in analysis))


class RoutingAndReportTests(unittest.TestCase):
    def test_passive_mention_is_read_only_and_save_is_explicit(self):
        self.assertFalse(route_intent("Unitree has a new model").writes)
        self.assertFalse(route_intent("Save this note in my wiki").writes)  # Routing proposes; host turn grant authorizes.
        def authorized(text, operation):
            grant = UserAuthorization("synthetic-turn", "wp-test", operation, "note", request_digest(text), True, "Explicit directive")
            return route_intent(text, authorization=grant.to_dict(), instance_id="wp-test", target="note")
        self.assertTrue(authorized("Save this note in my wiki", "save").writes)
        self.assertEqual(route_intent("Add this entity to my wiki").operation, "add")
        self.assertTrue(route_intent("What changed since yesterday?").requires_external_evidence)
        self.assertEqual(route_intent("Show installation status").operation, "status")
        self.assertEqual(observed_receipt(authorized("Investigate this", "investigate"), durable_reference="q-1", canonical_merged=True), "QUEUED")
        self.assertEqual(observed_receipt(authorized("Save this", "save"), durable_reference="cmd-1"), "ACCEPTED_PENDING_MERGE")

    def test_bounded_retrieval_and_host_metadata_status(self):
        pages = [
            {"id": "a", "title": "Alpha", "aliases": ["shared"], "relationships": []},
            {"id": "b", "title": "Beta", "aliases": [], "relationships": ["alpha"]},
            {"id": "c", "title": "Gamma", "aliases": [], "relationships": []},
        ]
        self.assertEqual([p["id"] for p in select_relevant_pages("alpha", pages, limit=1)], ["a"])
        self.assertEqual(routing_profile_status(2, 1), "pending_host_update")

    def test_overlapping_instances_ask_once_and_explicit_wins(self):
        profiles = [
            InstanceProfile("wp-a", "Alpha", ("shared topic", "optics")),
            InstanceProfile("wp-b", "Beta", ("shared topic", "biology")),
        ]
        ambiguous = resolve_instance("Save this shared topic note", profiles)
        self.assertIsNone(ambiguous.instance_id)
        self.assertEqual(ambiguous.ambiguous_ids, ("wp-a", "wp-b"))
        explicit = resolve_instance("This sounds like biology", profiles, explicit_instance_id="wp-a")
        self.assertEqual(explicit.instance_id, "wp-a")

    def test_report_includes_all_classes_once_and_importance_ranks(self):
        records = [
            EvidenceSummary("low", "research", "Routine", "minor", 10, "high"),
            EvidenceSummary("major", "research", "Major", "material", 95, "medium", implications=["review project"], source_refs=["src-major"]),
            EvidenceSummary("monitor", "monitoring", "Topic check", "no material update", 20, "medium", limitations=["two sources checked"]),
            EvidenceSummary("maint", "maintenance", "Audit", "one gap", 30, "high"),
        ]
        text, state = render_daily_report(local_date="2026-01-15", coverage_window="24h", evidence=records, events=["Event today"], pending_queue=["Urgent overflow"], operational_gaps=[], report_key="daily-1")
        self.assertLess(text.index("Major: material"), text.index("Topic check: no material update"))
        self.assertIn("Event today", text)
        self.assertIn("Urgent overflow", text)
        self.assertEqual(len(pending_evidence(records, [state])), 4)  # Rendering is not persistence.
        state.saved = True
        self.assertEqual(pending_evidence(records, [state]), [])

    def test_delivery_states_are_separate(self):
        delivery = DeliveryState("report-1")
        with self.assertRaises(ValidationError):
            delivery.mark_published()
        delivery.mark_saved()
        delivery.mark_published()
        self.assertTrue(delivery.result_published)
        self.assertIsNone(delivery.notification_observed)

    def test_publication_retry_does_not_resave_or_touch_research(self):
        delivery = DeliveryState("report-1")
        calls = {"save": 0, "publish": 0}
        def save():
            calls["save"] += 1
        def fail_publish():
            calls["publish"] += 1
            raise RuntimeError("host result unavailable")
        with self.assertRaises(RuntimeError):
            reconcile_delivery(delivery, save, fail_publish)
        self.assertTrue(delivery.saved)
        reconcile_delivery(delivery, save, lambda: calls.__setitem__("publish", calls["publish"] + 1))
        self.assertEqual(calls, {"save": 1, "publish": 2})


class MaintenanceAndUpgradeTests(unittest.TestCase):
    def test_structural_and_rotating_semantic_audit(self):
        broken = page("broken", [claim("x", "1"), claim("y", "2")])
        broken.relationship_ids = ["missing"]
        other = page("other")
        other.aliases = ["Synthetic page"]
        findings = structural_lint([broken, other])
        self.assertTrue(any(f.kind == "broken_link" for f in findings))
        self.assertTrue(any(f.kind == "duplicate_topic" for f in findings))
        state = MaintenanceState()
        semantic, covered = semantic_audit([broken, other], state, max_pages=1)
        self.assertEqual(len(covered), 1)
        semantic2, covered2 = semantic_audit([broken, other], state, max_pages=1)
        self.assertNotEqual(covered, covered2)
        repeated, _ = semantic_audit([broken, other], state, max_pages=2)
        keys = [finding.key for finding in semantic + semantic2 + repeated]
        self.assertEqual(len(keys), len(set(keys)))

    def test_update_check_does_not_adopt_and_upgrade_preserves_data(self):
        image = InstanceImage("wp-test", "1.0", {"code": b"old"}, {"notes": b"keep"}, {"scope": "keep"}, "1.0", "1.0")
        check = available_update("1.0.0", "1.1.0")
        self.assertFalse(check["adopted"])
        with self.assertRaises(CapabilityError):
            apply_upgrade(image, "1.1", {"code": b"new"}, explicit_user_request=True)
        self.assertEqual(image.runtime_files["code"], b"old")
        self.assertEqual(image.data_files["notes"], b"keep")
        self.assertFalse(image.paused)

    def test_failed_upgrade_restores_runtime_without_deleting_new_data(self):
        image = InstanceImage("wp-test", "1.0", {"code": b"old"}, {"new-research": b"keep"}, {}, "1.0", "1.0")
        with self.assertRaises(CapabilityError):
            apply_upgrade(image, "1.1", {"code": b"new"}, explicit_user_request=True, fail_stage="runtime_written")
        self.assertEqual(image.runtime_files["code"], b"old")
        self.assertEqual(image.data_files["new-research"], b"keep")
        self.assertEqual(image.skill_binding_release, "1.0")

    def test_private_export_is_detached(self):
        image = InstanceImage("wp-test", "1.0", {"code": b"old"}, {"notes": b"keep"}, {}, "1.0", "1.0")
        exported = export_private_raw(image)
        exported["data_files"]["notes"] = b"changed"
        self.assertEqual(image.data_files["notes"], b"keep")


if __name__ == "__main__":
    unittest.main()
