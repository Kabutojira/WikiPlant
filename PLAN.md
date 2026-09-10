# WikiPlant — implementation plan for Codex

Specification revision: 2.0 · 2026-09-10
Companion: `AGENTS.md` is authoritative for product constraints.  
Delivery: a public, domain-neutral scaffold and a tested repository-URL installer for private, Drive-backed research instances.

This is an implementation specification, not a claim that its components already exist. Check milestones only after implementing them and recording evidence. The previous Work + Drive PoC establishes the selected feasibility baseline; it does not establish production reliability or the new installer.

The approved [HARDENING_PLAN.md](HARDENING_PLAN.md) now governs implementation in M0–M8 order. The v1 contracts and checked milestones below describe the original baseline, not hardening acceptance. V2 replaces editable primary-topic names with references to user anchors in `data/TOPICS.md`, adds shared scoped admission, terminal peripheral expiry and compact archival memory, requires snapshot-bound replay-safe writes and affirmative operation authorization, adds claim-specific evidence/challenge controls, separates represented/deferred report coverage, and uses detached release manifests and verified resumable upgrades. Existing data migrates conservatively; no legacy status or inferred topic becomes user authorization or verified evidence. See [docs/hardening-status.md](docs/hardening-status.md) for current contracts and actual evidence.

## 1. Approved product contract

| Area | Required behavior |
|---|---|
| Product | WikiPlant: continuously researched, linked understanding and project-specific implications. |
| Distribution | Public GitHub scaffold; an end user gives its URL to cloud ChatGPT Work. |
| Storage | Google Drive only; raw Markdown, CSV, JSON, and YAML, not converted Docs/Sheets. |
| Production runtime | Native scheduled cloud ChatGPT Work. No external research runner or GitHub operational workflows. |
| Instance interface | One private, topic-customized installed skill per independent WikiPlant instance. |
| Installation | One consolidated setup exchange plus unavoidable host authorization/installation actions. Work performs copying, mapping, configuration, initial research, and schedule creation. |
| Runtime copy | Self-contained operational snapshot, pinned to a release/commit with hashes. |
| Configuration | Ask once for missing topics/goals, Drive destination, language/timezone, and daily/weekly scheduling. English and UTC defaults; times are not hard-coded. |
| Initial research | At most 5 initial investigations, resumable and separately metered. |
| Main-topic coverage | Search/update every configured primary topic every day, **outside queued-research slots**. |
| Queued work | 5 ordinary daily attempts; additional priority-0 attempts may increase the total to 10. |
| Expansion | +20 inherited expansion score; reject >100; maximum 3 selected follow-ups per investigation; urgency cannot reset lineage. |
| Exploration | Proactively investigate useful adjacent areas and generate new ideas tied to the instance's goals. |
| Calendar | Events and future research refreshes; due/overdue occurrences enter the queue; relevant today's/upcoming events appear in reports. |
| Reporting | Daily saved Markdown report plus native task result/notifications, ranked by importance and including implications. |
| Maintenance | Weekly structural lint and bounded semantic review; resolve only supported issues and queue uncertain research. |
| Updates | Announce available versions; explicit user-requested upgrades with backup/migration/verification. |

**Do not reintroduce:** GitHub data storage, a mandatory global instance registry, ten separately installed workflow skills, fixed Europe/Rome defaults, a five-slot allowance that includes main-topic monitoring, or a production infrastructure layer modeled on PaperTrader.

### Evidence already available

The owner-provided Drive PoC contains reports for two scheduled executions on 2026-09-09. They record persisted raw-file updates and no human approval interruption. Both mark the changed-input nonce check `NOT MET`. Accept the selected runtime/backend and carry this unfinished check into release testing. Do not copy the private reports, IDs, nonce, or folder links into the public scaffold.

The installation and skill-routing designs below are new work. Local Codex tests cannot certify cloud skill installation, native schedule activation, notification delivery, or a particular account's exposed connector actions.

## 2. Target user journeys

### A. Install from a repository URL

The normal user should be able to say:

```text
Install WikiPlant from <public-repository-url>.
```

Work discovers `README.md` -> `INSTALL.md` -> a release manifest, checks capabilities, and asks a single consolidated setup question for missing fields. A complete opening request can avoid the interview:

```text
Install WikiPlant from <public-repository-url> as "Robot Research".
Use <approved-drive-parent-url>. Study humanoid robotics and technologies
relevant to affordable robots. English, Europe/Rome; daily at 06:00,
weekly maintenance on Sunday at 04:00. Start with these links: <links>.
```

This is an illustrative instance, not a production default. Work derives missing nonessential choices, presents a scoped setup summary, creates a private instance, generates a personalized skill, and asks the user only to complete genuine host installation/authorization controls. No manual package upload, Drive-ID extraction, source checkout, cron expression, API key, or YAML edit is part of the supported happy path.

Use an already-personalized skill for the first install; gather the necessary topic details before generating it. The installer bootstrap itself is repository instructions executed by Work, using supported built-in tooling. It does not have to be another permanently installed user skill.

After a bound-skill smoke test and up to five seed investigations, create and verify the daily and weekly native tasks. Return the actual Drive root, installed skill identity, setup status, and next local/UTC execution times. A saved schedule is not proof that its first autonomous run has occurred.

### B. Save and retrieve without reopening the setup conversation

In a fresh ordinary chat, with the generated skill installed:

```text
Add Unitree to my robot research storage.
Tell me about Unitree.
Save this actuator design note in my Robot Research wiki.
What changed about humanoid robotics since your last report?
```

The description should make the right instance discoverable. Bindings identify the data once selected. Retrieve current stored knowledge, not remembered installation text. Write only on save/add/track/update intent; distinguish a saved note from a researched claim and an enqueued investigation from completed research.

A second instance gets a different skill, root, configuration, and schedules. An overlapping topic must not cause both instances to receive an edit. Ask one disambiguation when the user does not identify a unique destination. Do not require users to type the skill name when the topic/intent already resolves correctly; explicit invocation remains the reliable escape hatch for routing misses.

### C. Daily operation without a backlog item for the main subject

An instance about pump design checks its declared primary topic every day even with no pending queue. It checks evidence behind relevant developments, updates the wiki, finds upcoming events, and explains applicability to saved goals/constraints. A difficult new question becomes queued work; the basic daily check does not consume one of the five slots.

A synthetic news fixture about a major fluid-dynamics breakthrough must yield an applicability analysis—not an unsupported claim that the user's pump will improve. The fixture is hypothetical, including any organization names.

### D. Resume, pause, change, and upgrade

