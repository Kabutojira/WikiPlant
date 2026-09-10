# Calendar processing

Read the complete mapped raw calendar and per-occurrence state. Keep factual `event` records separate from executable `research_refresh` rows. Expand only supported none/daily/weekly/monthly recurrence with explicit local-date semantics. Do not invent an exact time for date-only events.

For each due/overdue unprocessed refresh occurrence, derive its stable occurrence/action ID, validate question/priority/lineage, deduplicate, persist the queue item, verify readback, and then mark occurrence intake complete. Recovery after a crash recognizes the same ID. Cancellation suppresses future intake; rescheduling preserves old evidence and cancels/revises unprocessed actions.

Return today's and configured-lookahead events regardless of queue allowance. A factual event never authorizes registration, invites, or another external action without explicit user direction.

V2 rows bind `topic_id`, causal `parent_ids`, and original `lineage_root_id` separately from calendar/occurrence IDs. Before enqueue and again before execution use the shared topic-governance admission gate. Archived, provisional, expired and terminal peripheral ancestry cannot create recurring research through the calendar. Preserve original monthly anchor days (January 31 → February 28 → March 31) and express deadlines in the event's local timezone. Partial dates remain visibly partial, not precise research execution dates.

Missed equivalent refreshes are coalesced to one latest occurrence per calendar row. Persist the covered/coalesced occurrence IDs only alongside verified queue intake; an attempted callback is not completion. Legitimate new evidence/dated observations retain distinct novelty and occurrence identities.
