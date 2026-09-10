# Runtime capability profile

Installation records observed capabilities in `installation/capability-profile.json`. Names below describe requirements, not promised tool names:

| Capability | Required before activation | Evidence |
|---|---:|---|
| Drive raw file create | yes | create response + exact MIME/content readback |
| Drive full current content read by exact ID | yes | non-truncated raw bytes/text |
| Drive same-ID content update | yes | observed ID/revision/hash readback |
| Paginated folder inventory | yes | tokens/pages exhausted explicitly |
| Snapshot-bound conditional update | strict canonical writes | observed provider precondition and forced stale-edit rejection |
| Idempotent immutable creation | strict canonical operation journals | observed create/reconcile behavior under lost responses and overlap |
| Whole-run execution serialization | strict autonomous attempt reservations | observed host guarantee and forced-overlap outcome |
| Permanent raw lock read/replace | best-effort personal mode only | exact mapped ID/readback; owner/acquisition/expiry; fixed 20-hour stale threshold |
| Private skill install/update | yes | host installation reference + fresh invocation |
| Native task create/inspect | yes | real task IDs, prompts, schedules, next occurrences |
| Notification receipt | no (tracked separately) | user/host observation only |
| Python helper execution bridge | required for helper-dependent steps | actual Work execution receipt; helpers never call connectors |

Availability is account, workspace, surface, and permission dependent. Strict mode requires conditional replacement and idempotent creation; daily reservation execution additionally requires an observed serialization guard. When only raw read/replace is available, an explicitly approved `best-effort-personal` instance may use one permanent lock record. It refuses a live lock, reclaims it at/after 20 hours, verifies ownership before work, and unlocks rather than deleting the file. This is not atomic: duplicate acquisition and lost updates remain possible. Capabilities default absent, and every best-effort run/result must disclose that residual risk.

Current repository status: local fake adapter implemented; live capability profile `NOT RUN` in this workspace.

Platform references checked for this implementation: [Build skills](https://learn.chatgpt.com/docs/build-skills) and [Scheduled tasks in ChatGPT](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt). These document the host surfaces; they do not prove that a particular account exposes the needed Drive actions or approvals.
