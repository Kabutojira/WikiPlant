# Upgrades, export, and recovery

Normal operation uses its pinned Drive snapshot when upstream is unavailable. Weekly checks may compare release metadata only. An explicit user request is required to resolve and verify a new immutable release.

Upgrade pauses or quiesces only this instance, backs up affected runtime/migration inputs, writes a new versioned snapshot, migrates mutable schemas with checkpoints, and updates the installed skill and task bindings through supported host controls. Scope, notes, stable identity, queues, evidence, and customizations remain outside release-owned replacement. Resume follows fresh readback.

Rollback selects the prior verified runtime/bindings and never deletes post-backup research. Export is a private raw-file snapshot, not live synchronization or another backend. Deletion is separate and explicit; uninstalling a skill or pausing tasks leaves data intact.
