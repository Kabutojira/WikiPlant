# Hardening implementation evidence

Baseline: `c5907ca3fb2d44df2f73ce0b3202909f548e7ef0`, 2026-09-10. Initial tree: only untracked owner-supplied `HARDENING_PLAN.md`. No prior review bundle exists in the checkout; reconstruct regressions from the plan, without presenting them as historical executions.

Baseline commands: `PYTHONPATH=scripts python -m unittest discover -s tests -p 'test_*.py'` — 64 tests PASS. `PYTHONPATH=scripts python -m wikiplant.cli validate --root .` — PASS. These are local checks only.

Final local checkpoint, 2026-09-10: **178 tests PASS**, repository validator PASS, draft packaging PASS, synthetic installer e2e PASS. Development version: **0.2.0, unpublished**. Local M0–M7 implementation and M8 migration are present; behavioral release acceptance is PARTIAL and live acceptance is NOT RUN. No commit, push, public release, live Drive mutation, permission change or schedule operation was performed.

## Shared v2 implementation contracts

- Storage: `SafeWriter.replace(binding, content, operation_id, *, base: FileSnapshot)` requires the exact generation snapshot; returns a `WriteReceipt` with historical verified identity and current snapshot. Durable immutable intent/completion records and paginated exact reads drive replay. Capabilities default absent. Weak adapters preserve scoped intake but block canonical replacement; uncertain creates reconcile by immutable name/content and never blindly retry.
- Scope: `TopicRegistry` serializes to authoritative TOPICS Markdown. `AdmissionDecision` records disposition, scope revision, contribution and lineage. Topic IDs remain queue/calendar links. Config v2 uses `primary_topic_ids`; legacy v1 remains migration input. Changed/new contracts declare schema version 2; unchanged instance identity, mapping, schedule and queue-row formats retain their existing version. Old changed-format input is migrated rather than silently reinterpreted.
- Claims: keep `Claim` and `SourceRecord` in `records.py`; add optional evidence/dependency/assessment fields compatibly. The wiki embeds complete canonical JSON metadata and generates readable claims. Structural validation is not semantic truth assessment.
- Authorization: separate `authorization.py` holds a structured current-turn decision bound to instance/operation/target. Command payloads carry it; text routing is only a proposal. Scheduled grants are scoped separately from user commands and never permit anchors or software updates.
- Operations: pure helpers accept fetched inputs and emit outputs; provider calls remain in the host workflow. Persisted callback receipts are required for research removal, report coverage and update activation. No fake adapter capability counts as cloud evidence.
- Ownership: migrations own schema transitions; release files own runtime defaults; instance data and unknown valid fields remain user-owned. Detached runtime packaging must close all production imports without fake adapters.

## Coverage map (updated as milestones land)

| Requirement | Implementation/test evidence | Status |
|---|---|---|
| M0 baseline and reconciled contracts | Commands above; AGENTS.md and PLAN.md | PASS |
| WP-C01/C02 safe writes/replay | `storage.py`, fake adapter; stale/manual edits, lost responses, weak capability, ancestor scope and historical replay tests | PASS (local) |
| WP-C03 authorization | `authorization.py`, `intake.py`; typed current-turn grants, non-authorizing text proposals, request digest and cross-instance regressions | PASS (local boundary; multilingual model acceptance separate) |
| WP-C04 report coverage/publication | `reporting.py`; per-record appendix, represented/deferred indexes across dates, saved raw readback and lost-publication recovery | PASS (local) |
| WP-C05/C06/C10 lossless identity/index | `wiki.py`, queue/calendar, scaffold schema/template tests; full claim/unknown-field/user-note round-trip and duplicate identity rejection | PASS (local) |
| WP-P01 M2/M3 anchored growth/archive | `topics.py`, `admission.py`, `archive.py`; 26 synthetic regression tests in `test_topics_admission_archive.py` | PASS (local; live/behavioral gates separate) |
| WP-P02 M4 evidence/corrections | records/evidence, claim/evidence/source schemas; 22 local evidence/retrieval/correction tests below | PASS (local policy) |
| WP-P03 M5 adversarial checks | ChallengeRecord, evidence/adversarial workflows; blocked/unsearched, caps, terminal peripheral and false-balance tests; queue validation lane | PASS (local policy; behavioral acceptance PARTIAL) |
| WP-C07/C08/C09 M6 resilient execution | `monitoring.py`, `orchestrator.py`, `maintenance.py`; persisted results/reservations/backoff, assessed material monitoring, independent wiki/report receipts and isolated phase failures | PASS (local bridge contracts) |
| M7 releases, consent, updater | `releases.py`, `upgrades.py`, detached manifest/CLI and 23 targeted release/migration/update tests below | PASS (local helper/bridge contracts; live NOT RUN) |
| M8 legacy migration | `migrations/v1_to_v2.py`; conservative provenance/status mapping, byte preservation, idempotence and reconciliation report | PASS (local migration; live and model gates NOT RUN) |
| Behavioral evaluations | 10 actual bounded assistant judgments; retained rubric defect/fixture limits; 5 further governance cases prepared | PARTIAL; independent repeatability, governance model runs and human review NOT RUN |
| Live installation, raw freshness, overlap, update, notifications | Approved new Work sandbox required | NOT RUN |