"Continue installation" resumes the same instance. "Pause Robot Research" pauses only its tasks and preserves data. "Change the daily time to 07:00" updates verified task/config bindings, not just YAML. "Upgrade this WikiPlant" performs a controlled release migration; normal daily work never adopts upstream code silently.

## 3. Repository and runtime packaging

Suggested source layout; preserve the separation even if implementation names change coherently:

```text
/
  AGENTS.md
  PLAN.md
  README.md
  INSTALL.md
  VERSION
  config.example.yml
  pyproject.toml
  .gitignore
  release/
    runtime-manifest.schema.json
    runtime-manifest.json             # Generated for an immutable release
  skills/
    bootstrap/BOOTSTRAP.md
    instance/SKILL.md.template
    instance/ROUTING.md.template
    init/WORKFLOW.md
    query/WORKFLOW.md
    research/WORKFLOW.md
    main-topic-refresh/WORKFLOW.md
    discover/WORKFLOW.md
    calendar/WORKFLOW.md
    synthesize/WORKFLOW.md
    create-report/WORKFLOW.md
    wiki-maintenance/WORKFLOW.md
    upgrade/WORKFLOW.md
    daily-operation/WORKFLOW.md
  schemas/
    config.schema.json
    instance.schema.json
    research-queue.schema.json
    calendar.schema.json
    wiki-page.schema.json
    research-result.schema.json
    monitoring-result.schema.json
    command.schema.json
    operation.schema.json
    report.schema.json
    templates/
  scripts/
    wikiplant/                       # Small deterministic Python package
  cron/
    daily.prompt.md.template
    weekly.prompt.md.template
    schedules.schema.json
  templates/data/                    # Empty initialized structures, no personal data
  tests/
    unit/
    integration/
    evaluations/
    fixtures/                       # Explicitly synthetic domains and sources
  docs/
    architecture.md
    installation.md
    operations.md
    runtime-capabilities.md
    storage-integrity.md
    verification.md
    upgrades.md
    decisions/
```

The cloud runtime package is a generated allowlisted subset. Internal workflows do **not** need to be independently installed skills. If local Codex skill discovery is useful, expose a development helper in `.agents/skills`; do not register incomplete instance templates as active production skills. Follow the actual supported cloud packaging format, not an invented plugin manifest. [S1–S3]

Suggested Drive layout:

```text
<approved-parent>/WikiPlant-<instance-name>/
  INSTANCE.json
  config.yml
  installation/
    install-state.json
    drive-map.json
    capability-profile.json
    generated-skill/SKILL.md
    skill-binding.json
    schedule-bindings.json
    setup-summary.md
  runtime/<immutable-release-id>/
    RUNTIME.md
    source-manifest.json
    workflows/
    schemas/
    scripts/
    templates/
  data/
    SCOPE.md
    research_queue.csv
    calendar.csv
    sources/
    wiki/
      index.md
      log.md
      entities/
      concepts/
      projects/
      syntheses/
    research/
    monitoring/
    reports/
    state/
      runs/
      operations/
      inbox/
      deliveries/
      maintenance/
      calendar/
  backups/
```

`installation/drive-map.json` maps logical paths to observed IDs, MIME types, and the relevant instance root. Mappings are generated from actual writes/readbacks, never predicted from names. `INSTANCE.json` provides stable identity and binding references; `config.yml` is the sole operational-settings authority. `SCOPE.md` captures meaning, goals, and user constraints. References to `data/profile.yml` in old drafts should be migrated/retired rather than creating conflicting settings.

Runtime upgrades create a new versioned snapshot and change the active binding through an explicit migration. The old snapshot can remain available for rollback. Mutable research does not live inside release-owned files.

## 4. Configuration contract and default budgets

This is the intended `config.example.yml` shape. Placeholders/nulls are legal in a template, not in an activated instance. Schema validation must distinguish these states. Configuration fields are WikiPlant's own schema, **not assertions that similarly named host API parameters exist**.

```yaml
schema_version: 1
instance:
  id: null
  name: null
  language: en
  timezone: UTC
storage:
  provider: google-drive
  root_folder_id: null
runtime:
  release_id: null
  source_commit: null
  manifest_sha256: null
  upgrades: explicit-user-request
skill:
  per_instance: true
  installed_reference: null
  routing_profile_revision: 1
primary_topics: []
schedules:
  daily:
    local_time: null
  weekly:
    weekday: null
    local_time: null
initialization:
  max_research_attempts: 5
queue:
  normal_daily_attempts: 5
  urgent_daily_attempts_total: 10
  urgent_priority: 0
  max_attempts_per_item: 3
expansion:
  child_priority_increment: 20
  max_children_per_research: 3
  preserve_expansion_priority: true
main_topic_refresh:
  enabled: true
  outside_queue_budget: true
  max_search_queries_per_topic: 4
  max_source_fetches_per_topic: 8
  lookback_overlap_hours: 12
exploration:
  allow_adjacent_topics: true
  max_new_automatic_roots_per_day: 10
maintenance:
  max_semantic_pages_per_week: 30
reports:
  delivery: native-task-result
  upcoming_days: 7
  include_quiet_day_report: true
sources:
  retention: metadata-and-permitted-extracts
  retain_full_text: false
```

The user confirmed the **5/10/5, +20, and 3-child** settings. Search/source caps, overlap, automatic-root admission, semantic coverage size, retry ceiling, and event lookahead above are **implementation defaults**, not additional choices attributed to the user. Keep them configurable and document their rationale. Do not ask an end user about every engineering control during ordinary onboarding.

A primary-topic declaration has a stable `id`, `name`, approved aliases, related wiki page IDs, and optional preferred official sources/search terms. The main topic can be broad, but broad coverage is never represented as exhaustive. Only a user-authorized scope edit adds/removes primary topics; automatically discovered entities remain related topics until then. At least one primary topic is required for active operation.

Validate positive increments, nonnegative source limits compatible with a real search, unique IDs, supported timezone/time values, urgent maximum >= normal maximum, and priority range. Reject settings that disable mandatory daily primary-topic monitoring while the instance is advertised as active. A user can pause the whole instance explicitly.

### Accounting examples

| Daily situation with one main topic | Main-topic pass | Queued attempts | Interpretation |
|---|---:|---:|---|
| Empty queue | 1 | 0 | Still check and report main-topic changes/events. |
| Ordinary backlog | 1 | Up to 5 | Main-topic work has not stolen a queue slot. |
| Five attempts used, two urgent questions now eligible | 1 | 7 total | Only the two urgent extensions run. |
| Five attempts used, eight urgent questions eligible | 1 | 10 total | Five urgent questions remain visible as pending. |
| All five initial queue items were urgent; only normal work remains | 1 | 5 | Earlier urgency does not unlock ordinary slots 6–10. |
| Main-topic search fails but queue can be researched | Partial/failed | Up to 5/10 | Report the monitoring gap; do not declare no news. |
| Daily run replay | No extra completed pass | No new slots | Reconcile existing work; never reset allowances. |

