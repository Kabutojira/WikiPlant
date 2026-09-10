from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Iterable, Literal

from .errors import SimulatedLostResponse, ValidationError
from .records import Command, Receipt
from .storage import DriveAdapter, create_artifact
from .authorization import validate_user_authorization
from .util import normalize_question, pretty_json, sha256_text


@dataclass(frozen=True)
class RoutingDecision:
    operation: str
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


def route_intent(text: str, *, authorization: dict | None = None, instance_id: str = "", target: str = "") -> RoutingDecision:
    """Conservative proposal routing; only a separate host grant authorizes writes."""
    if authorization is not None:
        operation = authorization.get("operation", "")
        grant = validate_user_authorization(authorization, instance_id=instance_id, operation=operation, target=target)
        if grant.request_sha256 != sha256_text(text):
            raise ValidationError("authorization does not match the current request")
        if operation not in {"save", "add", "track", "investigate", "configure", "pause", "resume", "update"}:
            raise ValidationError("unsupported authorized operation")
        return RoutingDecision(operation, True, operation == "investigate")
    normalized = " " + normalize_question(text) + " "
    # These exclusions improve proposals only; they are not a multilingual
    # authorization classifier. Unrecognized language stays read-only.
    if re.search(r"\b(not|never|dont|don't|non|no|ne|pas|nicht|without|if|imagine|hypothetical|explain|meaning|how|what does)\b", normalized) or any(c in text for c in ('"', '“', '”', '`')):
        return RoutingDecision("query", False, False)
    if re.search(r"\b(check.*updates|updates available)\b", normalized):
        return RoutingDecision("check-updates", False, True)
    if re.search(r"\b(upgrade|update this wikiplant|update it)\b", normalized):
        return RoutingDecision("update", False, False)
    if re.search(r"\b(pause|stop schedules?)\b", normalized):
        return RoutingDecision("pause", False, False)
    if re.search(r"\b(resume|unpause)\b", normalized):
        return RoutingDecision("resume", False, False)
    if re.search(r"\b(configure|change the daily|change the weekly|change schedule)\b", normalized):
        return RoutingDecision("configure", False, False)
    if re.search(r"\b(status|installation state|last run)\b", normalized):
        return RoutingDecision("status", False, False)
    if re.search(r"\b(investigate|research this|look into)\b", normalized):
        return RoutingDecision("investigate", False, True)
    if re.search(r"\badd\b", normalized):
        return RoutingDecision("add", False, False)
    if re.search(r"\b(save|remember in|store in)\b", normalized):
        return RoutingDecision("save", False, False)
    if re.search(r"\b(track)\b", normalized):
        return RoutingDecision("track", False, False)
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


def durable_intake(adapter: DriveAdapter, inbox_folder_id: str, command: Command, *, approved_root_id: str, expected_instance_id: str) -> tuple[Receipt, str]:
    if command.instance_id != expected_instance_id:
        raise ValidationError("command belongs to another bound WikiPlant instance")
    command.validate()
    payload = asdict(command)
    filename = f"command-{sha256_text(command.id)}.json"
    key = f"{command.instance_id}:command:{command.id}"
    observed = create_artifact(adapter, approved_root_id, inbox_folder_id, filename, payload, key)
    return "ACCEPTED_PENDING_MERGE", observed.id


def select_relevant_pages(query: str, page_summaries: Iterable[dict], limit: int = 8, *,
                          semantic_selections: Iterable = (), retrieval_log: list[dict] | None = None) -> list[dict]:
    from .retrieval import select_active_pages
    result = select_active_pages(query, page_summaries, limit=limit, semantic_selections=semantic_selections)
    if retrieval_log is not None:
        retrieval_log.append(result.to_dict())
    return result.pages


def routing_profile_status(private_revision: int, installed_revision: int) -> str:
    if private_revision == installed_revision:
        return "synchronized"
    if private_revision > installed_revision:
        return "pending_host_update"
    raise ValidationError("installed routing revision cannot exceed private authority")
