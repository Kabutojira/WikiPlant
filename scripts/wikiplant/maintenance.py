from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .queue import QueueItem, deduplicate
from .util import normalize_question
from .wiki import WikiPage, claim_relationship


@dataclass
class MaintenanceFinding:
    key: str
    kind: str
    page_ids: list[str]
    detail: str
    needs_research: bool


@dataclass
class MaintenanceState:
    cursor: int = 0
    open_finding_keys: set[str] = field(default_factory=set)


def structural_lint(pages: Iterable[WikiPage]) -> list[MaintenanceFinding]:
    page_list = list(pages)
    ids = {page.id for page in page_list}
    findings: list[MaintenanceFinding] = []
    seen: set[str] = set()
    for page in page_list:
        if page.id in seen:
            findings.append(MaintenanceFinding(f"duplicate-id:{page.id}", "duplicate_id", [page.id], "Duplicate stable page ID", False))
        seen.add(page.id)
        for related in page.relationship_ids:
            if related not in ids:
                findings.append(MaintenanceFinding(f"broken-link:{page.id}:{related}", "broken_link", [page.id], f"Missing related page {related}", False))
        if not page.source_ids and any(claim.status in {"verified", "supported"} for claim in page.claims):
            findings.append(MaintenanceFinding(f"provenance:{page.id}", "provenance_gap", [page.id], "Supported claims exist without page-level source references", True))
    linked = {related for page in page_list for related in page.relationship_ids}
    for page in page_list:
        if page.type != "project" and page.id not in linked and len(page_list) > 1:
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


def semantic_audit(pages: list[WikiPage], state: MaintenanceState, max_pages: int = 30) -> tuple[list[MaintenanceFinding], list[str]]:
    if not pages:
        return [], []
    ordered = sorted(pages, key=lambda page: page.id)
    selected = [ordered[(state.cursor + offset) % len(ordered)] for offset in range(min(max_pages, len(ordered)))]
    state.cursor = (state.cursor + len(selected)) % len(ordered)
    findings: list[MaintenanceFinding] = []
    for page in selected:
        if page.claims and not page.last_checked_at:
            findings.append(MaintenanceFinding(f"stale:{page.id}", "staleness", [page.id], "Claims exist without a page freshness checkpoint", True))
        for index, left in enumerate(page.claims):
            for right in page.claims[index + 1 :]:
                relation = claim_relationship(left, right)
                if relation == "contradiction":
                    key = f"contradiction:{page.id}:{min(left.id, right.id)}:{max(left.id, right.id)}"
                    findings.append(MaintenanceFinding(key, "contradiction", [page.id], "Conflicting claims overlap in time; retain both evidentiary sides", True))
    unique = [finding for finding in findings if finding.key not in state.open_finding_keys]
    state.open_finding_keys.update(finding.key for finding in findings)
    return unique, [page.id for page in selected]
