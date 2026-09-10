# WikiPlant

WikiPlant is a public, domain-neutral scaffold for creating a private, evidence-linked research wiki in Google Drive. Its production runner is native scheduled ChatGPT Work. Each installed instance has one private, topic-customized skill; GitHub distributes only immutable runtime releases and never stores operational data.

## Install from a repository URL

In ChatGPT Work, send:

```text
Install WikiPlant from <public-repository-url>.
```

Work must follow [INSTALL.md](INSTALL.md). It asks once for missing setup details, provisions a private Drive instance, creates one personalized skill candidate, guides any required host installation action, seeds at most five investigations, and creates the native daily and weekly tasks. No API key, local checkout, ZIP upload, GitHub account, or copied Drive file ID belongs in the supported user flow.

This working tree is the unpublished **0.2.0 development scaffold**, with version 2 data contracts and a conservative migration from version 1. No release or live upgrade is implied by the version change. A published installation source must have an immutable source commit and a matching detached release-manifest asset; `release/runtime-manifest.json` is only a draft development inventory. The installer rejects draft or mismatched releases.

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
