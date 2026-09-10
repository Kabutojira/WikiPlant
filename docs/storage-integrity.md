# Storage integrity and concurrency

Canonical files are UTF-8 raw Markdown/CSV/JSON/YAML mapped by exact Drive ID and MIME type. Before replacement, fetch full current content, verify instance scope and binding, and record input hash/revision plus intended output hash in a durable operation. Update the same ID with a proved precondition when exposed, then independently read back. Native Docs/Sheets look-alikes are rejected.

Cross-file transactions are not assumed. Research/source records and wiki changes are verified before successful queue removal. Report publication retries are independent of research. Lost write responses are reconciled by operation ID, target ID, and hash before retry.

Interactive and weekly inputs use unique command/proposal files when an exclusive canonical writer cannot be established. The single canonical writer rebuilds from fresh current projections plus durable inputs. Forced conflicts fail closed and retain inputs. Pagination is mandatory; partial indexed text is never a replacement base. Residual risk from arbitrary simultaneous manual edits remains a live acceptance item.
