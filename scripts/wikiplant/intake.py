from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Iterable, Literal

from .errors import SimulatedLostResponse, ValidationError
from .records import Command, Receipt
from .storage import DriveAdapter
from .util import normalize_question, pretty_json, sha256_text


@dataclass(frozen=True)
class RoutingDecision:
    operation: Literal["query", "current_query", "status", "save", "add", "track", "investigate", "configure", "pause", "resume"]
    writes: bool
    requires_external_evidence: bool


@dataclass(frozen=True)
class InstanceProfile:
    instance_id: str
    name: str
    terms: tuple[str, ...]


@dataclass(frozen=True)
class InstanceResolution:
    instance_id: str | None
    ambiguous_ids: tuple[str, ...] = ()


def resolve_instance(request: str, profiles: Iterable[InstanceProfile], explicit_instance_id: str | None = None) -> InstanceResolution:
    profile_list = list(profiles)
    if explicit_instance_id:
        if any(profile.instance_id == explicit_instance_id for profile in profile_list):
            return InstanceResolution(explicit_instance_id)
        raise ValidationError("explicit WikiPlant instance is not installed")
    request_terms = set(normalize_question(request).split())
    scored: list[tuple[int, str]] = []
    for profile in profile_list:
        vocabulary = normalize_question(" ".join((profile.name, *profile.terms))).split()
        score = len(request_terms.intersection(vocabulary))
        if score:
            scored.append((score, profile.instance_id))
    if not scored:
        return InstanceResolution(None)
    best = max(score for score, _ in scored)
    matches = tuple(sorted(instance_id for score, instance_id in scored if score == best))
    return InstanceResolution(matches[0] if len(matches) == 1 else None, matches if len(matches) > 1 else ())


def route_intent(text: str) -> RoutingDecision:
    normalized = " " + normalize_question(text) + " "
    if re.search(r"\b(pause|stop schedules?)\b", normalized):
        return RoutingDecision("pause", True, False)
    if re.search(r"\b(resume|unpause)\b", normalized):
        return RoutingDecision("resume", True, False)
    if re.search(r"\b(configure|change the daily|change the weekly|change schedule)\b", normalized):
        return RoutingDecision("configure", True, False)
    if re.search(r"\b(status|installation state|last run)\b", normalized):
        return RoutingDecision("status", False, False)
    if re.search(r"\b(investigate|research this|look into)\b", normalized):
        return RoutingDecision("investigate", True, True)
    if re.search(r"\badd\b", normalized):
        return RoutingDecision("add", True, False)
    if re.search(r"\b(save|remember in|store in)\b", normalized):
        return RoutingDecision("save", True, False)
    if re.search(r"\b(track)\b", normalized):
        return RoutingDecision("track", True, False)
    if re.search(r"\b(current|latest|verify now|what changed)\b", normalized):
        return RoutingDecision("current_query", False, True)
    return RoutingDecision("query", False, False)


def observed_receipt(decision: RoutingDecision, *, durable_reference: str | None, canonical_merged: bool = False) -> Receipt:
    if not decision.writes:
        raise ValidationError("read-only operations do not have a write receipt")
    if not durable_reference:
        return "BLOCKED"
    if decision.operation == "investigate" and canonical_merged:
        return "QUEUED"
    if canonical_merged:
        return "SAVED"
    return "ACCEPTED_PENDING_MERGE"


def durable_intake(adapter: DriveAdapter, inbox_folder_id: str, command: Command) -> tuple[Receipt, str]:
    command.validate()
    payload = pretty_json(asdict(command)).encode("utf-8")
    filename = f"command-{command.id}.json"
    key = f"{command.instance_id}:command:{command.id}"
    try:
        observed = adapter.create_file(inbox_folder_id, filename, "application/json", payload, idempotency_key=key)
    except SimulatedLostResponse:
        observed = adapter.create_file(inbox_folder_id, filename, "application/json", payload, idempotency_key=key)
    readback = adapter.read_exact(observed.id)
    if not readback.complete or readback.content != payload:
        return "PARTIAL", observed.id
    return "ACCEPTED_PENDING_MERGE", observed.id


def select_relevant_pages(query: str, page_summaries: Iterable[dict], limit: int = 8) -> list[dict]:
    terms = set(normalize_question(query).split())
    scored: list[tuple[int, str, dict]] = []
    for page in page_summaries:
        haystack = " ".join([str(page.get("title", "")), *map(str, page.get("aliases", [])), *map(str, page.get("relationships", []))])
        score = len(terms.intersection(normalize_question(haystack).split()))
        if score:
            scored.append((-score, str(page.get("id", "")), page))
    return [page for _, _, page in sorted(scored)[:limit]]


def routing_profile_status(private_revision: int, installed_revision: int) -> str:
    if private_revision == installed_revision:
        return "synchronized"
    if private_revision > installed_revision:
        return "pending_host_update"
    raise ValidationError("installed routing revision cannot exceed private authority")
