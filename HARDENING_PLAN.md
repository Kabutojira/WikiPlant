# WikiPlant hardening and controlled-growth implementation plan

Status: local hardening implementation and synthetic verification completed on 2026-09-10; behavioral release acceptance remains partial and live migration/Work acceptance is NOT RUN. See [the implementation evidence](docs/hardening-status.md). This is not a production-ready or published-release claim.
Prepared: 2026-09-10.  
Repository: `Kabutojira/WikiPlant`.  
Baseline: `c5907ca3fb2d44df2f73ce0b3202909f548e7ef0`, rechecked as the current `main` commit.  
Audience: Codex implementing the next version of the existing repository, not replacing its architecture.

## 1. Objective and precedence

Implement anchored topic governance, compact archival memory, evidence-quality controls, adversarial research, and a safe release-update lifecycle. Resolve the correctness and verification findings from the first-implementation review.

Read the existing `AGENTS.md`, `PLAN.md`, implementation, and tests before editing. Preserve the original installation and research product. This plan records the owner's subsequent requirements and supersedes conflicting scope, retention, and upgrade rules in the earlier specifications. Reconcile `AGENTS.md` and the original plan in the first milestone; do not leave competing instructions.

This is an incremental hardening effort. Do not create a replacement project, new hosted service, external research agent, global instance router, or GitHub operational database. Do not mark planned behavior or synthetic tests as live evidence.

### Fixed product decisions

| Area | Required behavior |
|---|---|
| Execution | Native cloud ChatGPT Work; daily and weekly scheduled tasks. |
| Storage | Google Drive only for operational data. GitHub distributes the public scaffold and releases. |
| Installation | Repository URL, one consolidated exchange for missing settings, automatic Drive provisioning, and unavoidable host authorization/install controls only. |
| Skills | One private, topic-customized installed skill per instance; internal workflows remain modular references. |
| Language/time | Ask during initialization; English and UTC are defaults, not hardcoded user settings. |
| Primary monitoring | Search configured primary user topics every day, even with an empty or exhausted queue, outside the queued-investigation budget. Keep its own finite query/source allowance. |
| Queue budget | Five normal attempt slots per daily cycle; slots six through ten only for genuinely urgent priority-0 work. No allowance reset on retry, restart, timezone change, update, or reactivation. |
| Initialization | At most five initial investigation attempts, persisted and separate from daily work; then first synthesis/report. |
| Expansion | Child expansion priority is inherited plus 20; reject values above 100; at most three admitted children per logical investigation. Priority 0 changes execution order, not ancestry. |
| Exploration | Encourage useful cross-domain connections while requiring a contribution to an explicit user interest. |
| Archive | Retain compact metadata and a brief summary instead of deleting all knowledge of an inactive topic. |
| Updates | Check published releases weekly, alert the user, and update only after an explicit user request for that instance. |
| Privacy | No operational data, real Drive IDs, private skill bindings, or unsanitized test evidence in public repository commits. |

The model recommendation in section 15 is for developing WikiPlant with Codex. It does not add a paid API-model dependency to WikiPlant's production research workflow.

## 2. Deliverables and implementation order

Use dependency-ordered milestones, each with code, schemas, workflow changes, tests, and evidence. Prefer small reviewable commits. Local implementation and verification do not authorize publishing, updating a live instance, or changing its schedules.

| Milestone | Deliverable | Depends on |
|---|---|---|
| M0 | Reconciled contracts, baseline regression suite, coverage map | Existing repository |
| M1 | Safe writes, durable replay, serialization, authorization, report accounting | M0 |
| M2 | Canonical topic registry and shared admission/backpressure rules | M1 |
| M3 | Compact archive, selective retrieval, reference-safe compaction | M1–M2 |
| M4 | Claim-specific evidence assessment and correction propagation | M1–M2 |
| M5 | Bounded adversarial research with execution opportunities | M2, M4 |
| M6 | Resilient daily/weekly orchestration, freshness, retrieval and synthesis | M1–M5 |
| M7 | Release discovery and explicit, resumable instance updates | M1; schemas from M2–M6 |
| M8 | Existing-instance migration, behavioral evaluations, live acceptance | M1–M7 |

No milestone is complete solely because a workflow document says the behavior exists. Conversely, a Python helper cannot independently establish semantic relevance or truth: semantic decisions must be evidence-linked, recorded, and behaviorally evaluated.

## 3. M0 — Establish baseline and trace every finding

- [x] Record the actual checkout commit and working-tree state. Reconcile any changes since the baseline before porting fixes.
- [x] Run the existing suite and repository validator. Import the earlier review regressions when available; otherwise reconstruct them from the failure descriptions below.
- [x] Preserve the earlier review output as historical evidence, not a new test result. No historical review bundle was present; regressions were reconstructed and a fresh review was performed. No overall quality percentage is inferred.
- [x] Update `AGENTS.md`, configuration examples, and architectural decisions to include these requirements.
- [x] Create `docs/hardening-status.md` mapping each requirement to implementation files, tests, and actual status: `PASS`, `FAIL`, `BLOCKED`, `NOT RUN`, or `PENDING`.
- [x] Establish schema-version and migration ownership before changing persisted records.

Remaining acceptance checkboxes are release-level gates, not a claim that local implementation is absent. Consult the evidence map for the distinction between passing local contracts, bounded assistant judgments and unrun live/human/repeatability checks.

### Review-to-work mapping

