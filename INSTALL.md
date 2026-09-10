# Install WikiPlant from this repository

This file is the agent-readable bootstrap entry point. It is an instruction contract for ChatGPT Work, not a shell installer and not a claim that host actions succeeded.

## Trust and capability gate

1. Resolve the supplied public repository URL to an immutable commit and read `release/runtime-manifest.json` at that commit.
2. Accept only a manifest with `status: released`, a 40-character lowercase hexadecimal `source_commit` equal to the resolved commit, schema version 1, unique allowlisted relative paths, UTF-8 files, declared size limits, and matching SHA-256 hashes. Do not execute arbitrary repository files. A hash proves content identity, not publisher trust.
3. Confirm that this surface exposes Google Drive raw-file create/read/content-update/list operations, private skill creation or installation guidance, and native scheduled-task creation/inspection. Record observed capability/tool names in the private instance. Do not invent absent APIs.
4. If exact full-content reads, raw-file writes, or private destination safety cannot be established, stop before private seeding and return a resumable `BLOCKED` checkpoint.

## One setup exchange

Reuse every value already given. Ask one consolidated question only for missing required values:

- instance name;
- one or more primary topics and approved aliases;
- purpose, projects, constraints, and exclusions;
- initial links/documents/notes, if any;
- approved Google Drive parent destination;
- language (suggest `English`) and IANA timezone (suggest `UTC`);
- daily start time and weekly weekday/start time (offer choices, but never impose an author location or fixed time).

Summarize scope, destination, schedules, main-topic and queue budgets, then ask for one setup authorization in that same exchange. Mandatory host permission/installation controls remain separate. Do not ask for API keys, GitHub login, file IDs, YAML edits, cron expressions, or an archive upload.

## Resumable order

Use `skills/bootstrap/BOOTSTRAP.md` and advance only after observed readback:

```text
DISCOVERED -> CAPABILITIES_CHECKED -> SETUP_READY -> STORAGE_CREATED
-> RUNTIME_VERIFIED -> SKILL_CANDIDATE_CREATED -> AWAITING_HOST_INSTALL
-> SKILL_VERIFIED -> SEEDED -> SCHEDULES_VERIFIED
-> ACTIVE_AWAITING_FIRST_RUN -> ACTIVE_VERIFIED
```

Search the approved parent for a matching `INSTANCE.json`/installation record before creating anything. A same-name folder without matching stable identity is ambiguous. Resume checkpoints; never reset data, grant a second initialization allowance, or duplicate a root, skill, or task after an uncertain response.

## Provisioning invariants

- Create a new private subfolder under the approved parent and inspect inherited sharing before copying private content. Do not change permissions automatically.
- Create canonical UTF-8 raw files (Markdown/CSV/JSON/YAML), never Google Docs/Sheets conversions. Map observed IDs and MIME types in `installation/drive-map.json`.
- Copy only files listed by the verified runtime manifest into `runtime/<release-id>/`. Do not copy Git history, tests, fixtures, or development state.
- Create `INSTANCE.json`, the sole `config.yml`, `data/SCOPE.md`, empty canonical data, and durable installation/checkpoint records.
- Generate exactly one already-personalized private skill. Its body binds the exact instance/root/config/map/runtime IDs; its description contains approved topic routing terms but no unnecessary private project text.
- Treat a generated skill as a candidate until the host confirms installation and a fresh invocation verifies the binding.
- Seed at most five initialization investigations, recording each reservation so resume cannot repeat them.
- Inspect task inventory before creating at most one daily and one weekly task. Save actual task IDs and verify local/UTC next occurrences. A time is a start time, not a delivery deadline.

## Minimal host handoff when actions are unavailable

Return only the missing action and the checkpoint, for example:

```text
WikiPlant is paused at AWAITING_HOST_INSTALL. In the host's private skill
installation control, install the generated candidate shown in this chat.
Then reply "continue installation". No files, IDs, or settings need re-entry.
```

For unavailable scheduling, ask the user to open Scheduled and approve/save the two already prepared task cards, then resume by inspecting the resulting tasks. Never claim `ACTIVE`, a task ID, a notification, or a write that was not observed.
