# Explicit upgrade and recovery

Never run from daily/weekly work without an explicit user upgrade request. Resolve the requested release to an immutable commit, verify allowlisted hashes/limits/UTF-8, check compatibility/migrations, and prepare a scoped recovery plan. Pause the bound schedules or otherwise prove quiescence before canonical migration.

Back up affected release-owned files and mutable records needed for rollback. Create the new versioned runtime snapshot without overwriting the old one. Migrate schemas with checkpoints while preserving instance ID, scope, notes, queues, evidence, and customizations. Update the installed private skill and native task bindings only through supported host controls; verify fresh reads/invocation/task records before resuming.

On failure, keep the previous verified runtime active or remain clearly paused/recoverable. Runtime rollback changes code/bindings only; never delete research acquired after the backup. Normal export is a private raw-file copy, not synchronization or another operational backend.