| Review finding | Required remediation |
|---|---|
| WP-P01: drift/backlog | M2 anchored graph and breadth controls; M3 archival; M6 budget-aware scheduling. |
| WP-P02: evidence authority | M4 claim-level support, independence and promotion policy. |
| WP-P03: opinion bubble | M5 challenge search and counterevidence handling. |
| WP-C01: stale generated writes | M1 base-snapshot preconditions and conflict preservation. |
| WP-C02: replay conflicts | M1 original-intent journal and restart-safe reconciliation. |
| WP-C03: keyword authorization | M1 affirmative user-turn authorization, negation and quotation cases. |
| WP-C04: omitted-but-reported findings | M1 represented/deferred report coverage and publication state. |
| WP-C05: stale metadata/lost claim identity | M1 lossless page serialization and synchronized metadata. |
| WP-C06: invalid index folder names | M1 explicit type-to-folder mapping. |
| WP-C07: cross-page conflicts/staleness | M4 dependency model; M6 risk-prioritized maintenance. |
| WP-C08: search reservation mistaken for success | M6 outcome-based monitoring coverage. |
| WP-C09: immediate retries/aborting stages | M6 durable backoff and isolated failure handling. |
| WP-C10: duplicate IDs/weak deduplication | M1 unique identities; M2 bounded semantic duplicate review and lineage checks. |
| Fake adapters versus real guarantees | M1 explicit capability boundaries; M8 observed live checks. |
| Labels instead of outcome assertions | M6 persistence integration tests; M8 quality and cloud evaluations. |
| Retrieval/applicability weaknesses | M4 claim applicability; M6 graph-aware retrieval; M8 curated evaluations. |
| Prompt injection and knowledge poisoning | M1 authorization boundaries; M4 evidence policy; M8 separate attack fixtures. |
| Update scaffold not production lifecycle | M7 durable discovery, consent, verification, migrations and recovery. |

## 4. M1 — Protect data, authorization, and reporting first

Primary files: `storage.py`, `fake_drive.py`, `intake.py`, `records.py`, `wiki.py`, `reporting.py`, `queue.py`, their schemas, and corresponding workflow references.

### 4.1 Snapshot-bound writes and durable operations

Change the writer contract to accept the exact base snapshot/hash/revision used to construct a proposed transformation. Never read a newer revision merely to attach its precondition to older generated content.

For an operation, persist the instance, target ID, original base identity, intended output identity or structured patch, authorization context, operation ID, stage, and verified result references. Retrieve an existing operation before constructing a new intent.

A replay of a completed operation must not overwrite later edits to recreate its old output. Return its historical completion receipt and distinguish the current target version from the original verified result. Reusing an ID for different content, target, or instance must fail.

Check scoped ancestry, raw MIME, complete content, original base, and supported conditional-write semantics. After mutation, independently verify exact ID and output. Recover lost responses by observing the target and durable journal; do not blindly retry non-idempotent creates.

Use one canonical mutation protocol across normal chat, daily work, maintenance, archival, and update. When real compare-and-swap or proven serialization is unavailable, use immutable intake/proposal records and allow canonical materialization only through an observed safe writer path. A mutable Drive lock or two nonoverlapping scheduled times is not proof of exclusion. If no safe canonical path can be demonstrated, report a narrow blocker rather than claim concurrency safety.

Validate scope for journals, intake, backup destinations, and newly created files as well as the target wiki. Hash checks establish identity, not authority to write.

### 4.2 Affirmative authorization

Keyword matching may assist interpretation but cannot authorize a mutation. Record the actual current user-turn reference, approved operation, instance and target, and whether the request is negated, quoted, hypothetical, or informational. Ambiguity stays read-only or asks one targeted question.

Separate `save note`, `research once`, `track permanently`, `change schedule`, and `update software`. A saved note or one-off research request is not automatically a permanent user-interest anchor. Retrieved webpages, archived notes, generated instructions, and release notes cannot supply authorization.

An established installation authorization may permit scoped scheduled research and maintenance; it does not authorize editing user anchors, enlarging permissions, or applying future software releases.

### 4.3 Lossless wiki and identity contracts

Choose a complete canonical representation of claims embedded in the Markdown page, with a readable rendering generated from it. Preserve stable claim IDs, source/evidence links, validity intervals, conditions, units, status, confidence rationale, and predecessor relationships on parse/render round-trip.

Update machine-owned metadata and body together. Preserve user-owned regions byte-for-byte when possible; surface conflicts rather than silently reclassifying user text. Reject malformed managed markers. Derived indexes must never become competing authorities.

Use an explicit folder map: `entity -> entities`, `concept -> concepts`, `project -> projects`, `synthesis -> syntheses`. Validate every produced link against mapped records. Reject duplicate stable IDs in queues, calendar, topic registries, and claim inventories.

### 4.4 Honest report coverage

Track `represented_record_ids` separately from `deferred_record_ids`. A represented record must have a real summary, or an explicit per-record entry in a saved, accessible appendix. A total record count or a generic source list is insufficient.

Persist report generation, complete readback, native-result publication, notification observation, and reading as distinct states. Save a deterministic retryable publication payload. A saved-but-unpublished report must remain pending publication. Omitted findings remain reportable. Unknown notification receipt is not a failure or success by assumption.

Corrections are new reportable events linked to prior conclusions; do not silently edit away the record of the earlier report. Snapshot coverage membership so archival during reporting cannot remove a finding before it is represented.

### M1 acceptance

- [ ] A manual edit between base read and mutation is preserved or produces a safe conflict.
- [ ] Same operation replay succeeds across fresh process objects without a duplicate effect or overwrite of later work.
- [ ] Lost create/write/finalization responses reconcile without duplicate files.
- [ ] Negative, quoted, informational and multilingual requests do not authorize writes or upgrades.
- [ ] Claim data round-trips; metadata and readable content agree; all generated links resolve.
- [ ] A fourth ordinary finding omitted from the executive summary remains explicitly represented or pending.
- [ ] Failed publication can be retried without redoing research; notification state remains separately observable.

## 5. M2 — Implement the three-level topic model and admission control

New components: `topics.py`, `admission.py`, `schemas/topic.schema.json`, registry parser/renderer, and an internal `skills/topic-governance/WORKFLOW.md`. Update queue, calendar, source, research and wiki contracts to reference stable topic IDs.

### 5.1 Authoritative scope file

Use `data/TOPICS.md` with these exact user-facing sections:

```markdown
# Topics

## User topics and interests

## Adjacent topics

## Peripheral topics
```

Keep machine-validated per-topic metadata in structured blocks under these sections, alongside short readable explanations. The active registry is authoritative. Generated JSON indexes and summaries are rebuildable from it and cannot be edited as independent scope databases. `SCOPE.md` retains purpose, project context and exclusions; it must not contain a conflicting independently editable topic taxonomy.

