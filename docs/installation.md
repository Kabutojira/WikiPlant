# Installation details

The supported entry point is an `@Google Drive`-directed Work prompt containing the repository URL and, preferably, an empty private parent-folder link, plus [INSTALL.md](../INSTALL.md). The mention directs Work to the connected plugin; it is not evidence that the app/account/actions are enabled. `wikiplant.installer.Installer` models and tests checkpoints without pretending host installation. Real Work follows the same states and stores actual Drive/skill/task references privately.

Complete requests skip the interview. Partial requests receive one consolidated list of missing values with English/UTC suggestions. The user then authorizes the summarized scope and schedules once; required Drive and private-skill host controls remain visible human actions.

Resume uses the stable installation identity derived during first provisioning and reconciles scoped idempotency evidence. Same-name folders without matching `INSTANCE.json` are never guessed. Initialization reservations survive interruption and cannot exceed five. Skill candidates and schedule plans are not activation evidence.

After committing the intended runtime sources, a maintainer generates a detached manifest asset. Packaging verifies every runtime byte against that existing commit, so dirty or untracked release payloads fail. The asset is produced afterwards and does not contain itself or require a self-referential commit hash. These commands create/verify local artifacts; they do not publish:

```bash
PYTHONPATH=scripts python -m wikiplant.cli package --source-commit <40-hex-commit> --output dist/runtime-manifest.json
PYTHONPATH=scripts python -m wikiplant.cli validate --root . --require-released --manifest dist/runtime-manifest.json
```

The maintainer attaches that file to the published release through the separately authorized publication workflow. Prefer immutable releases when available. Because some Work web paths expose release metadata but cannot return attachment bodies, the maintainer may also commit the identical bytes under `release/published/` after the source commit and add an immutable raw `manifest_mirror` URL to the release notes. Installers accept that mirror only when its complete bytes, size and SHA-256 equal the actual release asset metadata. The source commit and mirror commit are distinct, avoiding self-reference. The committed draft inventory remains non-installable. End users need no GitHub credentials, terminal, or hand-created manifest.

The official ChatGPT Work guidance recommends using `@Google Drive` when a task should use that plugin. App availability, account authorization and allowed actions remain separate controls, so installation records the actual observed tools and permissions rather than inferring them from the mention.