Multiple explicitly approved primary topics each receive their own finite pass; count and report them separately. They do not change the five/ten queue limits. Initialization's five attempts are separate and consumed only once; a normal daily run on the same date is allowed after initialization, but initialization itself must not be repeated to gain extra research capacity.

## 5. Data contracts

Implement strict versioned schemas and typed records. Schema migrations must preserve IDs, user notes, lineage, and retained provenance. Define text encoding, dates, enum values, null representation, and list-cell encoding explicitly. Use LF output, real CSV quoting, and no embedded CR/LF in CSV cell values so first-column numeric sorting remains practical. Store long prose in linked Markdown records.

### 5.1 Research queue

Proposed exact v1 header:

```csv
priority,id,expansion_priority,kind,question,topic_id,related_page_ids,parent_ids,lineage_root_id,origin,origin_ref,created_at,not_before,due_at,status,attempts,priority_reason,urgency_reason,dedup_key,refresh_occurrence_id
```

| Field group | Contract |
|---|---|
| `priority` | First column; integer 0–100; lower first, 0 urgent. |
| `id` | Stable investigation identity, not generated anew on retry. |
| `expansion_priority` | Inherited score in 0–100, retained when urgency changes execution order. |
| `kind` | For example `investigation`, `refresh`, `contradiction`, `validation`; fixed enum in schema. |
| `question` | A researchable question, not merely a URL or opaque entity name. |
| `topic_id` / `related_page_ids` | A scoped topic and JSON array of page IDs, with missing-page handling. |
| `parent_ids` / `lineage_root_id` | JSON array of causal parents; root ID remains stable across derived work. |
| `origin` / `origin_ref` | `user`, `initialization`, `main-topic`, `discovery`, `research`, `calendar`, or `maintenance`; link the initiating evidence/command/occurrence. |
| Dates | ISO timestamps with explicit offsets/UTC. `not_before` supports short deferral; long future refresh scheduling belongs in the calendar. |
| `status` | `pending`, `in_progress`, `retry_wait`, or `blocked`; successful items leave this active queue. |
| `attempts` | Number of begun attempts, not number of tool calls. |
| Reasons | LLM justification based on purpose/urgency; priority 0 needs a nonempty urgency explanation. |
| Dedup/occurrence | Semantic normalized-question key plus relevant entity/time/evidence scope; dated refresh identity must not collapse into an old investigation accidentally. |

JSON arrays inside CSV cells must be properly CSV-escaped. Sort numerically on priority, then actual deadlines (missing last), creation time, and ID. Include a header-safe sorting helper. Roots normally initialize expansion score from their assigned baseline priority. Preserve the baseline when an urgency override applies.

For multiple genuine causal parents, choose the minimum eligible parent expansion score +20 and record all contributing parents; do not invent a low-score parent. This is an implementation convention and must have a test. A dedup merge may preserve the minimum **valid inherited** score across independent evidence paths, never reset it to zero solely for urgency.

A completed investigation can emit at most three selected children, including on resume. The cap counts admitted unique children across that logical investigation, not per LLM response. Explicit user requests are not rejected by an automated-discovery cap; they are accepted with their own reason and provenance.

### 5.2 Calendar

Proposed exact v1 header:

```csv
id,kind,title,start_date,start_at,end_at,timezone,date_precision,status,related_page_ids,source_refs,refresh_question,priority,expansion_priority,recurrence,lead_days,origin_ref,updated_at
```

`kind` is `event` or `research_refresh`. Support date-only/all-day entries without fabricating UTC midnight as a precise event time. Timed events require an offset and named timezone when known; unknown date precision stays explicit. Represent recurrence with a documented bounded structure (initially none/daily/weekly/monthly), not arbitrary prose. Unsupported recurrence requires clarification or a documented unsupported state.

Store per-occurrence action processing in `data/state/calendar/` so recurrence history does not overwrite the source event. An occurrence/action key survives retries. A reschedule cancels/revises unprocessed actions and preserves evidence of prior timing; it does not duplicate old and new live events. A cancelled event cannot re-enqueue cancelled refresh actions.

For a due refresh: validate the question, priority, lineage, and occurrence; ensure queue persistence; then mark occurrence intake complete. A crash between these steps is recovered by the shared idempotency key. A refresh is not marked researched merely because it was queued.

Events and refresh actions related to the same real-world occurrence can be separate linked rows. Today's event inclusion is not contingent on a completed investigation. Default upcoming lookahead is seven local dates; deadlines can justify earlier warnings through explicit lead-day rules.

### 5.3 Wiki and evidence records

Wiki front matter should include `schema_version`, `id`, `title`, `type`, `aliases`, `topic_ids`, `created_at`, `updated_at`, `last_checked_at`, and source/research references. Distinguish page-level checking from claim-level verification. The body should preserve supported claims, time scopes, uncertainties, relationships, and open questions. Project templates additionally record goals, constraints, assumptions, dependencies, design choices, and validation needs.

Source records contain canonical source URL/identifier, title, publisher/author when known, original publication/update date, retrieval date, relevant event date, source type, evidence extracts, and retrieval limitations. Do not infer missing dates. Copies of one press release do not count as independent confirmation. Full-text retention is opt-in and provenance/permission-aware.

Research records contain question, item/attempt/run IDs, origin, examined sources, findings, confidence/uncertainty, changes to previous conclusions, affected page IDs, applicability analysis, and selected follow-ups. Never store a plausible research narrative as `complete` without actual examined evidence or explicitly recorded source limitations appropriate to the question.

Main-topic records additionally include topic ID, local cycle date, coverage interval, actual search/source counters, new/corrected/unchanged findings, material events, wiki changes, and coverage status. An empty finding list with successful searches differs from a failed search.

### 5.4 Intake and receipts

Each explicit user write command has a stable command ID, instance ID, operation type, authorization context, submitted content/reference, timestamps, and outcome. Store a unique raw command file when canonical write safety is not currently available. A source page cannot create an authorized user command.

`ACCEPTED_PENDING_MERGE` is a successful durable intake receipt, not a successful canonical wiki edit. Queries must surface pending user notes relevant to the answer with their pending state. The next safe writer merges them and records the canonical result. Preserve commands until their applied state can be verified; unique filenames/IDs plus semantic reconciliation handle uncertain create responses.

### 5.5 Run, operation, and delivery records

Use stable logical run/cycle IDs separately from execution attempts. Keep per-day queue reservations and per-topic monitoring counters in durable run state. Cross-file operation records capture intended edits, original hashes/revisions, target IDs, readback results, and completion stage. Store immutable intent/result evidence where necessary for recovery rather than repeatedly overwriting the sole audit trail.

