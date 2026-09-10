# Calendar processing

Read the complete mapped raw calendar and per-occurrence state. Keep factual `event` records separate from executable `research_refresh` rows. Expand only supported none/daily/weekly/monthly recurrence with explicit local-date semantics. Do not invent an exact time for date-only events.

For each due/overdue unprocessed refresh occurrence, derive its stable occurrence/action ID, validate question/priority/lineage, deduplicate, persist the queue item, verify readback, and then mark occurrence intake complete. Recovery after a crash recognizes the same ID. Cancellation suppresses future intake; rescheduling preserves old evidence and cancels/revises unprocessed actions.

Return today's and configured-lookahead events regardless of queue allowance. A factual event never authorizes registration, invites, or another external action without explicit user direction.
