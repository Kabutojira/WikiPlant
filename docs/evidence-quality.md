# Evidence, challenge and applicability controls

V2 separates execution priority, source assessment, claim confidence and project applicability. `records.py` stores full claim/evidence metadata; `evidence.py` validates actual inspected passage identities and known origins before promotion. `supported` is a policy-checked assessment, not a fact mechanically inferred from a score. A source ID or number of URLs is insufficient. Unknown independence stays unknown; derived sources cannot invent a new origin or substitute for original inspection.

An official announcement can establish what was announced. Empirical promotion additionally requires applicable direct support and either independently originated corroboration or a documented reproducible method. These conditions do not prove semantic truth: the host must inspect evidence and record sound proposition-specific judgments. Adequate relevant opposition changes the conclusion; irrelevant measurements and unsupported comments cannot win by publisher prestige or vote count.

Consequential claims require a bounded counter-check inside their existing attempt/topic budget. The challenge record separates planned, executed and successful searches and retains alternatives, falsification criteria and coverage. Blocked and unsearched work is not successful challenge coverage. Deeper validation uses normal admission and budget; peripheral questions cannot spawn it. Queue selection exposes overdue validation opportunities while preserving genuine urgent precedence and the five/ten limits.

`propagate_source_correction` invalidates inspected source support, traverses claim dependencies and produces a stable correction event. Historical claims/assessments and previous reports remain intact. Persist the resulting claims and correction through the shared writer; `correction_summary` requires an observed artifact reference before the event can be represented in reporting.

Claim freshness uses actual assessment time plus each claim's positive review interval. Page modification timestamps are not claim verification. Maintenance normalizes propositions, conditions, supported unit conversions and time windows across a bounded active inventory. Risk selection and rotation persist reviewed page IDs, compared claim IDs, cursor, inventory coverage and oldest unreviewed age. Unknown units/conditions remain reviewable uncertain matches. Archive integrity is separate from active semantic rotation.

Retrieval consumes bounded active index summaries, not full page bodies or archive dossiers. It matches normalized entities/claims/project context, follows one hop of known relationships/dependencies and accepts explicitly reasoned semantic selections with validated claim IDs. The resulting decision record can be saved by the host alongside an answer. Archive lookup is selective and read-only; it never reactivates a topic. Applicability records bind findings to project assumptions, evidence and actual condition matches/mismatches with a concrete next step.

## Saved assessment boundary

`validate_research_assessment` reads the saved raw JSON assessment by exact ID, checks instance/item/attempt/run bindings, matches the result's claim/challenge/finding inventories and delegates artifact policy to `validate_assessment_payload`. The common helper also supports material-monitoring assessments; their caller must independently check instance/topic/date/coverage/key bindings and exact result coverage.

Each `source_files` entry binds a stable source ID to the exact raw SourceRecord JSON file ID and SHA-256. Dependencies must exist in the assessment's claim inventory or in `claim_files`, whose entries likewise bind each stable claim ID to a raw canonical Claim JSON artifact by exact ID/hash. Supply the full dependency closure and referenced source/challenge records. Missing references, duplicate authorities and cycles block validation. A dependent claim cannot retain supported status when a required parent fails the evidence policy or needs review. Existing dependency artifacts retain their historical status; the helper computes their effective status without mutating them.

Every challenge must validate, refer to its actual claim, be referenced back by that claim, resolve all inspected sources and counterevidence, and belong to the same attempt/monitoring operation when an operation binding is present. Extra unused or omitted challenge records cannot inflate claimed coverage. Helper safety limits are 256 source records, 512 total current/new claims, and 512 findings/challenges per assessment; larger work must be partitioned.

The common helper returns recomputed `computed_claim_assessments` and `computed_finding_texts`. These keys overwrite any corresponding untrusted fields in the stored payload. Finding text includes the assessed status, bounded literal proposition, and computed limitations. Untrusted confidence strings do not promote the finding. Long prose is explicitly abbreviated with a reference to the complete assessment. `assessed_finding_texts` performs validation itself; callers that already validated may use the computed fields directly. These records must be carried into report synthesis instead of replacing them with an unqualified high-confidence narrative.

These checks prove scoped persisted source metadata, matching byte identities, reference consistency and policy outcomes. They do not prove that an external provider actually returned a source, that an author interpreted it correctly, or that any host installed a skill. The Work bridge must separately record observable retrieval outcomes and assess semantic support. An indexed description or a model-generated source record alone is not external retrieval evidence.

## Evidence recorded locally

Run the deterministic policy and persisted correction tests with:

```sh
PYTHONPATH=scripts python -m unittest tests.unit.test_evidence_hardening tests.unit.test_assessment_integrity tests.unit.test_retrieval_hardening tests.integration.test_correction_reporting -v
```

These use fictional sources and the local fake Drive. The correction integration test reconstructs claims from persisted bytes, saves the report, reloads it through a fresh publisher and checks actual downstream review flags, correction/provenance text and coverage membership.

`tests/evaluations/evidence-corpus.json` contains ten curated fictional evidence bundles and outcome rubrics. Linked local tests exercise deterministic controls. `tests/evaluations/evidence-model-evaluation.json` records one actual assistant judgment per case, with visible rubrics and prior implementation context; it is not blinded or independent external evaluation. It retains a counterexample where the rubric conflates a future performance target with present achievement, plus missing-method/project-detail limitations. The exact model/version was not exposed. Human rubric review and independent repeated runs remain `NOT RUN`. Retain failures and apply zero tolerance to invented support, self-corroboration, unauthorized writes and data loss. The malicious instruction case is separate from benign misleading evidence. Live inspection/installation/scheduled correction reporting/notification proof remain separate Work acceptance gates.
