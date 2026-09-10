from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import date
from typing import Any, Literal

from .errors import ValidationError
from .util import require_timestamp


Receipt = Literal["SAVED", "QUEUED", "ACCEPTED_PENDING_MERGE", "BLOCKED", "PARTIAL"]


@dataclass
class SourceRecord:
    id: str
    canonical_ref: str
    title: str
    publisher: str | None
    published_at: str | None
    updated_at: str | None
    retrieved_at: str
    event_at: str | None
    source_type: str
    permitted_extracts: list[str]
    limitations: list[str]
    syndication_key: str | None = None
    full_text_retained: bool = False
    schema_version: int = 2
    evidence_origin_id: str | None = None
    derived_from_source_ids: list[str] = field(default_factory=list)
    inspected_passages: dict[str, str] = field(default_factory=dict)
    retrieval_status: str = "uninspected"
    integrity_status: str = "current"
    correction_ref: str | None = None
    topic_ids: list[str] = field(default_factory=list)
    extra_fields: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.id or not self.canonical_ref or not self.title:
            raise ValidationError("source identity, reference, and title are required")
        require_timestamp(self.retrieved_at, "source retrieved_at")
        for field_name in ("published_at", "updated_at", "event_at"):
            value = getattr(self, field_name)
            if value:
                require_timestamp(value, f"source {field_name}")
        if self.retrieval_status not in {"uninspected", "inspected", "partial", "blocked"}:
            raise ValidationError("invalid source retrieval status")
        if self.integrity_status not in {"current", "corrected", "retracted"}:
            raise ValidationError("invalid source integrity status")
        if self.integrity_status != "current" and not self.correction_ref:
            raise ValidationError("source correction/retraction requires an observed reference")
        if any(not locator.strip() or not extract.strip() for locator, extract in self.inspected_passages.items()):
            raise ValidationError("inspected passages need exact locators and retained extracts")
        if self.id in self.derived_from_source_ids:
            raise ValidationError("source cannot derive from itself")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceRecord:
        known = {item.name for item in fields(cls)}
        values = {key: value for key, value in data.items() if key in known}
        values["schema_version"] = data.get("schema_version", 1)
        values["extra_fields"] = {**data.get("extra_fields", {}), **{key: value for key, value in data.items() if key not in known}}
        return cls(**values)


@dataclass
class EvidenceLink:
    source_id: str
    locator: str
    passage_sha256: str
    role: str
    inspected_at: str
    evidence_origin_id: str | None
    method: str
    directness: str
    assessment_reason: str
    applicability: str = "unknown"
    conditions: dict[str, str] = field(default_factory=dict)
    conflicts_of_interest: list[str] = field(default_factory=list)
    uncertainty: list[str] = field(default_factory=list)
    method_quality: str = "unknown"
    reproducible: bool = False
    reproducibility_reason: str | None = None
    invalidated_by: str | None = None
    extra_fields: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not all((self.source_id, self.locator.strip(), self.method.strip(), self.assessment_reason.strip())):
            raise ValidationError("evidence needs source, exact locator, method and assessment reason")
        if len(self.passage_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.passage_sha256):
            raise ValidationError("evidence passage requires a SHA-256 identity")
        require_timestamp(self.inspected_at, "evidence inspected_at")
        if self.role not in {"supports", "contradicts", "context"}:
            raise ValidationError("invalid evidence role")
        if self.directness not in {"direct", "secondary", "lead", "derived"}:
            raise ValidationError("invalid evidence directness")
        if self.applicability not in {"applicable", "potentially_applicable", "not_applicable", "unknown"}:
            raise ValidationError("invalid evidence applicability")
        if self.method_quality not in {"adequate", "limited", "unknown"}:
            raise ValidationError("invalid method quality")
        if self.reproducible and not self.reproducibility_reason:
            raise ValidationError("reproducibility needs a recorded basis")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceLink:
        known = {item.name for item in fields(cls)}
        values = {key: value for key, value in data.items() if key in known}
        values["extra_fields"] = {**data.get("extra_fields", {}), **{key: value for key, value in data.items() if key not in known}}
        return cls(**values)


