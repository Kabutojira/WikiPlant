"""Synthetic propositions only; these tests certify policy outcomes, not truth."""
from __future__ import annotations

import json
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timezone

from wikiplant.errors import ValidationError
from wikiplant.evidence import (ChallengeRecord, apply_assessment, assess_applicability,
                               assess_claim, challenge_followup_disposition,
                               claim_is_stale, compare_claims, independent_origin_count,
                               propagate_source_correction, source_origin_groups)
from wikiplant.maintenance import MaintenanceState, semantic_audit, structural_lint
from wikiplant.records import Claim, EvidenceLink, SourceRecord
from wikiplant.util import sha256_text
from wikiplant.wiki import WikiPage


STAMP = "2026-09-01T12:00:00+00:00"


def source(identifier="source-a", *, origin="experiment-a", source_type="measurement", parents=()):
    return SourceRecord(identifier, "https://synthetic.invalid/" + identifier,
                        "Synthetic measurement " + identifier, "Fictional laboratory", STAMP, None, STAMP,
                        None, source_type, ["Synthetic test output: 10 kPa at room temperature."], [],
                        evidence_origin_id=origin, derived_from_source_ids=list(parents),
                        inspected_passages={"Table 2, row 3": "Synthetic test output: 10 kPa at room temperature."},
                        retrieval_status="inspected")


def evidence(src, *, role="supports", quality="adequate", applicability="applicable", reproducible=False):
    return EvidenceLink(src.id, "Table 2, row 3", sha256_text(src.inspected_passages["Table 2, row 3"]),
                        role, STAMP, src.evidence_origin_id, "Controlled measurement", "direct",
                        "The inspected table measures this synthetic pressure under matching conditions.",
                        applicability, {"temperature": "room"}, method_quality=quality,
                        reproducible=reproducible, reproducibility_reason="Protocol and repeat measurements inspected" if reproducible else None)


def claim(identifier="claim-a", sources=None, links=None, **kwargs):
    return Claim(identifier, "Synthetic device", "Pressure", "10", None, None,
                 sources or [], "unknown", "reported", evidence_links=links or [],
                 conditions={"temperature": "room"}, units="kPa", **kwargs)


def page(identifier, claims):
    return WikiPage(identifier, "Synthetic " + identifier, "concept", [], ["anchor"], STAMP, STAMP,
                    "2026-09-10T00:00:00+00:00", source_ids=[s for c in claims for s in c.source_ids], claims=claims)


