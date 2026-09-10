# WikiPlant

WikiPlant is a public, domain-neutral scaffold for creating a private, evidence-linked research wiki in Google Drive. Its production runner is native scheduled ChatGPT Work. Each installed instance has one private, topic-customized skill; GitHub distributes only immutable runtime releases and never stores operational data.

## Install from a repository URL

In ChatGPT Work, send:

```text
@Google Drive Install WikiPlant from https://github.com/Kabutojira/WikiPlant
Use this private parent folder: <google-drive-folder-link>
```

Create the empty private parent folder in Drive first and paste its normal sharing link in place of the placeholder. If you prefer Work to ask for the destination, omit the second line. The folder link selects the destination; you do not create or upload a manifest, runtime file, ZIP, or Google Doc.

Work must follow [INSTALL.md](INSTALL.md). It asks once for missing setup details, provisions a private Drive instance, creates one personalized skill candidate, guides any required host installation action, seeds at most five investigations, and creates the native daily and weekly tasks. If the surface cannot read a GitHub release attachment, it uses the release's immutable raw manifest mirror and verifies the bytes against GitHub's asset digest. No API key, local checkout, ZIP upload, GitHub account, copied Drive file ID, or user-created manifest belongs in the supported flow.

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

- Google Drive is the only operational store.
- ChatGPT Work scheduled tasks are the production execution engine.
- Internal workflows are progressive-load references, not separate installed skills.
- Daily primary-topic monitoring has its own finite allowance and never consumes the normal five or urgent-qualified maximum ten queue attempts.
- Upgrades are explicit, pinned, backed up, and reversible without deleting later research.

See [docs/architecture.md](docs/architecture.md), [docs/operations.md](docs/operations.md), [docs/troubleshooting.md](docs/troubleshooting.md), and [PLAN.md](PLAN.md).
