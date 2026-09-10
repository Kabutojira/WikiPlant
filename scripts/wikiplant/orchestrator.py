from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterable

from .monitoring import MonitoringRecord
from .queue import DailyBudget, QueueItem, select_next
from .records import ResearchResult


@dataclass
class DailyOutcome:
    order: list[str] = field(default_factory=list)
    monitoring: list[MonitoringRecord] = field(default_factory=list)
    research: list[ResearchResult] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)


def run_daily(
    *, topics: list[dict], queue_items: list[QueueItem], budget: DailyBudget, now: datetime,
    calendar_step: Callable[[], list[str]], monitor_topic: Callable[[dict], MonitoringRecord],
    investigate: Callable[[QueueItem, str], ResearchResult], queue_available: bool = True,
) -> DailyOutcome:
    outcome = DailyOutcome()
    outcome.order.append("recover-bindings-config")
    outcome.events = calendar_step()
    outcome.order.append("calendar")
    for topic in topics:
        outcome.monitoring.append(monitor_topic(topic))
    outcome.order.append("main-topic-refresh")
    outcome.order.append("bounded-discovery")
    if not queue_available:
        outcome.gaps.append("Queue unavailable; mandatory main-topic results and events were retained.")
    else:
        while True:
            item = select_next(queue_items, budget, now)
            if item is None:
                break
            reservation = budget.reserve(item)
            if reservation is None:
                break
            item.status = "in_progress"
            item.attempts += 1
            result = investigate(item, reservation.reservation_id)
            outcome.research.append(result)
            if result.status == "complete":
                queue_items.remove(item)
            else:
                item.status = "retry_wait" if item.attempts < 3 else "blocked"
        outcome.order.append("queued-research")
    outcome.order.extend(["synthesis", "report-save", "native-result"])
    return outcome