## Evidence, challenge and semantic review verification

`PYTHONPATH=scripts python -m unittest tests.unit.test_evidence_hardening tests.unit.test_retrieval_hardening tests.integration.test_correction_reporting` — 22 tests PASS. A separate seven-test run of existing wiki, maintenance rotation and lexical retrieval tests also passes. All sources and Drive artifacts are synthetic; these results do not prove live research quality or notification delivery.

Outcomes include one origin for ten copies; zero invented independence for unknown origins or archive self-corroboration; rejection of missing/uninspected/changed passage locators; distinction between announcement, measured performance and project suitability; no promotion from inapplicable strong evidence; revision under strong relevant opposition without false balance; full claim/evidence metadata round-trip; transitive correction and replay; accurate blocked/unsearched challenge state; finite counter-check and terminal peripheral rules; normalized cross-page conditions/units/time; actual elapsed claim freshness; persisted risk/rotation/coverage; bounded graph and recorded semantic retrieval. The fake-Drive correction integration reconstructs saved claims and independently reads the resulting report's correction, dependencies, provenance and represented coverage.

Implementation: `records.py`, `evidence.py`, `maintenance.py`, `retrieval.py`, the intake retrieval wrapper, evidence/claim/challenge/correction/applicability schemas and internal evidence/adversarial/research/synthesis/query/maintenance workflows. [Evidence quality](evidence-quality.md) documents the policy and limits. Source artifact checks and assessments remain a required production host-workflow boundary before supporting claims; deterministic validators do not decide semantic truth.

The ten-case [evidence evaluation corpus](../tests/evaluations/evidence-corpus.json) supplies fictional evidence and decision rubrics, including a malicious-source case separate from benign misleading evidence. The [actual bounded assistant evaluation](../tests/evaluations/evidence-model-evaluation.json) records one judgment per case, source locators, permitted actions and retained limitations. It is non-blinded self-evaluation with the rubric and previous implementation in context; a concrete model/version was not exposed. It found a rubric counterexample: evidence that a device missed a future target does not contradict an asserted achieved result unless achievement was actually asserted. Several fixtures lack methods or project conditions sufficient for full conclusions. These outcomes were retained, not rewritten as clean passes. The corpus's original NOT RUN metadata remains as authored; the separate hash-bound receipt records the later review.

The additional [governance corpus](../tests/evaluations/governance-corpus.json) covers irrelevant adjacent chains, overload/backpressure, archived rediscovery, private-query minimization and multilingual current-turn intent. Its model runs are NOT RUN. Human review, independent repeatability, actual external-source challenge behavior and live Work execution are NOT RUN. Linked deterministic tests and JSON receipt checks are not model-quality measurements; no latency, cost or quality percentage is fabricated.

Saved research and material monitoring now independently resolve assessment/source/dependency files by ID/hash, exact inspected locators, finding/claim/challenge inventories, dependency cycles and effective support. Ten assessment-integrity regressions cover missing/cyclic dependencies, unrelated/unused challenges, forged computed status, and bounded status/condition/units/time-preserving report text. Unstructured implications remain labeled proposals, not completed applicability analysis.

## Integrity, execution and fresh-review verification

`PYTHONPATH=scripts python -m unittest tests.unit.test_hardening_integrity tests.unit.test_review_regressions tests.integration.test_persisted_daily` — 30 tests PASS. These use actual raw synthetic artifacts, not merely phase labels. A fresh reviewer contributed 11 regressions; all pass after implementation fixes. Historical failed reproductions are not represented as current failures.