class EvidencePolicyTests(unittest.TestCase):
    def test_copies_unknown_origins_and_self_corroboration(self):
        original = source()
        copies = [source(f"copy-{i}", origin="invented-" + str(i), source_type="reporting", parents=[original.id]) for i in range(10)]
        archive = source("capsule", origin="fake-independent", source_type="archive", parents=[original.id])
        self.assertEqual(independent_origin_count([original, *copies, archive]), 1)
        self.assertEqual(source_origin_groups([original, archive])[archive.id], frozenset(["experiment-a"]))
        self.assertEqual(independent_origin_count([source("unknown-a", origin=None), source("unknown-b", origin=None)]), 0)
        self.assertEqual(independent_origin_count([source("self", source_type="wiki")]), 0)

    def test_nonexistent_uninspected_and_changed_passage_cannot_promote(self):
        src = source()
        item = claim(sources=[src.id], links=[evidence(src, reproducible=True)])
        for inventory in ([], [replace(src, inspected_passages={})], [replace(src, retrieval_status="uninspected")],
                          [replace(src, inspected_passages={"Table 2, row 3": "Changed output"})]):
            with self.subTest(inventory=inventory), self.assertRaises(ValidationError):
                assess_claim(item, inventory, rationale="Evaluate measurement")

    def test_announcement_performance_and_project_suitability_are_distinct(self):
        src = source(source_type="announcement")
        item = claim(sources=[src.id], links=[evidence(src)], claim_type="announcement")
        self.assertEqual(assess_claim(item, [src], rationale="The source establishes what was announced").status, "supported")
        performance = replace(item, claim_type="performance")
        self.assertEqual(assess_claim(performance, [src], rationale="Self report has no independent measurement").status, "reported")
        performance.evidence_links[0] = replace(performance.evidence_links[0], reproducible=True, reproducibility_reason="Repeatable test inspected")
        self.assertEqual(assess_claim(performance, [src], rationale="Measured protocol supplies reproducibility").status, "supported")
        suitability = assess_applicability(finding_id=item.id, project_id="synthetic-project", affected_assumption_ids=["pressure-assumption"],
                    evidence_conditions={"fluid": "water"}, project_conditions={"fluid": "oil"}, evidence_refs=[src.id + "#Table2"],
                    rationale="The result assumes water, while this project uses oil", next_step="Retain the assumption until an oil test exists")
        self.assertEqual(suitability.status, "not_applicable")
        self.assertIn("evidence=water; project=oil", suitability.unmet_conditions[0])

    def test_irrelevant_strong_source_has_no_promotion_weight(self):
        src = source()
        item = claim(sources=[src.id], links=[evidence(src, reproducible=True, applicability="not_applicable")])
        decision = assess_claim(item, [src], rationale="High quality result uses another operating regime")
        self.assertEqual(decision.status, "uncertain")
        self.assertEqual(decision.support_source_ids, ())

    def test_copied_aggregator_cannot_manufacture_direct_independent_measurement(self):
        first, second = source(), source("second", origin="experiment-b")
        copied = source("aggregator", origin="experiment-a", source_type="reporting", parents=[first.id, second.id])
        item = claim(sources=[copied.id], links=[evidence(copied, reproducible=True)])
        decision = assess_claim(item, [first, second, copied], rationale="Reading an aggregator is not an original measurement")
        self.assertEqual(decision.status, "uncertain")
        self.assertEqual(decision.independent_origins, ())

    def test_strong_counterevidence_revises_attractive_unsupported_thesis(self):
        rumor, measured = source("rumor", origin="press"), source("measured", origin="independent-measurement")
        item = claim(sources=[rumor.id, measured.id], links=[evidence(rumor, quality="limited"), evidence(measured, role="contradicts", reproducible=True)])
        decision = assess_claim(item, [rumor, measured], rationale="Independent measurements contradict the attractive marketing thesis")
        revised = apply_assessment(item, decision, assessed_at=STAMP, confidence="low")
        self.assertEqual(revised.status, "uncertain")
        self.assertEqual(decision.opposing_source_ids, (measured.id,))
        self.assertEqual(revised.status_history[0]["status"], "reported")

    def test_weak_criticism_does_not_force_false_balance(self):
        supported, weak = source(), source("anonymous-comment", origin="comment")
        item = claim(sources=[supported.id, weak.id], links=[evidence(supported, reproducible=True), evidence(weak, role="contradicts", quality="limited")])
        decision = assess_claim(item, [supported, weak], rationale="Controlled measurement outweighs an unsubstantiated comment")
        self.assertEqual(decision.status, "supported")
        self.assertEqual(decision.opposing_source_ids, ())
        self.assertTrue(any("limited" in reason for reason in decision.limitations))

    def test_complete_claim_metadata_and_unknown_fields_roundtrip(self):
        src = source()
        item = claim(sources=[src.id], links=[evidence(src, reproducible=True)], dependency_claim_ids=["earlier-claim"], predecessor_ids=["old"], extra_fields={"manual-annotation": "preserve"})
        item.evidence_links[0].extra_fields["instrument"] = "fictional-sensor"
        restored = Claim.from_dict(json.loads(json.dumps(item.to_dict())))
        self.assertEqual(restored, item)
        new_input = item.to_dict()
        new_input["future_valid_field"] = {"preserved": True}
        self.assertEqual(Claim.from_dict(new_input).extra_fields["future_valid_field"], {"preserved": True})

    def test_v2_supported_requires_more_than_source_id(self):
        item = claim(sources=["missing"])
        item.status = "supported"
        with self.assertRaises(ValidationError):
            item.validate()
        item.status = "verified"
        with self.assertRaises(ValidationError):
            item.validate()

    def test_correction_reaches_transitive_dependencies_and_replays(self):
        src = source()
        root = claim(sources=[src.id], links=[evidence(src, reproducible=True)])
        child = claim("conclusion", dependency_claim_ids=[root.id])
        downstream = claim("project-decision", dependency_claim_ids=[child.id])
        unaffected = claim("unrelated")
        changed, record = propagate_source_correction([root, child, downstream, unaffected], source_id=src.id,
                correction_ref="https://synthetic.invalid/correction/1", observed_at=STAMP, reason="Instrument calibration corrected")
        self.assertEqual(set(record.affected_claim_ids), {root.id, child.id, downstream.id})
        self.assertTrue(all(c.review_required for c in changed[:3]))
        self.assertIsNotNone(changed[0].evidence_links[0].invalidated_by)
        self.assertFalse(changed[3].review_required)
        repeated, replay = propagate_source_correction([Claim.from_dict(c.to_dict()) for c in changed], source_id=src.id,
                correction_ref=record.source_reference, observed_at=STAMP, reason=record.reason)
        self.assertEqual(repeated, changed)
        self.assertEqual(replay, record)
        self.assertEqual(json.loads(json.dumps(asdict(record)))["kind"], "correction")

    def test_origin_and_claim_dependency_cycles_are_rejected(self):
        with self.assertRaises(ValidationError):
            source_origin_groups([source("a", parents=["b"]), source("b", parents=["a"])])
        with self.assertRaises(ValidationError):
            propagate_source_correction([claim("a", dependency_claim_ids=["b"]), claim("b", dependency_claim_ids=["a"])],
                source_id="s", correction_ref="r", observed_at=STAMP, reason="correction")


