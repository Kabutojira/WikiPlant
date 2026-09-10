from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import json
from datetime import date
from typing import Iterable, Literal

from .errors import ConflictError, ValidationError
from .records import Claim, SourceRecord
from .util import pretty_json


MANAGED_START = "<!-- wikiplant:managed:start -->"
MANAGED_END = "<!-- wikiplant:managed:end -->"
PAGE_FOLDERS = {"entity": "entities", "concept": "concepts", "project": "projects", "synthesis": "syntheses"}


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
    extra_fields: dict = field(default_factory=dict)

    def validate(self) -> None:
        if self.type not in {"entity", "concept", "project", "synthesis"}:
            raise ValidationError("wiki page type is invalid")
        if not self.id or not self.title or not self.topic_ids:
            raise ValidationError("wiki page id/title/topic are required")
        for claim in self.claims:
            claim.validate()
        if len({claim.id for claim in self.claims}) != len(self.claims):
            raise ValidationError("duplicate stable claim IDs")
        if self.type != "project" and any((self.goals, self.constraints, self.assumptions, self.dependencies, self.decision_context)):
            raise ValidationError("project-only fields used on a non-project page")


def render_page(page: WikiPage, user_text: str = "") -> str:
    page.validate()
    metadata = {**page.extra_fields, **asdict(page), "schema_version": 2}
    metadata.pop("extra_fields", None)
    metadata["claims"] = [claim.to_dict() if hasattr(claim, "to_dict") else asdict(claim) for claim in page.claims]
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
    managed = [line if line in {MANAGED_START, MANAGED_END} else line.replace("<", "&lt;").replace(">", "&gt;") for line in managed]
    canonical_json = pretty_json(metadata).replace("<", "\\u003c").replace(">", "\\u003e")
    return "---json\n" + canonical_json + "---\n\n# " + page.title + "\n\n" + "\n".join(managed) + "\n\n## User notes\n\n" + user_text


def _sections(text: str) -> tuple[int, int, int]:
    if not text.startswith("---json\n") or "\n---\n" not in text:
        raise ValidationError("page needs complete canonical JSON front matter")
    header_end = text.index("\n---\n") + len("\n---\n")
    if text.count(MANAGED_START) != 1 or text.count(MANAGED_END) != 1:
        raise ConflictError("page lacks one unambiguous managed section")
    start, end = text.index(MANAGED_START), text.index(MANAGED_END) + len(MANAGED_END)
    if start < header_end or end <= start:
        raise ConflictError("malformed managed marker order")
    return header_end, start, end


def parse_page(text: str) -> tuple[WikiPage, str]:
    header_end, start, end = _sections(text)
    try:
        metadata = json.loads(text[len("---json\n"):header_end - len("\n---\n")])
        if metadata.pop("schema_version") != 2:
            raise ValidationError("legacy page requires explicit migration; claim identity cannot be inferred from prose")
        known = {f.name for f in fields(WikiPage)} - {"extra_fields"}
        extras = {key: value for key, value in metadata.items() if key not in known}
        values = {key: value for key, value in metadata.items() if key in known}
        values["claims"] = [Claim.from_dict(c) if hasattr(Claim, "from_dict") else Claim(**c) for c in values.get("claims", [])]
        page = WikiPage(**values, extra_fields=extras)
        page.validate()
    except (TypeError, KeyError, ValueError) as exc:
        raise ValidationError("invalid canonical page metadata") from exc
    canonical = render_page(page)
    _, generated_start, generated_end = _sections(canonical)
    if text[start:end] != canonical[generated_start:generated_end]:
        raise ConflictError("managed body and canonical claim metadata disagree")
    suffix = "\n\n## User notes\n\n"
    if not text[end:].startswith(suffix):
        raise ConflictError("unrecognized user region boundary; preserve and reconcile")
    return page, text[end + len(suffix):]


def replace_managed_section(existing: str, replacement: str) -> str:
    old_page, _ = parse_page(existing)
    new_page, _ = parse_page(replacement)
    if (old_page.id, old_page.type) != (new_page.id, new_page.type):
        raise ConflictError("page identity/type cannot change in a managed update")
    new_page.extra_fields = {**old_page.extra_fields, **new_page.extra_fields}
    replacement = render_page(new_page)
    old_header, old_start, old_end = _sections(existing)
    new_header, new_start, new_end = _sections(replacement)
    between = existing[old_header:old_start]
    if not between.startswith(f"\n# {old_page.title}\n\n"):
        raise ConflictError("machine-owned title changed externally")
    between = f"\n# {new_page.title}\n\n" + between[len(f"\n# {old_page.title}\n\n"):]
    return replacement[:new_header] + between + replacement[new_start:new_end] + existing[old_end:]


def _range(claim: Claim) -> tuple[date | None, date | None]:
    start = date.fromisoformat(claim.valid_from) if claim.valid_from else None
    end = date.fromisoformat(claim.valid_to) if claim.valid_to else None
    return start, end


def claim_relationship(left: Claim, right: Claim) -> Literal["same", "temporal_change", "contradiction", "unrelated"]:
    from .evidence import compare_claims
    return compare_claims(left, right)


def independent_source_count(sources: Iterable[SourceRecord]) -> int:
    from .evidence import independent_origin_count
    return independent_origin_count(list(sources))


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
    if len({page.id for page in sorted_pages}) != len(sorted_pages):
        raise ValidationError("duplicate page identity in index")
    ids = {page.id for page in sorted_pages}
    lines = ["# Wiki index", ""]
    for page in sorted_pages:
        page.validate()
        from .util import safe_relative_path
        safe_relative_path(page.id)
        if "/" in page.id or any(ref not in ids for ref in page.relationship_ids):
            raise ValidationError("index references require mapped stable page records")
        title = page.title.replace("[", "\\[").replace("]", "\\]")
        lines.append(f"- [{title}]({PAGE_FOLDERS[page.type]}/{page.id}.md) — `{page.id}`; aliases: {', '.join(page.aliases) or 'none'}")
    return "\n".join(lines) + "\n"


def append_change_log(existing: str, *, timestamp: str, operation_id: str, page_ids: Iterable[str], summary: str) -> str:
    if not existing.startswith("# Wiki change log"):
        raise ValidationError("unexpected wiki change-log format")
    entry = f"- {timestamp} `{operation_id}` pages={','.join(page_ids)} — {summary}\n"
    return existing.rstrip() + "\n" + entry
