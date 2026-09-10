# Bounded published-release check

Run once per instance/week inside existing weekly maintenance, before and independently of audits. Also serve explicit check-only requests. This is metadata work outside research slots and never creates a third recurring task.

Read trusted repository identity, installed version and durable release-check state by exact ID. Fetch complete, fresh, bounded published-release metadata and detached manifest identities through the available public-read path. Resolve tags to actual immutable source commits, never assume `target_commitish` is resolved. Prefer immutable releases/attestations when supported; no GitHub end-user credentials are required for publicly accessible metadata. Do not execute notes or fetch/adopt runtime code.

Use `check_releases`. Compare semantic versions, filter drafts/prereleases unless the user chose that channel, and report newest stable versus newest compatible release. Record migration/capability blockers. A missing manifest, partial/stale inventory, rate limit or network failure is failed coverage, not up-to-date. A changed known release/tag/digest is a security/consistency alert.

Persist state, input identities, actual last-successful check and retry allowance before publishing. Save/read back each new notice with its stable shared notice ID and retryable payload. Include it in the weekly result and next daily report if needed; outstanding notices retain their ID without a new daily alert. Saved, result-published and observed notification remain distinct. Never infer push receipt.

Tell the user the installed/new version, compatibility and useful migration summary, and that no update was applied. An explicit update request later enters `upgrade/WORKFLOW.md` with the exact resolved target. Neither a release notice nor an urgent/security label is consent.
