# GitHub operational storage plan

Status: **implemented and locally verified; live feasibility and release gate not proven**

Date: 2026-09-12

Scope: add GitHub as an alternative operational backend while retaining Google Drive.

## 1. Decision and rollout boundary

Google Drive remains the default. GitHub is implemented as an opt-in backend for a new instance or an explicitly requested migration, but remains capability-gated until live acceptance succeeds. An instance has exactly one authoritative writable backend at a time:

```text
                         +-> private Drive folder (current/default)
public WikiPlant release +
                         +-> dedicated private GitHub repository (capability-gated)
                                      |
                         one bound canonical branch/ref
```

There is no bidirectional synchronization, automatic failover, or background mirroring. These create split-brain and disclosure risks and are outside scope. A backend switch is a resumable migration: pause writers, snapshot and verify the source, import and verify the destination, update the installed skill and the two scheduled tasks, run a smoke test, then activate the destination. The old backend remains a clearly labeled read-only recovery source until the user explicitly retires it.

ChatGPT Work remains the production research runner. GitHub Actions may run public-repository development checks, but must not run private WikiPlant research or mutate instance data.

## 2. Feasibility gate

The standard GitHub app in ChatGPT cannot currently be used as this backend: OpenAI documents it as repository search/read access and directs users to Codex for edits and pushes. Scheduled tasks can use connected apps, but actions and approval behavior depend on the account, workspace, app, and granted permissions. Therefore a GitHub instance must not be activated until the exact Work surface proves every required read/write action without per-run approval.

The acceptable integration is a GitHub App or equivalent connected app scoped to one selected private repository. Prefer repository `Metadata: read` and `Contents: read/write`; do not request Issues, Pull requests, Actions, Workflows, Administration, organization, or account-wide permissions. If the connector cannot expose the low-level Git object and ref operations below, record `BLOCKED_GITHUB_WRITE_CAPABILITY`. Do not fall back to a personal access token, local process, GitHub Actions, or Drive mirroring in the supported path.

Required observed operations:

| Capability | Required observation |
|---|---|
| Repository binding | Resolve immutable repository ID plus owner/name; confirm private visibility and selected-app access. |
| Ref protection and growth | Observe canonical-ref force-push/deletion protection and retained Git object size. |
| Ref creation | Create an absent canonical ref only from a verified initialized-empty default branch; reconcile uncertainty. |
| Exact generation read | Read the canonical full ref SHA, commit, tree and exact blobs without search/index truncation. |
| Transaction construction | Create blobs/tree and a commit with the observed base commit as its sole parent. |
| Compare-and-swap publication | Update the canonical ref with force disabled; a competing sibling commit must be rejected. |
| Verification | Re-read ref, commit, tree and changed blobs and match expected IDs/hashes. |
| Recovery | Reconcile a lost response by operation ID and reachable commit contents before retrying. |
| Scheduled use | Daily and weekly Work tasks can perform the same bounded operations without interactive approval. |

Primary references:

