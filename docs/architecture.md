# Architecture

```text
public immutable release
  -> repository-URL bootstrap in ChatGPT Work
  -> private Drive instance + pinned runtime snapshot
  -> one private bound instance skill
       -> ordinary Chat query/intake
       -> Work initialize/daily/weekly/upgrade workflows
  -> verified Drive writes + native task result
```

GitHub is distribution only. Google Drive is the sole operational store. Deterministic Python helpers validate and transform content but have no connector credentials and perform no network calls. Provider actions are executed by ChatGPT Work following the workflow modules and checked against the observed capability profile.

## Ownership

- `INSTANCE.json`: immutable instance identity and binding references.
- `config.yml`: sole writable operational configuration authority.
- `data/SCOPE.md`: semantic purpose, projects, constraints, and exclusions.
- `data/TOPICS.md`: sole user/adjacent/peripheral taxonomy, scope provenance and lifecycle; config references primary user-anchor IDs.
- `runtime/<release-id>/`: immutable release-owned snapshot.
- `data/`: user/operation-owned evolving knowledge.
- installed skill and task prompts: derived host bindings, never configuration authorities.

## Commit safety

Interactive and weekly changes are first written as uniquely named immutable commands/proposals. A single canonical writer applies projection changes. Strict mode requires observed conditional replacement and idempotent immutable creation; daily attempt reservation additionally requires whole-run serialization. Replacements bind to the exact generation snapshot, journal original intent, and independently read back. Without these guarantees strict canonical writes remain blocked while scoped intake is retained.

An explicitly approved `best-effort-personal` instance is the compatibility exception for a raw read/replace-only Drive connector. It uses one exact-ID permanent lock record with an owner token and a fixed 20-hour expiry, verifies it before work, and unlocks without deletion. It still uses snapshot/readback checks, but neither the lock nor a post-write readback is atomic. Reports label this reduced guarantee, and malformed/live locks fail closed.

The local fake adapter proves replay, lost-response reconciliation, pagination, exact-ID/MIME checks, and conflict preservation. The actual connector serialization guarantee remains a live acceptance item.