Each topic has: stable ID, label, aliases, classification, user-anchor IDs, parent IDs, direct-contribution statement, evidence/reason for classification, added/reviewed dates, lifecycle status, scope revision, and relevant user authorization. Peripheral topics also carry a fixed expiration checkpoint and `may_spawn_research: false`. Resolve expiry to the next distinct future scheduled maintenance occurrence when the topic is created; retries or topics created during maintenance must not reset it or recursively expire within the same occurrence.

Only an affirmative user tracking directive can add/edit/remove user anchors. Maintenance may suggest such a change, never enact it. Existing explicit configuration can be migrated as user-confirmed history where that provenance is established; a model-inferred topic must not be relabeled user-authored.

Configured daily monitoring references user-anchor IDs rather than maintaining a second editable list of topic names. Default initialization monitors all active user anchors; preserve explicit user monitoring choices. The agent cannot silently disable mandatory primary-topic coverage.

### 5.2 Classification and lifecycle are separate

| Classification | Admission rule | Expansion |
|---|---|---|
| User | Explicit user interest/goal. | Follow-ups may qualify independently. |
| Adjacent | Direct, recorded contribution to at least one active user anchor. | May spawn eligible adjacent/peripheral questions. |
| Peripheral | Useful only through an adjacent topic; no established direct anchor contribution. | Terminal: no autonomous follow-up investigations or recurring refresh. |
| Outside scope | No qualifying anchor relationship, or violates exclusions. | Do not admit automatic research. |

Lifecycle states such as `active`, `provisional`, `archived`, and `retired` must not change the meaning of classification. Archived records cannot act as graph-expansion anchors.

An adjacent topic must be relevant directly to the user's anchor, not merely to another adjacent topic. Promotion from peripheral requires new recorded evidence of that direct contribution. Popularity, number of mentions, urgency, age, or accumulated notes are insufficient.

Classify the actual question, not only its assigned topic ID. Ancestor relabeling, calendar origin, a new run/root ID, semantic duplicate merging, reactivation, or an urgent label cannot reset lineage. Maintain all causal parents and validate any lower inherited score instead of blindly selecting a minimum. Reject cycles and unknown references.

Counterevidence and critiques directly affecting a user goal are in scope even when they contradict the user's preferred thesis.

### 5.3 Shared admission decision

All automatic candidates from monitoring, discovery, research, calendar and maintenance pass the same decision function, before enqueueing and again before execution after scope changes.

Return a structured disposition: `admit`, `merge`, `defer_capacity`, `archive_candidate`, `reject_scope`, or `needs_user_scope_decision`. Include scope revision, original user anchors, proposed contribution, classification, causal lineage, evidence of novelty, priority/urgency rationale, and capacity checks.

A peripheral investigation may inspect sources and perform bounded counter-checks necessary to answer its current question. It cannot emit further queued research, recurring calendar obligations, or fresh roots through another workflow. Deeper unanswered questions remain labeled uncertainties in its compact record.

An explicit one-off user request does not change permanent scope. If a temporary exception is necessary, bind it to that request/question with no automatic descendants; do not treat it as a reusable user anchor.

### 5.4 Breadth controls and backpressure

Initial tunable defaults below are proposed engineering starting points, not empirically calibrated optimal values. Record them in configuration and validate positive integer bounds. Do not ask the user to hand-edit them during installation.

```yaml
topic_governance:
  max_active_adjacent_topics: 30
  max_active_peripheral_topics: 15
  peripheral_expiry: next_weekly_maintenance
  archive_summary_target_words: [100, 200]
queue_admission:
  max_active_automatic_items: 50
  max_new_automatic_roots_per_day: 5
  revalidate_pending_after_days: 14
  automatic_candidate_deferral_days: 30
expansion:
  child_priority_increment: 20
  max_children_per_research: 3
  preserve_expansion_priority: true
```

Count pending, retrying, in-progress and blocked automatic obligations toward capacity. Count their derived/calendar/validation forms too. At capacity, merge duplicates, defer or compact less useful automatic candidates; never silently replace an in-progress operation or discard explicit user work. User requests exceeding immediate capacity receive a durable pending-capacity receipt and visible backlog state. Do not claim total storage is bounded when retained user requests/history are not.

Use ageing and per-anchor fairness to stop recurring fresh discoveries from monopolizing service. Reassess novelty, relevance and expected contribution before re-admission. Deferred records are inactive and cannot spawn research.

Rename text-normalization deduplication to describe what it actually does. Add bounded semantic candidate comparison over question, entity/version, conditions, evidence novelty, time window and refresh occurrence. Preserve legitimate later refreshes. Record merge decisions and lineage; do not equate paraphrase detection with automatic factual equivalence.

### M2 acceptance

- [ ] An irrelevant locally adjacent chain is rejected; a useful distant scientific connection to a pump project is admitted.
- [ ] Maintenance cannot create user anchors or promote a topic without direct anchor justification.
- [ ] Peripheral research cannot enqueue children through any origin or calendar route.
- [ ] Repeated roots, paraphrases, urgency and merged ancestry cannot replenish expansion depth.
- [ ] Sustained arrival overload stays within configured active automatic limits and exposes deferrals.
- [ ] Explicit user requests are preserved; a one-off request does not become permanent tracking.
- [ ] A counterexample remains in scope because of relevance, not favorable sentiment.

## 6. M3 — Compact and archive instead of forgetting

New components: `archive.py`, `schemas/archive-topic.schema.json`, `skills/archive/WORKFLOW.md`, and derived archive retrieval indexes.

### 6.1 Storage layout and archive record

```text
data/
  TOPICS.md
  wiki/
  archive/
    topics/<topic-id>.md
    indexes/                  # Derived, partitionable lookup; not routinely loaded in full
  state/
    scope-changes/
    archive-operations/
```

Retain one canonical compact capsule per distinct archived topic. Target 100–200 summary words, excluding structured metadata; preserve uncertainty and applicability qualifiers rather than blindly truncating at a word count.