Reports identify the exact evidence record IDs included, configuration/runtime revision, relevance ranking, events, coverage gaps, and saved-file reference. Delivery state is independent from research completion: `saved`, `result_published`, `notification_observed`, and `read` are distinct. Only set states actually observable through the host or user acknowledgment. A normal user not acknowledging a push must not freeze the next day's reporting window.

## 6. Core behavioral algorithms

### 6.1 Personalized routing metadata

Generate a concise description from approved setup context. Example for an explicitly fictional test instance:

```yaml
name: wikiplant-robot-research-a1b2c3
description: >-
  Use the user's Robot Research wiki to retrieve, save, and research information
  about humanoid robotics, robot makers, actuators, and locomotion, including
  Unitree and other tracked companies. Use for related questions and explicit
  requests to add topics or save notes. Do not write merely because a topic is
  mentioned, and do not use this instance for another named WikiPlant.
```

The binding IDs belong in the private body/configuration, not a public marketing description. Do not include secret project details in globally visible metadata. Approved aliases and representative entities improve implicit matching; description length remains bounded. Validate host metadata requirements against current documentation and actual tooling. [S2–S3]

The body loads exact instance bindings, fetches fresh config/index, routes the operation, and loads only the necessary pinned workflow modules. Ordinary queries must not first load every wiki page. Use indexes/aliases/relationships to retrieve a bounded relevant subset and expand when warranted.

Topic evolution changes the routing profile and may require updating the installed skill. Do not reinstall for every researched entity. Maintain a small representative vocabulary and update through the supported host workflow when there is a meaningful mismatch. Record when the installed description is older than the private routing profile; a generated file in Drive is not proof of synchronization.

### 6.2 Daily main-topic pass and discovery

Run this before queue execution; it is first-class work even with an empty backlog:

```text
for each user-configured primary topic:
    use (instance, local_date, topic_id) as the durable monitoring key
    if a verified pass already completed: reuse its results
    otherwise:
        reserve/resume this topic's separate search/source allowance
        search from last successful coverage checkpoint with overlap
        inspect the most material original evidence
        compare against stored claims, projects, constraints, and calendar
        save supported updates, event changes, implications, and coverage
        select bounded deeper questions and persist queued requests
```

Search query variation should include the user's topic, key concepts, original source announcements, corrections, and relevant events—not only one exact company name. Previously fetched evidence can be reused with provenance. Preserve source publication and actual event dates so a newly indexed old story is not treated as a new event.

The pass's search/source limits are separate from queued slots. Short direct verification and analysis of the news is allowed here; a new multi-source investigation into a distinct question is not. Examples:

- Read a release and its technical announcement; update an announced product specification: part of the main-topic pass.
- Determine whether the new actuator architecture meets the user's full torque/cost/reliability requirements: enqueue a validation investigation.

Create scored evidence/root records for genuinely new independent findings. Derived questions inherit +20 and preserve causal lineage. Select at most three follow-up questions per primary-topic pass, in addition to the applicable automatic-root admission ceiling; do not evade the child rule by splitting one pass into many anonymous roots. Existing causal chains retain their previous root/expansion identity when rediscovered.

Adjacent discovery may use a separately bounded set of leads from wiki relationships and sources. It must not duplicate the daily primary-topic pass or consume unlogged deep-research effort. Prioritize diversity and potential impact rather than maximizing question count. Newly discovered primary-topic-relevant evidence remains useful even when all queue slots are used.

### 6.3 Queue selection

```text
reconcile prior reservations and completed items for this daily cycle
repeat:
    refresh eligible queue state through the safe writer protocol
    used = this cycle's durably reserved queue attempt count
    if used >= 10: stop
    eligible = pending/retry-eligible items whose dates permit execution
    if used >= 5: retain only items with priority == 0 and valid urgency reason
    if eligible is empty: stop
    choose minimum numeric priority, then deadline, created_at, id
    reserve the next attempt before starting investigation
    execute or resume the investigation; verify its required durable outputs
    finalize successful queue removal; record bounded retry/blocker otherwise
```

A new urgent question generated after attempt five can be selected the same day if slots remain. A queued priority-0 item waiting for `not_before` is not eligible early. A root at expansion 100 may be researched but cannot create executable children at 120. A child from expansion 80 may be admitted at 100 and then independently promoted to urgent execution without making its descendants eligible.

Daily run IDs use the instance's configured local date, and resume retains the originating cycle even after midnight. DST changes cannot create two budgets for the same local date. A user changing timezone/schedule cannot silently reset already-reserved research allowance; record a transition rule and carry reservations until the next genuine daily cycle.

### 6.4 Research commit and recovery

A successful write sequence is a recoverable multi-step operation, not a transaction:

```text
validate current bindings/state -> persist intent/reservation
-> fetch/read evidence -> save research/source records
-> update affected wiki/index/calendar through validated write plans
-> fresh readback of required records and wiki changes
-> remove only the successful queue item from the current queue
-> verify queue readback -> finalize research operation
```

Follow-up queue additions belong to the same replay-safe operation family, with stable IDs. Report generation follows research finalization and may retry independently. A temporary report failure must not reinsert and re-research a completed item.

When a write response is lost, compare mapped IDs, operation markers, and fresh hashes before issuing another write/create. Partial success must preserve enough evidence to repair remaining files. Never rebuild a CSV from a cached copy that predates a concurrent user request.

### 6.5 Concurrency strategy

Resolve this early rather than hiding it in a final hardening stage:

1. Discover the actual connector's conditional-write, revision, create-idempotency, and task-serialization capabilities. Record only confirmed behavior, with tool/schema references.
2. Prefer validated conditional content updates or a tested serialized commit protocol. A metadata version counter is not automatically a usable write precondition.
3. Where unsafe concurrent replacement is possible, use unique durable intake/proposal files for interactive and maintenance changes, with one canonical committer for the mutable wiki/CSV projections. Keep immutable evidence to rebuild projections after detected conflict.
4. Test duplicate daily executions as well as daily/weekly/manual overlap. A non-overlapping timetable is only an optimization. A lease written to a normal Drive file is not sufficient proof of exclusivity.
5. If safe exclusive commits cannot be established, fail closed on conflicting canonical writes while preserving accepted intake/results. Do not claim exactly-once execution or install an external coordinator without a new owner decision.

The shipping protocol must state the actual guarantee: for example, idempotent operations plus serialized projection updates and conflict reconciliation. Document any unavoidable manual-edit conflict risk. Protect unrelated manual text with fresh reads, diffs, and preserved originals; do not promise arbitrary concurrent external editor merges that have not been tested.