| Boundary | Observed local outcome |
|---|---|
| Generation snapshot and operation replay | Manual/later edits survive; stale bases conflict; fresh writers recover lost intent/write/completion responses; historical receipt proof remains distinct from current content. |
| Scope and authorization | Target/journal/inbox ancestry is validated; foreign instance grants and truthy non-boolean flags reject; text without a semantic current-turn grant cannot write. |
| Installer resume | Broad-sharing rechecks run before every resume; approved setup/release provenance stays pinned; reserved seed IDs cannot duplicate the five-attempt allowance. The installer harness is development-only and excluded from runtime snapshots. |
| Daily recovery | Five ordinary reservations and mandatory monitoring persist separately; malformed queues or independent callback failures still allow safe reports; future backoff, numeric slot ordering and pending wiki merge resume without repeat research. |
| Material monitoring | Source artifacts, passage locators and bound assessments resolve; canonical wiki intent/completion receipts agree. Pre-commit ledgers remain partial without a watermark; the verified finalizer completes the raw ledger after receipts. |
| Canonical receipts | A folder, arbitrary Markdown file, forged COMPLETE-shaped artifact, mismatched original intent or unrelated page cannot remove queue work. Later legitimate edits do not invalidate historical proof. |
| Report coverage/publication | The fourth finding has a substantive appendix entry; deferred evidence stays pending; per-record coverage works across dates; saved raw reports resolve; uncertain claims remain uncertain despite an inflated callback confidence. Lost native responses reconcile independently of research. |
| Honest accounting | Raw run state and saved reports separate queue slots and per-topic query/source counters, active/archive registry totals, queue age/deferrals and challenge coverage. External bytes/latency/cost are unknown when not exposed. |
| Whole-run overlap | An absent serialization guard blocks canonical execution before callbacks; weak adapters preserve intake but cannot write projections. This is not live provider concurrency proof. |

## Final commands and release boundary

```text
PYTHONPATH=scripts python -m unittest discover -s tests -p 'test_*.py'
  PASS — 178 tests
PYTHONPATH=scripts python -m wikiplant.cli package --root . --draft
  PASS — release/runtime-manifest.json (draft, not installable)
PYTHONPATH=scripts python -m wikiplant.cli validate --root .
  PASS — schemas, templates, policies, private-marker scan, manifest and runtime import closure
PYTHONPATH=scripts python -m wikiplant.cli e2e --root .
  PASS — synthetic only: 1 skill, 2 tasks, 1 seed attempt, 164 fake Drive objects
git diff --check
  PASS
```

The fake installer's `ACTIVE_VERIFIED` is a test-state outcome, not a real installed skill or unattended run. Runtime closure is checked with an isolated staged-module subprocess; updater reconstruction also has a fresh-process regression. The public source bytes must be committed and a detached released asset produced in a separately authorized maintainer workflow before repository-URL release acceptance can run. The minimal Work handoff is [verification.md](verification.md): approve one fresh sandbox, verify capabilities/install/routing, raw changed-input freshness and overlap, then weekly archival/notices and an explicitly authorized update/recovery followed by a real scheduled run. Human notification observation stays separate.

## Topic governance and compact archive verification

`PYTHONPATH=scripts python -m unittest tests.unit.test_topics_admission_archive -v` — 26 tests PASS. The full local suite before the two additional calendar regressions (`PYTHONPATH=scripts python -m unittest discover -s tests -p 'test_*.py'`) — 147 tests PASS. Synthetic fixtures only; these are deterministic/persistence results, not an observed Work installation or a model-quality evaluation.

