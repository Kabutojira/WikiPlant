# Decision 0002: Optional GitHub operational storage

Status: accepted direction; implementation pending.

Google Drive remains WikiPlant's current, supported default backend. Add GitHub as an opt-in alternative for new instances and explicitly authorized migrations. Each instance has exactly one authoritative writable provider; synchronization, mirroring and automatic failover are excluded.

A GitHub-backed instance uses one dedicated private repository and one bound canonical ref. Canonical multi-file changes publish through non-force fast-forward ref updates from an observed base commit. ChatGPT Work remains the production runner, and GitHub Actions do not run research.

The standard GitHub app in ChatGPT is documented as read-only, so it does not satisfy the write contract. GitHub activation is gated on an observed Work-accessible, least-privilege GitHub App/integration with exact read, Git object creation, non-force ref update and readback capabilities. The local adapter, installer and migration path are implemented; until live acceptance passes, GitHub remains experimental and Drive remains the recommended installation choice.

Rationale, migration behavior, milestones and acceptance gates are in [the GitHub storage plan](../github-storage-plan.md).