Required metadata: stable topic ID, title/aliases, previous classification, original user anchors/parents, scope revision, creation/last-investigation/archive dates, reason for archival, key claim/evidence references, negative findings, unresolved uncertainty, known applicability limits, research lineage/expansion score, reactivation conditions, and content/schema version.

The summary must explain what was learned and why research stopped. Capacity exclusion is not evidence of irrelevance. A preliminary result is not upgraded to verified merely because it is summarized.

### 6.2 Weekly resolution of peripheral topics

At the next scheduled maintenance checkpoint, each peripheral topic is resolved to one of:

1. Promote to adjacent only with a documented direct user-interest contribution.
2. Integrate useful supported findings into an existing retained page, then archive the peripheral topic.
3. Archive its metadata and brief summary, including negative/unresolved results, without adding a retained active page.

Maintenance may add, edit, demote, merge and archive adjacent/peripheral topics under the admission rules. Any new candidate is still subject to capacity and terminal-peripheral restrictions. Updating a mention or missing a maintenance run cannot renew expiration indefinitely. Expired peripheral work becomes ineligible for new automatic attempts even before the next compaction succeeds.

### 6.3 Reference-safe archival transaction

Before compaction, inventory inbound claim, source, report, queue, calendar and user-note references. Save and verify the archive capsule, preserve required evidence and aliases/redirects, update active indexes and topic membership, then retire automatic queue/calendar obligations with reason codes. Resume this sequence from durable checkpoints after interruption.

Preserve user-authored material and evidence supporting active or archived claims. Do not delete source locators or qualifiers needed to audit the compact summary. Historical reports remain historical artifacts; link their old topic references to the archive capsule. Unreported findings must be represented or explicitly deferred before their working records are compacted.

Do not retain complete peripheral dossiers indefinitely by silently placing them in another archive folder. Retain referenced evidence and a bounded recovery snapshot where necessary; compact disposable, unreferenced bulk records under an explicit policy. Never delete the only viable recovery copy during an incomplete transaction.

Preserve a canonical raw file's Drive ID when it is compacted or moved where supported. If a new capsule is necessary, maintain a verified stable-ID redirect and one authoritative destination; do not create two editable versions. Renaming or moving must use observed connector support, not guessed paths.

### 6.4 Retrieval and reactivation

Archived topics have no scheduled research, no children, no routine semantic-audit obligation and no effect on expansion eligibility. Retrieve compact records selectively for a user question, deduplication, or a materially relevant new finding. Label freshness and archive status in answers.

Reading an archive record never reactivates it. Reactivation requires an explicit user request, changed user goals, or genuinely new evidence of direct relevance, plus a recorded admission decision, existing lineage, and available capacity. Repeated rediscovery is not novelty. A new explicit user anchor is recorded as such; automatic reactivation may not invent one.

An archive summary is not an independent source confirming its own underlying research. Maintain lightweight archive integrity checks separately from rotating active-topic semantic review. Retention of indefinitely many unique summaries still grows historical storage; report bytes/counts and avoid claims of an absolute lifetime bound.

### M3 acceptance

- [ ] Peripheral topics become compact searchable capsules without continuing automatic obligations.
- [ ] Useful findings and user notes survive; source and report references resolve after compaction.
- [ ] Negative findings, uncertainty and original lineage survive summary round-trip.
- [ ] Retrieval, repeated mentions and failed maintenance do not reactivate or extend expiry.
- [ ] Archival interruption at each checkpoint is recoverable without lost data or duplicate authority.
- [ ] An archive corpus much larger than the active wiki is not fetched in full on ordinary daily runs.

## 7. M4 — Define source authority and claim confidence

Extend `SourceRecord`, `Claim`, source/research/wiki schemas and add `evidence.py` plus an internal evidence-review workflow.

### 7.1 Keep three dimensions separate

Research priority determines which question is investigated. Source/evidence assessment describes the quality and applicability of support. Claim confidence summarizes what the evidence establishes. Do not derive any of these automatically from the other two.

Define a claim-context source selection policy: prefer direct, inspectable evidence suited to the proposition; assess method, independence, conditions and provenance; use secondary reporting for context and discovery; treat unsupported/social material as leads unless independently established. These are claim-dependent preferences, not an absolute domain trust score. A credible technical report can be inapplicable, and an official commercial announcement can establish what was announced without establishing independent performance.

User statements are authoritative for the user's goals and preferences. Their empirical assertions retain user-note status until evaluated.

### 7.2 Evidence relationships

An evidence link must identify a resolvable, actually inspected source, exact passage/table/section locator, role (`supports`, `contradicts`, `context`), evidence-origin group, method/directness, conflicts of interest, uncertainty, applicability conditions and assessment reason.

Retain publication, revision, retrieval and event dates separately. Track publisher versus underlying evidence origin. Unknown independence must remain unknown; distinct URLs or publishers do not prove independent origin.

Use a source-dependence graph or explicit origin groups to detect syndication, common press releases, copied datasets and wiki self-corroboration. A summary derived from source A remains dependent on A even when quoted elsewhere.

### 7.3 Claim state and correction rules

Implement explicit states such as `reported`, `supported`, `disputed`, `uncertain`, `hypothesis`, `user_note`, and `superseded`. Legacy `verified` claims migrate without unjustified confidence: preserve original text/status history and require evidence-policy re-evaluation before continuing a strong status.

Promotion requires inspected support for the actual proposition, applicable conditions, and an assessment rationale; independent corroboration or reproducibility is required where the claim type warrants it. A source ID alone never authorizes promotion. The validator checks required evidence artifacts and references, not truth from a numeric score.

Maintain claim-to-source and claim-to-claim dependencies. A correction/retraction invalidates affected support, triggers dependent conclusion review and produces a reportable correction. Preserve unresolved disagreement and temporal changes instead of flattening everything into the newest assertion.

### M4 acceptance

