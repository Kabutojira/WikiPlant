"""Conservative v1 -> v2 migration: retain evidence, identity and user ownership."""
from __future__ import annotations

import copy
import csv
import io
import json
from dataclasses import dataclass, fields

from ..errors import ConflictError, ValidationError
from ..records import Claim
from ..topics import Topic, TopicRegistry, migrate_approved_topics
from ..util import pretty_json, require_timestamp, sha256_bytes
from ..wiki import MANAGED_END, MANAGED_START, WikiPage, parse_page, render_page
from ..yamlio import dumps, loads


MARKER = "installation/migrations/1_to_2.json"


@dataclass
class MigrationResult:
    files: dict[str, bytes]
    report: dict
    changed_paths: list[str]
    created_paths: list[str]
    ready_for_activation: bool


def _defaults(existing: dict, new: dict) -> dict:
    """Only add absent release defaults. Existing overrides/unknown data remain."""
    result = copy.deepcopy(existing)
    for key, value in new.items():
        if key not in result:
            result[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(result[key], dict):
            result[key] = _defaults(result[key], value)
    return result


def _claim(value: dict, reviews: list[str]) -> dict:
    result = copy.deepcopy(value)
    if result.get("schema_version") == 2:
        return result
    if not result.get("id"):
        raise ValidationError("legacy structured claim lacks stable ID; preserve for manual reconciliation")
    old_status, old_confidence = result.get("status"), result.get("confidence")
    if old_status in {"verified", "supported"}:
        result["status"] = "uncertain"
    result["schema_version"] = 2
    result["review_required"] = old_status not in {"user_note", "hypothesis", "superseded"}
    result.setdefault("status_history", []).append({"status": old_status, "confidence": old_confidence,
                                                     "reason": "Legacy assessment retained; exact evidence requires policy re-evaluation", "assessed_at": None})
    result["assessment_reason"] = "Migrated without inventing evidence locators, inspection, independence or challenge results"
    if result["review_required"]:
        reviews.append(result["id"])
    Claim.from_dict(result).validate()
    return result


def migrate_instance(files: dict[str, bytes], *, instance_id: str, authorization_history: dict[str, dict],
                     migrated_at: str, new_defaults: dict | None = None) -> MigrationResult:
    """Plan detached bytes. Updater backs up and applies same-ID snapshot writes.

    An already migrated input is returned byte-identically. No budget/calendar/queue
    reset, no archive compaction outside its separate verified transaction.
    """
    require_timestamp(migrated_at, "migration time")
    original = dict(files)
    if MARKER in original:
        report = json.loads(original[MARKER])
        if report.get("instance_id") != instance_id:
            raise ValidationError("migration marker instance mismatch")
        registry = TopicRegistry.parse(original["data/TOPICS.md"].decode())
        if registry.instance_id != instance_id or loads(original["config.yml"].decode()).get("schema_version") != 2:
            raise ConflictError("migration marker does not match migrated config/registry")
        return MigrationResult(original, report, [], [], not report["unresolved_topic_ids"] and not report["blockers"])
    if "config.yml" not in original:
        raise ValidationError("migration requires a complete canonical configuration")
    config = loads(original["config.yml"].decode("utf-8"))
    if config.get("instance", {}).get("id") != instance_id:
        raise ValidationError("configuration belongs to another instance")
    if config.get("schema_version") != 1:
        raise ValidationError("1_to_2 migration requires schema 1 or its own completion marker")
    registry, config2, unresolved = migrate_approved_topics(config, instance_id=instance_id,
                                                         authorization_history=authorization_history, created_at=migrated_at)
    output = copy.deepcopy(original)
    reviews, legacy_prose_pages, blockers, changes = [], [], [], []
    found_topics = set(registry.by_id)
    source_ids, source_refs = set(), set()
    page_count = 0
    claim_count = 0

    def walk(value):
        nonlocal claim_count
        if isinstance(value, list):
            return [walk(item) for item in value]
        if not isinstance(value, dict):
            return value
        for key in ("topic_ids",):
            found_topics.update(value.get(key, []))
        if value.get("topic_id"):
            found_topics.add(value["topic_id"])
        source_refs.update(value.get("source_ids", []))
        if {"id", "subject", "predicate", "value", "status"} <= value.keys():
            claim_count += 1
            return _claim(value, reviews)
        return {key: walk(item) for key, item in value.items()}

    for path, payload in sorted(original.items()):
        if path == "config.yml":
            continue
        if path.endswith(".csv"):
            # Inventory uses real CSV; preserve every original byte/unknown column.
            rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8"))))
            ids = [row["id"] for row in rows if row.get("id")]
            if len(ids) != len(set(ids)):
                blockers.append(f"duplicate stable IDs in {path}")
            found_topics.update(row["topic_id"] for row in rows if row.get("topic_id"))
        elif path.endswith(".json") and path.startswith("data/"):
            value = json.loads(payload)
            updated = walk(value)
            if path.startswith("data/sources/") and isinstance(value, dict) and value.get("id"):
                source_ids.add(value["id"])
            if updated != value:
                output[path] = pretty_json(updated).encode()
        elif path.startswith("data/wiki/") and payload.startswith(b"---json\n"):
            text = payload.decode("utf-8")
            end = text.index("\n---\n")
            meta = json.loads(text[len("---json\n"):end])
            page_count += 1
            found_topics.update(meta.get("topic_ids", []))
            source_refs.update(meta.get("source_ids", []))
            if meta.get("schema_version") == 2:
                parse_page(text)
                continue
            if text.count(MANAGED_START) != 1 or text.count(MANAGED_END) != 1:
                blockers.append(f"malformed managed region: {path}")
                continue
            start, finish = text.index(MANAGED_START), text.index(MANAGED_END) + len(MANAGED_END)
            boundary = "\n\n## User notes\n\n"
            if not text[finish:].startswith(boundary):
                blockers.append(f"unrecognized user boundary: {path}")
                continue
            user_text = text[finish + len(boundary):]
            updated = walk(meta)
            updated.pop("schema_version", None)
            names = {field.name for field in fields(WikiPage)} - {"extra_fields"}
            values = {key: value for key, value in updated.items() if key in names}
            extras = {key: value for key, value in updated.items() if key not in names}
            if "claims" not in values:
                # v1 renderer discarded claim IDs. Preserve exact old material and
                # refuse to infer canonical identities or factual confidence.
                extras["legacy_managed_content"] = text[start:finish]
                extras["legacy_assessment_required"] = True
                legacy_prose_pages.append(meta["id"])
                values["uncertainties"] = ["Legacy rendered findings retained in metadata; claim identities/evidence require reconciliation."]
            values["claims"] = [Claim.from_dict(c) for c in values.get("claims", [])]
            page = WikiPage(**values, extra_fields=extras)
            output[path] = render_page(page, user_text).encode()
            changes.append({"path": path, "reason": "lossless legacy content/notes retained; unsupported assessments downgraded"})
    for topic_id in sorted(found_topics - set(registry.by_id)):
        registry.topics.append(Topic(topic_id, topic_id, "adjacent", [], [], "", "Legacy referenced topic; direct anchor relevance unresolved",
                                     migrated_at, migrated_at, 1, lifecycle="provisional", may_spawn_research=False,
                                     extra={"legacy_label_unknown": True}))
        unresolved.append(topic_id)
    registry.validate()
    config2 = _defaults(config2, new_defaults or {})
    if not config2.get("primary_topic_ids"):
        blockers.append("No demonstrably authorized monitored anchor; retain paused until scope resolved")
    output["config.yml"] = dumps(config2).encode()
    output["data/TOPICS.md"] = registry.render().encode()
    if source_refs - source_ids:
        blockers.append("Referenced source records are unresolved; complete inventory/reconciliation before activation")
    report = {"schema_version": 2, "migration": "1_to_2", "instance_id": instance_id, "migrated_at": migrated_at,
              "input_hashes": {p: sha256_bytes(b) for p, b in sorted(original.items())},
              "unresolved_topic_ids": sorted(set(unresolved)), "unresolved_source_ids": sorted(source_refs - source_ids),
              "claim_revalidation_ids": sorted(set(reviews)), "legacy_prose_page_ids": legacy_prose_pages,
              "blockers": blockers, "changes": changes,
              "counts": {"before_files": len(original), "after_files": len(output) + 1, "wiki_pages_preserved": page_count,
                         "structured_claims_preserved": claim_count, "topics_preserved": len(registry.topics)},
              "preserved_without_rewrite": [p for p in original if output[p] == original[p]],
              "revalidation_policy": "Submit reviews through shared admission; unresolved topics cannot execute automatically",
              "archive_policy": "No ad hoc deletion: peripheral legacy compaction requires the reference-safe archive transaction",
              "compatibility": {"old_reader": "v1 reader is incompatible with v2 registry/claims", "new_reader": "v2; unassessed legacy prose retained"}}
    output[MARKER] = pretty_json(report).encode()
    return MigrationResult(output, report, [p for p in original if output[p] != original[p]],
                           [p for p in output if p not in original], not unresolved and not blockers)
