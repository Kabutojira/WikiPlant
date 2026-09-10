from __future__ import annotations

import unittest
from datetime import datetime, timezone

from wikiplant.monitoring import MonitoringLedger
from wikiplant.orchestrator import run_daily as execute_daily
from wikiplant.queue import DailyBudget, QueueItem
from wikiplant.records import ResearchResult


NOW = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)


def run_daily(**kwargs):
    """Legacy callback policy tests are explicitly simulations; persisted tests are separate."""
    return execute_daily(**kwargs, simulate=True)


def queue_item(identifier: str, priority: int) -> QueueItem:
    return QueueItem(
        priority, identifier, 20 if priority == 0 else priority, "investigation", f"Question {identifier}?", "topic-a", [], [],
        identifier, "user", "cmd", NOW.isoformat(), priority_reason="Synthetic priority",
        urgency_reason="Synthetic urgent event" if priority == 0 else "",
    )


def result(item: QueueItem, reservation: str) -> ResearchResult:
    return ResearchResult(
        f"result-{item.id}", item.question, item.id, reservation, "run-1", item.origin, ["source-fixture"],
        ["Synthetic finding"], "medium", [], [], [], ["Check applicability"], [], "complete",
    )


class DailyOperationTests(unittest.TestCase):
    def monitor(self, ledger: MonitoringLedger):
        def callback(topic):
            record, created = ledger.begin(
                instance_id="wp-test", local_date="2026-01-15", topic_id=topic["id"],
                last_successful_end="2026-01-14T00:00:00+00:00", scheduled_end=NOW.isoformat(), overlap_hours=12,
                max_queries=2, max_sources=3,
            )
            if created:
                record.reserve_query()
                record.record_query(1, status="success", query="Synthetic update", result_reference="synthetic-search")
                record.finish("no_material_update")
            return record
        return callback

    def test_main_pass_plus_five_ordinary(self):
        ledger = MonitoringLedger()
        queue = [queue_item(f"n{i}", 20 + i) for i in range(7)]
        budget = DailyBudget("wp-test", "2026-01-15", "UTC")
        outcome = run_daily(
            topics=[{"id": "topic-a"}], queue_items=queue, budget=budget, now=NOW,
            calendar_step=lambda: [], monitor_topic=self.monitor(ledger), investigate=result,
        )
        self.assertEqual(len(outcome.monitoring), 1)
        self.assertEqual(len(outcome.research), 5)
        self.assertEqual(len(budget.reservations), 5)

    def test_main_pass_plus_ten_urgent(self):
        ledger = MonitoringLedger()
        queue = [queue_item(f"u{i}", 0) for i in range(12)]
        budget = DailyBudget("wp-test", "2026-01-15", "UTC")
        outcome = run_daily(
            topics=[{"id": "topic-a"}], queue_items=queue, budget=budget, now=NOW,
            calendar_step=lambda: [], monitor_topic=self.monitor(ledger), investigate=result,
        )
        self.assertEqual(len(outcome.monitoring), 1)
        self.assertEqual(len(outcome.research), 10)
        self.assertEqual(len(queue), 2)

    def test_two_topics_do_not_change_queue_allowance(self):
        ledger = MonitoringLedger()
        queue = [queue_item(f"n{i}", 30) for i in range(8)]
        budget = DailyBudget("wp-test", "2026-01-15", "UTC")
        outcome = run_daily(
            topics=[{"id": "a"}, {"id": "b"}], queue_items=queue, budget=budget, now=NOW,
            calendar_step=lambda: ["event today"], monitor_topic=self.monitor(ledger), investigate=result,
        )
        self.assertEqual(len(outcome.monitoring), 2)
        self.assertEqual(len(outcome.research), 5)
        self.assertEqual(outcome.events, ["event today"])

    def test_queue_failure_does_not_suppress_monitoring_events_or_report(self):
        ledger = MonitoringLedger()
        outcome = run_daily(
            topics=[{"id": "a"}], queue_items=[], budget=DailyBudget("wp-test", "2026-01-15", "UTC"), now=NOW,
            calendar_step=lambda: ["today"], monitor_topic=self.monitor(ledger), investigate=result, queue_available=False,
        )
        self.assertEqual(len(outcome.monitoring), 1)
        self.assertEqual(outcome.events, ["today"])
        self.assertIn("report-save", outcome.order)
        self.assertTrue(outcome.gaps)

    def test_replay_reuses_monitoring_and_budget(self):
        ledger = MonitoringLedger()
        budget = DailyBudget("wp-test", "2026-01-15", "UTC")
        queue = [queue_item(f"n{i}", 30) for i in range(7)]
        first = run_daily(topics=[{"id": "a"}], queue_items=queue, budget=budget, now=NOW, calendar_step=lambda: [], monitor_topic=self.monitor(ledger), investigate=result)
        second = run_daily(topics=[{"id": "a"}], queue_items=queue, budget=budget, now=NOW, calendar_step=lambda: [], monitor_topic=self.monitor(ledger), investigate=result)
        self.assertIs(first.monitoring[0], second.monitoring[0])
        self.assertEqual(first.monitoring[0].queries_used, 1)
        self.assertEqual(len(budget.reservations), 5)
        self.assertEqual(len(second.research), 0)


if __name__ == "__main__":
    unittest.main()