@dataclass
class Claim:
    id: str
    subject: str
    predicate: str
    value: str
    valid_from: str | None
    valid_to: str | None
    source_ids: list[str]
    confidence: str
    status: Literal["verified", "reported", "supported", "disputed", "uncertain", "user_note", "hypothesis", "superseded"]
    schema_version: int = 2
    evidence_links: list[EvidenceLink] = field(default_factory=list)
    dependency_claim_ids: list[str] = field(default_factory=list)
    conditions: dict[str, str] = field(default_factory=dict)
    units: str | None = None
    assessment_reason: str = ""
    claim_type: str = "empirical"
    assessed_at: str | None = None
    review_after_days: int = 90
    impact: str = "ordinary"
    challenge_id: str | None = None
    review_required: bool = False
    predecessor_ids: list[str] = field(default_factory=list)
    status_history: list[dict[str, Any]] = field(default_factory=list)
    extra_fields: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not all((self.id, self.subject, self.predicate, self.value)):
            raise ValidationError("claim identity and proposition are required")
        if self.status not in {"verified", "reported", "supported", "disputed", "uncertain", "user_note", "hypothesis", "superseded"}:
            raise ValidationError("invalid claim status")
        if self.status in {"verified", "supported"} and not self.source_ids:
            raise ValidationError("evidence-backed claims require a source reference")
        if len(self.source_ids) != len(set(self.source_ids)) or len(self.dependency_claim_ids) != len(set(self.dependency_claim_ids)):
            raise ValidationError("duplicate claim evidence or dependencies")
        if self.id in self.dependency_claim_ids or self.id in self.predecessor_ids:
            raise ValidationError("claim cannot depend on or supersede itself")
        try:
            start = date.fromisoformat(self.valid_from) if self.valid_from else None
            end = date.fromisoformat(self.valid_to) if self.valid_to else None
        except ValueError as exc:
            raise ValidationError("claim validity must use ISO dates") from exc
        if start and end and end < start:
            raise ValidationError("claim validity interval is reversed")
        if type(self.review_after_days) is not int or self.review_after_days <= 0:
            raise ValidationError("claim freshness allowance must be positive")
        if self.impact not in {"ordinary", "consequential"}:
            raise ValidationError("invalid claim impact")
        if self.assessed_at:
            require_timestamp(self.assessed_at, "claim assessed_at")
        for link in self.evidence_links:
            link.validate()
            if link.source_id not in self.source_ids:
                raise ValidationError("evidence source absent from claim source IDs")
        if self.schema_version >= 2 and self.status in {"verified", "supported"}:
            if self.status == "verified":
                raise ValidationError("legacy verified status requires conservative migration")
            if not self.assessment_reason or not self.assessed_at or self.review_required:
                raise ValidationError("supported claim requires a current assessment")
            support = [link for link in self.evidence_links if link.role == "supports" and link.applicability == "applicable" and not link.invalidated_by]
            if not support:
                raise ValidationError("supported claim requires inspected applicable evidence links")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Claim:
        known = {item.name for item in fields(cls)}
        values = {key: value for key, value in data.items() if key in known}
        values["schema_version"] = data.get("schema_version", 1)
        values["evidence_links"] = [EvidenceLink.from_dict(link) if isinstance(link, dict) else link for link in data.get("evidence_links", [])]
        values["extra_fields"] = {**data.get("extra_fields", {}), **{key: value for key, value in data.items() if key not in known}}
        return cls(**values)


@dataclass
class ResearchResult:
    id: str
    question: str
    item_id: str
    attempt_id: str
    run_id: str
    origin: str
    source_ids: list[str]
    findings: list[str]
    confidence: str
    uncertainties: list[str]
    changed_conclusions: list[str]
    affected_page_ids: list[str]
    applicability: list[str]
    selected_followup_ids: list[str]
    status: Literal["complete", "partial", "blocked"]
    schema_version: int = 2
    topic_ids: list[str] = field(default_factory=list)
    claim_ids: list[str] = field(default_factory=list)
    challenge_ids: list[str] = field(default_factory=list)
    correction_ids: list[str] = field(default_factory=list)
    applicability_records: list[dict[str, Any]] = field(default_factory=list)
    scope_revision: int | None = None
    evidence_assessment_ref: str | None = None

    def validate(self) -> None:
        if not self.id or not self.question or not self.attempt_id or not self.run_id:
            raise ValidationError("research identity/question/attempt/run are required")
        if self.status == "complete" and self.findings and not self.source_ids:
            raise ValidationError("completed factual findings require examined source records")
        if len(self.selected_followup_ids) > 3:
            raise ValidationError("one investigation may select at most three follow-ups")


@dataclass
class Command:
    id: str
    instance_id: str
    operation: str
    authorization: dict
    submitted_content: str
    submitted_at: str
    outcome: str = "pending"
    canonical_reference: str | None = None
    target: str = ""
    schema_version: int = 2

    def validate(self) -> None:
        if self.operation not in {"save", "add", "track", "investigate", "configure", "pause", "resume", "update"}:
            raise ValidationError("unsupported command operation")
        from .authorization import validate_user_authorization
        if not self.id or not self.instance_id or not self.target or self.schema_version != 2:
            raise ValidationError("command identity, target and schema version are required")
        validate_user_authorization(self.authorization, instance_id=self.instance_id, operation=self.operation, target=self.target)
        require_timestamp(self.submitted_at, "command submitted_at")


@dataclass
class DeliveryState:
    report_id: str
    saved: bool = False
    result_published: bool = False
    notification_observed: bool | None = None
    read: bool | None = None

    def mark_saved(self) -> None:
        self.saved = True

    def mark_published(self) -> None:
        if not self.saved:
            raise ValidationError("report result cannot publish before saved readback")
        self.result_published = True
