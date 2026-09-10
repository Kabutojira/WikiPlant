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