| Contract | Implementation and tested outcome | Status |
|---|---|---|
| Canonical taxonomy, provenance, lifecycle | `topics.py`, topic schema, `TOPICS.md` template; exact three sections, unknown metadata/notes round-trip, explicit operation-bound tracking grants, duplicate/cyclic/unknown references rejected, provisional legacy preservation | PASS (local) |
| Direct anchor relevance and terminal ancestry | `admission.py`; every automatic origin uses one decision function; locally adjacent chain rejects, recorded direct contribution and relevant critique admit; peripheral/archived/expired ancestors cannot gain descendants by relabeling, calendar, urgency, merge or reactivation | PASS (local policy) |
| Capacity, novelty, locality and fairness | Persisted `AdmissionGate`; 40-arrival overload retains 3 active items and 37 visible deferrals under configured cap; explicit user request remains a pending-capacity exception, no anchor; semantic merge decisions retain ancestry; local-day root counting excludes execution revalidation; overdue validation lane respects priority 0 and 5/10 | PASS (local) |
| Fixed expiry and conservative migration | `next_weekly_checkpoint` uses next strictly future local occurrence; retries cannot extend expiry; only proven historical tracking becomes a user anchor, unknown legacy input remains provisional | PASS (local) |
| Reference-safe archival | `archive.py`; original snapshots and seven checkpoints persist. Fresh writers resume after each interruption; same canonical raw ID, notes/unknown fields, archive redirect and original lineage survive; active index membership and automatic queue/calendar/admission obligations retire; explicit requests remain | PASS (fake Drive) |
| Recovery and dossier compaction | Completed verified archive recovery snapshots compact after retention into audit identities; incomplete/too-new states block. Generated single-topic research dossiers compact only with represented/deferred coverage and retained sources; uncertainty, applicability, confidence, lineage and unknown metadata survive | PASS (local/fake Drive) |
| Selective archive retrieval | 2,000-topic fixture retrieves one matching capsule through one partition; archive status/freshness reported and no reactivation | PASS (local) |
| Calendar identities and dates | Legacy header is explicit compatibility input; v2 topic/parent/root fields, unique IDs, monthly original day, local-zone deadlines, bounded equivalent missed occurrences, partial-date visibility | PASS (local) |
| Semantic judgment, real compaction and concurrent provider bridge | Work must supply actual inspected evidence, question-specific relevance assessments, complete reference inventory, observed writer capabilities and verified mappings; schemas alone cannot establish these | NOT RUN (live/behavioral) |

New internal workflows are `topic-governance` and `archive`, referenced by discovery/calendar instructions; they are not additional end-user skill installations. The new schemas and config defaults are domain-neutral. Historical archive storage remains unbounded across indefinitely many unique summaries or user requests; only active growth and routine fetch/work are bounded.

## Release and existing-instance migration verification

`PYTHONPATH=scripts python -m unittest tests.unit.test_release_hardening tests.unit.test_migration_hardening tests.integration.test_upgrade_hardening` — 20 tests PASS. `PYTHONPATH=scripts python -m unittest discover -s tests -p 'test_*.py'` — 155 tests PASS at this checkpoint. `PYTHONPATH=scripts python -m wikiplant.cli e2e --root .` — PASS, one synthetic installed skill, two synthetic tasks, one seed attempt. These are local outcomes; no release was published and no live instance changed.

Release tests establish semantic-version ordering/channel filtering, incompatible notices, changed known-version alerts, distinct failed/stale/partial versus empty release observations, bounded check retries, saved notice readback and retryable publication. Detached manifests contain compatibility/migration/rollback metadata, verify all source bytes against an already-existing commit at packaging, reject missing runtime dependencies, and import every staged runtime module in an isolated Python subprocess. The committed manifest remains a draft inventory; released assets are detached.

Updater tests stop and reconstruct after each phase using serialized fake Drive entries while forgetting global fake idempotency caches. A separate fresh Python process resumes `DATA_MIGRATED` through actual persisted synthetic host/file outcomes. Tests also cover lost host responses, actual new-file/runtime mapping IDs, post-update edits, preserved queue/attempt bytes, stale-generation and weak-adapter blocks, tampered staged code, missing private-skill update controls, and rejection of boolean-only binding receipts. The updater pins exact current-turn consent, repository/version/commit/manifest, original generation inputs, migration output hashes and host observations. Compatibility-gated rollback has durable recovery phases and preserves later raw notes; incompatible rollback stays blocked and never restores old data over new work.

The v1 migration preserves source/report/queue/calendar/budget bytes, unknown fields, user notes, original IDs, attempt/lineage records and old claim assessments. Only documented historical tracking becomes an anchor; unknown topics remain provisional. Strong legacy claim status becomes uncertain with a revalidation record. When the old renderer discarded claim IDs, original prose is retained unassessed rather than inventing identities/locators. Counts/hashes/reclassifications/source gaps are reported; a second migration is byte-identical. Peripheral compaction remains the shared reference-safe archive transaction. Unsupported references or unresolved scope prevent activation.

The OpenAI Docs skill informed the documented host boundary: updating Drive text is not installed-skill verification. GitHub release/immutable-release and OpenAI skill-control documentation was checked on 2026-09-10; [upgrades](upgrades.md) links those sources. Actual public-release retrieval, installation, skill/task updates, writer draining, new-account migration, later scheduled execution and notification receipt remain **NOT RUN** pending a separately approved Work sandbox. The helper bridge requires observed tool references and never represents a synthetic receipt as live proof.
