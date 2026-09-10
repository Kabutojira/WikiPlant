from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from wikiplant.calendar import CalendarItem, due_refreshes, mark_occurrence_queued, read_calendar, reschedule, visible_events, write_calendar
from wikiplant.errors import ValidationError
from wikiplant.monitoring import MonitoringRecord, is_new_event


def calendar_item(identifier: str, kind: str = "research_refresh", **changes) -> CalendarItem:
    values = dict(
        id=identifier, kind=kind, title="Synthetic event", start_date="2026-01-13", start_at="", end_at="",
        timezone="Europe/Rome", date_precision="date", status="scheduled", related_page_ids=["page-1"],
        source_refs=["source-1"], refresh_question="What changed?" if kind == "research_refresh" else "",
        priority=20, expansion_priority=20, recurrence={"frequency": "none", "interval": 1}, lead_days=0,
        origin_ref="fixture", updated_at="2026-01-10T00:00:00+00:00",
    )
    values.update(changes)
    return CalendarItem(**values)


class CalendarTests(unittest.TestCase):
    def test_csv_roundtrip_and_overdue_intake_once(self):
        original = calendar_item("refresh-1", title='Event, "quoted"')
        restored = read_calendar(write_calendar([original]))[0]
        state = {}
        first = due_refreshes([restored], date(2026, 1, 15), state, "2026-01-15T00:00:00+00:00")
        self.assertEqual(len(first), 1)
        mark_occurrence_queued(state, first[0])
        self.assertEqual(due_refreshes([restored], date(2026, 1, 15), state, "2026-01-15T00:00:00+00:00"), [])

    def test_queue_persisted_before_crash_dedups_by_occurrence(self):
        target = calendar_item("refresh-1")
        first = due_refreshes([target], date(2026, 1, 15), {}, "2026-01-15T00:00:00+00:00")[0]
        second = due_refreshes([target], date(2026, 1, 15), {}, "2026-01-15T00:00:00+00:00")[0]
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.dedup_key, second.dedup_key)

    def test_cancelled_and_rescheduled_visibility(self):
        cancelled, rescheduled = reschedule(
            calendar_item("old", kind="event"), new_id="new", new_start_date="2026-01-16",
            updated_at="2026-01-14T00:00:00+00:00",
        )
        visible = visible_events([cancelled, rescheduled], date(2026, 1, 15), 7)
        self.assertEqual([(item.id, when.isoformat()) for item, when in visible], [("new", "2026-01-16")])

    def test_date_only_event_keeps_no_invented_time(self):
        event = calendar_item("event", kind="event")
        restored = read_calendar(write_calendar([event]))[0]
        self.assertEqual(restored.start_at, "")
        self.assertEqual(restored.date_precision, "date")

    def test_weekly_recurrence_and_upcoming_even_without_research(self):
        event = calendar_item("weekly", kind="event", recurrence={"frequency": "weekly", "interval": 1})
        visible = visible_events([event], date(2026, 1, 15), 14)
        self.assertEqual([when.isoformat() for _, when in visible], ["2026-01-20", "2026-01-27"])


class MonitoringTests(unittest.TestCase):
    def record(self):
        return MonitoringRecord(
            "wp-test", "2026-01-15", "topic-a", "2026-01-14T00:00:00+00:00", "2026-01-15T00:00:00+00:00", 2, 3
        )

    def test_separate_bounded_counters_and_resume(self):
        record = self.record()
        self.assertEqual([record.reserve_query(), record.reserve_query(), record.reserve_query()], [1, 2, None])
        self.assertEqual([record.reserve_source(), record.reserve_source(), record.reserve_source(), record.reserve_source()], [1, 2, 3, None])
        self.assertEqual(record.key, "wp-test:2026-01-15:topic-a")

    def test_no_update_requires_successful_search(self):
        record = self.record()
        with self.assertRaises(ValidationError):
            record.finish("no_material_update")
        record.reserve_query()
        with self.assertRaises(ValidationError):
            record.finish("no_material_update")
        record.record_query(1, status="success", query="Synthetic topic update", result_reference="synthetic-search-1")
        record.finish("no_material_update")
        self.assertEqual(record.status, "no_material_update")

    def test_failed_search_is_partial_not_no_news(self):
        record = self.record()
        record.finish("partial", limitation="search provider unavailable")
        self.assertEqual(record.status, "partial")
        self.assertIn("search provider unavailable", record.limitations)

    def test_late_indexed_old_article_is_not_new_event(self):
        coverage = datetime(2026, 1, 14, tzinfo=timezone.utc)
        old = datetime(2025, 12, 1, tzinfo=timezone.utc)
        self.assertFalse(is_new_event(publication_at=old, event_at=None, coverage_start=coverage))


if __name__ == "__main__":
    unittest.main()
