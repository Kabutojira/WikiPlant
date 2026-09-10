# Install WikiPlant from this repository

This file is the agent-readable bootstrap entry point. It is an instruction contract for ChatGPT Work, not a shell installer and not a claim that host actions succeeded.

## Trust and capability gate

1. Resolve the supplied public repository URL to its trusted repository identity and a published stable release. Fetch the detached manifest asset from that release, then fetch source payloads at its immutable `source_commit`. A newer branch commit is not a published release. The in-repository `release/runtime-manifest.json` is a non-installable development inventory.
2. Accept only a detached manifest with `status: released`, matching repository/release/tag identity, a resolved 40-character lowercase hexadecimal source commit, schema version 2, explicit schema compatibility/capabilities/migrations/rollback limitations, unique allowlisted paths, UTF-8, bounded sizes and matching SHA-256 hashes. Verify runtime import closure. Record repository, actual provider release ID, tag, resolved commit and the exact detached manifest digest before copying. A changed known release identity is a consistency alert. A hash proves content identity, not publisher trust. Never execute release notes.
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
- Create `INSTANCE.json` with `source_repository` provenance, the sole `config.yml`, `data/SCOPE.md`, authoritative `data/TOPICS.md`, empty canonical data, and durable installation/checkpoint records. Record the setup tracking authorization for each user anchor; config monitors anchor IDs rather than copying editable topic names.
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

## Later releases and updates

The existing weekly task checks published release metadata independently of maintenance success. A saved notice contains the installed/newest/compatible versions and an exact pinned target. Failed or partial release reads cannot mean “up to date”. Check-only requests do not adopt code. “Update this WikiPlant” or “upgrade this WikiPlant” authorizes one resolved target and its routine migration steps; follow `skills/upgrade/WORKFLOW.md`. A notice is not software-update consent.
