from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from .errors import ValidationError
from .evidence import claim_is_stale, compare_claims
from .util import normalize_question, require_timestamp
from .wiki import WikiPage


@dataclass
class MaintenanceFinding:
    key: str
    kind: str
    page_ids: list[str]
    detail: str
    needs_research: bool
    claim_ids: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)


@dataclass
class MaintenanceState:
    cursor: int = 0
    open_finding_keys: set[str] = field(default_factory=set)
    reviewed_at: dict[str, str] = field(default_factory=dict)
    last_reviewed_ids: list[str] = field(default_factory=list)
    last_compared_claim_ids: list[str] = field(default_factory=list)
    inventory_total: int = 0
    inventory_complete: bool = False
    semantic_coverage_complete: bool = False
    oldest_unreviewed_age_days: int | None = None
    review_round: int = 0
    coverage_limits: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        values = asdict(self)
        values["open_finding_keys"] = sorted(self.open_finding_keys)
        return values

    @classmethod
    def from_dict(cls, value: dict) -> MaintenanceState:
        values = dict(value)
        values["open_finding_keys"] = set(values.get("open_finding_keys", []))
        return cls(**values)


def structural_lint(pages: Iterable[WikiPage], *, inventory_complete: bool = True) -> list[MaintenanceFinding]:
    page_list = list(pages)
    ids = {page.id for page in page_list}
    findings: list[MaintenanceFinding] = []
    seen: set[str] = set()
    claim_pages: dict[str, str] = {}
    for page in page_list:
        if page.id in seen:
            findings.append(MaintenanceFinding(f"duplicate-id:{page.id}", "duplicate_id", [page.id], "Duplicate stable page ID", False))
        seen.add(page.id)
        for claim in page.claims:
            if claim.id in claim_pages:
                findings.append(MaintenanceFinding(f"duplicate-claim:{claim.id}", "duplicate_claim_id", [claim_pages[claim.id], page.id], "Duplicate stable claim ID", False, [claim.id]))
            claim_pages[claim.id] = page.id
        for related in page.relationship_ids:
            if related not in ids and inventory_complete:
                findings.append(MaintenanceFinding(f"broken-link:{page.id}:{related}", "broken_link", [page.id], f"Missing related page {related}", False))
        if not page.source_ids and any(claim.status in {"verified", "supported"} for claim in page.claims):
            findings.append(MaintenanceFinding(f"provenance:{page.id}", "provenance_gap", [page.id], "Supported claims exist without page-level source references", True))
    linked = {related for page in page_list for related in page.relationship_ids}
    for page in page_list:
        if inventory_complete and page.type != "project" and page.id not in linked and len(page_list) > 1:
            findings.append(MaintenanceFinding(f"orphan:{page.id}", "orphan", [page.id], "Page has no inbound relationship", False))
    topic_terms: dict[str, set[str]] = {}
    for page in page_list:
        for term in (page.title, *page.aliases):
            normalized = normalize_question(term)
            if normalized:
                topic_terms.setdefault(normalized, set()).add(page.id)
    for term, page_ids in topic_terms.items():
        if len(page_ids) > 1:
            ids = sorted(page_ids)
            findings.append(MaintenanceFinding(f"duplicate-topic:{term}:{':'.join(ids)}", "duplicate_topic", ids, f"Shared title/alias: {term}", False))
    return findings


