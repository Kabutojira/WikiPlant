"""Bounded active-index selection with explicit graph/semantic reasoning receipts."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .errors import ValidationError
from .util import normalize_question


@dataclass(frozen=True)
class SemanticSelection:
    page_id: str
    reason: str
    supporting_claim_ids: tuple[str, ...] = ()


@dataclass
class RetrievalResult:
    pages: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    considered_active_summaries: int
    excluded_archived_summaries: int
    limit: int
    coverage: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_text(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_text(item) for item in value)
    return str(value or "")


def select_active_pages(query: str, summaries: Iterable[dict[str, Any]], *, limit: int = 8,
                        semantic_selections: Iterable[SemanticSelection] = (), max_candidates: int = 5000) -> RetrievalResult:
    """Read supplied index summaries only; no fetching, scope changes or archive expansion.

    Semantic selections are explicit model reasoning supplied by the host, with
    referenced claim IDs checked against the selected page's indexed inventory.
    Their reasons are recorded, not accepted as new source evidence.
    """
    if type(limit) is not int or not 1 <= limit <= 100 or type(max_candidates) is not int or max_candidates < limit:
        raise ValidationError("retrieval bounds are invalid")
    inventory: dict[str, dict] = {}
    seen_ids: set[str] = set()
    archived = 0
    for count, page in enumerate(summaries, 1):
        if count > max_candidates:
            raise ValidationError("index partition exceeds bounded retrieval candidate allowance")
        identifier = page.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ValidationError("retrieval summaries require stable page IDs")
        if identifier in seen_ids:
            raise ValidationError("duplicate retrieval page identity")
        seen_ids.add(identifier)
        if page.get("lifecycle", page.get("status")) in {"archived", "retired"}:
            archived += 1
            continue
        inventory[identifier] = page
    terms = set(normalize_question(query).split())
    weights = {"title": 4, "aliases": 4, "entities": 3, "claims": 2, "goals": 2,
               "constraints": 2, "assumptions": 2, "relationships": 1, "dependencies": 1}
    scores: dict[str, int] = {}
    reasons: dict[str, list[dict]] = {}
    for identifier, page in inventory.items():
        matches = {key: sorted(terms.intersection(normalize_question(_text(page.get(key, ""))).split())) for key in weights}
        matches = {key: value for key, value in matches.items() if value}
        score = sum(weights[key] * len(value) for key, value in matches.items())
        if score:
            scores[identifier] = score * 10
            reasons[identifier] = [{"kind": "lexical", "matched_fields": matches}]
    seed_ids = sorted(scores, key=lambda identifier: (-scores[identifier], identifier))[:limit]
    # One bounded hop captures existing concepts/projects connected to a match.
    for identifier, page in inventory.items():
        edges = {ref for field_name in ("relationship_ids", "relationships", "dependencies")
                 for ref in page.get(field_name, []) if isinstance(ref, str)}
        for seed_id in seed_ids:
            seed = inventory[seed_id]
            seed_edges = {ref for field_name in ("relationship_ids", "relationships", "dependencies")
                          for ref in seed.get(field_name, []) if isinstance(ref, str)}
            if identifier != seed_id and (seed_id in edges or identifier in seed_edges):
                scores[identifier] = max(scores.get(identifier, 0), scores[seed_id] // 2)
                reasons.setdefault(identifier, []).append({"kind": "relationship", "via_page_id": seed_id,
                                                          "reason": "Existing direct relationship or project dependency"})
    seen_semantic: set[str] = set()
    semantic_score = max(scores.values(), default=0) + 1
    for selection in semantic_selections:
        if selection.page_id in seen_semantic or selection.page_id not in inventory or not selection.reason.strip():
            raise ValidationError("semantic selection requires one active known page and recorded reason")
        seen_semantic.add(selection.page_id)
        page = inventory[selection.page_id]
        known_claims = set(page.get("claim_ids", [])) | {claim["id"] for claim in page.get("claims", []) if isinstance(claim, dict) and "id" in claim}
        if not set(selection.supporting_claim_ids) <= known_claims:
            raise ValidationError("semantic selection refers to unknown indexed claims")
        scores[selection.page_id] = semantic_score
        reasons.setdefault(selection.page_id, []).append({"kind": "semantic", "reason": selection.reason,
                                                          "supporting_claim_ids": list(selection.supporting_claim_ids)})
    selected_ids = sorted(scores, key=lambda identifier: (-scores[identifier], identifier))[:limit]
    return RetrievalResult([inventory[identifier] for identifier in selected_ids],
                           [{"page_id": identifier, "reasons": reasons[identifier]} for identifier in selected_ids],
                           len(inventory), archived, limit,
                           f"Selected {len(selected_ids)} active pages from {len(inventory)} supplied index summaries; archive lookup is separate and does not reactivate topics")