### 6.6 Report synthesis

Reconcile previously unreported completed evidence, including initialization, explicit manual research, main-topic monitoring, calendar facts, and weekly outcomes. Avoid a timestamp-only window that loses delayed writes. Include every record at most once in a normal report, with later corrections linked to the earlier conclusion.

Report structure:

```text
Title / date / actual coverage window
Executive assessment: what matters most
Critical and time-sensitive findings
Main-topic developments and confidence
Impact on existing projects, assumptions, and wiki conclusions
New ideas and cross-topic connections
Events today and important upcoming dates
Completed and pending research, including urgent overflow
Coverage gaps, failures, blocked operations, and provenance links
```

Rank by materiality and urgency for this instance, not by click popularity or the original queue score. There is no requirement to fill each section with content on a quiet day. Technical applicability claims must identify assumptions, source support, and what remains to validate. Show suggested actions as analysis, not actions already taken in external systems.

Save and verify the report before including its Drive reference in a native task result. Track result publication separately from push/email delivery. If publication cannot be confirmed after interruption, reconcile the host's actual result when possible, otherwise mark it uncertain and expose the saved report. Do not create indefinite replay/notification loops.

## 7. Milestones and acceptance gates

All implementation items below start unchecked. Each milestone requires code/instructions, tests, user documentation where applicable, and honest verification status. Run feasible local work even when the final host-only test requires a Work handoff.

### M0 — adopt decisions and freeze contracts

- [x] Read both specification files and inventory any existing scaffold without overwriting unrelated work.
- [x] Replace obsolete GitHub-storage/global-router/PoC-blocked defaults. Archive old drafts clearly; do not leave competing active instruction files.
- [x] Create a sanitized Work + Drive evidence note with successful and uncompleted checks separated.
- [x] Establish schema versions, authoritative configuration locations, naming, raw MIME types, and source/runtime ownership rules.
- [x] Add the smallest test/validation harness and a manifest-driven packaging plan.

**Acceptance:** production defaults contain no user-specific research interests, timezone, Drive IDs, or operational data. The next work is implementation, not a new backend feasibility study.

### M1 — repository bootstrap and resumable installer skeleton

- [x] Implement `README.md`/`INSTALL.md` as the agent-readable entry point from a bare repository URL.
- [x] Resolve a release to a pinned commit and verify the allowlisted manifest/payloads.
- [x] Implement complete-input extraction, one missing-fields interview, and a scoped setup summary.
- [x] Model installer states and resume checkpoints with fake storage/host adapters.
- [x] Generate the intended private Drive layout, bindings, personalized skill candidate, and schedule plans without pretending they are installed/saved yet.
- [x] Ensure the public happy path does not require a GitHub connection, manual archive upload, API key, or local terminal.

Installation state model:

```text
DISCOVERED -> CAPABILITIES_CHECKED -> SETUP_READY -> STORAGE_CREATED
-> RUNTIME_VERIFIED -> SKILL_CANDIDATE_CREATED -> AWAITING_HOST_INSTALL
-> SKILL_VERIFIED -> SEEDED -> SCHEDULES_VERIFIED
-> ACTIVE_AWAITING_FIRST_RUN -> ACTIVE_VERIFIED
```

Any stage can be `BLOCKED` with a resumable checkpoint. Do not collapse `AWAITING_HOST_INSTALL` into success. Repeated requests must not create a second skill, root, or daily task. Reconcile an interrupted create response against existing scoped evidence.

**Acceptance:** a fake end-to-end installation handles fully supplied settings with no interview, partially supplied settings with one consolidated response, and every interruption point without destructive resets.

### M2 — Drive adapter and safe operation journal

- [x] Implement logical path/ID/MIME binding validation, complete reads, raw writes, pagination, and verified readback.
- [x] Build deterministic helpers for parsing, hashing, merge planning, schema validation, and operation replay.
- [ ] Capture a real capability profile from an approved test instance; do not reuse stale tool names from another surface.
- [x] Implement and test the selected conditional-write/serialized-intake protocol from section 6.5.
- [x] Handle same-name native Docs/Sheets look-alikes, truncated text, moved files, missing permissions, and lost responses.
- [ ] Verify the helper-execution bridge in actual Work; do not assume Python can call connectors or that Drive scripts execute themselves.

**Acceptance:** exact-ID roundtrips preserve raw MIME, original content and manual notes, Unicode, CSV header/quoting, and file identity. Forced overlap never silently discards an accepted command. Unprovable serialization is a visible release blocker for conflicting mutations, not grounds for changing the selected architecture.

### M3 — personalized skill generation and normal-chat operations

- [x] Generate one bound private skill from setup topics, aliases, goals, and representative entities.
- [ ] Use the actual supported skill-creator/install or private distribution path; avoid requiring extra permanent user workflow skills.
- [ ] Verify installed identity and invocation in a fresh cloud Work conversation, not only the original setup chat.
- [x] Implement query/save/add/track/status/configure/pause/resume operation routing with accurate receipts.
- [x] Implement bounded wiki-first retrieval and explicit current-evidence behavior.
- [x] Add routing-profile updates and installed-description synchronization status.
- [x] Test two unrelated instances and two intentionally overlapping instances.

**Acceptance:** fresh ordinary Chat can retrieve stored relevant data and accept/persist scoped writes without reopening setup. Ambiguous instances ask once and perform no premature write. A passive topic mention does not persist a conversation. A metadata update in Drive alone is not reported as a host skill update. Record actual implicit-routing misses as evaluation outcomes; do not promise infallible automatic matching.

### M4 — queue policy, daily reservations, and calendar

- [x] Implement exact CSV schemas, numeric sorting, stable dedup, statuses, reasons, and attempt reservations.
- [x] Implement inherited +20 expansion, <=100 admission, urgency overrides, and a persisted three-child limit.
- [x] Enforce five ordinary slots and urgent-only extensions through ten.
- [x] Handle retries, duplicate run IDs, run-now commands, local-date boundaries, and timezone/DST transitions.
- [x] Implement due/overdue occurrence intake, cancellations, reschedules, and today's/upcoming event selection.

**Acceptance:** all policy and date cases in section 8 pass with deterministic tests, including queue overflow rejection rather than clamping. Events are not suppressed when the research allowance is exhausted.

### M5 — mandatory main-topic refresh outside the queue budget

- [x] Implement per-topic/day monitoring records, separate source/query counters, coverage checkpoints, and bounded retries.
- [ ] Search current original sources, compare against wiki claims, and save material updates/implications/events directly.
- [x] Generate bounded deeper questions with valid lineage and dedup instead of recursively researching outside the queue.
- [x] Run when the queue is empty, exhausted, blocked, or absent due to a recoverable queue-specific error, provided safe storage remains available.
- [x] Add explicit no-update/partial/blocked coverage states and correct date handling for late-indexed old news.

