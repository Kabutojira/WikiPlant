# Troubleshooting

- `AWAITING_HOST_INSTALL`: the generated candidate exists but is not installed. Complete the private host installation control once, then say “continue installation.” Do not regenerate it.
- Release metadata visible, manifest body unavailable: inspect the asset's GitHub-reported digest/size and use the release-note `manifest_mirror` pinned to a full commit. Continue only if complete mirror bytes match both. Never ask the user to create/upload the manifest, and never accept a `main`-branch mirror.
- `@Google Drive` unavailable: enable/connect the Google Drive plugin and authorize the appropriate account/actions for this Work surface. A mention does not grant access. If connected but the destination is missing, create one empty private parent folder and paste its normal link; do not create any WikiPlant files yourself.
- `BLOCKED` after seeding: inspect Scheduled for the prepared daily/weekly task plans. Save/approve only those two cards, then resume so WikiPlant can record actual IDs and next occurrences.
- Hash/commit/path failure: stop. Use a published immutable release whose manifest matches the resolved commit; never bypass the allowlist.
- Same-name Drive file: use the mapped exact raw ID and MIME type. Never substitute a Google Doc/Sheet conversion.
- Partial/truncated read, moved file, or denied permission: make no replacement. Restore appropriate access/scope or mapping, then resume the recorded operation.
- Conflict during canonical write: retain the unique inbox/proposal and current manual content. Let the canonical writer reconcile from fresh reads; do not overwrite from a cached CSV/page.
- Main-topic search outage: record `PARTIAL`/`BLOCKED` with unused/used counters. Do not call it “no update” and do not spend queue slots to disguise the missing pass.
- Report saved but result failed: retry native result publication using the saved report; do not repeat research.
- No push/email observed: check Settings → Notifications. Keep `notification_observed` unknown unless the host/user actually observes it.
- Upstream unavailable: continue on the pinned Drive runtime. Upgrades are explicit and never required for a normal daily run.
