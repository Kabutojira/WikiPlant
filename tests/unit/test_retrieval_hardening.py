from __future__ import annotations

import json
import unittest

from wikiplant.errors import ValidationError
from wikiplant.intake import select_relevant_pages
from wikiplant.retrieval import SemanticSelection, select_active_pages


class RetrievalHardeningTests(unittest.TestCase):
    def test_existing_graph_connects_a_distant_concept_to_a_project(self):
        pages = [
            {"id": "pump", "title": "Synthetic pump cavitation", "relationship_ids": ["surface-physics"]},
            {"id": "surface-physics", "title": "Wetting energetics", "claims": [{"id": "meniscus", "subject": "surface", "value": "energy constraint"}]},
            {"id": "project", "title": "Prototype inlet", "dependencies": ["pump"]},
            {"id": "unrelated", "title": "Synthetic stellar dynamics"},
        ]
        result = select_active_pages("pump cavitation", pages, limit=3)
        self.assertEqual({page["id"] for page in result.pages}, {"pump", "surface-physics", "project"})
        distant = next(item for item in result.decisions if item["page_id"] == "surface-physics")
        self.assertEqual(distant["reasons"][0]["kind"], "relationship")
        self.assertEqual(distant["reasons"][0]["via_page_id"], "pump")

    def test_semantic_reason_and_claim_identity_are_recorded_without_new_authority(self):
        pages = [{"id": "physics", "title": "Wetting energetics", "claim_ids": ["surface-energy"]}]
        reason = SemanticSelection("physics", "Surface energy affects the inlet pressure assumption through the meniscus condition", ("surface-energy",))
        log = []
        self.assertEqual(select_relevant_pages("cavitation", pages, semantic_selections=[reason], retrieval_log=log), pages)
        serialized = json.loads(json.dumps(log))
        decision = serialized[0]["decisions"][0]["reasons"][0]
        self.assertEqual(decision["kind"], "semantic")
        self.assertEqual(decision["supporting_claim_ids"], ["surface-energy"])
        self.assertIn("inlet pressure", decision["reason"])
        with self.assertRaises(ValidationError):
            select_active_pages("cavitation", pages, semantic_selections=[SemanticSelection("physics", "Guess", ("nonexistent",))])

    def test_large_index_fetches_only_bounded_active_selection_and_excludes_archive(self):
        pages = [{"id": f"active-{i}", "title": f"Synthetic active result {i}"} for i in range(100)]
        pages.extend({"id": f"archived-{i}", "title": "Synthetic active result", "lifecycle": "archived"} for i in range(1000))
        result = select_active_pages("synthetic result", pages, limit=8)
        self.assertEqual(len(result.pages), 8)
        self.assertEqual(result.considered_active_summaries, 100)
        self.assertEqual(result.excluded_archived_summaries, 1000)
        self.assertTrue(all(p["id"].startswith("active-") for p in result.pages))
        self.assertTrue(all(p["lifecycle"] == "archived" for p in pages[100:]))
        self.assertIn("does not reactivate", result.coverage)

    def test_index_reorder_does_not_change_ties_or_create_unknown_relationships(self):
        pages = [{"id": "b", "title": "Synthetic result", "relationships": ["unknown"]}, {"id": "a", "title": "Synthetic result"}]
        self.assertEqual([p["id"] for p in select_active_pages("result", pages).pages], ["a", "b"])
        self.assertEqual(select_active_pages("result", pages).pages, select_active_pages("result", reversed(pages)).pages)
        with self.assertRaises(ValidationError):
            select_active_pages("result", [pages[0], pages[0]])
        with self.assertRaises(ValidationError):
            select_active_pages("result", pages, limit=1, max_candidates=1)


if __name__ == "__main__":
    unittest.main()