- [OpenAI: Connecting GitHub to ChatGPT](https://help.openai.com/en/articles/11145903-connecting-github-to-chatgpt)
- [OpenAI: Scheduled tasks in ChatGPT](https://help.openai.com/en/articles/10291617)
- [GitHub: Git trees REST API](https://docs.github.com/en/rest/git/trees)
- [GitHub: Git commits REST API](https://docs.github.com/en/rest/git/commits)
- [GitHub: Git references REST API](https://docs.github.com/en/rest/git/refs)
- [GitHub: Choosing permissions for a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app)

These provider documents describe possible APIs, not actions proven to be available to a particular ChatGPT Work task.

## 3. GitHub instance model

Use one dedicated private repository per WikiPlant instance. Do not store an instance in the public scaffold repository, a public fork, GitHub Issues, pull-request descriptions, Actions artifacts, releases, a gist, or a shared multi-instance repository. This keeps repository authorization, accidental publication risk, lifecycle, and recovery bounded to one instance.

Default binding:

```yaml
storage:
  provider: github
  repository_id: "<immutable-provider-id>"
  repository: "<owner>/<name>"        # readable locator; ID remains authoritative
  canonical_ref: "refs/heads/wikiplant-data"
  root_prefix: ""                     # reserved for future layout support
  consistency_mode: git-fast-forward
```

The installer records the immutable repository ID, current owner/name, canonical full ref, repository visibility, app installation/account reference, observed capability profile, and the first verified commit. A repository rename fails closed until an explicitly verified host repair updates the derived owner/name bindings while retaining the immutable repository ID and ancestry anchor. A similarly named repository is never a fallback.

The canonical ref must have provider-observed force-push and deletion protection. The adapter also rejects a non-monotonic head within a run and requires every head to descend from the trusted first commit. These local checks do not prove a live ruleset; installation remains blocked unless the selected integration can observe the protection and repository growth.

The existing logical layout is preserved as repository paths:

```text
INSTANCE.json
config.yml
installation/
runtime/<release-id>/
data/
  SCOPE.md
  TOPICS.md
  research_queue.csv
  calendar.csv
  sources/
  wiki/
  research/
  monitoring/
  reports/
  state/
backups/
```

Do not enable Git LFS or store opaque binaries in the initial backend. Keep canonical content UTF-8 Markdown/CSV/JSON/YAML. Store source metadata, exact evidence locators and permitted bounded extracts; refer to large or binary sources externally. Add conservative per-file, per-transaction and repository-growth limits to configuration and report approaching limits during weekly maintenance.

Git history is useful audit and recovery state, but it is also retention: removing a path in a later commit does not erase its earlier content. Installation must disclose this. Sensitive-data deletion or repository sanitization is a separate explicit administrative operation and must not be automated as ordinary wiki maintenance.

## 4. Provider-neutral storage contract

Refactor Drive-shaped domain code before adding GitHub behavior. The domain layer should depend on concepts, not folders or Git object APIs:

- `StorageBinding`: provider, immutable container identity, logical root, canonical generation locator.
- `ObjectSnapshot`: logical path, complete bytes, media type, content hash, provider revision, generation ID, within-scope flag.
- `StorageTransaction`: instance ID, operation ID, base generation, immutable original intent, a bounded set of path writes/deletes, expected input hashes, authorization reference.
- `TransactionReceipt`: operation ID, base generation, committed generation, changed paths and hashes, verification reference, replay flag.
- `StorageAdapter`: exact read, bounded inventory, persist immutable intake, commit transaction, reconcile operation, and verify generation.

Keep Drive-specific exact IDs, MIME checks, pagination and optional personal lock inside `DriveStorageAdapter`. Put GitHub repository/ref/tree/blob handling inside `GitHubStorageAdapter`. Queue, wiki, reporting, archival, maintenance and upgrades must not branch on the provider.

Do not weaken current guarantees to fit a lowest-common-denominator interface. Provider capabilities are explicit. A provider may activate only when it satisfies the required semantic contract, even if its primitive APIs differ.

## 5. GitHub write protocol

The canonical branch is an append-only sequence of non-force commits from WikiPlant's perspective. Manual user commits are allowed but are treated as concurrent edits and must pass normal schema/ownership validation.

For each canonical mutation:

1. Read the bound canonical ref and retain its commit SHA as `base_generation`.
2. Read the complete required blobs from that exact commit. Never base a write on code search, an indexed excerpt, a moving branch URL, or mixed commits.
3. Validate instance binding, authorization, schemas, unknown-field preservation, input hashes, budgets and the operation's durable original intent.
4. Persist a uniquely named immutable intent in a small first commit when it does not already exist. Publication uses the same non-force protocol.
5. Re-read the canonical head. If it changed, reconstruct from the durable intent and fresh head; do not silently regenerate a different intent.
6. Create blobs and a tree based on the fresh base tree, then create one commit with that base commit as its sole parent. Include all related canonical file changes and the operation checkpoint in this one commit.
7. Update the bound ref with `force=false`. Never force-push, delete, or rewind the canonical ref.
8. Re-read the ref. If it points to the intended commit, verify its tree and blobs. If a later commit already advanced the ref, verify that the intended commit is an ancestor and return a historical receipt plus the current snapshot only when the durable completion and intended output still reconcile. An orphaned or unrelated commit, or successful object creation alone, is not completion.
9. On `409`/`422`, lost response, unexpected head or branch-rule rejection, reconcile first. Retry only from the durable original intent and within a bounded policy. Preserve conflicting intake and return `ACCEPTED_PENDING_MERGE`, `PARTIAL`, or `BLOCKED` honestly.

This makes each successful ref movement an atomic multi-file visibility point. It does not make external research calls transactional, so existing reservations, operation journals, replay rules and publication-state separation remain necessary.

The Contents API may be used for bootstrap only if the connector cannot initialize an empty repository through Git objects. It is not the canonical multi-file write protocol. File-by-file commits would expose partial projections and are therefore insufficient for activation.

## 6. Installation and instance selection

Add `storage provider` to the consolidated setup exchange only when it is missing. Recommend Google Drive until GitHub passes the live release gate. For GitHub, request a normal repository link rather than copied IDs or credentials. The selected repository must be dedicated, private, initialized or safely initializable, and authorized to the exact write-capable app.

Installation sequence for GitHub:

1. Resolve and verify the public WikiPlant release exactly as today.
2. Inspect Work, scheduled-task, skill-install and GitHub integration capabilities.
3. Collect missing instance settings and the private repository destination in one exchange.
4. Confirm scope, schedules, selected provider, permissions and Git-history retention implications.
5. Resolve immutable repository identity; reject public, archived, forked, ambiguous or shared-instance destinations.
6. Create or verify the canonical branch and atomically commit the instance skeleton plus pinned runtime snapshot.
7. Generate one provider-aware personalized skill bound to this repository/ref and verify a fresh read.
8. Seed at most five investigations through normal journal/budget rules.
9. Create and inspect exactly one daily and one weekly native Work task.
10. Run read/write/replay smoke checks and return `ACTIVE_AWAITING_FIRST_RUN`; promote to verified operation only after an observed unattended run.

Repeated installation resumes the same installation record and commit lineage. It must not create another repository, branch, skill, schedule pair, or repeat seed work.

## 7. Drive-to-GitHub migration

Migration is optional and is not part of adding support for new GitHub instances. Never migrate an existing Drive instance merely because GitHub support becomes available.

1. Record explicit current-user authorization binding source instance, destination repository and target release.
2. Pause the instance's actual daily and weekly tasks and verify their IDs/states.
3. Drain/reconcile active writers and pending delivery/publication state.
4. Read a complete fresh Drive inventory by exact mapped IDs; validate canonical raw MIME types and schemas.
5. Write a detached export manifest containing logical paths, byte sizes, hashes, Drive IDs/revisions, source config/scope revisions and operation watermarks. Exclude the Drive lock and provider-only mapping fields from active GitHub configuration, but retain them in migration evidence.
6. Import into an unbound staging ref or unreachable commit chain in bounded commits, then publish the completed tree through one creation/non-force update of the canonical ref with `storage.provider: github` and GitHub bindings. Partial staging must never become the active generation.
7. Verify every logical file hash and all cross-file IDs, queue reservations, lineage, report coverage, runtime provenance and schedule/skill binding inputs.
8. Update the existing installed skill and both existing tasks through observed host controls; verify a fresh ordinary-chat read and a low-risk GitHub write/replay.
9. Activate tasks and mark Drive `MIGRATED_READ_ONLY` with the destination identity if a safe final Drive write is possible. Never delete the source automatically.

Rollback before GitHub activation simply resumes Drive after validating it is still current. After any GitHub-side operational commit, do not reactivate the stale Drive copy. A rollback then requires a new GitHub-to-Drive migration that preserves later data and passes the same verification.

## 8. Performance design and benchmark

GitHub is being considered because Drive latency is unsatisfactory, but the repository must not claim that GitHub is faster until the actual Work integration is measured. The adapter should minimize provider round trips:

- read the canonical ref once to pin a generation, then address immutable commit/tree/blob objects by ID for the rest of that attempt;
- cache immutable reads only within a run and key them by repository ID plus commit/blob SHA;
- fetch only required blobs for an ordinary query, using the wiki index and stable paths rather than repository code search;
- batch all related writes into one tree/commit/ref publication;
- use bounded recursive tree inventory and fall back to paginated subtree traversal when the provider reports truncation;
- record provider calls, bytes, per-phase latency, rate-limit observations, conflicts and retries without logging private content.

Before G9, benchmark Drive and GitHub on the same eligible Work surface with equivalent synthetic instances and at least these workloads: indexed read of five pages, one immutable intake write, a daily transaction updating twenty paths, and a weekly inventory of 500 small files. Run enough cold and warm samples to report median and tail latency rather than one favorable execution. Publish sanitized measurements and limitations. GitHub should be promoted as the performance-oriented alternative only if it materially improves the measured storage phases without unacceptable conflict, rate-limit or tail-latency regressions; otherwise ship it only as a user-selectable backend with the tradeoff disclosed.

## 9. Implementation milestones

| Milestone | Deliverable | Exit condition |
|---|---|---|
| G0 | Reconcile instructions, ADR and this plan | Drive is described as current/default; GitHub as planned/opt-in; no document promises live support. |
| G1 | Provider-neutral storage types and domain call sites | Existing test baseline remains green against renamed/generalized fake storage contracts. |
| G2 | `FakeGitHub` commit/tree/ref model | Forced overlap, sibling commits, lost responses, orphan objects and manual edits are deterministically tested. |
| G3 | Config/instance schemas | Tagged `oneOf` storage bindings reject mixed Drive/GitHub fields; v1/v2 Drive configs remain valid. |
| G4 | GitHub adapter and safe writer | Multi-file transactions use one non-force ref update and verify exact committed bytes; no force path exists. |
| G5 | Installer, skill and workflow providerization | New Drive install behavior is unchanged; GitHub install blocks precisely when any required action is absent. |
| G6 | One-way migration tooling | Synthetic Drive→GitHub and GitHub→Drive migrations resume at every checkpoint and preserve all IDs/data. |
| G7 | Local regression/security suite | The existing Drive regression suite remains green and the GitHub contract suite covers equivalent exact-read, replay, conflict, isolation and verification semantics plus GitHub-specific privacy, concurrency and injection cases. Provider-specific atomicity stays explicit. |
| G8 | Isolated live acceptance | A new private test repo completes fresh install, ordinary chat, scheduled daily/weekly, forced overlap, changed-input and recovery checks. |
| G9 | GitHub backend release | Documentation recommends GitHub only on surfaces matching the tested capability profile; Drive remains fully supported. |

G0 is documentation only. Do not change `config.example.yml`, `schemas/config.schema.json`, runtime manifests, installer behavior, or the claim in release status that GitHub is unavailable until G1–G5 are implemented and tested together.

## 10. Required tests and acceptance evidence

The existing strict fake-Drive suite and the GitHub suite must exercise the following shared storage semantics. They need not use one mechanically identical adapter test because Drive and GitHub expose different atomicity primitives:

- exact current read and complete inventory;
- immutable intent idempotency and operation-ID collision rejection;
- stale-generation conflict with no overwrite;
- atomic related-file visibility;
- lost response before and after publication;
- replay after newer unrelated/manual changes;
- cross-instance/container/ref rejection;
- unknown valid fields and user-authored text preservation;
- queue reservation, main-topic accounting, report coverage and upgrade rollback invariants.

GitHub-specific tests:

- two writers start from the same head; exactly one sibling ref update succeeds and the loser preserves/reconciles intent;
- the adapter never sets `force=true` and refuses ref deletion/rewind;
- branch rename, repository rename, public visibility, archived repository, ruleset rejection and revoked app permission fail closed;
- truncated tree inventory and oversized blobs/transactions do not become replacement bases;
- search results from another branch or stale index cannot authorize or support a write;
- orphaned commit creation after a lost response is reconciled without reporting completion;
- manual valid commits are preserved; invalid or foreign-instance commits block canonical work;
- repository content, commit messages and task prompts do not expose credentials or unnecessary private excerpts.

Live evidence is separate from local tests. The minimum GitHub release gate is:

- exact connector/action names and scopes recorded;
- repository confirmed private and restricted to the intended app installation;
- unattended scheduled raw read and multi-file write observed;
- two genuinely overlapping writers produce a conflict without data loss;
- changed-input nonce is fetched from the latest committed generation;
- lost-response/replay behavior is observed or safely marked untestable;
- installed-skill routing and exact repository/ref binding verified in a fresh chat;
- report save, native result publication and notification observation reported separately;
- Drive regression acceptance still passes.

Until this gate passes, GitHub remains `EXPERIMENTAL_BLOCKED_FOR_PRODUCTION` and installation should recommend Drive.

## 11. Risks and deliberate tradeoffs

| Risk | Control |
|---|---|
| Standard ChatGPT GitHub app is read-only | Hard capability gate; require a tested write-capable app/integration. |
| Write actions pause scheduled runs for approval | Verify persistent scheduled authorization in a sandbox; otherwise do not activate. |
| Private knowledge leaks into a public/code repository | Dedicated private repository, visibility check on every run, immutable repository binding, no public PR/issues/actions. |
| Concurrent commits race | Single canonical ref, sole-parent commits, `force=false`, conflict/reconcile loop. |
| Git history retains deleted sensitive text | Installation disclosure, minimize retained content, explicit administrative purge only. |
| Repository grows indefinitely | Bounded extracts/files/transactions, weekly size reporting, later compaction design without rewriting history by default. |
| Branch protection blocks the app | Preflight an actual low-risk write/ref update; report the exact rule blocker. Do not request admin bypass by default. |
| GitHub outage or rate limit | Persist partial state when possible, report unsearched/unwritten work, resume later; do not silently write to Drive. |
| Provider abstractions erase safety differences | Capability-driven interface; retain provider-specific verification and receipts. |
| Migration creates split brain | Pause/verify tasks, one activation point, old backend read-only, no dual writer. |

## 12. Definition of done

GitHub is a supported alternative only when a new eligible user can choose it during the consolidated installation flow, bind one dedicated private repository, install one personalized skill, and complete verified ordinary-chat plus unattended daily/weekly operations without a PAT, local runtime, GitHub Actions research workflow, per-run write approval, force push, data loss, or Drive dependency. Existing Drive installation, execution, upgrade and recovery behavior must remain supported and regression-tested.
