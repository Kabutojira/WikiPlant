# Installation details

The supported entry point is the repository URL plus [INSTALL.md](../INSTALL.md). `wikiplant.installer.Installer` models and tests checkpoints without pretending host installation. Real Work follows the same states and stores actual Drive/skill/task references privately.

Complete requests skip the interview. Partial requests receive one consolidated list of missing values with English/UTC suggestions. The user then authorizes the summarized scope and schedules once; required Drive and private-skill host controls remain visible human actions.

Resume uses the stable installation identity derived during first provisioning and reconciles scoped idempotency evidence. Same-name folders without matching `INSTANCE.json` are never guessed. Initialization reservations survive interruption and cannot exceed five. Skill candidates and schedule plans are not activation evidence.

After committing the intended runtime sources, a maintainer generates a detached manifest asset. Packaging verifies every runtime byte against that existing commit, so dirty or untracked release payloads fail. The asset is produced afterwards and does not contain itself or require a self-referential commit hash. These commands create/verify local artifacts; they do not publish:

```bash
PYTHONPATH=scripts python -m wikiplant.cli package --source-commit <40-hex-commit> --output dist/runtime-manifest.json
PYTHONPATH=scripts python -m wikiplant.cli validate --root . --require-released --manifest dist/runtime-manifest.json
```

The maintainer attaches that file to the published release through the separately authorized publication workflow. Prefer immutable releases when available. The committed draft inventory is regenerated with `package --draft` for local validation only. End users read public metadata/source through Work's available public-read path and need no GitHub credentials or terminal.
