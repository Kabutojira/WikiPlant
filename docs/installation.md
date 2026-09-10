# Installation details

The supported entry point is the repository URL plus [INSTALL.md](../INSTALL.md). `wikiplant.installer.Installer` models and tests checkpoints without pretending host installation. Real Work follows the same states and stores actual Drive/skill/task references privately.

Complete requests skip the interview. Partial requests receive one consolidated list of missing values with English/UTC suggestions. The user then authorizes the summarized scope and schedules once; required Drive and private-skill host controls remain visible human actions.

Resume uses the stable installation identity derived during first provisioning and reconciles scoped idempotency evidence. Same-name folders without matching `INSTANCE.json` are never guessed. Initialization reservations survive interruption and cannot exceed five. Skill candidates and schedule plans are not activation evidence.

Published releases must replace the development manifest with `status: released`, the exact immutable commit, and regenerated payload hashes:

```bash
PYTHONPATH=scripts python -m wikiplant.cli package --source-commit <40-hex-commit>
PYTHONPATH=scripts python -m wikiplant.cli validate --root . --require-released
```
