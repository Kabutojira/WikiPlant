import json
import unittest
from pathlib import Path

from wikiplant.queue import QUEUE_HEADER
from wikiplant.util import sha256_bytes
from wikiplant.wiki import parse_page, render_page


ROOT = Path(__file__).resolve().parents[2]


class ScaffoldContractTests(unittest.TestCase):
    def test_page_template_uses_lossless_current_reader(self):
        page, notes = parse_page((ROOT / "schemas/templates/wiki-page.md").read_text())
        second, second_notes = parse_page(render_page(page, notes))
        self.assertEqual(page, second)
        self.assertEqual(notes, second_notes)
        self.assertEqual(page.claims, [])

    def test_every_canonical_queue_column_has_a_schema_property(self):
        schema = json.loads((ROOT / "schemas/research-queue.schema.json").read_text())
        self.assertEqual(set(QUEUE_HEADER), set(schema["properties"]))

    def test_evaluation_receipt_keeps_the_original_inspected_corpus_hash(self):
        receipt = json.loads((ROOT / "tests/evaluations/evidence-model-evaluation.json").read_text())
        corpus = (ROOT / receipt["corpus"]["path"]).read_bytes()
        self.assertEqual(receipt["corpus"]["sha256"], sha256_bytes(corpus))
        self.assertEqual(receipt["corpus"]["cases_inspected"], len(receipt["cases"]))
        # Structural receipt validation is not a model-quality evaluation.
        self.assertEqual(receipt["human_review"]["status"], "NOT RUN")
