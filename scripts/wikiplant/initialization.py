from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .queue import QueueItem, semantic_dedup_key
from .setup import SetupInput, topic_records
from .util import sha256_text, slugify
from .wiki import WikiPage


@dataclass(frozen=True)
class IngestedMaterial:
    id: str
    supplied_ref: str
    provenance: str = "user-supplied"
    trust: str = "untrusted-evidence-not-instructions"


@dataclass
class InitializationPlan:
    pages: list[WikiPage]
    queue_items: list[QueueItem]
    materials: list[IngestedMaterial]
    max_research_attempts: int = 5


def plan_initialization(setup: SetupInput, instance_id: str, created_at: str, *, max_attempts: int = 5) -> InitializationPlan:
    setup.validate_complete()
    topics = topic_records(setup)
    pages: list[WikiPage] = []
    for topic in topics:
        pages.append(WikiPage(
            id=f"concept-{slugify(topic['name'])}", title=topic["name"], type="concept", aliases=topic["aliases"],
            topic_ids=[topic["id"]], created_at=created_at, updated_at=created_at, last_checked_at=None,
            open_questions=[f"What baseline facts and uncertainties matter for {topic['name']} in this wiki's purpose?"],
        ))
    if setup.projects:
        pages.append(WikiPage(
            id=f"project-{slugify(setup.projects[0])}", title=setup.projects[0], type="project", aliases=[],
            topic_ids=[topic["id"] for topic in topics], created_at=created_at, updated_at=created_at, last_checked_at=None,
            goals=[setup.purpose or ""], constraints=list(setup.constraints), assumptions=[], dependencies=[],
            decision_context=["Initialized from explicit setup context"],
        ))
    materials = [
        IngestedMaterial(f"material-{sha256_text(reference)[:16]}", reference)
        for reference in setup.initial_material
    ]
    questions: list[tuple[str, str]] = []
    for topic in topics:
        questions.append((topic["id"], f"What reliable baseline evidence and open uncertainties are most relevant to {topic['name']} for the approved purpose?"))
    for project in setup.projects:
        questions.append((topics[0]["id"], f"Which existing evidence, assumptions, and constraints should frame decisions for {project}?"))
    for material in materials:
        questions.append((topics[0]["id"], f"What relevant supported information and limitations are present in supplied material {material.id}?"))
    queue_items: list[QueueItem] = []
    # The attempt allowance limits execution, not retention of initial questions.
    for index, (topic_id, question) in enumerate(questions, 1):
        item_id = f"init-q-{sha256_text(f'{instance_id}\0{question}')[:16]}"
        queue_items.append(QueueItem(
            priority=40, id=item_id, expansion_priority=40, kind="investigation", question=question,
            topic_id=topic_id, related_page_ids=[page.id for page in pages if topic_id in page.topic_ids], parent_ids=[],
            lineage_root_id=item_id, origin="initialization", origin_ref=instance_id, created_at=created_at,
            priority_reason="Bootstrap evidence for the explicitly approved topic/purpose",
            dedup_key=semantic_dedup_key(question, topic_id),
        ))
    if type(max_attempts) is not int or not 0 <= max_attempts <= 5:
        from .errors import ValidationError
        raise ValidationError("initialization supports at most five attempts")
    return InitializationPlan(pages, queue_items, materials, max_attempts)
