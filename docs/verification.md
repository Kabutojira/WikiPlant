# Verification

## Local commands

```bash
PYTHONPATH=scripts python -m unittest discover -s tests -p 'test_*.py'
PYTHONPATH=scripts python -m wikiplant.cli validate --root .
PYTHONPATH=scripts python -m wikiplant.cli e2e
```

The suites use synthetic fixtures, provider fakes, and an in-memory host. They verify deterministic data, installer resume, failure injection, isolation, budgeting, monitoring, calendar, wiki/report, maintenance, and upgrade behavior. Provider-contract coverage exercises exact reads, complete inventories, durable intent, replay, conflicts, scope and verification across the existing strict fake-Drive suite and the GitHub suite; provider-specific atomicity remains explicit because Drive does not offer Git commit semantics. GitHub tests additionally cover sibling commits, non-force publication, lost responses/orphan objects, manual edits, repository/ref isolation, visibility/archive/permission failures, and truncated/oversized inputs. Local tests do not authenticate to Google Drive, GitHub, or ChatGPT.

## Opt-in live Drive Work acceptance

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

## Opt-in live GitHub Work acceptance

Use a newly approved isolated private repository dedicated to one synthetic instance. Never use the public scaffold, a production repository, the owner's Drive PoC, a public fork, or a shared repository. The standard ChatGPT GitHub app is read-only and is not eligible. Record the exact write-capable integration/actions and repository-scoped permissions privately.

1. Resolve immutable repository ID and owner/name; verify private, non-fork, non-archived status, selected-app access, canonical full ref, and empty root prefix.
2. In a fresh Work conversation, install from the public release into that repository. Confirm one instance tree, one personalized skill, one daily task, and one weekly task; record actual IDs/references privately.
3. Demonstrate exact full ref/commit/tree/blob reads without search/index excerpts. Publish a bounded multi-file transaction by creating blobs/tree/one-parent commit and one `force=false` ref update; independently verify ref, parentage, tree, and blob hashes.
4. In a fresh ordinary non-Work chat, retrieve the wiki and submit an explicit saved note. Verify the exact committed generation and replay receipt. Confirm a similarly named repository/branch cannot be selected.
5. Let daily and weekly occurrences run unattended. Confirm the same bounded write operations complete without per-run approval; separately inspect monitoring counters, reservations, wiki/evidence commits, report save, native result publication, and observable notification state.
6. Force two genuinely overlapping writers from the same base. Exactly one sibling ref update may succeed. The loser must preserve durable intent, reload the new head, and reconcile without force, rewind, deletion, data loss, or duplicate research.
7. Inject a lost response before and after ref publication. Reconcile by operation ID, reachability, current ref, parentage, tree and blob hashes. Orphaned objects must not be reported as saved.
8. Change a nonce and a valid manual note on the canonical ref between runs. Confirm the next run reads and preserves the latest committed generation. Invalid or foreign-instance manual commits must fail closed.
9. Verify public/archive state, revoked app permission, branch-rule rejection, truncated tree, oversized blob/transaction, repository rename, and canonical-ref mismatch all fail closed with durable evidence.
10. Run the equivalent Drive/GitHub synthetic benchmark workloads described in the GitHub storage plan and report median/tail storage latency, calls, bytes, conflicts, retries, and rate-limit observations without private content.

Use `PASS`, `FAIL`, `PARTIAL`, `BLOCKED`, `NOT RUN`, or `PENDING`. GitHub activation additionally requires the exact connector/action names and scopes, observed unattended reads/writes, forced-overlap behavior, changed-input freshness, installed-skill binding in a fresh chat, and separate save/publication/notification evidence. Until all required gates pass, report `EXPERIMENTAL_BLOCKED_FOR_PRODUCTION` or `BLOCKED_GITHUB_WRITE_CAPABILITY`; Drive remains available only as an explicitly selected alternative, never an automatic fallback.
