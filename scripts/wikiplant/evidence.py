"""Evidence artifact checks, not a truth oracle or a network research runner.

The Work workflow supplies inspected passages and reasoned assessments. These
helpers enforce their identities, dependencies and conservative promotion rules.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping
import json

from .errors import ValidationError
from .records import Claim, EvidenceLink, SourceRecord
from .util import canonical_json, normalize_question, require_timestamp, sha256_text


def validate_research_assessment(adapter, root_id: str, instance_id: str, result) -> dict:
    """Resolve a saved assessment and its raw source bytes before accepting findings.

    This validates observed artifacts and policy consistency, not the semantic
    accuracy of a model's passage interpretation. A random existing file is not
    an assessment receipt, and an embedded source object is not retrieval proof.
    """
    from .storage import validate_scope
    if not result.evidence_assessment_ref:
        raise ValidationError("research requires its saved evidence assessment")
    snapshot = validate_scope(adapter, result.evidence_assessment_ref, root_id)
    if snapshot.mime_type != "application/json":
        raise ValidationError("assessment must be raw JSON")
    assessment = json.loads(snapshot.content)
    expected = {"schema_version": 2, "kind": "research_assessment", "instance_id": instance_id,
                "item_id": result.item_id, "attempt_id": result.attempt_id, "run_id": result.run_id}
    if any(assessment.get(key) != value for key, value in expected.items()):
        raise ValidationError("assessment is bound to another instance/investigation/attempt")
    validated = validate_assessment_payload(adapter, root_id, assessment)
    if not set(result.source_ids) <= set(validated.get("source_files", {})):
        raise ValidationError("result source IDs are absent from inspected source inventory")
    claims = _unique([Claim.from_dict(c) for c in validated.get("claims", [])], "assessed claim")
    if len(result.claim_ids) != len(set(result.claim_ids)) or set(result.claim_ids) != set(claims):
        raise ValidationError("result claim inventory differs from assessment")
    challenges = _unique([ChallengeRecord.from_dict(c) for c in validated.get("challenges", [])], "challenge")
    if len(result.challenge_ids) != len(set(result.challenge_ids)) or set(result.challenge_ids) != set(challenges):
        raise ValidationError("result challenge inventory differs from assessment")
    findings = validated.get("findings", [])
    if [finding.get("text") for finding in findings] != result.findings:
        raise ValidationError("each result finding must match exact assessed coverage")
    return validated


def _read_assessed_json(adapter, root_id: str, binding: dict, label: str) -> dict:
    from .storage import validate_scope
    if not isinstance(binding, dict) or not binding.get("file_id") or not binding.get("sha256"):
        raise ValidationError(f"{label} needs exact file ID and hash")
    raw = validate_scope(adapter, binding["file_id"], root_id)
    if raw.mime_type != "application/json" or raw.sha256 != binding["sha256"]:
        raise ValidationError(f"{label} bytes changed or are not raw JSON")
    try:
        value = json.loads(raw.content)
    except (ValueError, UnicodeError) as exc:
        raise ValidationError(f"{label} is not complete JSON") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must contain one canonical object")
    return value


def _display_fragment(value: str, limit: int) -> str:
    """Render bounded untrusted prose as literal inline data, not Markdown."""
    text = value if len(value) <= limit else value[:limit] + "… [truncated; see assessed record]"
    text = json.dumps(text, ensure_ascii=False)
    for character in "`*_{}[]<>#|":
        text = text.replace(character, "\\" + character)
    return text


def _finding_text(finding: dict, claim: Claim, checked: ClaimAssessment) -> str:
    limitations = [*checked.limitations]
    if checked.status != "supported":
        limitations.insert(0, "This finding is not an established empirical conclusion")
    details = "; ".join(_display_fragment(limit, 240) for limit in limitations[:8])
    if len(limitations) > 8:
        details += "; additional limitations retained in the assessment"
    qualifiers = []
    if claim.units:
        qualifiers.append("Units: " + _display_fragment(claim.units, 80))
    if claim.conditions:
        qualifiers.append("Conditions: " + _display_fragment(canonical_json(claim.conditions), 500))
    if claim.valid_from or claim.valid_to:
        qualifiers.append("Validity: " + _display_fragment(claim.valid_from or "unknown start", 32)
                          + " through " + _display_fragment(claim.valid_to or "open end", 32))
    return (f"[{checked.status}] Claim {_display_fragment(claim.id, 120)}: "
            f"{_display_fragment(claim.subject, 180)} — {_display_fragment(claim.predicate, 180)}: "
            f"{_display_fragment(claim.value, 240)}. " + (". ".join(qualifiers) + ". " if qualifiers else "")
            + f"Finding: {_display_fragment(finding['text'], 1200)}"
            + (f". Limitations: {details}" if details else ""))


def validate_assessment_payload(adapter, root_id: str, assessment: dict) -> dict:
    """Validate common evidence artifacts for research or material monitoring.

    The caller checks instance/cycle/attempt bindings and exact result inventories.
    This function resolves every source and dependency by ID/hash, validates all
    challenges, rejects dependency cycles, and recomputes policy assessments.
    Computed output keys overwrite any similarly named untrusted input fields.
    Stored SourceRecords demonstrate persisted inspection metadata, not proof of
    an external provider invocation or semantic accuracy of the source assessment.
    """
    if not isinstance(assessment, dict) or assessment.get("schema_version") != 2:
        raise ValidationError("assessment payload requires schema version 2")
    source_files, claim_files = assessment.get("source_files", {}), assessment.get("claim_files", {})
    if not isinstance(source_files, dict) or not isinstance(claim_files, dict):
        raise ValidationError("assessment file inventories must be mappings")
    if not all(isinstance(assessment.get(key, []), list) for key in ("claims", "challenges", "findings")):
        raise ValidationError("assessment record inventories must be lists")
    if (len(source_files) > 256 or len(claim_files) + len(assessment.get("claims", [])) > 512
            or len(assessment.get("findings", [])) > 512 or len(assessment.get("challenges", [])) > 512):
        raise ValidationError("assessment exceeds bounded source/claim inventory; split the work")
    sources = []
    for identifier, binding in source_files.items():
        source = SourceRecord.from_dict(_read_assessed_json(adapter, root_id, binding, "assessed source"))
        source.validate()
        if source.id != identifier or source.retrieval_status not in {"inspected", "partial"}:
            raise ValidationError("assessment source identity/inspection mismatch")
        sources.append(source)
    claims = _unique([Claim.from_dict(c) for c in assessment.get("claims", [])], "assessed claim")
    dependency_claims: dict[str, Claim] = {}
    for identifier, binding in claim_files.items():
        claim = Claim.from_dict(_read_assessed_json(adapter, root_id, binding, "dependency claim"))
        claim.validate()
        if claim.id != identifier or identifier in claims:
            raise ValidationError("dependency claim identity conflicts with assessed inventory")
        dependency_claims[identifier] = claim
    all_claims = {**claims, **dependency_claims}
    findings = assessment.get("findings", [])
    if any(not isinstance(finding, dict) or not isinstance(finding.get("text"), str)
           or not finding["text"].strip() or finding.get("claim_id") not in claims for finding in findings):
        raise ValidationError("each substantive finding needs its assessed claim")
    challenges = _unique([ChallengeRecord.from_dict(c) for c in assessment.get("challenges", [])], "challenge")
    source_inventory = {source.id: source for source in sources}
    for challenge in challenges.values():
        challenge.validate()
        if challenge.claim_id not in all_claims or all_claims[challenge.claim_id].challenge_id != challenge.id:
            raise ValidationError("challenge is not bound back to its assessed/current claim")
        if any(identifier not in source_inventory for identifier in challenge.inspected_source_ids):
            raise ValidationError("challenge references a missing inspected source")
        challenged_claim = all_claims[challenge.claim_id]
        for link in challenge.counterevidence:
            if link not in challenged_claim.evidence_links:
                raise ValidationError("challenge counterevidence is absent from its claim assessment")
        operation_id = assessment.get("attempt_id") or assessment.get("monitoring_key")
        if challenge.parent_operation_id and challenge.parent_operation_id != operation_id:
            raise ValidationError("challenge belongs to another attempt/monitoring operation")
    visiting: set[str] = set()
    checked_claims: dict[str, ClaimAssessment] = {}

    def check_claim(identifier: str) -> ClaimAssessment:
        if identifier not in all_claims or identifier in visiting:
            raise ValidationError("claim dependency is missing or cyclic")
        if identifier in checked_claims:
            return checked_claims[identifier]
        visiting.add(identifier)
        claim = all_claims[identifier]
        claim.validate()
        if claim.challenge_id and claim.challenge_id not in challenges:
            raise ValidationError("claim's challenge record is missing")
        parents = {parent: check_claim(parent) for parent in claim.dependency_claim_ids}
        checked = assess_claim(claim, sources, rationale=claim.assessment_reason,
                               challenge=challenges.get(claim.challenge_id))
        invalid_parents = [parent for parent, verdict in parents.items()
                           if verdict.status != "supported" or all_claims[parent].review_required]
        if invalid_parents:
            limits = tuple(f"Dependency {parent} is {parents[parent].status} and needs revalidation" for parent in invalid_parents)
            checked = replace(checked, status="uncertain" if checked.status == "supported" else checked.status,
                              limitations=checked.limitations + limits)
        if identifier in claims and claim.status != checked.status:
            raise ValidationError("claim status exceeds or conflicts with its actual evidence policy assessment")
        # Dependency artifacts may preserve a legacy assessment. Their effective
        # evidence status is recomputed, never used as a promotion shortcut.
        if identifier in dependency_claims and claim.status != checked.status:
            checked = replace(checked, limitations=checked.limitations + (f"Stored dependency assessment {claim.status} differs from current policy {checked.status}",))
        visiting.remove(identifier)
        checked_claims[identifier] = checked
        return checked

    for identifier in all_claims:
        check_claim(identifier)
    return {**assessment,
            "computed_claim_assessments": {identifier: asdict(checked) for identifier, checked in checked_claims.items()},
            "computed_finding_texts": [_finding_text(finding, claims[finding["claim_id"]], checked_claims[finding["claim_id"]]) for finding in findings]}


def assessed_finding_texts(adapter, root_id: str, assessment: dict) -> list[str]:
    """Return bounded status-qualified findings after revalidating actual artifacts."""
    return validate_assessment_payload(adapter, root_id, assessment)["computed_finding_texts"]


def _unique(records: Iterable[Any], label: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for record in records:
        if record.id in result:
            raise ValidationError(f"duplicate {label} ID: {record.id}")
        result[record.id] = record
    return result


def source_origin_groups(sources: Iterable[SourceRecord]) -> dict[str, frozenset[str]]:
    """Resolve original evidence, including copied datasets and wiki summaries.

    Empty sets mean unknown independence. Publisher/URL uniqueness supplies no
    origin. A derived source cannot override its ancestry with a new origin ID.
    """
    inventory = _unique(sources, "source")
    memo: dict[str, frozenset[str]] = {}

    def visit(source_id: str, path: frozenset[str]) -> frozenset[str]:
        if source_id in memo:
            return memo[source_id]
        if source_id not in inventory or source_id in path:
            raise ValidationError("unresolved or cyclic evidence-origin dependency")
        source = inventory[source_id]
        source.validate()
        if source.derived_from_source_ids:
            groups = frozenset().union(*(visit(parent, path | {source_id}) for parent in source.derived_from_source_ids))
        elif source.source_type in {"wiki", "archive", "summary"}:
            groups = frozenset()
        else:
            origin = source.evidence_origin_id or source.syndication_key
            groups = frozenset([origin]) if origin else frozenset()
        memo[source_id] = groups
        return groups

    for source_id in inventory:
        visit(source_id, frozenset())
    return memo


def independent_origin_count(sources: Iterable[SourceRecord]) -> int:
    groups = source_origin_groups(sources)
    return len(frozenset().union(*groups.values())) if groups else 0


def validate_evidence_links(claim: Claim, sources: Iterable[SourceRecord]) -> dict[str, frozenset[str]]:
    inventory = _unique(sources, "source")
    origins = source_origin_groups(inventory.values())
    for source_id in claim.source_ids:
        if source_id not in inventory:
            raise ValidationError(f"claim references nonexistent source: {source_id}")
    for link in claim.evidence_links:
        link.validate()
        if link.source_id not in inventory or link.source_id not in claim.source_ids:
            raise ValidationError("evidence link does not resolve to a claim source")
        source = inventory[link.source_id]
        if source.retrieval_status not in {"inspected", "partial"} or link.locator not in source.inspected_passages:
            raise ValidationError("evidence locator was not actually inspected")
        if sha256_text(source.inspected_passages[link.locator]) != link.passage_sha256:
            raise ValidationError("evidence passage differs from inspected source")
        if require_timestamp(link.inspected_at) < require_timestamp(source.retrieved_at):
            raise ValidationError("evidence inspection predates retrieved source")
        if link.evidence_origin_id is not None and link.evidence_origin_id not in origins[link.source_id]:
            raise ValidationError("evidence link invents an independent origin")
    return origins


@dataclass
class ChallengeRecord:
    id: str
    claim_id: str
    state: str
    reason: str
    strongest_alternative: str = ""
    falsification_conditions: list[str] = field(default_factory=list)
    planned_queries: list[str] = field(default_factory=list)
    executed_queries: list[str] = field(default_factory=list)
    successful_queries: list[str] = field(default_factory=list)
    inspected_source_ids: list[str] = field(default_factory=list)
    counterevidence: list[EvidenceLink] = field(default_factory=list)
    applicability_limits: list[str] = field(default_factory=list)
    conclusion_change: str = ""
    coverage: str = ""
    max_queries: int = 2
    max_sources: int = 3
    deeper_question: str | None = None
    deeper_disposition: str | None = None
    parent_operation_id: str | None = None
    schema_version: int = 2

    def validate(self) -> None:
        if not self.id or not self.claim_id or not self.reason:
            raise ValidationError("challenge identity, claim and reason are required")
        if self.state not in {"not_required", "not_searched", "searched", "partial", "blocked"}:
            raise ValidationError("invalid challenge state")
        if any(type(limit) is not int or limit <= 0 for limit in (self.max_queries, self.max_sources)):
            raise ValidationError("challenge limits must be positive")
        if len(self.executed_queries) > self.max_queries or len(self.inspected_source_ids) > self.max_sources:
            raise ValidationError("counter-check exceeded its existing operation allowance")
        if not set(self.successful_queries) <= set(self.executed_queries) <= set(self.planned_queries):
            raise ValidationError("challenge success must follow a planned invoked query")
        if self.state == "searched" and (not self.successful_queries or set(self.successful_queries) != set(self.planned_queries) or not self.coverage):
            raise ValidationError("searched requires successful planned coverage")
        if self.state in {"not_required", "not_searched", "blocked"} and self.successful_queries:
            raise ValidationError("successful partial search cannot be labeled unsearched/blocked")
        if self.state == "partial" and not self.executed_queries:
            raise ValidationError("partial challenge requires actual attempted coverage")
        if self.state != "not_required" and (not self.strongest_alternative or not self.falsification_conditions):
            raise ValidationError("challenge must identify an alternative and falsification conditions")
        for link in self.counterevidence:
            link.validate()
            if link.role != "contradicts" or link.source_id not in self.inspected_source_ids:
                raise ValidationError("counterevidence requires an inspected contradicting source")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ChallengeRecord:
        values = dict(value)
        values["counterevidence"] = [EvidenceLink.from_dict(link) for link in value.get("counterevidence", [])]
        return cls(**values)


@dataclass(frozen=True)
class ClaimAssessment:
    status: str
    rationale: str
    support_source_ids: tuple[str, ...]
    opposing_source_ids: tuple[str, ...]
    independent_origins: tuple[str, ...]
    limitations: tuple[str, ...]


def assess_claim(claim: Claim, sources: Iterable[SourceRecord], *, rationale: str,
                 challenge: ChallengeRecord | None = None) -> ClaimAssessment:
    """Check promotion against evidence for this proposition and its conditions.

    The caller's applicability/method decisions must be grounded by the workflow;
    this function cannot establish their semantic correctness from labels.
    """
    if not rationale.strip():
        raise ValidationError("claim assessment requires a reasoned rationale")
    inventory = _unique(sources, "source")
    origins = validate_evidence_links(claim, inventory.values())
    limitations: list[str] = []
    usable: list[EvidenceLink] = []
    for link in claim.evidence_links:
        source = inventory[link.source_id]
        if link.invalidated_by or source.integrity_status != "current":
            limitations.append(f"{link.source_id}: corrected/retracted support requires review")
            continue
        if link.applicability != "applicable" or any(link.conditions.get(key) != value for key, value in claim.conditions.items()):
            limitations.append(f"{link.source_id}: conditions do not establish this proposition")
            continue
        if link.method_quality != "adequate" or link.directness in {"lead", "derived"}:
            limitations.append(f"{link.source_id}: limited/derived evidence retained without corroborating weight")
            continue
        if source.source_type in {"wiki", "archive", "summary"}:
            limitations.append(f"{link.source_id}: wiki/archive synthesis is not independent evidence")
            continue
        if source.derived_from_source_ids and link.directness == "direct":
            limitations.append(f"{link.source_id}: copied evidence cannot be assessed as a direct inspection of its underlying source")
            continue
        usable.append(link)
    support = [link for link in usable if link.role == "supports"]
    opposition = [link for link in usable if link.role == "contradicts"]
    supporting_origins = frozenset().union(*(origins[link.source_id] for link in support))
    direct = [link for link in support if link.directness == "direct"]
    if claim.claim_type == "announcement":
        warranted = bool(direct)
    else:
        warranted = bool(direct) and (len(supporting_origins) >= 2 or any(link.reproducible for link in direct))
        if support and not warranted:
            limitations.append("Empirical promotion needs independent corroboration or documented reproducibility")
    if opposition:
        status = "disputed" if support else "uncertain"
    elif warranted and not claim.review_required:
        status = "supported"
    else:
        status = "reported" if support else "uncertain"
    if claim.status in {"user_note", "hypothesis"} and not claim.evidence_links:
        status = claim.status
    if claim.impact == "consequential":
        if challenge is None:
            limitations.append("Consequential claim has not received a bounded counter-check")
            if status == "supported":
                status = "reported"
        else:
            challenge.validate()
            if challenge.claim_id != claim.id or claim.challenge_id not in {None, challenge.id}:
                raise ValidationError("challenge is bound to another claim")
            if any(source_id not in inventory or inventory[source_id].retrieval_status not in {"inspected", "partial"}
                   for source_id in challenge.inspected_source_ids):
                raise ValidationError("challenge inspected sources must resolve to inspected source records")
            if challenge.state != "searched":
                limitations.append(f"Counter-check is {challenge.state}: {challenge.reason}")
                if status == "supported":
                    status = "reported"
            for link in challenge.counterevidence:
                if link not in claim.evidence_links:
                    raise ValidationError("strongest counterevidence must participate in claim assessment")
            limitations.append("No counterevidence found is not proof that the proposition is true")
    return ClaimAssessment(status, rationale, tuple(sorted({link.source_id for link in support})),
                           tuple(sorted({link.source_id for link in opposition})), tuple(sorted(supporting_origins)), tuple(limitations))


def apply_assessment(claim: Claim, assessment: ClaimAssessment, *, assessed_at: str,
                     confidence: str, challenge_id: str | None = None) -> Claim:
    require_timestamp(assessed_at)
    history = [*claim.status_history, {"status": claim.status, "confidence": claim.confidence,
                                     "assessment_reason": claim.assessment_reason, "changed_at": assessed_at}]
    result = replace(claim, schema_version=2, status=assessment.status, confidence=confidence,
                     assessment_reason=assessment.rationale, assessed_at=assessed_at,
                     challenge_id=challenge_id or claim.challenge_id, status_history=history)
    result.validate()
    return result


@dataclass(frozen=True)
class CorrectionRecord:
    id: str
    source_id: str
    source_reference: str
    observed_at: str
    reason: str
    affected_claim_ids: tuple[str, ...]
    previous_statuses: dict[str, str]
    schema_version: int = 2
    kind: str = "correction"


def correction_summary(record: CorrectionRecord, *, artifact_reference: str, prior_report_refs: Iterable[str] = ()):
    """Create a reportable correction only after its artifact has been saved."""
    from .reporting import EvidenceSummary

    if not artifact_reference:
        raise ValidationError("reportable correction requires an observed saved artifact")
    return EvidenceSummary(record.id, "correction", "Source correction changes dependent conclusions", record.reason,
                           90, "review required", changed_assumptions=[f"{identifier}: prior {record.previous_statuses[identifier]} assessment now requires review" for identifier in record.affected_claim_ids],
                           source_refs=[artifact_reference, record.source_reference, *prior_report_refs],
                           limitations=["Dependent conclusions retain prior evidence/history; correction does not establish a replacement proposition"])


def propagate_source_correction(claims: Iterable[Claim], *, source_id: str, correction_ref: str,
                                observed_at: str, reason: str) -> tuple[list[Claim], CorrectionRecord]:
    require_timestamp(observed_at)
    if not all((source_id, correction_ref, reason)):
        raise ValidationError("correction requires observed identity and explanation")
    inventory = _unique(claims, "claim")
    visiting: set[str] = set()
    visited: set[str] = set()

    def validate_graph(claim_id: str) -> None:
        if claim_id in visiting or claim_id not in inventory:
            raise ValidationError("cyclic or unresolved claim dependency")
        if claim_id in visited:
            return
        visiting.add(claim_id)
        for parent in inventory[claim_id].dependency_claim_ids:
            validate_graph(parent)
        visiting.remove(claim_id)
        visited.add(claim_id)

    for claim_id in inventory:
        validate_graph(claim_id)
    affected = {claim.id for claim in inventory.values() if source_id in claim.source_ids}
    while True:
        expanded = affected | {claim.id for claim in inventory.values() if affected.intersection(claim.dependency_claim_ids)}
        if expanded == affected:
            break
        affected = expanded
    correction_id = "correction-" + sha256_text(canonical_json([source_id, correction_ref]))[:24]
    previous: dict[str, str] = {}
    updated = []
    for claim in inventory.values():
        if claim.id not in affected:
            updated.append(claim)
            continue
        prior = next((entry for entry in claim.status_history if entry.get("correction_id") == correction_id), None)
        previous[claim.id] = prior["status"] if prior else claim.status
        if prior:
            updated.append(claim)
            continue
        links = [replace(link, invalidated_by=correction_id) if link.source_id == source_id else link for link in claim.evidence_links]
        history = [*claim.status_history, {"status": claim.status, "confidence": claim.confidence,
                                          "correction_id": correction_id, "changed_at": observed_at, "reason": reason}]
        updated.append(replace(claim, status="uncertain" if claim.status != "superseded" else "superseded",
                               confidence="unknown", review_required=True, evidence_links=links,
                               status_history=history))
    return updated, CorrectionRecord(correction_id, source_id, correction_ref, observed_at, reason, tuple(sorted(affected)), previous)


def claim_is_stale(claim: Claim, now: datetime) -> bool:
    if now.tzinfo is None:
        raise ValidationError("freshness requires an offset-aware clock")
    return claim.assessed_at is None or now - require_timestamp(claim.assessed_at) >= timedelta(days=claim.review_after_days)


_UNITS = {"pa": ("pressure", Decimal(1)), "kpa": ("pressure", Decimal(1000)), "mpa": ("pressure", Decimal(1000000)),
          "bar": ("pressure", Decimal(100000)), "m": ("length", Decimal(1)), "cm": ("length", Decimal("0.01")),
          "mm": ("length", Decimal("0.001")), "w": ("power", Decimal(1)), "kw": ("power", Decimal(1000))}


def compare_claims(left: Claim, right: Claim) -> str:
    if (normalize_question(left.subject), normalize_question(left.predicate)) != (normalize_question(right.subject), normalize_question(right.predicate)):
        return "unrelated"
    if left.valid_to and right.valid_from and left.valid_to < right.valid_from or right.valid_to and left.valid_from and right.valid_to < left.valid_from:
        return "temporal_change"
    left_conditions = {normalize_question(k): normalize_question(v) for k, v in left.conditions.items()}
    right_conditions = {normalize_question(k): normalize_question(v) for k, v in right.conditions.items()}
    if any(left_conditions[key] != right_conditions[key] for key in left_conditions.keys() & right_conditions.keys()):
        return "different_conditions"
    if left_conditions != right_conditions:
        return "uncertain_match"
    left_value, right_value = normalize_question(left.value), normalize_question(right.value)
    try:
        left_value, right_value = Decimal(left.value), Decimal(right.value)
    except InvalidOperation:
        pass
    left_unit, right_unit = (left.units or "").casefold(), (right.units or "").casefold()
    if left_unit != right_unit:
        if left_unit not in _UNITS or right_unit not in _UNITS or _UNITS[left_unit][0] != _UNITS[right_unit][0]:
            return "uncertain_match"
        try:
            left_value = Decimal(left.value) * _UNITS[left_unit][1]
            right_value = Decimal(right.value) * _UNITS[right_unit][1]
        except InvalidOperation:
            return "uncertain_match"
    return "same" if left_value == right_value else "contradiction"


@dataclass(frozen=True)
class ApplicabilityAssessment:
    finding_id: str
    project_id: str
    status: str
    affected_assumption_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    reasons: tuple[str, ...]
    unmet_conditions: tuple[str, ...]
    next_step: str


def assess_applicability(*, finding_id: str, project_id: str, affected_assumption_ids: Iterable[str],
                        evidence_conditions: Mapping[str, str], project_conditions: Mapping[str, str],
                        evidence_refs: Iterable[str], rationale: str, next_step: str) -> ApplicabilityAssessment:
    if not all((finding_id, project_id, rationale, next_step)):
        raise ValidationError("applicability requires finding/project identity, rationale and useful next step")
    affected, refs = tuple(affected_assumption_ids), tuple(evidence_refs)
    mismatches = tuple(f"{key}: evidence={value}; project={project_conditions[key]}" for key, value in evidence_conditions.items()
                       if key in project_conditions and normalize_question(value) != normalize_question(project_conditions[key]))
    missing = tuple(f"{key}: project condition unknown" for key in evidence_conditions if key not in project_conditions)
    uncovered = tuple(f"{key}: not established by evidence" for key in project_conditions if key not in evidence_conditions)
    if not refs or not affected or not evidence_conditions:
        status = "unknown"
    elif mismatches:
        status = "not_applicable"
    elif missing or uncovered:
        status = "potentially_applicable"
    else:
        status = "applicable"
    return ApplicabilityAssessment(finding_id, project_id, status, affected, refs, (rationale,), mismatches + missing + uncovered, next_step)


def challenge_followup_disposition(*, deeper_question: str | None, topic_classification: str) -> str:
    if not deeper_question:
        return "not_needed"
    return "record_unresolved_terminal" if topic_classification == "peripheral" else "requires_shared_admission"