- [ ] Ten copies of one announcement remain one origin; unexamined/nonexistent IDs cannot support promotion.
- [ ] Manufacturer announcement, measured performance and project suitability remain distinct propositions.
- [ ] An applicable independent measurement is evaluated on its merits, not outvoted by copied articles.
- [ ] A strong irrelevant source does not dominate relevant evidence merely because of its publisher.
- [ ] Source correction/retraction reaches dependent claims and appears in the next report.
- [ ] Archived summaries and wiki pages do not become independent confirmation of themselves.

## 8. M5 — Make research actively challenge conclusions

Add `skills/adversarial-review/WORKFLOW.md` and structured challenge records; expose no additional installed skill to the user.

For consequential conclusions, record the strongest alternative explanation, falsification conditions, planned counterevidence queries, sources inspected, strongest relevant counterevidence found, applicability limits, and how the conclusion changed. Challenge search has explicit states: `not_required`, `not_searched`, `searched`, `partial`, or `blocked`, each with coverage/reason.

Fit a bounded counter-check inside the current investigation or primary-monitoring source allowance. If a deeper challenge is needed, enqueue it under the same topic/admission/lineage/budget rules. A terminal peripheral question cannot spawn a deeper challenge task; record its unresolved limitation and avoid confident promotion.

Weekly maintenance identifies high-impact, single-origin, stale, disputed, or never-challenged claims and proposes validation work. Configure one of the first five daily queue slots as available to overdue validation/challenge work when eligible, subject to genuinely urgent work taking precedence. Record starvation and reason; do not fabricate priority 0 to force validation. This selection lane changes scheduling fairness, not the total attempt allowance. Main-topic monitoring remains independent.

Avoid false balance: unsupported criticism receives no mandatory equal weight, and absence of found counterevidence is not proof of truth. A separate critic prompt may help, but only evidence and tested behavior establish the quality of the challenge.

### M5 acceptance

- [ ] Relevant counterevidence is actively sought without the user having to supply it.
- [ ] An attractive but unsupported thesis is revised when stronger opposing evidence is found.
- [ ] Weak criticism does not displace strong support to satisfy a quota.
- [ ] Blocked searches and unsearched claims are not described as successfully challenged.
- [ ] Eligible overdue challenges receive real execution opportunities without violating priority-0 or 5/10 constraints.

## 9. M6 — Repair and integrate daily/weekly operations

### 9.1 Actual persistence, not phase labels

Replace order-label-only outcomes with explicit phase results and durable artifact receipts. Main-topic monitoring, queue work, synthesis, report saving and native publication must either execute through the observed host bridge or record an accurate blocker. Helper simulations remain useful but cannot claim host execution.

Daily sequence:

```text
Recover operations; read exact bindings, runtime, config and current scope
  -> Reconcile authorized intake and scope changes
  -> Calendar: due/overdue refreshes and visible events
  -> Mandatory per-primary-topic update research outside queue budget
  -> Shared candidate admission and bounded adjacent discovery
  -> Up to 5 ordinary / 10 urgent-qualified queue attempts
  -> Evidence adjudication, bounded challenge and cross-project synthesis
  -> Save/read back findings, corrections, report and coverage membership
  -> Publish native result; persist delivery state
```

Weekly sequence:

```text
Read exact state and recover unfinished work
  -> Check releases and persist any update notice independently of audit success
  -> Structural integrity checks with recorded inventory coverage
  -> Re-evaluate adjacent/peripheral relevance; compact expired branches
  -> Risk-prioritized and rotating claim/contradiction/freshness review
  -> Admit eligible validation work; reconcile indexes and obligations
  -> Save maintenance report, update notice and native completion result
```

A release metadata check is bounded administrative work outside the research queue. Do not create a third recurring task just for checking versions.

### 9.2 Durable attempts and real monitoring coverage

Persist slot reservations before work, attempt result, future retry time, and terminal status. Resuming an existing attempt reuses its reservation; a later retry consumes a new one. Use bounded configurable backoff and max attempts; never immediately exhaust all retries in a tight loop.

Track search reservation, invocation, successful result, fetched/inspected sources, query coverage and failure independently. `no_material_update` requires actual successful coverage, not just a reserved query count. Partial coverage must remain visible; do not advance a topic's successful watermark over failed intervals.

Isolate calendar, topic, research, synthesis and publication failures. A failed topic should not suppress other independent topics or available events. Stop unsafe mutation without losing already saved evidence. Produce a partial report when possible; do not disguise provider failure as a quiet day.

### 9.3 Calendar correctness and scope

Re-evaluate refresh eligibility against current topic state; archived/peripheral topics cannot acquire recurring obligations. Process overdue occurrences idempotently without generating unlimited catch-up rows for repeated equivalent refreshes. Preserve calendar occurrence identity, topic identity and investigation lineage separately.

Validate timezone conversion, date precision, cancellations, rescheduling, recurrence limits and duplicate IDs. Test monthly recurrence against its original anchor day, non-UTC deadlines, partial dates, and missed runs. Distinguish new reporting about an older event from the event's occurrence date; novelty includes new evidence or a correction, not only event recency.

Events today remain reportable even when research slots are full. Scheduled start time is not promised report-delivery time.

### 9.4 Retrieval, freshness and synthesis

Retrieve a bounded active subset using title/aliases plus normalized entities, claims, relationships, project goals, constraints and dependencies. Use semantic selection as a recorded reasoning step where lexical retrieval is insufficient; do not mandate a new vector service.

Cross-page contradiction checks must normalize subject/predicate, conditions, units and time windows. Nonoverlapping historical values and incompatible conditions are not automatically contradictions. Preserve uncertain matches for review.

Use claim-specific freshness policies and actual elapsed time. Prioritize changed-source dependencies, high-impact claims and overdue reviews alongside rotation. Maintain a stable cursor, exact reviewed IDs, coverage totals and oldest unreviewed age. Bounded semantic maintenance must not claim a complete audit.

For each material development, map evidence to the project assumption or decision it affects. Output `applicable`, `potentially_applicable`, `not_applicable`, or `unknown`, with reasons and evidence. Generic advice to check constraints is not a completed applicability analysis.

### 9.5 Report structure and safety