def semantic_audit(pages: list[WikiPage], state: MaintenanceState, max_pages: int = 30, *,
                   now: datetime | None = None, changed_source_ids: Iterable[str] = (),
                   inventory_complete: bool = True, max_comparisons: int = 300) -> tuple[list[MaintenanceFinding], list[str]]:
    """Bounded risk plus rotation review of supplied active-page inventory.

    Comparisons use a proposition index across pages, not only pairs within a
    page. Matching counterparts are recorded separately from fully reviewed pages.
    No network research or canonical mutations occur here.
    """
    if type(max_pages) is not int or max_pages <= 0 or type(max_comparisons) is not int or max_comparisons <= 0:
        raise ValidationError("semantic audit limits must be positive integers")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValidationError("semantic audit requires an offset-aware clock")
    if len({page.id for page in pages}) != len(pages):
        raise ValidationError("duplicate page IDs prevent stable semantic coverage")
    claim_inventory = [claim.id for page in pages for claim in page.claims]
    if len(claim_inventory) != len(set(claim_inventory)):
        raise ValidationError("duplicate claim IDs prevent dependency review")
    state.inventory_total = len(pages)
    state.inventory_complete = inventory_complete
    state.coverage_limits = [] if inventory_complete else ["Active inventory is incomplete; structural and semantic totals are partial"]
    state.last_reviewed_ids = []
    state.last_compared_claim_ids = []
    if not pages:
        state.semantic_coverage_complete = inventory_complete
        state.oldest_unreviewed_age_days = None
        return [], []
    ordered = sorted(pages, key=lambda page: page.id)
    changed_sources = set(changed_source_ids)

    def risk(page: WikiPage) -> int:
        return sum(20 * int(bool(changed_sources.intersection(claim.source_ids)) or claim.review_required)
                   + 8 * int(claim.status == "disputed") + 5 * int(claim.impact == "consequential")
                   + 3 * int(claim_is_stale(claim, now))
                   + 2 * int(claim.impact == "consequential" and not claim.challenge_id)
                   + 2 * int(claim.impact == "consequential" and len({link.evidence_origin_id for link in claim.evidence_links if link.evidence_origin_id}) <= 1)
                   for claim in page.claims)

    limit = min(max_pages, len(ordered))
    # Every round with >1 slot retains a rotating slot; one-slot audits alternate.
    rotate_count = 1 if limit > 1 or state.review_round % 2 else 0
    rotated = [ordered[(state.cursor + offset) % len(ordered)] for offset in range(len(ordered))]
    selected = rotated[:rotate_count]
    state.cursor = (state.cursor + rotate_count) % len(ordered)
    for page in sorted(ordered, key=lambda p: (-risk(p), state.reviewed_at.get(p.id, ""), p.id)):
        if len(selected) == limit:
            break
        if page.id not in {chosen.id for chosen in selected}:
            selected.append(page)
    if not rotate_count and selected:
        state.cursor = (ordered.index(selected[-1]) + 1) % len(ordered)
    # Rotation reserves a real slot even while high-risk findings remain open.
    state.review_round += 1
    findings: list[MaintenanceFinding] = []
    propositions: dict[tuple[str, str], list[tuple[WikiPage, object]]] = {}
    for page in ordered:
        for claim in page.claims:
            key = (normalize_question(claim.subject), normalize_question(claim.predicate))
            propositions.setdefault(key, []).append((page, claim))
    comparisons: set[tuple[str, str]] = set()
    for page in selected:
        for left in page.claims:
            if claim_is_stale(left, now):
                findings.append(MaintenanceFinding(f"stale-claim:{left.id}", "staleness", [page.id],
                                f"Claim has no assessment or exceeds its {left.review_after_days}-day policy; page last_checked is not claim verification", True, [left.id], left.source_ids))
            if changed_sources.intersection(left.source_ids) or left.review_required:
                findings.append(MaintenanceFinding(f"dependency-review:{left.id}", "changed_dependency", [page.id], "Source/dependent support changed; reassess this conclusion", True, [left.id], left.source_ids))
            if left.impact == "consequential" and not left.challenge_id:
                findings.append(MaintenanceFinding(f"challenge:{left.id}", "validation", [page.id], "Consequential claim has no recorded bounded counter-check", True, [left.id], left.source_ids))
            if left.impact == "consequential" and len({link.evidence_origin_id for link in left.evidence_links if link.evidence_origin_id}) <= 1:
                findings.append(MaintenanceFinding(f"single-origin:{left.id}", "validation", [page.id], "Consequential claim has one or no established evidence origin; assess replication and independence", True, [left.id], left.source_ids))
            matches = propositions[(normalize_question(left.subject), normalize_question(left.predicate))]
            for other, right in matches:
                pair = tuple(sorted((left.id, right.id)))
                if left.id == right.id or pair in comparisons:
                    continue
                if len(comparisons) >= max_comparisons:
                    if "Claim comparison allowance exhausted" not in state.coverage_limits:
                        state.coverage_limits.append("Claim comparison allowance exhausted")
                    break
                comparisons.add(pair)
                relation = compare_claims(left, right)
                if relation in {"contradiction", "uncertain_match"}:
                    key = f"{relation}:{pair[0]}:{pair[1]}"
                    detail = "Conflicting normalized propositions overlap in conditions/time; retain both evidentiary sides" if relation == "contradiction" else "Units or incomplete conditions prevent a definite contradiction decision"
                    findings.append(MaintenanceFinding(key, relation, sorted({page.id, other.id}), detail, True, list(pair), sorted(set(left.source_ids + right.source_ids))))
        state.reviewed_at[page.id] = now.isoformat()
    state.last_reviewed_ids = [page.id for page in selected]
    state.last_compared_claim_ids = sorted({claim_id for pair in comparisons for claim_id in pair})
    state.semantic_coverage_complete = inventory_complete and limit == len(ordered) and not state.coverage_limits
    remaining = [page for page in ordered if page.id not in state.last_reviewed_ids]
    state.oldest_unreviewed_age_days = max((max(0, (now - require_timestamp(state.reviewed_at.get(page.id, page.created_at))).days) for page in remaining), default=None)
    if limit < len(ordered):
        state.coverage_limits.append(f"Reviewed {limit} of {len(ordered)} active pages")
    unique = [finding for finding in findings if finding.key not in state.open_finding_keys]
    state.open_finding_keys.update(finding.key for finding in findings)
    return unique, [page.id for page in selected]