**Acceptance:** one successful main-topic pass plus five ordinary investigations is allowed; ten urgent-qualified queued attempts plus that pass is allowed. The pass never consumes a queue slot. A separate deep follow-up does consume a slot when executed. Replaying a completed date does not generate another free pass or fresh source allowance.

### M6 — initial research, ongoing research, and linked wiki synthesis

- [x] Implement input ingestion for topics, supplied links, and documents with source provenance and trust boundaries.
- [x] Create useful initial entities/concepts/project pages and a linked index under the five-attempt bootstrap allowance.
- [x] Implement evidence-backed research, cross-page impact analysis, contradiction handling, and replay-safe follow-up generation.
- [x] Preserve user-authored text and differentiate user notes, hypotheses, and verified claims.
- [x] Maintain indexes, relationships/backlinks, change logs, freshness markers, and source/research links.
- [x] Use small targeted retrieval rather than loading the entire wiki for every question.

**Acceptance:** unrelated domain fixtures initialize without domain leakage. The synthetic pump/news scenario identifies relevant saved constraints, distinguishes a breakthrough from applicability to the design, and proposes validation instead of inventing performance gains. Failure during a wiki update does not lose the research item or overwrite unrelated manual changes.

### M7 — complete daily operation, reports, and native schedules

- [x] Orchestrate calendar -> primary-topic refresh -> bounded discovery -> metered research -> synthesis/report -> native result.
- [x] Include all newly completed evidence classes, same-day events, urgent overflow, quiet days, and operational gaps.
- [x] Implement report save/publication reconciliation without claiming unobservable notification receipt.
- [x] Generate self-contained daily/weekly task prompts from verified bindings and the pinned runtime.
- [ ] Create and inspect actual native cloud schedules through available supported tools; save real IDs and next occurrences.
- [x] Resume interrupted scheduling without duplicate tasks and update schedules safely after a user setting change.

Task prompts must contain the private installed skill reference, instance ID, root/config/map IDs, operation name, approved scope, fresh-read requirement, immutable runtime binding/version-check rule, and truthful failure-reporting instructions. Do not paste an old queue, scope contents, nonce, temporary sandbox paths, or full mutable state into the schedule. No dependency on uploaded Project files or a remembered setup chat.

**Acceptance:** an automatically started cloud daily run performs actual writes and returns an actual saved report. The next run reads a raw file changed after scheduling and preserves that change. Paused/approval-dependent tasks are reported accurately. The normal schedule starts at the chosen time; report arrival is not promised at that exact minute.

### M8 — weekly wiki maintenance and useful exploration

- [x] Implement structural lint for schema/IDs, broken links, orphaned pages, duplicate topics, malformed CSV, and provenance gaps.
- [x] Implement rotating semantic coverage for contradiction, staleness, assumption changes, and useful missing connections.
- [x] Propose or safely apply supported repairs and queue research under the shared lineage/admission rules.
- [x] Persist maintenance findings/proposals even when the canonical writer is busy, without concurrent CSV replacement.
- [x] Include relevant maintenance conclusions and new ideas in the next daily report.

**Acceptance:** planted contradictions are reported with both evidentiary sides; temporal change is not mislabeled a contradiction. An audit of 30 pages does not claim complete review of a 1,000-page wiki. The same unresolved issue does not generate duplicate follow-ups every week. Maintenance does not execute deep research outside daily allowances.

### M9 — controlled upgrades, pause/resume, export, and recovery

- [x] Implement metadata-only update checks with no automatic code adoption.
- [ ] Implement a user-requested upgrade: compatibility plan, versioned backup, safe writer/quiescence handling, schema/data migration, skill/schedule rebinding, and readback.
- [x] Preserve scope, notes, stable identity, queued work, completed evidence, and user customizations.
- [x] Implement runtime rollback without deleting post-backup research, plus safe recovery from an interrupted migration.
- [x] Implement simple private raw-file export/backup; no live synchronization or second storage backend.
- [x] Pause/resume only the intended instance's schedules; leave data intact. Deletion is a separate explicit action, not a consequence of uninstalling a skill.

**Acceptance:** a pinned instance continues operating while upstream is unavailable. A new release is announced but not loaded. A migration failure leaves either the previous verified runtime active or a clearly paused recoverable state—not a half-upgraded running task.

### M10 — release verification and low-friction installation acceptance

- [x] Run the deterministic and failure-injection suites; validate release payload reproducibility and absence of private data.
- [ ] Test from a fresh Work conversation with a public repository URL and no previously generated WikiPlant skill.
- [ ] Complete two independent instance installations with different topics/destinations/settings.
- [ ] Test fresh normal-chat routing, save/retrieve, and isolation in the actual target surface.
- [ ] Complete real scheduled read-after-change, repeat execution, failed-report recovery, and manual-note preservation tests in an approved sandbox.
- [ ] Record unavoidable human actions, extra question rounds, installed skill count, actual task count, and resume behavior.
- [x] Publish an accurate supported-account/capability checklist and compact troubleshooting guide.

**Acceptance:** the functional definition of done below is met. Label host-dependent checks `NOT RUN`, `BLOCKED`, or `PARTIAL` unless actually observed. Do not ship a claim of zero-click installation, universally reliable implicit routing, or notification delivery that has not been verified.

## 8. Required test matrix

These are acceptance scenarios to implement, not results already obtained. Group them into deterministic unit tests, fault-injected adapter/integration tests, LLM evaluations, and actual cloud acceptance checks.

