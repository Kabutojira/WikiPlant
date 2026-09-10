from __future__ import annotations

import json
import unittest

from wikiplant.authorization import UserAuthorization, request_digest
from wikiplant.errors import ValidationError
from wikiplant.migrations import migrate_instance
from wikiplant.migrations.v1_to_v2 import MARKER
from wikiplant.topics import TopicRegistry
from wikiplant.util import pretty_json
from wikiplant.wiki import parse_page
from wikiplant.yamlio import dumps, loads


class MigrationTests(unittest.TestCase):
    def fixture(self):
        config = {"schema_version": 1, "instance": {"id": "wp-test", "timezone": "Asia/Tokyo", "language": "ja"},
                  "primary_topics": [{"id": "t1", "name": "Synthetic materials", "aliases": ["fixture"]}],
                  "queue": {"normal_daily_attempts": 5, "urgent_daily_attempts_total": 10},
                  "user_customization": {"keep": ["exact", "values"]}}
        meta = {"schema_version": 1, "id": "p1", "title": "Legacy fixture", "type": "concept", "aliases": [],
                "topic_ids": ["t1"], "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-09-09T00:00:00+00:00",
                "last_checked_at": None, "source_ids": ["s1"], "manual_metadata": {"keep": True}}
        page = "---json\n" + pretty_json(meta) + "---\n\n# Legacy fixture\n\n<!-- wikiplant:managed:start -->\n## Claims\n- [verified; high] synthetic claim (sources: s1)\n<!-- wikiplant:managed:end -->\n\n## User notes\n\n  私のメモ\nKeep trailing space  \n"
        files = {"config.yml": dumps(config).encode(), "data/wiki/concepts/p1.md": page.encode(),
                 "data/research_queue.csv": b'priority,id,topic_id,attempts,expansion_priority,parent_ids\n0,q1,t1,3,80,"[""q0""]"\n',
                 "data/calendar.csv": b"id,kind,origin_ref\ne1,research_refresh,occurrence-9\n",
                 "data/state/runs/budget.json": b'{"slots":[1,2,3,4,5],"originating_date":"2026-09-09"}',
                 "data/reports/yesterday.md": b"Historical report, unchanged",
                 "data/sources/s1.json": b'{"id":"s1","canonical_ref":"https://example.invalid/synthetic"}'}
        auth = UserAuthorization("original-turn", "wp-test", "track", "t1", request_digest("track synthetic materials"), True, "original explicit tracking").to_dict()
        return files, {"t1": {"source_role": "approved_configuration_history", "approval_record_ref": "setup-record", "original_authorization": auth}}

    def migrate(self, files, history):
        return migrate_instance(files, instance_id="wp-test", authorization_history=history, migrated_at="2026-09-10T00:00:00+00:00",
                                new_defaults={"schema_version": 2, "queue": {"normal_daily_attempts": 5}, "topic_governance": {"max_active_adjacent_topics": 30}})

    def test_lossless_migration_replay_counts_and_old_reader_gate(self):
        files, history = self.fixture()
        result = self.migrate(files, history)
        self.assertTrue(result.ready_for_activation)
        restored = self.migrate(result.files, history)
        self.assertEqual(restored.files, result.files)
        self.assertEqual(restored.changed_paths, [])
        self.assertEqual(restored.created_paths, [])
        self.assertEqual(result.report["counts"]["before_files"], len(files))
        self.assertEqual(result.report["counts"]["after_files"], len(result.files))
        config = loads(result.files["config.yml"].decode())
        self.assertEqual(config["primary_topic_ids"], ["t1"])
        self.assertNotIn("primary_topics", config)
        self.assertEqual(config["instance"]["timezone"], "Asia/Tokyo")
        page, notes = parse_page(result.files["data/wiki/concepts/p1.md"].decode())
        self.assertEqual(notes, "  私のメモ\nKeep trailing space  \n")
        self.assertIn("[verified; high]", page.extra_fields["legacy_managed_content"])
        self.assertEqual(page.claims, [])  # v1 lost IDs; no invented replacement identity.
        self.assertTrue(page.extra_fields["manual_metadata"]["keep"])
        for path in files:
            if path not in result.changed_paths:
                self.assertEqual(result.files[path], files[path])
        self.assertIn("incompatible", result.report["compatibility"]["old_reader"])

    def test_missing_anchor_authorization_is_provisional_and_blocks_activation(self):
        files, _ = self.fixture()
        result = self.migrate(files, {})
        self.assertFalse(result.ready_for_activation)
        registry = TopicRegistry.parse(result.files["data/TOPICS.md"].decode())
        self.assertEqual(registry.by_id["t1"].lifecycle, "provisional")
        self.assertFalse(registry.by_id["t1"].may_spawn_research)
        self.assertEqual(result.report["unresolved_topic_ids"], ["t1"])
        self.assertEqual(result.files["data/research_queue.csv"], files["data/research_queue.csv"])

    def test_structured_legacy_claim_retains_identity_and_downgrades_confidence_status(self):
        files, history = self.fixture()
        claim = {"id": "claim-preserved", "subject": "fixture", "predicate": "measurement", "value": "12", "valid_from": None,
                 "valid_to": None, "source_ids": ["s1"], "confidence": "high", "status": "verified", "unknown_custom": "keep"}
        files["data/research/r1.json"] = pretty_json({"claims": [claim], "selected_followup_ids": ["old-child"], "attempt_id": "original-attempt"}).encode()
        result = self.migrate(files, history)
        record = json.loads(result.files["data/research/r1.json"])
        migrated = record["claims"][0]
        self.assertEqual(migrated["id"], "claim-preserved")
        self.assertEqual(migrated["status"], "uncertain")
        self.assertEqual(migrated["status_history"][0]["confidence"], "high")
        self.assertIsNone(migrated["status_history"][0]["assessed_at"])
        self.assertNotIn("evidence_links", migrated)
        self.assertEqual(migrated["unknown_custom"], "keep")
        self.assertEqual(record["attempt_id"], "original-attempt")
        self.assertEqual(result.report["claim_revalidation_ids"], ["claim-preserved"])

    def test_marker_is_not_cross_instance_authority(self):
        files, history = self.fixture()
        result = self.migrate(files, history)
        bad = json.loads(result.files[MARKER])
        bad["instance_id"] = "another"
        result.files[MARKER] = pretty_json(bad).encode()
        with self.assertRaises(ValidationError):
            self.migrate(result.files, history)


if __name__ == "__main__":
    unittest.main()
