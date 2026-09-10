from __future__ import annotations

import json
import unittest
from dataclasses import asdict

from wikiplant.evidence import correction_summary, propagate_source_correction
from wikiplant.fake_drive import FakeDrive
from wikiplant.records import Claim
from wikiplant.reporting import ReportPublisher, pending_evidence, render_daily_report
from wikiplant.storage import create_artifact


class CorrectionReportPersistenceTests(unittest.TestCase):
    def test_correction_survives_reconstruction_and_is_in_saved_report(self):
        drive = FakeDrive()
        root = drive.create_folder(None, "Synthetic correction sandbox", idempotency_key="correction-root")
        reports = drive.create_folder(root.id, "reports", idempotency_key="reports")
        state_folder = drive.create_folder(root.id, "state", idempotency_key="state")
        source_claim = Claim("source-claim", "Synthetic material", "strength", "10", None, None, ["synthetic-source"], "unknown", "reported")
        conclusion = Claim("dependent-decision", "Synthetic project", "choice", "candidate", None, None, [], "unknown", "hypothesis", dependency_claim_ids=[source_claim.id])
        updated, correction = propagate_source_correction([source_claim, conclusion], source_id="synthetic-source",
                correction_ref="https://synthetic.invalid/correction/1", observed_at="2026-09-10T10:00:00+00:00", reason="A calibration correction invalidates the old measurement.")
        persisted = create_artifact(drive, root.id, state_folder.id, correction.id + ".json", asdict(correction), correction.id)
        claims_artifact = create_artifact(drive, root.id, state_folder.id, "corrected-claims.json", {"claims": [c.to_dict() for c in updated]}, "corrected-claims")
        reconstructed = [Claim.from_dict(c) for c in json.loads(drive.read_exact(claims_artifact.id).content)["claims"]]
        self.assertTrue(all(c.review_required for c in reconstructed))
        summary = correction_summary(correction, artifact_reference=persisted.id, prior_report_refs=["synthetic-prior-report"])
        markdown, state = render_daily_report(local_date="2026-09-10", coverage_window="unrepresented completed records", evidence=[summary],
                events=[], pending_queue=["Revalidate affected claim"], operational_gaps=[], report_key="synthetic-daily")
        saved = ReportPublisher(drive, root.id, reports.id, state_folder.id).save(markdown, state)
        # A fresh helper instance verifies the actual stored Markdown and coverage.
        report, restored = ReportPublisher(drive, root.id, reports.id, state_folder.id).load("synthetic-daily")
        self.assertEqual(report, drive.read_exact(saved.report_reference).content.decode())
        self.assertIn(correction.id, report)
        self.assertIn("dependent-decision", report)
        self.assertIn(persisted.id, report)
        self.assertIn("synthetic-prior-report", report)
        self.assertEqual(pending_evidence([summary], [restored]), [])


if __name__ == "__main__":
    unittest.main()