| ID | Scenario | Expected result |
|---|---|---|
| INST-01 | Bare public repository URL | Work finds installation entry point; no manual ZIP required. |
| INST-02 | Complete setup provided in opening message | No repeated questions about already known settings. |
| INST-03 | Only topics supplied | One consolidated missing-fields interview with English/UTC defaults. |
| INST-04 | Existing partial instance | Resume; no second root, reset data, skill, or task. |
| INST-05 | Failure after each create/checkpoint | Discover actual prior success or retry safely; no silent duplication. |
| INST-06 | Hash mismatch / unsafe path / oversized manifest | Stop before unsafe copy/execute; preserve existing data. |
| INST-07 | Drive destination inherited publicly shared access | Warn/block private-data seeding; do not alter permissions automatically. |
| INST-08 | Skill candidate generated but not installed | Status awaits host install; not active. |
| INST-09 | One skill installed for one instance | Internal workflows require zero additional user installs. |
| INST-10 | Bootstrap completed once, then resumed | No second five-investigation allowance. |
| ROUTE-01 | Named instance add request | Exactly one durable scoped command/queue item and truthful receipt. |
| ROUTE-02 | Related question without skill mention | Evaluate implicit routing and wiki retrieval in fresh normal Chat. |
| ROUTE-03 | Passive mention of related topic | No automatic save of conversation content. |
| ROUTE-04 | Two instances with overlapping topic | Ask destination once; no cross-instance reads/writes before resolution. |
| ROUTE-05 | Explicit instance conflicts with inferred topic | Explicit intended instance governs. |
| ROUTE-06 | Source text asks to use another instance | Treat as untrusted; preserve binding. |
| ROUTE-07 | Skill metadata edited only in Drive | Host binding remains old/pending update; no fabricated synchronization. |
| ROUTE-08 | Relevant user note pending merge | Query includes it as pending/user-provided, not verified canonical fact. |
| STORE-01 | Raw Markdown/CSV same-ID replacement | Verified exact target, preserved MIME/content/manual notes. |
| STORE-02 | Same-name Google Doc/Sheet look-alike | Use mapped raw ID; do not edit or read the converted substitute. |
| STORE-03 | Truncated/indexed text only | No destructive rewrite from incomplete contents. |
| STORE-04 | Folder inventory exceeds one provider page | Paginate; do not infer absent items from a partial listing. |
| STORE-05 | Write succeeded but response lost | Reconcile before retry; no duplicate file/report. |
| STORE-06 | Interactive add during daily queue mutation | Accepted request retained through safe intake/commit. |
| STORE-07 | Daily/weekly overlap and duplicate daily trigger | Tested serialization or fail-closed preservation; no fake file lock. |
| STORE-08 | Readable file moved outside approved scope | Revalidate binding/scope; do not follow it blindly into unrelated data. |
| QUEUE-01 | Priorities 0, 2, 10, 100 | Numeric ascending order; header intact. |
| QUEUE-02 | Embedded commas, quotes, Unicode | Valid CSV roundtrip; no field shifts. |
| QUEUE-03 | Embedded newline in a queue cell | Validation rejects/normalizes into linked Markdown, preserving row structure. |
| QUEUE-04 | Equal priorities with different deadlines | Earliest deadline first; absent deadline last; stable final ID tie-break. |
| GROW-01 | Expansion 30 with increment 20 | Children 50 -> 70 -> 90; 110 not admitted. |
| GROW-02 | Expansion 80 / 100 | 100 admitted; its 120 child rejected, never clamped. |
| GROW-03 | Execution promoted from 60 to urgent 0 | Expansion remains 60; ordinary child is 80. |
| GROW-04 | Fourth child or replay of a three-child result | No fourth admitted child; same children reused on replay. |
| GROW-05 | Same derived question rediscovered tomorrow | No artificial independent root or expansion reset. |
| GROW-06 | Genuine new external event / user request | Valid new root with provenance and reason; no unexplained reset. |
| BUDGET-01 | Ordinary backlog only | At most 5 attempted investigations. |
| BUDGET-02 | Urgent eligible work after fifth attempt | Urgent-only extension, total at most 10. |
| BUDGET-03 | Earlier urgent item but only normal backlog after five | Stop at 5. |
| BUDGET-04 | Resumed attempt / failed attempt retried | Same resume reservation; new retry consumes next slot. |
| BUDGET-05 | Replay / run-now / midnight continuation | Originating daily counters persist; no fresh allowance. |
| BUDGET-06 | DST and approved timezone change | No duplicate local-date budget/reset. |
| MAIN-01 | Queue empty | Primary topic still searched; saved coverage and report. |
| MAIN-02 | Five queue slots already used | Required main-topic pass remains outside those slots. |
| MAIN-03 | Main-topic pass plus ordinary backlog | Pass plus 5, not pass plus 4. |
| MAIN-04 | Main-topic pass plus urgent-qualified research | Pass plus up to 10; no claim that total external work is capped at ten. |
| MAIN-05 | Two configured primary topics | Two separately logged finite passes; unchanged queue allowance. |
| MAIN-06 | Deep question found during monitoring | Enqueue with lineage; execution consumes a queued slot. |
| MAIN-07 | Ordinary evidence verification for a monitored update | Allowed in the separate pass; not a second hidden research pipeline. |
| MAIN-08 | Search unavailable or cap reached | Partial/blocked coverage, never "nothing happened". |
| MAIN-09 | No material news found successfully | Honest bounded no-update result; do not manufacture insight. |
| MAIN-10 | Pass replay or interrupted retry | Reuse result/remaining source allowance; no duplicate free pass. |
| MAIN-11 | Agent discovers several new entities | They do not become new daily primary topics automatically. |
| MAIN-12 | Newly indexed old article | Publication/event dates prevent false new-event classification. |
| CAL-01 | Due refresh and duplicate calendar run | Exactly one effective occurrence intake. |
| CAL-02 | Missed date then next successful run | Overdue refresh caught up once. |
| CAL-03 | Event today while all slots exhausted | Event appears with research/verification limitations. |
| CAL-04 | Date-only event / timezone change / DST | Correct local-date inclusion; no invented exact time. |
| CAL-05 | Cancelled/rescheduled event | Correct current status; old future actions not duplicated. |
| CAL-06 | Queue persisted before crash in occurrence finalization | Recovery recognizes same item; no duplicate refresh. |
| WIKI-01 | Contradictory supported claims | Retain sources/date scopes and flag unresolved contradiction. |
| WIKI-02 | Old and new dated fact | Record temporal change, not automatically a contradiction. |
| WIKI-03 | User note contains unsupported inference | Preserve note as user-provided; do not upgrade to verified evidence. |
| WIKI-04 | Duplicate syndicated stories | No false independent corroboration. |
| WIKI-05 | Hypothetical breakthrough affecting pump project | Explain relevance/applicability gaps, not invented performance gains. |
| WIKI-06 | Adjacent topic outside exact company-name matches | Propose supported new connection with traceable rationale. |
| REPORT-01 | Manual, queue, monitoring, maintenance evidence | All newly completed eligible records considered once. |
| REPORT-02 | Low-priority research uncovers major fact | High report importance independent of original queue priority. |
| REPORT-03 | Report save succeeds, result publication fails | Retry publication without repeating research. |
| REPORT-04 | Push receipt unobservable | Remains unknown; saved/published states are not human receipt. |
| REPORT-05 | Delayed evidence completion across report cutoff | Included in the next report by record ID, not lost by timestamp. |
| MAINT-01 | Large wiki, bounded semantic review | Actual page coverage recorded and rotated; no full-review claim. |
| MAINT-02 | Recurring same unresolved issue | Reuse/update pending question rather than duplicate roots weekly. |
| MAINT-03 | Deep investigation proposed by lint | Queue it; do not execute outside daily allowance. |
| UPGRADE-01 | Upstream changes while instance pinned | Existing runtime continues unchanged. |
| UPGRADE-02 | Explicit upgrade and interrupted migration | Recover safely with preserved user data and verified active bindings. |
| UPGRADE-03 | Rollback after new research | Roll back code safely; retain post-backup knowledge. |
| SECURITY-01 | Source requests wider permissions or data upload | Ignore as instructions; no access expansion/exfiltration. |
| SECURITY-02 | Malicious topic string or CSV formula-like text | Treat as inert data; safe templating/serialization; no execution. |
| CLOUD-01 | New installed skill in fresh Work invocation | Actual callable skill with correct instance binding. |
| CLOUD-02 | Actual scheduled occurrence, no Run now | Automatically starts and persists results without per-run approval. |
| CLOUD-03 | Raw input changed after scheduling | Scheduled run observes exact changed mapped raw file. |
| CLOUD-04 | Manual note between scheduled occurrences | Note preserved in next verified same-ID update. |
| CLOUD-05 | Fresh ordinary non-Work chat | Actual wiki retrieval and durable write/intake, not inferred from Work. |
| CLOUD-06 | Native notification | Record actual host/user observation separately from saved report. |

