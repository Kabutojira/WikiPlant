from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Literal

from .errors import ConflictError, ValidationError
from .records import Claim, SourceRecord
from .util import pretty_json


MANAGED_START = "<!-- wikiplant:managed:start -->"
MANAGED_END = "<!-- wikiplant:managed:end -->"


@dataclass
class WikiPage:
    id: str
    title: str
    type: str
    aliases: list[str]
    topic_ids: list[str]
    created_at: str
    updated_at: str
    last_checked_at: str | None
    source_ids: list[str] = field(default_factory=list)
    research_ids: list[str] = field(default_factory=list)
    relationship_ids: list[str] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    decision_context: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if self.type not in {"entity", "concept", "project", "synthesis"}:
            raise ValidationError("wiki page type is invalid")
        if not self.id or not self.title or not self.topic_ids:
            raise ValidationError("wiki page id/title/topic are required")
        for claim in self.claims:
            claim.validate()
        if self.type != "project" and any((self.goals, self.constraints, self.assumptions, self.dependencies, self.decision_context)):
            raise ValidationError("project-only fields used on a non-project page")


def render_page(page: WikiPage, user_text: str = "") -> str:
    page.validate()
    metadata = {
        "schema_version": 1, "id": page.id, "title": page.title, "type": page.type, "aliases": page.aliases,
        "topic_ids": page.topic_ids, "created_at": page.created_at, "updated_at": page.updated_at,
        "last_checked_at": page.last_checked_at, "source_ids": page.source_ids, "research_ids": page.research_ids,
        "relationship_ids": page.relationship_ids,
    }
    managed = [
        MANAGED_START,
        "## Claims",
        *[f"- [{claim.status}; {claim.confidence}] {claim.subject} — {claim.predicate}: {claim.value} (sources: {', '.join(claim.source_ids) or 'none'})" for claim in page.claims],
        "", "## Uncertainties", *[f"- {value}" for value in page.uncertainties],
        "", "## Relationships", *[f"- {value}" for value in page.relationship_ids],
        "", "## Open questions", *[f"- {value}" for value in page.open_questions],
    ]
    if page.type == "project":
        managed.extend(["", "## Project context", *[f"- Goal: {v}" for v in page.goals], *[f"- Constraint: {v}" for v in page.constraints], *[f"- Assumption: {v}" for v in page.assumptions], *[f"- Dependency: {v}" for v in page.dependencies], *[f"- Decision: {v}" for v in page.decision_context]])
    managed.append(MANAGED_END)
    return "---json\n" + pretty_json(metadata) + "---\n\n# " + page.title + "\n\n" + "\n".join(managed) + "\n\n## User notes\n\n" + user_text.rstrip() + "\n"


def replace_managed_section(existing: str, replacement: str) -> str:
    if existing.count(MANAGED_START) != 1 or existing.count(MANAGED_END) != 1:
        raise ConflictError("page lacks one unambiguous managed section")
    if replacement.count(MANAGED_START) != 1 or replacement.count(MANAGED_END) != 1:
        raise ValidationError("replacement lacks one managed section")
    old_start = existing.index(MANAGED_START)
    old_end = existing.index(MANAGED_END) + len(MANAGED_END)
    new_start = replacement.index(MANAGED_START)
    new_end = replacement.index(MANAGED_END) + len(MANAGED_END)
    return existing[:old_start] + replacement[new_start:new_end] + existing[old_end:]


def _range(claim: Claim) -> tuple[date | None, date | None]:
    start = date.fromisoformat(claim.valid_from) if claim.valid_from else None
    end = date.fromisoformat(claim.valid_to) if claim.valid_to else None
    return start, end


def claim_relationship(left: Claim, right: Claim) -> Literal["same", "temporal_change", "contradiction", "unrelated"]:
    if (left.subject, left.predicate) != (right.subject, right.predicate):
        return "unrelated"
    if left.value == right.value:
        return "same"
    left_start, left_end = _range(left)
    right_start, right_end = _range(right)
    if left_end and right_start and left_end < right_start:
        return "temporal_change"
    if right_end and left_start and right_end < left_start:
        return "temporal_change"
    return "contradiction"


def independent_source_count(sources: Iterable[SourceRecord]) -> int:
    groups = {source.syndication_key or source.canonical_ref for source in sources}
    return len(groups)


def applicability_analysis(finding: str, project: WikiPage) -> list[str]:
    if project.type != "project":
        raise ValidationError("applicability analysis requires a project page")
    output = [f"Potential relevance: {finding}"]
    output.extend(f"Check constraint: {constraint}" for constraint in project.constraints)
    output.extend(f"Revalidate assumption: {assumption}" for assumption in project.assumptions)
    output.append("No project performance improvement is verified until the applicable constraints are tested against source-backed evidence.")
    return output


def update_index(pages: Iterable[WikiPage]) -> str:
    sorted_pages = sorted(pages, key=lambda page: (page.type, page.title.casefold(), page.id))
    lines = ["# Wiki index", ""]
    for page in sorted_pages:
        lines.append(f"- [{page.title}]({page.type}s/{page.id}.md) — `{page.id}`; aliases: {', '.join(page.aliases) or 'none'}")
    return "\n".join(lines) + "\n"


def append_change_log(existing: str, *, timestamp: str, operation_id: str, page_ids: Iterable[str], summary: str) -> str:
    if not existing.startswith("# Wiki change log"):
        raise ValidationError("unexpected wiki change-log format")
    entry = f"- {timestamp} `{operation_id}` pages={','.join(page_ids)} — {summary}\n"
    return existing.rstrip() + "\n" + entry
