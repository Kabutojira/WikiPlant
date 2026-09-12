# Runtime capability profile

Installation records observed capabilities in `installation/capability-profile.json`. Names below describe requirements, not promised tool names:

| Capability | Provider / required before activation | Evidence |
|---|---|---|
| Drive raw file create | Drive / yes | create response + exact MIME/content readback |
| Drive full current content read by exact ID | Drive / yes | non-truncated raw bytes/text |
| Drive same-ID content update | Drive / yes | observed ID/revision/hash readback |
| Paginated folder inventory | Drive / yes | tokens/pages exhausted explicitly |
| Snapshot-bound conditional update | Drive strict canonical writes | observed provider precondition and forced stale-edit rejection |
| Idempotent immutable creation | Drive strict canonical operation journals | observed create/reconcile behavior under lost responses and overlap |
| Whole-run execution serialization | Drive strict autonomous attempt reservations | observed host guarantee and forced-overlap outcome |
| Permanent raw lock read/replace | Drive best-effort personal mode only | exact mapped ID/readback; owner/acquisition/expiry; fixed 20-hour stale threshold |
| Immutable repository binding | GitHub / yes | repository ID, owner/name, private visibility, app installation/account, canonical full ref, root prefix |
| Canonical ref creation | GitHub installation / yes | create the absent bound ref from a verified empty initialized default branch; reconcile uncertain response |
| Exact generation read | GitHub / yes | full ref SHA, commit/tree and complete exact blobs without search/index truncation |
| Git object construction | GitHub / yes | observed blob/tree creation and one-parent commit from the bound base |
| Compare-and-swap publication | GitHub / yes | exactly one canonical ref update with `force=false`; forced sibling conflict rejected |
| Generation verification | GitHub / yes | ref, parentage, tree and changed blob IDs/hashes independently re-read |
| Trusted ancestry verification | GitHub / yes | every head descends from the provider-bound first verified commit; rewrites fail closed |
| Repository growth observation | GitHub / yes | retained Git object bytes plus a conservative prospective-object allowance remain within the configured bound |
| Conflict/lost-response recovery | GitHub / yes | durable intent reconciled against reachable commits/current head before bounded retry |
| Scheduled GitHub mutation | GitHub / yes | unattended daily and weekly use of the same bounded actions without per-run approval |
| Private skill install/update | yes | host installation reference + fresh invocation |
| Native task create/inspect | yes | real task IDs, prompts, schedules, next occurrences |
| Notification receipt | no (tracked separately) | user/host observation only |
| Python helper execution bridge | required for helper-dependent steps | actual Work execution receipt; helpers never call connectors |

Availability is account, workspace, surface, and permission dependent. Drive strict mode requires conditional replacement and idempotent creation; daily reservation execution additionally requires an observed serialization guard. When only Drive raw read/replace is available, an explicitly approved `best-effort-personal` instance may use one permanent lock record. It refuses a live lock, reclaims it at/after 20 hours, verifies ownership before work, and unlocks rather than deleting the file. This is not atomic: duplicate acquisition and lost updates remain possible. GitHub has no best-effort mode: all GitHub requirements above are mandatory, and the standard read-only ChatGPT GitHub app does not satisfy them. Missing GitHub evidence returns `BLOCKED_GITHUB_WRITE_CAPABILITY` while leaving Drive available as a separately selected option. Capabilities default absent.

Current repository status: local provider fakes and deterministic contracts do not establish live capability. Drive live acceptance and the separate GitHub capability profile remain `NOT RUN` unless documented otherwise in the hardening status.

Platform references checked for this implementation: [Build skills](https://learn.chatgpt.com/docs/build-skills), [Scheduled tasks in ChatGPT](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt), and [Connecting GitHub to ChatGPT](https://help.openai.com/en/articles/11145903-connecting-github-to-chatgpt). These document host surfaces, including the standard GitHub app's read-only repository access; they do not prove that a particular account exposes the required Drive or write-capable GitHub actions.