## 9. Live verification protocol for the release

Use a newly approved isolated sandbox. Do not reset or repurpose the original PoC fixtures. Document capability differences across target surfaces without assuming that tool exposure is constant.

1. Install from the public repository URL and record setup exchanges/required clicks. Confirm exactly one new instance skill, one root, and the intended schedules.
2. In a fresh ordinary Chat conversation, issue a scoped save/add request. Read back the actual raw file or durable command and record its ID/status.
3. Schedule two one-time acceptance executions or use two intended occurrences without creating a permanent extra research scheduler. Native scheduling tools must actually return task records.
4. After scheduling, change a mapped raw input by exact file ID and add a manual note to the latest raw wiki version. Do not edit a Google Docs conversion with the same name. Observe the changed input through an independent fresh read before the run.
5. Let the scheduled occurrence start automatically. Inspect research, monitoring, queue, calendar, report, and operation evidence. Record approval behavior and actual coverage counters.
6. Change the raw input and add a second note between executions. Verify the next run observes both prior persistent state and the new input without overwriting either note.
7. Replay a completed logical run: no extra queue attempts, no duplicated main-topic pass, no additional children, and no duplicate report.
8. Collect notifications only to the extent actually observed. A report in Drive is storage evidence; a native task result is publication evidence; a user's observed push/email is delivery evidence.
9. Disable only temporary acceptance schedules; preserve evidence and the user's intended instance tasks. Do not modify sharing/permissions as a cleanup shortcut.

Statuses: `PASS`, `FAIL`, `BLOCKED`, `PARTIAL`, `NOT RUN`, and `PENDING` have distinct meanings. Record real file/task references privately. Public test documentation uses synthetic or redacted examples unless the owner explicitly authorizes publication.

## 10. Definition of done

WikiPlant is release-ready when a new eligible user can start from the repository URL, supply one consolidated set of missing preferences, install one personalized private skill, and receive an initialized Drive wiki with verified native daily/weekly schedules. No required local computer process, GitHub Actions research workflow, extra storage backend, API key, manual archive transfer, or ID-copying step is hidden in the instructions.

The instance must operate after its setup chat is closed, answer relevant questions from durable knowledge, safely accept new notes/research, perform the main-topic update pass every day outside queued slots, enforce 5/10 research and +20/three-child exploration policy, process calendar refreshes, preserve manual changes, synthesize project-specific implications, and deliver saved reports through native task results. Weekly maintenance and explicit upgrades must preserve provenance and instance isolation.

Local tests, mocked tool tests, LLM-routing evaluations, and live cloud outcomes are reported separately. Unverified platform behavior remains explicitly unverified. A partially completed installer or a paused write-approval task must not be described as autonomously active.

## 11. Codex execution and completion reporting

Start with M0/M1, then resolve storage safety and host installation before adding complex autonomous behavior. Maintain the checkboxes as implementation progresses. Keep `AGENTS.md` within its intended instruction budget; link detailed contracts rather than expanding it indefinitely. [S1]

Expected developer commands should be added as part of implementation, then kept truthful in README: one command for deterministic tests, one for schema/template/release validation, one for synthetic end-to-end tests, and a separate explicitly opt-in live acceptance procedure. Avoid ad hoc scripts that bypass the production policy functions.

At each milestone report changed files, implemented behavior, tests actually run and results, host-only checks still pending, unresolved risks, and the next implementation item. Do not report the existence of this plan as evidence that those functions are implemented. Do not fabricate remote commits, scheduled task IDs, install cards, or notifications.

Preserve an existing repository license. Do not invent an owner's legal identity, private release permission, or license grant. Public distribution documentation must match the actual repository/license chosen by its maintainer; this does not prevent local scaffold development.

## 12. Source notes and requirements provenance

All product decisions in sections 1–6 come from the owner's WikiPlant requirements and the explicitly labeled implementation conventions in this plan. They are not claims that OpenAI provides a turnkey WikiPlant installer.

The owner-provided Drive PoC supports the selected runtime/backend in that tested environment. Its changed-input check remains unfinished; the new release matrix closes that gap. Keep the evidence itself private.

Official platform references checked on 2026-09-09:

- [S1] OpenAI, custom instructions and `AGENTS.md` discovery: https://developers.openai.com/codex/guides/agents-md . Codex reads project instructions and has a configurable combined instruction-size limit; use this for file organization, not as proof that arbitrary Drive files are automatically loaded.
- [S2] OpenAI, skill metadata, implicit/explicit invocation, progressive loading, and authoring/distribution: https://developers.openai.com/codex/skills . Topic-rich descriptions support routing; actual matching must still be evaluated.
- [S3] OpenAI, Skills in ChatGPT: https://help.openai.com/en/articles/20001066 . Creation/installation and workspace controls are host-specific. A generated file is not installation evidence.
- [S4] OpenAI, scheduled tasks: https://help.openai.com/en/articles/10291617 . Native tasks and connected-app operations remain subject to availability/approval; verify actual saved tasks and runs.
- [S5] Google, Drive file uploads: https://developers.google.com/workspace/drive/api/guides/manage-uploads ; Drive file update API: https://developers.google.com/workspace/drive/api/reference/rest/v3/files/update . These describe provider capabilities, not the exact connector actions exposed to Work.

When sources differ across product surfaces or change after this date, record the discrepancy and test the target surface. Do not let a stale documentation assumption silently alter the owner's selected architecture or count as an integration pass.