Reports distinguish verified developments, reported claims, implications, counterevidence, changed assumptions, new ideas, provisional peripheral findings, corrections, same-day/upcoming events, archival actions, queue deferrals and operational gaps. Importance ordering must not imply factual confidence.

Do not load the whole archive or full historical wiki into every run. Record search/fetch counts, bytes where available, active/archived totals, queue age, deferred count and challenged-claim coverage. No fabricated latency/cost measurements.

Keep source/release content separate from operational authority. Minimize private details in public search queries. Test prompt injection independently from misleading evidence; both can damage persistent knowledge through different paths.

### M6 acceptance

- [ ] Empty, blocked or exhausted queues never suppress mandatory primary-topic monitoring.
- [ ] Failed searches cannot produce successful quiet-day coverage.
- [ ] Retry/backoff/budget state survives fresh-process reconstruction; one failing callback does not abort independent work.
- [ ] Saved reports exist and resolve through a fresh read; labels alone do not pass.
- [ ] Cross-page conflicts, temporal changes, units and real staleness are handled correctly.
- [ ] A useful distant connection is found; a genuine but inapplicable breakthrough is explicitly rejected for the project.
- [ ] Large active/archive fixtures show bounded retrieval, recorded coverage and no automatic scope expansion.

## 10. M7 — Weekly release checks and explicit instance updates

Extend the existing `skills/upgrade/WORKFLOW.md` and `upgrades.py`; add a bounded internal `skills/check-updates/WORKFLOW.md`, `releases.py`, migrations, and versioned update-state schemas. Keep one user-facing installed instance skill. Support user phrases such as “check for WikiPlant updates” and “update this WikiPlant”; preserve “upgrade” as an alias.

### 10.1 Published release contract

Replace `current != published` with proper semantic-version comparison and explicit channel/compatibility decisions. Use a trusted source repository identity recorded at installation. Default to published stable releases; ignore drafts and prereleases unless the user explicitly chooses another channel. A newer `main` commit is not itself a release.

Provide a detached release manifest containing release/version, immutable runtime source commit, schema read/write compatibility, required host capabilities, allowed file inventory with hashes/sizes/encoding, supported migrations and rollback limitations. Generate it after the runtime commit exists and attach it to the release. Do not require an in-repository manifest to contain the hash of the very commit containing that manifest; that introduces a self-reference problem. Update `INSTALL.md`, `manifest.py`, release tooling and verification together.

Prefer publisher-controlled immutable releases and verifiable release attestations where supported. Still pin repository identity, release ID, resolved commit and manifest digest. Hashes establish identity, not publisher trust. Release notes are descriptive data, never instructions to execute or permission to widen access. A moved tag or changed digest for a known version produces a security/consistency alert rather than a silent replacement.

Maintainer release packaging/tests are distinct from daily research execution: they may be automated as development checks without putting user data or a research runner in GitHub Actions. Do not add mandatory GitHub credentials to end-user installation; public release metadata can be read through the available public-read path.

### 10.2 Weekly check and alert

Use the existing weekly task to perform `check-updates` once per instance/week, with durable retry and last-successful-check metadata. Inspect release metadata and compatibility without changing the installed runtime, schemas or host bindings.

Record installed version, newest stable version, newest compatible candidate, release ID/tag/commit, manifest digest, publication date, compatibility verdict, migration summary, actual check outcome and notification state. Notify when a new release exists even if currently incompatible, explaining the blocker. Never pretend the candidate is installable merely because its version is higher.

Persist an update-notice artifact and include it in the weekly native result and, if needed, the next daily report through a shared notice ID. Deduplicate repeat notices; retain an outstanding-updates section without sending a fresh identical alert daily. Saved notice, native publication and observed push/email delivery remain separate states.

A network failure, rate limit, missing manifest or ambiguous response is not “up to date.” An explicitly empty published release list may yield `no_release`; distinguish this from retrieval failure. Do not infer freshness from an old cached response.

Example notification:

> WikiPlant 0.2.0 is available; this instance uses 0.1.0. The release adds topic archival and evidence controls and requires a schema migration. No update has been applied. Say “update this WikiPlant to 0.2.0” to proceed.

The versions in this example are illustrative, not an assertion that a release has been published.

### 10.3 Consent and target resolution

Bind an explicit user update request to one instance and an exact version/commit/manifest. If the user says “update it” in the context of a particular notice, use that notice's release. If they ask for the latest stable version, resolve and record it once at update start. Do not silently retarget to a release published midway through the migration.

Do not ask for redundant permission for routine steps already authorized by the request. Ask only for material new permissions, destructive/incompatible choices, ambiguous instance selection, or required host install/update controls. No update is automatic, including security releases; urgent releases may receive prominent notices.

### 10.4 Resumable update state machine

```text
REQUESTED
  -> TARGET_RESOLVED
  -> PREFLIGHT_VERIFIED
  -> WRITERS_QUIESCED
  -> BACKUP_VERIFIED
  -> RUNTIME_STAGED
  -> MIGRATION_VALIDATED
  -> DATA_MIGRATED
  -> HOST_BINDINGS_VERIFIED
  -> SMOKE_TESTED
  -> ACTIVATED
  -> COMPLETE
```

Each phase has durable input/output identities, success evidence and recovery behavior. A failure produces a precise blocked/recoverable state, not false completion.

Preflight checks current versions, schema compatibility, available tools, ownership/customizations, pending operations, backup space and migration path. Pause only the bound instance's tasks and prove in-flight writers are drained. A pause flag alone does not stop a running task. Queue new user submissions as durable intake until activation; do not lose them or have old/new runtimes process them concurrently.

Create and verify a backup of every mutable file affected by migration, runtime pointers, installed skill metadata, task bindings, configuration and active/archived indexes. Retain prior runtime releases. Stage new runtime files under a new versioned path; never overwrite the current release in place.

Validate migrations against a detached snapshot, then migrate with exact-ID, snapshot-bound writes and restartable checkpoints. Preserve user anchors, projects, notes, archives, evidence, queue priorities/lineages/attempts, calendar occurrences, pending reports, locale/schedules and instance identity. Do not rerun initialization or reset budgets.

