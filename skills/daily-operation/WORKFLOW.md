# Daily operation

Execute in this order with one stable local-date cycle key:

1. Validate exact instance/config/map/runtime bindings and reconcile unfinished operations/authorized intake.
2. Process due/overdue calendar refresh intake and collect today/upcoming events.
3. Run or resume every configured primary-topic refresh with separate finite query/source counters.
4. Perform bounded adjacent discovery and persist deduplicated questions.
5. Reconcile queue reservations; run at most five general attempts, then only eligible priority-0 work through the hard total of ten.
6. Synthesize all new evidence with existing relevant wiki/project context.
7. Refresh the completed-evidence/event inventory, save/read back the Markdown report, publish a native result, and record observable delivery states.

A queue failure must not suppress possible monitoring, events, or an operational-failure report. Unsafe shared storage may block mutation; preserve intake/results and report `BLOCKED` instead of pretending persistence. Replays perform no new completed pass, queue attempt, child admission, or duplicate report.

Read `storage.consistency_mode` before any external search or mutation. In `strict` mode, use `DailyRunStore` only with observed host serialization covering the whole invocation. In explicitly approved `best-effort-personal` mode, acquire the exact mapped permanent lock first: generate a unique run owner token, read the complete lock by ID, stop without research while a lock is younger than 20 hours, replace a stale/unlocked record with this owner and current offset timestamp, and read it back by ID. Re-check ownership immediately before each external research/search call and canonical write. Set the permanent record to unlocked in a final cleanup step; never delete it and never clear another owner. This is a collision-reduction mechanism, not atomic serialization, and every report/receipt must disclose that residual risk. Persist attempt reservation before research; save the result, evidence assessment and verified wiki/source receipts before queue removal. On restart, reconcile saved results and unfinished attempts; never re-run an ambiguous external invocation merely because its completion response was lost. Failed attempts receive future exponential backoff and remain visible. Use current `AdmissionGate` before every automatic admission and execution; record per-anchor service and overdue validation opportunity/starvation while keeping urgent precedence and the five/ten limits.

Isolate calendar, each topic, queue, synthesis and publication failures. Before the report snapshot, refresh events and all not-yet-represented evidence IDs, including manual work, corrections, maintenance and saved notes. Include source quality, challenge coverage, provisional peripheral findings, archive actions, deferrals and actual resource/coverage counts where observed. `simulate=True` is only a local test mode and cannot produce host acceptance evidence. A phase name without saved artifact receipts is not completion.
