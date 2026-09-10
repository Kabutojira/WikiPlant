from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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

    def validate(self) -> None:
        if not self.id or not self.canonical_ref or not self.title:
            raise ValidationError("source identity, reference, and title are required")
        require_timestamp(self.retrieved_at, "source retrieved_at")
        for field_name in ("published_at", "updated_at", "event_at"):
            value = getattr(self, field_name)
            if value:
                require_timestamp(value, f"source {field_name}")


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
    status: Literal["verified", "supported", "uncertain", "user_note", "hypothesis"]

    def validate(self) -> None:
        if self.status in {"verified", "supported"} and not self.source_ids:
            raise ValidationError("evidence-backed claims require a source reference")


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
    authorization: str
    submitted_content: str
    submitted_at: str
    outcome: str = "pending"
    canonical_reference: str | None = None

    def validate(self) -> None:
        if self.operation not in {"save", "add", "track", "investigate", "configure", "pause", "resume"}:
            raise ValidationError("unsupported command operation")
        if not self.authorization.startswith("explicit-user"):
            raise ValidationError("durable user command requires explicit user authorization")
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