Merge configuration defaults by ownership. Release-owned files may update; user overrides require a three-way merge or explicit conflict. New scope limits do not silently delete existing work. Record proposed reclassifications; do not manufacture user consent or factual confidence during migration.

Use supported host operations to update the existing private skill and task prompts/bindings. A modified `SKILL.md` on Drive is not proof of an installed-skill update. Verify a fresh invocation and inspect the actual bound task IDs/prompts. Preserve the same two tasks where supported; if replacement is unavoidable, verify old tasks are disabled before enabling replacements. Do not create a second daily/weekly pair accidentally.

During an incomplete update, only the explicitly authorized updater/recovery path may recognize both pinned from/to release identities. Ordinary research handlers stay paused or reject a mixed binding; do not globally relax runtime integrity checks to get through migration.

Activate only after schema/reference checks, data-count reconciliation, raw readbacks, a read-only wiki query, archive lookup and installed-binding verification succeed. Resume bound tasks and merge pending intake exactly once. Produce a saved update report with before/after versions and observed evidence. Actual future scheduled execution remains pending until it happens.

### 10.5 Rollback and failure handling

A code-only rollback is permitted only when the previous runtime can read the current data schema. Otherwise perform a validated reverse migration/forward repair or remain paused; do not point an old runtime at incompatible data and claim recovery.

Never restore an old whole-instance backup over research or user submissions created later. Preserve durable intake and operation history and reconcile post-backup changes. Failure at every stage must either leave the previous verified version usable or a clearly paused, recoverable instance.

Maintain a bounded recovery-backup policy after successful verification, but never compact the only recovery state of an incomplete upgrade. Export remains a detached private copy, not another synchronization backend.

### M7 acceptance

- [ ] Same/older versions are not upgrades; `0.10.0` sorts after `0.9.0`; draft/prerelease/channel and incompatibility cases are handled explicitly.
- [ ] Weekly discovery saves/notifies once per new release and makes no runtime changes without consent.
- [ ] Release/API failure does not produce “up to date”; changed known-version identity produces an alert.
- [ ] Detached manifest pins real source bytes without self-referential commit requirements.
- [ ] User request updates exactly one instance, preserves all required state, and does not duplicate tasks or reseed research.
- [ ] Lost responses and interruption at every phase resume deterministically from Drive state.
- [ ] Unsupported host skill update stops at a precise handoff instead of reporting completion.
- [ ] Rollback compatibility and later data preservation are demonstrated, not assumed.

## 11. M8 — Migrate existing instances without losing knowledge

Treat the remediation schema transition as a release migration, not an ad hoc reset. Implement the updater foundations before exercising this migration on any live instance.

Inventory and back up the existing registry/config, wiki, source records, queue, calendar, reports, task bindings and notes. Produce a dry-run migration report with schema transitions and unresolved references.

Build user anchors from demonstrably user-approved existing configuration, and preserve their provenance. Classify the remaining topics against those anchors; inferred classifications are agent decisions. Preserve unresolved topics provisionally and block autonomous expansion until resolved instead of silently inventing scope.

Retain stable IDs and Drive IDs where possible. Map legacy claim statuses conservatively, retain their prior assessment, and queue revalidation within the new admission policy. Do not manufacture evidence locators, independence groups, timestamps or challenge-search results.

Compact peripheral legacy content through the archive transaction, preserving cited evidence, report references and user material. Do not automatically archive an explicit unresolved user request. Preserve every attempt counter, deadline, occurrence marker and original lineage.

Compare before/after counts and explain every merge, reclassification, compaction, redirect or deferred item. Re-running the migration must produce no further logical changes. Verify old/new reader compatibility and backup recovery before activation.

## 12. Test strategy and release gates

### Deterministic and property tests

Retain all existing valid controls, add the review regressions, and test schema round-trips, stable-ID uniqueness, graph invariants, terminal peripheral behavior, active-capacity bounds, monotonic lineage constraints, exact budget accounting, scope revision checks, delivery coverage and semantic-version ordering. Use fake clocks for expiry/freshness/recurrence/backoff tests.

Property tests should verify that retries, reordering, paraphrases, duplicates, archive/reactivation cycles and changed timezones cannot create extra attempts, independent evidence, user authorization or peripheral descendants.

### Stateful integration and failure injection

Reconstruct every run from serialized records in a fresh process. Test paginated inventories, truncated content, missing permissions, partial writes, lost responses, concurrent edits, two instances, scope changes mid-run, archival during reporting, and updates with pending commands. Assert actual persisted content and receipts, not phase names.

Exercise both a strong conditional adapter and a deliberately weak adapter with no global idempotency table. The latter must demonstrate the real safe fallback or remain blocked. Do not grant fake capabilities merely to pass integration tests.

### Behavioral evaluation corpus

Create curated, synthetic evidence bundles and expected decision criteria for: useful cross-domain connection; irrelevant adjacent chain; oversized backlog; archived duplicate rediscovery; vendor assertion versus measurement; copied sources; correction/retraction; false but attractive thesis; strong support with weak criticism; misleading but non-malicious evidence; malicious source instructions; private-query minimization; applicable versus inapplicable project results; and multilingual read/write intent.

Evaluate conclusions, evidence usage, uncertainty and permitted actions, not exact prose. Give critical safety cases zero tolerance for unauthorized mutation, invented support, evidence self-corroboration or hidden data loss. Record model/version and run IDs; repeat nondeterministic quality scenarios and retain failures. Human review of curated rubric outcomes is separate from automatic structural checks.

### Live Work checks

Only in a newly and explicitly approved sandbox: install from a release URL; verify one personalized installed skill; seed within budget; test ordinary-chat read/save; observe a genuinely automatic daily run; change the actual canonical raw input after scheduling; verify exact-ID freshness; exercise overlap/recovery; observe weekly compaction and release notification; explicitly request an upgrade; test migration and recovery; verify a fresh invocation and later scheduled run.

