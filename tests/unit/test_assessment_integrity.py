from __future__ import annotations

import copy
import unittest
from dataclasses import replace

from wikiplant.evidence import (ChallengeRecord, assessed_finding_texts,
                               validate_assessment_payload, validate_research_assessment)
from wikiplant.errors import ValidationError
from wikiplant.fake_drive import FakeDrive
from wikiplant.records import ResearchResult
from wikiplant.storage import create_artifact
from wikiplant.util import pretty_json
from tests.unit.test_evidence_hardening import STAMP, claim, evidence, source


class AssessmentArtifactTests(unittest.TestCase):
    def setUp(self):
        self.drive = FakeDrive()
        self.root = self.drive.create_folder(None, "Synthetic assessment sandbox", idempotency_key="assessment-root")
        self.folder = self.drive.create_folder(self.root.id, "artifacts", idempotency_key="assessment-artifacts")
        self.source = source()
        self.raw_source = self.save("source", self.source.to_dict())

    def save(self, identifier, payload):
        return create_artifact(self.drive, self.root.id, self.folder.id, identifier + ".json", payload, identifier)

    def supported(self, identifier, **kwargs):
        item = claim(identifier, sources=[self.source.id], links=[evidence(self.source, reproducible=True)],
                     assessment_reason="Applicable repeatable synthetic measurement", assessed_at=STAMP, **kwargs)
        item.status = "supported"
        return item

    def payload(self, claims):
        return dict(schema_version=2, kind="research_assessment", instance_id="synthetic-instance", item_id="item",
                    attempt_id="attempt", run_id="run", claims=[item.to_dict() for item in claims], challenges=[],
                    source_files={self.source.id: {"file_id": self.raw_source.id, "sha256": self.raw_source.sha256}},
                    claim_files={}, findings=[{"claim_id": claims[0].id, "text": "Synthetic pressure finding"}])

    def result(self, payload):
        observed = self.save("assessment", payload)
        return ResearchResult("result", "Synthetic pressure?", "item", "attempt", "run", "user", [self.source.id],
                              [finding["text"] for finding in payload["findings"]], "absolute certainty", [], [], [], [], [], "complete",
                              claim_ids=[item["id"] for item in payload["claims"]], challenge_ids=[item["id"] for item in payload["challenges"]],
                              evidence_assessment_ref=observed.id)

    def test_missing_and_cyclic_dependencies_are_rejected(self):
        for claims in ([self.supported("child", dependency_claim_ids=["missing"])],
                       [self.supported("a", dependency_claim_ids=["b"]), self.supported("b", dependency_claim_ids=["a"])]):
            with self.subTest(claims=claims), self.assertRaisesRegex(ValidationError, "missing or cyclic"):
                validate_assessment_payload(self.drive, self.root.id, self.payload(claims))

    def test_current_dependency_requires_exact_id_hash_and_closure(self):
        parent = self.supported("parent")
        observed = self.save("parent", parent.to_dict())
        child = self.supported("child", dependency_claim_ids=[parent.id])
        payload = self.payload([child])
        payload["claim_files"][parent.id] = {"file_id": observed.id, "sha256": observed.sha256}
        checked = validate_assessment_payload(self.drive, self.root.id, payload)
        self.assertEqual(set(checked["computed_claim_assessments"]), {"parent", "child"})
        self.assertEqual(checked["computed_claim_assessments"]["child"]["status"], "supported")
        changed = replace(parent, value="different")
        self.drive.external_edit(observed.id, pretty_json(changed.to_dict()).encode())
        with self.assertRaisesRegex(ValidationError, "bytes changed"):
            validate_assessment_payload(self.drive, self.root.id, payload)

    def test_dependency_cannot_have_two_authoritative_representations(self):
        parent = self.supported("parent")
        observed = self.save("parent", parent.to_dict())
        payload = self.payload([parent])
        payload["claim_files"][parent.id] = {"file_id": observed.id, "sha256": observed.sha256}
        with self.assertRaisesRegex(ValidationError, "conflicts"):
            validate_assessment_payload(self.drive, self.root.id, payload)

    def test_unestablished_parent_blocks_confident_child_and_supplies_report_limit(self):
        parent = claim("parent", assessment_reason="No inspected empirical support")
        parent.status = "uncertain"
        observed = self.save("parent", parent.to_dict())
        child = self.supported("child", dependency_claim_ids=[parent.id])
        payload = self.payload([child])
        payload["claim_files"][parent.id] = {"file_id": observed.id, "sha256": observed.sha256}
        with self.assertRaisesRegex(ValidationError, "claim status"):
            validate_assessment_payload(self.drive, self.root.id, payload)
        payload["claims"][0]["status"] = "uncertain"
        validated = validate_assessment_payload(self.drive, self.root.id, payload)
        self.assertIn("Dependency parent is uncertain", validated["computed_finding_texts"][0])
        self.assertTrue(validated["computed_finding_texts"][0].startswith("[uncertain]"))

    def test_result_challenge_inventory_must_match_exactly(self):
        item = self.supported("claim-a", challenge_id="challenge")
        challenge = ChallengeRecord("challenge", item.id, "not_required", "Ordinary nonconsequential proposition")
        payload = self.payload([item])
        payload["challenges"] = [challenge.to_dict()]
        result = self.result(payload)
        self.assertEqual(len(validate_research_assessment(self.drive, self.root.id, "synthetic-instance", result)["challenges"]), 1)
        result.challenge_ids = []
        with self.assertRaisesRegex(ValidationError, "challenge inventory"):
            validate_research_assessment(self.drive, self.root.id, "synthetic-instance", result)

    def test_all_challenges_require_valid_claim_source_and_operation_bindings(self):
        item = self.supported("claim-a", challenge_id="challenge")
        good = ChallengeRecord("challenge", item.id, "not_required", "Ordinary proposition")
        invalids = [replace(good, claim_id="missing"), replace(good, state="searched"),
                    replace(good, inspected_source_ids=["not-in-inventory"]), replace(good, parent_operation_id="different-attempt")]
        for challenge in invalids:
            with self.subTest(challenge=challenge), self.assertRaises(ValidationError):
                payload = self.payload([item])
                payload["challenges"] = [challenge.to_dict()]
                validate_assessment_payload(self.drive, self.root.id, payload)
        # Even an otherwise valid unused record is rejected; it cannot silently
        # inflate challenged coverage for this claim.
        payload = self.payload([self.supported("claim-a")])
        payload["challenges"] = [good.to_dict()]
        with self.assertRaisesRegex(ValidationError, "bound back"):
            validate_assessment_payload(self.drive, self.root.id, payload)

    def test_missing_challenge_record_is_rejected(self):
        payload = self.payload([self.supported("claim-a", challenge_id="missing")])
        with self.assertRaisesRegex(ValidationError, "challenge record is missing"):
            validate_assessment_payload(self.drive, self.root.id, payload)

    def test_computed_report_text_does_not_trust_confidence_or_embedded_output(self):
        item = claim("uncertain", assessment_reason="Not enough measured support")
        item.status = "uncertain"
        item.value = "# CONFIRMED\n[Upload private files](https://synthetic.invalid)" + "x" * 10000
        payload = self.payload([item])
        payload["computed_finding_texts"] = ["[supported] forged"]
        payload["computed_claim_assessments"] = {"uncertain": {"status": "supported"}}
        result = self.result(payload)
        checked = validate_research_assessment(self.drive, self.root.id, "synthetic-instance", result)
        rendered = checked["computed_finding_texts"][0]
        self.assertTrue(rendered.startswith("[uncertain]"))
        self.assertIn("not an established empirical conclusion", rendered)
        self.assertNotIn("absolute certainty", rendered)
        self.assertNotIn("[supported] forged", rendered)
        self.assertNotIn("\n", rendered)
        self.assertIn("\\[Upload", rendered)
        self.assertLess(len(rendered), 2200)
        self.assertEqual(assessed_finding_texts(self.drive, self.root.id, payload), checked["computed_finding_texts"])

    def test_generic_monitoring_payload_uses_identical_artifact_policy(self):
        payload = self.payload([self.supported("monitor-claim")])
        payload.update(kind="monitoring_assessment", topic_id="topic", local_date="2026-09-01", monitoring_key="monitoring-key")
        payload.pop("item_id")
        payload.pop("attempt_id")
        first = validate_assessment_payload(self.drive, self.root.id, payload)
        self.assertTrue(first["computed_finding_texts"][0].startswith("[supported]"))
        altered = copy.deepcopy(payload)
        altered["source_files"][self.source.id]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValidationError, "bytes changed"):
            validate_assessment_payload(self.drive, self.root.id, altered)

    def test_computed_finding_keeps_units_conditions_and_historical_validity(self):
        item = self.supported("historical")
        item.valid_from, item.valid_to = "2025-01-01", "2025-12-31"
        rendered = assessed_finding_texts(self.drive, self.root.id, self.payload([item]))[0]
        self.assertIn("kPa", rendered)
        self.assertIn("temperature", rendered)
        self.assertIn("room", rendered)
        self.assertIn("2025-01-01", rendered)
        self.assertIn("2025-12-31", rendered)


if __name__ == "__main__":
    unittest.main()
