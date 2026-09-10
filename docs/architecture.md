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
- `runtime/<release-id>/`: immutable release-owned snapshot.
- `data/`: user/operation-owned evolving knowledge.
- installed skill and task prompts: derived host bindings, never configuration authorities.

## Commit safety

Interactive and weekly changes are first written as uniquely named immutable commands/proposals. A single canonical writer applies projection changes. When the connector exposes and the instance capability profile verifies a content-write precondition, the writer uses it. Otherwise it reads the exact mapped raw file, records the input hash and intended output in an operation journal, writes, reads back, and fails closed if the observed input changed. This is idempotent conflict detection, not a claim of an atomic Drive lock or arbitrary text merge.

The local fake adapter proves replay, lost-response reconciliation, pagination, exact-ID/MIME checks, and conflict preservation. The actual connector serialization guarantee remains a live acceptance item.