Keep PoC feasibility evidence, local regression results, live storage outcomes, host installation, native publication and observed notifications as separate evidence classes. Do not reuse private PoC identifiers in public fixtures. Without the required live tools, provide the minimal Work handoff and mark those gates `NOT RUN` or `BLOCKED`; continue feasible local implementation.

### Definition of done

- [ ] Every review finding and new requirement maps to implementation and tests in `docs/hardening-status.md`.
- [ ] All deterministic/integration regressions pass with real outcome assertions.
- [ ] Behavioral evaluations demonstrate controlled scope, evidence quality and meaningful applicability analysis.
- [ ] Historical peripheral knowledge survives compactly without automatic obligations.
- [ ] Existing-instance migration is repeatable, auditable and recoverable.
- [ ] Weekly update checks alert, never self-install; explicit updates verify real host bindings.
- [ ] Documentation and schemas agree; public releases contain no instance data; runtime dependency closure is checked.
- [ ] Live outcomes are reported honestly and unresolved gates block a production-ready claim.

## 13. Suggested file changes

| Area | Existing files to revise | New components as needed |
|---|---|---|
| Authority/integrity | `storage.py`, `intake.py`, `records.py`, `fake_drive.py` | Durable operation schemas and real-capability contract tests |
| Scope/queue | `queue.py`, `config.py`, `setup.py`, `installer.py`, `calendar.py` | `topics.py`, `admission.py`, topic templates/schemas |
| Archive | `wiki.py`, maintenance/query workflows | `archive.py`, archive schema, compact capsule template |
| Evidence | `records.py`, source/research/wiki schemas | `evidence.py`, evidence-link/challenge schemas |
| Execution | `monitoring.py`, `orchestrator.py`, `maintenance.py`, `reporting.py` | Durable phase/result adapters and coverage indexes |
| Updates | `upgrades.py`, `manifest.py`, `skillgen.py`, `schedules.py`, `INSTALL.md` | `releases.py`, `migrations/`, check-updates workflow, update notice/state schemas |
| Verification | Existing unit/integration suites, validator, docs | Behavioral evaluation bundles, release/migration failure matrix |

Keep existing module names where sensible. Do not create a second competing subsystem just to match this table. Include new runtime dependencies in the runtime manifest and verify imports from the staged runtime alone, without development-only files accidentally masking missing modules.

## 14. Codex execution handoff

```text
Read AGENTS.md, PLAN.md, and HARDENING_PLAN.md completely.

Implement HARDENING_PLAN.md against the existing WikiPlant repository.
Reconcile the new owner requirements into AGENTS.md and the original
plan first, then follow milestones M0 through M8 in dependency order.

Start by reproducing the reviewed correctness defects and fixing data
integrity and authorization. Do not replace the Work + Drive architecture.
Implement code, schemas, internal workflow instructions, tests, migration,
release packaging, weekly update notices, and explicit user-driven updates.

Preserve one customized installed skill per instance, daily main-topic
monitoring outside the queue budget, 5/10 attempt accounting, terminal
peripheral topics, compact archival memory, and user-owned scope anchors.

Use actual persisted artifacts as test outcomes. Keep local, behavioral,
and live cloud evidence separate. Never weaken a regression merely to
make the current behavior pass. Never fabricate a source, authorization,
installed skill reference, task ID, update completion, or live test result.

Work milestone by milestone, maintain docs/hardening-status.md, run
applicable tests, and record assumptions and remaining blockers. Do not
publish releases, push changes, alter permissions, or mutate a live Drive
instance unless separately authorized for those actions. When a host-only
step is unavailable, write its precise minimal Work handoff and continue
other feasible implementation work.
```

## 15. Recommended Codex model and reasoning effort

Recommendation for this project: **GPT-6 Astra with Extra High (`xhigh`)** for the initial cross-cutting implementation and final adversarial code review. This is a judgment based on the task's interacting persistence, authorization, lineage and migration invariants, not a benchmark run on WikiPlant.

Use `high` for narrower follow-up milestones after contracts are stable. A lower-cost alternative is **GPT-5.6 Sol with `high`**, with an Astra `xhigh` review of storage, migration and release activation. Avoid using Max for every edit; reserve additional effort for unresolved difficult failures rather than assuming it replaces tests.

The current official model guidance lists Astra and Sol for Codex and describes High/Extra High as suited to difficult multistep work. Availability remains account/client dependent. Verify the actual picker and current session rather than assuming an API model ID is accessible in every account.

```bash
# Main implementation / cross-cutting review
codex -m gpt-6-astra -c 'model_reasoning_effort="xhigh"'

# Lower-cost alternative for scoped implementation milestones
codex -m gpt-5.6-sol -c 'model_reasoning_effort="high"'
```

Use a fresh reviewer session for the final regression/security review. Parallelize independent tests or evidence-schema work only after shared contracts are fixed; do not let several agents concurrently redesign the same state machine.

## 16. Source and evidence notes

Repository observations are based on the pinned source and the prior review. This document prescribes behavior; it does not certify implementation success. The old review output in the accompanying bundle is historical and has not been rerun while preparing this plan.

Primary references checked on 2026-09-10:

```text
Repository baseline:
https://github.com/Kabutojira/WikiPlant/tree/c5907ca3fb2d44df2f73ce0b3202909f548e7ef0
Existing updater scaffold:
https://github.com/Kabutojira/WikiPlant/blob/c5907ca3fb2d44df2f73ce0b3202909f548e7ef0/scripts/wikiplant/upgrades.py
Existing upgrade workflow:
https://github.com/Kabutojira/WikiPlant/blob/c5907ca3fb2d44df2f73ce0b3202909f548e7ef0/skills/upgrade/WORKFLOW.md
Codex models:
https://learn.chatgpt.com/docs/models
Codex reasoning-effort configuration:
https://learn.chatgpt.com/docs/config-file/config-reference
Codex commands/model selection:
https://learn.chatgpt.com/docs/developer-commands?surface=cli
Astra reasoning levels:
https://developers.openai.com/api/docs/models/gpt-6-astra
GitHub public release API:
https://docs.github.com/en/rest/releases/releases
GitHub immutable release guarantees:
https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases
```
