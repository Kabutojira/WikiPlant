# Verification

## Local commands

```bash
PYTHONPATH=scripts python -m unittest discover -s tests -p 'test_*.py'
PYTHONPATH=scripts python -m wikiplant.cli validate --root .
PYTHONPATH=scripts python -m wikiplant.cli e2e
```

The suites use synthetic fixtures and an in-memory Drive/host. They verify deterministic data, installer resume, failure injection, isolation, budgeting, monitoring, calendar, wiki/report, maintenance, and upgrade behavior. They do not authenticate to Google Drive or ChatGPT.

## Opt-in live Work acceptance

Use only a newly approved isolated Drive sandbox; never the owner's PoC or production data by default.

1. In a fresh Work conversation with no WikiPlant skill, provide the public released repository URL. Record question rounds and unavoidable clicks.
2. Confirm one private root, one personalized skill, one daily task, and one weekly task. Record actual IDs privately.
3. In a fresh ordinary non-Work chat, retrieve the wiki and submit an explicit saved note. Verify the raw canonical file or durable inbox command by exact ID.
4. After scheduling, update a mapped raw input and add a manual wiki note by exact ID. Independently read both back; do not edit a same-name Google Doc/Sheet.
5. Let a scheduled occurrence start automatically. Inspect monitoring counters, queue reservations, evidence/wiki writes, report readback, result status, and approvals.
6. Change the raw input and manual note again between two occurrences. Verify the next run observes and preserves both.
7. Replay the completed logical run. Confirm no extra primary-topic allowance, queue reservation, children, or report.
8. Force daily/daily and daily/weekly overlap. Strict mode passes only with proved serialization or fail-closed durable preservation. Best-effort personal mode must visibly refuse an observed live lock, reclaim at exactly 20 hours, refuse cross-owner release, and disclose that simultaneous acquisition can still race; it is not strict overlap acceptance.
9. Record notification delivery only if the host or user actually observes it. Clean up only temporary acceptance tasks.
10. Observe weekly expiry/archival: inspect retained source/user notes, capsule redirects and removed automatic obligations. Verify bounded archive retrieval without reactivation.
11. Observe a weekly release check and saved update notice. Confirm no runtime adoption; explicitly request the pinned candidate in this sandbox, then inspect checkpoints, migrated raw IDs/counts, preserved budgets, the same installed skill/two tasks and fresh invocation.
12. Inject an approved update interruption, resume from stored intent, and test compatible recovery while preserving later notes/intake. Observe a later scheduled run on the activated runtime. Keep each host capability and result receipt separate from local fake outcomes.

Use `PASS`, `FAIL`, `PARTIAL`, `BLOCKED`, `NOT RUN`, or `PENDING`. A Drive report proves storage; a task result proves publication; neither proves a received push/email.

Current live status: `NOT RUN`. The precise minimal handoff is to run the steps above in an eligible ChatGPT Work account with Google Drive and private skill/task controls available, then store private IDs/receipts in the sandbox instance and a sanitized status table in this repository.
