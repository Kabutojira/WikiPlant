# WikiPlant

WikiPlant is a public, domain-neutral scaffold for creating a private, evidence-linked research wiki. Google Drive is the supported default storage backend; a dedicated private GitHub repository is implemented as a capability-gated, opt-in alternative. Its production runner remains native scheduled ChatGPT Work. Each installed instance has one private, topic-customized skill and exactly one authoritative writable backend.

## Install from a repository URL

In ChatGPT Work, send:

```text
@Google Drive Install WikiPlant from https://github.com/Kabutojira/WikiPlant
Use this private parent folder: <google-drive-folder-link>
```

Create the empty private parent folder in Drive first and paste its normal sharing link in place of the placeholder. If you prefer Work to ask for the destination, omit the second line. The folder link selects the destination; you do not create or upload a manifest, runtime file, ZIP, or Google Doc.

Work must follow [INSTALL.md](INSTALL.md). It asks once for missing setup details, provisions the selected private storage backend, creates one personalized skill candidate, guides any required host installation action, seeds at most five investigations, and creates the native daily and weekly tasks. If the surface cannot read a GitHub release attachment, it uses the release's immutable raw manifest mirror and verifies the bytes against GitHub's asset digest. No API key, local checkout, ZIP upload, copied provider ID, or user-created manifest belongs in the supported flow. A GitHub account is needed only when the user explicitly selects the GitHub storage alternative.

To request the GitHub alternative, replace the Drive destination line with `Use GitHub storage in this dedicated private repository: <repository-link>`. Installation proceeds only if the Work surface exposes the full observed write-capability profile; the standard read-only ChatGPT GitHub app does not qualify. Otherwise installation returns `BLOCKED_GITHUB_WRITE_CAPABILITY` without mutating the repository, and Drive remains available.

Installations prefer strict conditional/idempotent Drive writes and serialized task runs. If the connected Drive surface exposes only raw create/read/replace/list operations, WikiPlant can instead use an explicitly approved `best-effort-personal` mode with one permanent lock file. The lock expires after 20 hours and reduces ordinary overlap, but it is not atomic and does not provide exactly-once execution.

This is the **0.2.1 development scaffold**, with version 2 data contracts and a conservative migration from version 1. A usable published installation source consists of an immutable GitHub release and its matching detached release-manifest asset; a version string or branch commit alone is not a release. `release/runtime-manifest.json` is only a non-installable development inventory. The installer rejects draft or mismatched releases.

## Developer verification

```bash
python -m unittest discover -s tests -p 'test_*.py'
python -m wikiplant.cli validate --root .
python -m wikiplant.cli e2e
```

`pyproject.toml` adds `scripts/` to the package layout. Without installing the project, prefix commands with `PYTHONPATH=scripts`.

Live cloud acceptance is intentionally separate. Follow [docs/verification.md](docs/verification.md) only in an explicitly approved, isolated Drive sandbox. Local tests do not prove private skill installation, connected-app write permissions, scheduled execution, or notification receipt.

The [hardening evidence map](docs/hardening-status.md) records implemented contracts, regression results, the bounded assistant evaluation and remaining release gates. No production-readiness claim follows from local tests alone.

## Architecture constraints

- Google Drive is the current/default operational store.
- GitHub storage is a locally implemented, gated alternative: one dedicated private repository per instance, no mirroring or automatic fallback. Its fake-provider transaction, installer, migration, and failure tests pass, but it is not live-validated or enabled as the recommended default.
- ChatGPT Work scheduled tasks are the production execution engine.
- Internal workflows are progressive-load references, not separate installed skills.
- Daily primary-topic monitoring has its own finite allowance and never consumes the normal five or urgent-qualified maximum ten queue attempts.
- Upgrades are explicit, pinned, backed up, and reversible without deleting later research.

See [docs/architecture.md](docs/architecture.md), the [GitHub storage plan](docs/github-storage-plan.md), [docs/operations.md](docs/operations.md), and [docs/troubleshooting.md](docs/troubleshooting.md).