class ChallengeTests(unittest.TestCase):
    def challenge(self, state):
        return ChallengeRecord("challenge-1", "claim-a", state, "Counter-check quality", "Measurement artifact explains result",
              ["Independent replication fails"], ["Synthetic pressure replication failures"], coverage="One planned counter-query")

    def test_unsearched_or_blocked_challenge_cannot_promote_consequential_claim(self):
        src = source()
        item = claim(sources=[src.id], links=[evidence(src, reproducible=True)], impact="consequential")
        for state in ("not_searched", "blocked"):
            counter = self.challenge(state)
            self.assertEqual(assess_claim(item, [src], rationale="Test consequential conclusion", challenge=counter).status, "reported")
        counter = self.challenge("searched")
        with self.assertRaises(ValidationError):
            counter.validate()
        counter.executed_queries = counter.planned_queries.copy()
        counter.successful_queries = counter.planned_queries.copy()
        counter.inspected_source_ids = [src.id]
        decision = assess_claim(item, [src], rationale="The bounded counter-check completed", challenge=counter)
        self.assertEqual(decision.status, "supported")
        self.assertTrue(any("not proof" in text for text in decision.limitations))
        self.assertEqual(ChallengeRecord.from_dict(json.loads(json.dumps(counter.to_dict()))), counter)

    def test_challenge_limits_and_peripheral_terminal_rule(self):
        counter = self.challenge("partial")
        counter.planned_queries = ["a", "b", "c"]
        counter.executed_queries = counter.planned_queries.copy()
        with self.assertRaises(ValidationError):
            counter.validate()
        self.assertEqual(challenge_followup_disposition(deeper_question="Replication?", topic_classification="peripheral"), "record_unresolved_terminal")
        self.assertEqual(challenge_followup_disposition(deeper_question="Replication?", topic_classification="adjacent"), "requires_shared_admission")


class SemanticMaintenanceTests(unittest.TestCase):
    def test_normalized_cross_page_units_conditions_time(self):
        left = claim("left")
        equivalent = replace(claim("equivalent"), subject=" SYNTHETIC device ", value="10000", units="Pa")
        different = replace(claim("different"), value="20")
        regime = replace(different, conditions={"temperature": "cold"})
        past = replace(different, valid_to="2025-01-01")
        current = replace(left, valid_from="2026-01-01")
        self.assertEqual(compare_claims(left, equivalent), "same")
        self.assertEqual(compare_claims(left, different), "contradiction")
        self.assertEqual(compare_claims(left, regime), "different_conditions")
        self.assertEqual(compare_claims(current, past), "temporal_change")
        state = MaintenanceState()
        findings, covered = semantic_audit([page("one", [left]), page("two", [different])], state,
                                now=datetime(2026, 9, 10, tzinfo=timezone.utc))
        conflicts = [f for f in findings if f.kind == "contradiction"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].page_ids, ["one", "two"])
        self.assertEqual(set(conflicts[0].claim_ids), {"left", "different"})
        self.assertEqual(set(covered), {"one", "two"})

    def test_real_claim_freshness_ignores_recent_page_touch(self):
        item = claim(assessed_at="2026-01-01T00:00:00+00:00", review_after_days=30)
        now = datetime(2026, 9, 10, tzinfo=timezone.utc)
        self.assertTrue(claim_is_stale(item, now))
        findings, _ = semantic_audit([page("recently-touched", [item])], MaintenanceState(), now=now)
        self.assertTrue(any(f.kind == "staleness" for f in findings))

    def test_risk_priority_rotation_and_reconstruction_bound_coverage(self):
        pages = [page(f"p-{i:03}", [claim(f"c-{i}", assessed_at=STAMP)]) for i in range(12)]
        pages[-1].claims[0].impact = "consequential"
        state = MaintenanceState()
        now = datetime(2026, 9, 10, tzinfo=timezone.utc)
        _, first = semantic_audit(pages, state, max_pages=2, now=now)
        self.assertIn("p-011", first)
        covered = set(first)
        for _ in range(12):
            state = MaintenanceState.from_dict(json.loads(json.dumps(state.to_dict())))
            _, current = semantic_audit(pages, state, max_pages=2, now=now)
            covered.update(current)
            self.assertEqual(len(current), 2)
            self.assertFalse(state.semantic_coverage_complete)
        self.assertEqual(len(covered), len(pages))
        self.assertEqual(state.inventory_total, 12)
        self.assertTrue(state.coverage_limits)

    def test_incomplete_inventory_does_not_invent_broken_links(self):
        item = page("one", [])
        item.relationship_ids = ["not-fetched"]
        self.assertFalse(any(f.kind == "broken_link" for f in structural_lint([item], inventory_complete=False)))
        state = MaintenanceState()
        semantic_audit([item], state, inventory_complete=False)
        self.assertFalse(state.semantic_coverage_complete)
        self.assertFalse(state.inventory_complete)


if __name__ == "__main__":
    unittest.main()
