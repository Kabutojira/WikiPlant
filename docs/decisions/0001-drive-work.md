# Decision 0001: Drive storage and ChatGPT Work execution

Status: superseded in part by [Decision 0002](0002-optional-github-storage.md).

Operational state lives only in private Google Drive raw files. Native scheduled ChatGPT Work is the autonomous production runner. GitHub distributes immutable public scaffold releases. No GitHub operational backend, external agent service, local cron dependency, or API-key onboarding is part of WikiPlant.

The Work execution decision remains in force. The Drive-only storage restriction was superseded on 2026-09-12; Drive remains the implemented default while GitHub is a locally implemented, capability-gated opt-in alternative. GitHub live acceptance remains separate.
