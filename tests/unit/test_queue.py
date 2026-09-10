from __future__ import annotations

import unittest
from datetime import datetime, timezone

from wikiplant.errors import ValidationError
from wikiplant.queue import DailyBudget, QueueItem, admit_children, deduplicate, derived_child, read_queue, select_next, write_queue


NOW = "2026-01-15T10:00:00+00:00"


def item(identifier: str, priority: int, *, expansion: int | None = None, due: str = "", question: str | None = None, urgency: str | None = None) -> QueueItem:
    return QueueItem(
        priority=priority, id=identifier, expansion_priority=priority if expansion is None else expansion,
        kind="investigation", question=question or f"Question {identifier}?", topic_id="topic-a", related_page_ids=[],
        parent_ids=[], lineage_root_id=identifier, origin="user", origin_ref="cmd-1", created_at=NOW,
        due_at=due, priority_reason="Relevant to synthetic goal",
        urgency_reason=(urgency if urgency is not None else ("Synthetic deadline" if priority == 0 else "")),
    )


class QueueTests(unittest.TestCase):
    def test_numeric_sort_and_csv_unicode_quoting(self):
        values = [item("hundred", 100), item("ten", 10, question='Does "α, β" work?'), item("zero", 0), item("two", 2)]
        text = write_queue(values)
        self.assertEqual([v.priority for v in read_queue(text)], [0, 2, 10, 100])
        self.assertIn('"Does ""α, β"" work?"', text)
        self.assertTrue(text.startswith("priority,"))

    def test_embedded_newline_rejected(self):
        with self.assertRaises(ValidationError):
            write_queue([item("bad", 10, question="line one\nline two")])

    def test_deadline_missing_last_and_id_tie_break(self):
        early = item("b", 10, due="2026-01-16T00:00:00+00:00")
        later = item("c", 10, due="2026-01-17T00:00:00+00:00")
        no_deadline = item("a", 10)
        self.assertEqual([v.id for v in read_queue(write_queue([no_deadline, later, early]))], ["b", "c", "a"])

    def test_expansion_and_urgency_lineage(self):
        parent = item("parent", 0, expansion=60)
        child = derived_child(child_id="child", question="Derived?", topic_id="topic-a", parents=[parent], created_at=NOW, priority_reason="Causal follow-up")
        self.assertEqual((child.priority, child.expansion_priority), (80, 80))
        child.priority = 0
        child.urgency_reason = "New deadline"
        grandchild = derived_child(child_id="grand", question="Grandchild?", topic_id="topic-a", parents=[child], created_at=NOW, priority_reason="Causal follow-up")
        self.assertEqual((grandchild.priority, grandchild.expansion_priority), (100, 100))
        self.assertIsNone(derived_child(child_id="overflow", question="Overflow?", topic_id="topic-a", parents=[grandchild], created_at=NOW, priority_reason="Too deep"))

    def test_multiple_parents_minimum_valid_expansion(self):
        child = derived_child(child_id="child", question="Multi-parent?", topic_id="topic-a", parents=[item("p1", 60), item("p2", 20)], created_at=NOW, priority_reason="Two causes")
        self.assertEqual(child.expansion_priority, 40)
        self.assertEqual(child.parent_ids, ["p1", "p2"])

    def test_three_child_cap_persists_on_replay(self):
        parent = item("parent", 20)
        children = [derived_child(child_id=f"c{i}", question=f"Child {i}?", topic_id="topic-a", parents=[parent], created_at=NOW, priority_reason="Useful") for i in range(4)]
        admitted, persisted = admit_children(children, [])
        self.assertEqual([v.id for v in admitted], ["c0", "c1", "c2"])
        replayed, persisted2 = admit_children(children, persisted)
        self.assertEqual(replayed, [])
        self.assertEqual(persisted2, persisted)

    def test_dedup_preserves_urgent_reason_deadline_and_links(self):
        first = item("a", 40, question="Equivalent question?")
        first.related_page_ids = ["p1"]
        second = item("b", 0, expansion=40, question="Equivalent question!", due="2026-01-16T00:00:00+00:00")
        second.related_page_ids = ["p2"]
        merged = deduplicate([first, second])[0]
        self.assertEqual(merged.priority, 0)
        self.assertEqual(merged.expansion_priority, 40)
        self.assertEqual(merged.related_page_ids, ["p1", "p2"])
        self.assertTrue(merged.urgency_reason)


class BudgetTests(unittest.TestCase):
    def test_five_ordinary_then_urgent_only_to_ten(self):
        budget = DailyBudget("wp-test", "2026-01-15", "UTC")
        for index in range(5):
            self.assertIsNotNone(budget.reserve(item(f"n{index}", 50)))
        self.assertIsNone(budget.reserve(item("ordinary-six", 1)))
        for index in range(5):
            self.assertIsNotNone(budget.reserve(item(f"u{index}", 0)))
        self.assertIsNone(budget.reserve(item("u6", 0)))

    def test_earlier_urgent_does_not_unlock_ordinary_six(self):
        budget = DailyBudget("wp-test", "2026-01-15", "UTC")
        budget.reserve(item("urgent-first", 0))
        for index in range(4):
            budget.reserve(item(f"n{index}", 20))
        self.assertIsNone(budget.reserve(item("ordinary-six", 1)))

    def test_resume_reuses_reservation(self):
        budget = DailyBudget("wp-test", "2026-01-15", "UTC")
        target = item("target", 20)
        reservation = budget.reserve(target)
        resumed = budget.reserve(target, resume_reservation_id=reservation.reservation_id)
        self.assertIs(reservation, resumed)
        self.assertEqual(len(budget.reservations), 1)

    def test_not_before_is_not_eligible(self):
        budget = DailyBudget("wp-test", "2026-01-15", "UTC")
        target = item("later", 0)
        target.not_before = "2026-01-16T00:00:00+00:00"
        self.assertIsNone(select_next([target], budget, datetime(2026, 1, 15, tzinfo=timezone.utc)))

    def test_timezone_transition_does_not_reset_cycle(self):
        budget = DailyBudget("wp-test", "2026-10-25", "Europe/Rome")
        budget.reserve(item("one", 10))
        original_key = budget.cycle_key
        budget.transition_timezone("UTC")
        self.assertEqual(budget.cycle_key, original_key)
        self.assertEqual(len(budget.reservations), 1)


if __name__ == "__main__":
    unittest.main()
