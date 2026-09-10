"""Compact archival memory with staged snapshot-bound writes and selective lookup."""
from __future__ import annotations

import base64
import copy
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Callable, Any

from .calendar import CalendarItem, read_calendar, write_calendar
from .errors import ConflictError, ValidationError
from .queue import read_queue, write_queue
from .storage import Binding, FileSnapshot, SafeWriter, create_artifact, find_artifact, validate_binding
from .topics import TopicRegistry, ID
from .util import canonical_json, normalize_question, pretty_json, require_timestamp, sha256_text


@dataclass
class ArchiveCapsule:
    topic_id: str
    title: str
    aliases: list[str]
    previous_classification: str
    original_anchor_ids: list[str]
    parent_ids: list[str]
    scope_revision: int
    created_at: str
    last_investigation_at: str | None
    archived_at: str
    reason: str
    summary: str
    key_claim_refs: list[str]
    evidence_refs: list[str]
    negative_findings: list[str]
    uncertainty: list[str]
    applicability_limits: list[str]
    research_parent_ids: list[str]
    lineage_root_ids: list[str]
    expansion_priority: int
    reactivation_conditions: list[str]
    user_notes: str = ""
    redirects: list[str] = field(default_factory=list)
    schema_version: int = 2
    content_version: int = 1
    lifecycle: str = "archived"
    may_spawn_research: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not ID.fullmatch(self.topic_id) or self.schema_version != 2 or self.content_version < 1:
            raise ValidationError("archive stable ID/schema/version required")
        if self.previous_classification not in {"user", "adjacent", "peripheral"} or self.lifecycle != "archived" or self.may_spawn_research:
            raise ValidationError("archive is inactive and terminal")
        if not self.title.strip() or not self.reason.strip() or not self.summary.strip() or not self.reactivation_conditions:
            raise ValidationError("archive must explain learning, stopping reason and reactivation conditions")
        if type(self.expansion_priority) is not int or not 0 <= self.expansion_priority <= 100:
            raise ValidationError("archive must preserve valid expansion score")
        if type(self.scope_revision) is not int or self.scope_revision < 1:
            raise ValidationError("archive scope revision required")
        require_timestamp(self.created_at)
        require_timestamp(self.archived_at)
        if self.last_investigation_at:
            require_timestamp(self.last_investigation_at)
        for name in ("aliases", "original_anchor_ids", "parent_ids", "key_claim_refs", "evidence_refs", "negative_findings", "uncertainty", "applicability_limits", "research_parent_ids", "lineage_root_ids", "reactivation_conditions", "redirects"):
            values = getattr(self, name)
            if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
                raise ValidationError(f"archive {name} must be a list of nonempty strings")
        if self.key_claim_refs and not self.evidence_refs:
            raise ValidationError("retained claims need their evidence locators or explicit user-note references")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        value = asdict(self)
        extra = value.pop("extra")
        if set(extra) & set(value):
            raise ValidationError("archive unknown fields cannot override canonical metadata")
        return {**extra, **value}

    def render(self) -> str:
        value = self.to_dict()
        notes = value.pop("user_notes")
        return "---json\n" + pretty_json(value) + "---\n\n# " + self.title.replace("\n", " ") + " (archived)\n\n" + self.summary + "\n\n## User notes\n\n" + notes

    @classmethod
    def parse(cls, text: str) -> "ArchiveCapsule":
        if not text.startswith("---json\n") or "\n---\n" not in text:
            raise ValidationError("complete archive metadata required")
        try:
            raw, body = text[len("---json\n"):].split("\n---\n", 1)
            value = json.loads(raw)
            names = set(cls.__dataclass_fields__) - {"extra"}
            prefix = "\n# " + value["title"].replace("\n", " ") + " (archived)\n\n" + value["summary"] + "\n\n## User notes\n\n"
            if not body.startswith(prefix):
                raise ValidationError("archive readable summary disagrees with metadata")
            value["user_notes"] = body[len(prefix):]
            capsule = cls(**{k: v for k, v in value.items() if k in names}, extra={k: v for k, v in value.items() if k not in names})
            capsule.validate()
            return capsule
        except (KeyError, ValueError, TypeError) as exc:
            raise ValidationError("invalid archive capsule") from exc


@dataclass
class ArchiveMutation:
    stage: str
    binding: Binding
    base: FileSnapshot
    content: str

    def to_dict(self) -> dict[str, Any]:
        snapshot = asdict(self.base)
        snapshot["content"] = base64.b64encode(self.base.content).decode("ascii")
        return {"stage": self.stage, "binding": asdict(self.binding), "base": snapshot, "content": self.content}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ArchiveMutation":
        snapshot = dict(value["base"])
        snapshot["content"] = base64.b64decode(snapshot["content"], validate=True)
        return cls(value["stage"], Binding(**value["binding"]), FileSnapshot(**snapshot), value["content"])


@dataclass
class ArchivePlan:
    operation_id: str
    instance_id: str
    topic_id: str
    mutations: list[ArchiveMutation]
    inventory: dict[str, list[str]]
    represented_record_ids: list[str]
    deferred_record_ids: list[str]
    retained_evidence_ids: list[str]
    retired_queue_ids: list[str]
    retired_calendar_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 2, **asdict(self), "mutations": [m.to_dict() for m in self.mutations]}


def plan_archive(*, operation_id: str, instance_id: str, capsule: ArchiveCapsule,
                 topic_file: tuple[Binding, FileSnapshot], registry_file: tuple[Binding, FileSnapshot],
                 queue_file: tuple[Binding, FileSnapshot], calendar_file: tuple[Binding, FileSnapshot],
                 index_file: tuple[Binding, FileSnapshot], active_index_file: tuple[Binding, FileSnapshot],
                 admission_file: tuple[Binding, FileSnapshot], inventory: dict[str, list[str]],
                 complete_inventory: bool, unreported_record_ids: list[str], represented_record_ids: list[str],
                 deferred_record_ids: list[str], retained_evidence_ids: list[str],
                 disposable_research_files: list[tuple[Binding, FileSnapshot]] | None = None) -> ArchivePlan:
    """Preserve the existing raw file ID as capsule and record one redirect authority."""
    capsule.validate()
    required = {"claims", "sources", "reports", "queue", "calendar", "user_notes"}
    if not complete_inventory or not required.issubset(inventory):
        raise ValidationError("reference-safe compaction requires complete inbound inventory")
    if not set(unreported_record_ids).issubset(set(represented_record_ids) | set(deferred_record_ids)):
        raise ValidationError("unreported evidence must be represented or explicitly deferred before compaction")
    if not set(inventory["claims"]).issubset(capsule.key_claim_refs):
        raise ValidationError("archive would lose referenced claim identities")
    if not set(inventory["sources"]).issubset(retained_evidence_ids):
        raise ValidationError("archive would discard required source evidence")
    registry = TopicRegistry.parse(registry_file[1].content.decode("utf-8"))
    if registry.instance_id != instance_id or capsule.topic_id not in registry.by_id:
        raise ValidationError("archive topic/instance binding mismatch")
    topic = registry.by_id[capsule.topic_id]
    if topic.classification == "user":
        raise ValidationError("automatic archival cannot remove a user anchor")
    if (capsule.previous_classification != topic.classification or capsule.original_anchor_ids != topic.user_anchor_ids or capsule.parent_ids != topic.parent_ids or
            capsule.expansion_priority != topic.expansion_priority or capsule.research_parent_ids != topic.research_parent_ids or capsule.lineage_root_ids != topic.lineage_root_ids):
        raise ValidationError("archive must preserve original classification, anchors and lineage")
    # Reject silent loss of user-owned passages, including unknown pages.
    from .wiki import parse_page
    original_page, notes = parse_page(topic_file[1].content.decode("utf-8"))
    if capsule.user_notes != notes:
        raise ValidationError("archive must preserve user notes byte-for-byte")
    capsule = copy.deepcopy(capsule)
    capsule.extra["preserved_page_fields"] = copy.deepcopy(original_page.extra_fields)
    archived = copy.deepcopy(topic)
    archived.lifecycle = "archived"
    archived.may_spawn_research = False
    archived.reviewed_at = capsule.archived_at
    updated_registry = registry.transition(archived)
    from .admission import AdmissionGate
    gate = AdmissionGate.from_dict(json.loads(admission_file[1].content), registry)
    for record in gate.lineage.values():
        if record.topic_id == capsule.topic_id and not record.explicit_user:
            record.status = "archived"
            record.terminal = True
    gate.registry = updated_registry
    queue = read_queue(queue_file[1].content.decode("utf-8"))
    affected = [q for q in queue if q.topic_id == capsule.topic_id and q.origin != "user"]
    if any(q.status == "in_progress" for q in affected):
        raise ConflictError("archive must wait for active investigation writers to drain")
    queue_out = [q for q in queue if q not in affected]
    calendar = read_calendar(calendar_file[1].content.decode("utf-8"))
    retired_calendar = []
    for item in calendar:
        belongs = item.topic_id == capsule.topic_id or (not item.topic_id and (original_page.id in item.related_page_ids or item.id in inventory["calendar"]))
        if item.kind == "research_refresh" and belongs and item.status not in {"cancelled", "completed"}:
            item.status = "cancelled"
            item.updated_at = capsule.archived_at
            retired_calendar.append(item.id)
    # Derived archive index: ID -> the same canonical file, never a second editable copy.
    try:
        index = json.loads(index_file[1].content.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError("archive redirect index must be complete JSON") from exc
    entry = {"topic_id": capsule.topic_id, "file_id": topic_file[0].file_id, "title": capsule.title, "aliases": capsule.aliases, "lifecycle": "archived", "archived_at": capsule.archived_at}
    existing = index.get(capsule.topic_id)
    if existing and existing.get("file_id") != topic_file[0].file_id:
        raise ConflictError("archive topic already has another authoritative destination")
    index[capsule.topic_id] = entry
    active_index = active_index_file[1].content.decode("utf-8")
    if not active_index.startswith("# Wiki index"):
        raise ValidationError("active wiki index format must be reconciled before compaction")
    matched = [line for line in active_index.splitlines() if f"`{original_page.id}`" in line]
    if len(matched) != 1:
        raise ValidationError("active index must identify exactly one mapped page to archive")
    active_index = active_index.replace(matched[0] + "\n", "", 1)
    redirect = f"<!-- archived-topic:{capsule.topic_id}; page:{original_page.id}; file:{topic_file[0].file_id} -->\n"
    active_index += "\n" + redirect
    mutations = [ArchiveMutation("CAPSULE_VERIFIED", *topic_file, capsule.render()),
                 ArchiveMutation("REDIRECTS_VERIFIED", *index_file, pretty_json(index)),
                 ArchiveMutation("ACTIVE_INDEX_RECONCILED", *active_index_file, active_index),
                 ArchiveMutation("REGISTRY_ARCHIVED", *registry_file, updated_registry.render()),
                 ArchiveMutation("ADMISSION_RETIRED", *admission_file, pretty_json(gate.to_dict())),
                 ArchiveMutation("QUEUE_RETIRED", *queue_file, write_queue(queue_out)),
                 ArchiveMutation("CALENDAR_RETIRED", *calendar_file, write_calendar(calendar))]
    for binding, base in disposable_research_files or []:
        compacted = compact_research_dossier(base.content.decode("utf-8"), capsule=capsule, capsule_file_id=topic_file[0].file_id,
            represented_record_ids=represented_record_ids, deferred_record_ids=deferred_record_ids, retained_evidence_ids=retained_evidence_ids)
        mutations.append(ArchiveMutation("DOSSIER_COMPACTED-" + sha256_text(binding.file_id)[:16], binding, base, pretty_json(compacted)))
    return ArchivePlan(operation_id, instance_id, capsule.topic_id, mutations, inventory, represented_record_ids, deferred_record_ids, retained_evidence_ids, [q.id for q in affected], retired_calendar)


def compact_research_dossier(text: str, *, capsule: ArchiveCapsule, capsule_file_id: str,
                            represented_record_ids: list[str], deferred_record_ids: list[str], retained_evidence_ids: list[str]) -> dict[str, Any]:
    """Replace disposable generated findings with a compact redirect; retain audit metadata.

    Unknown fields and qualifiers are preserved rather than guessed disposable.
    A record linked to another active topic is never compacted by this operation.
    """
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError("research compaction needs complete raw JSON") from exc
    if record.get("schema_version") != 2 or record.get("topic_ids") != [capsule.topic_id] or not record.get("id"):
        raise ValidationError("only a known v2 dossier exclusively owned by this archived topic is disposable")
    if record["id"] not in set(represented_record_ids) | set(deferred_record_ids):
        raise ValidationError("dossier coverage membership must survive compaction")
    if not set(record.get("source_ids", [])).issubset(retained_evidence_ids):
        raise ValidationError("dossier evidence must be retained before generated narrative compaction")
    if record.get("status") not in {"complete", "partial", "blocked"}:
        raise ValidationError("do not compact an in-progress research operation")
    output = copy.deepcopy(record)
    output["record_type"] = "archived-research-reference"
    output["original_status"] = output.pop("status")
    output["findings"] = []
    output["archive_reference"] = {"topic_id": capsule.topic_id, "file_id": capsule_file_id, "summary": capsule.summary, "archived_at": capsule.archived_at}
    output["original_record_sha256"] = sha256_text(text)
    output["may_spawn_research"] = False
    return output


def execute_archive(writer: SafeWriter, operations_folder_id: str, plan: ArchivePlan, *, interrupt_after: str | None = None) -> dict[str, Any]:
    """Durable original snapshots allow fresh-process replay at every checkpoint."""
    if plan.instance_id != writer.instance_id:
        raise ValidationError("archive plan belongs to another instance")
    key = sha256_text(plan.operation_id)[:24]
    payload = plan.to_dict()
    prior = find_artifact(writer.adapter, writer.root_id, operations_folder_id, f"archive-{key}-intent.json")
    final = find_artifact(writer.adapter, writer.root_id, operations_folder_id, f"archive-{key}-complete.json")
    if final and prior:
        previous = json.loads(prior.content)
        matches = previous == payload or (previous.get("compacted") is True and previous.get("original_intent_sha256") == sha256_text(canonical_json(payload)))
        if not matches:
            raise ConflictError("completed archive operation ID reused for a different intent")
        return json.loads(final.content)
    intent = create_artifact(writer.adapter, writer.root_id, operations_folder_id, f"archive-{key}-intent.json", payload, f"archive:{plan.operation_id}:intent")
    original = json.loads(intent.content)
    if original != payload:
        raise ConflictError("archive operation ID reused with different original intent")
    receipts = []
    for mutation in [ArchiveMutation.from_dict(value) for value in original["mutations"]]:
        receipt = writer.replace(mutation.binding, mutation.content.encode("utf-8"), f"{plan.operation_id}:{mutation.stage}", base=mutation.base)
        observed = {"stage": mutation.stage, "file_id": receipt.target_id, "verified_sha256": receipt.verified_sha256, "completion_reference": receipt.completion_reference}
        create_artifact(writer.adapter, writer.root_id, operations_folder_id, f"archive-{key}-{mutation.stage}.json", observed, f"archive:{plan.operation_id}:{mutation.stage}:receipt")
        receipts.append(observed)
        if interrupt_after == mutation.stage:
            raise RuntimeError(f"injected archive interruption after {mutation.stage}")
    result = {"schema_version": 2, "operation_id": plan.operation_id, "topic_id": plan.topic_id, "status": "COMPLETE", "receipts": receipts,
              "retired_queue_ids": plan.retired_queue_ids, "retired_calendar_ids": plan.retired_calendar_ids,
              "deferred_record_ids": plan.deferred_record_ids, "recovery_snapshot_ref": intent.id,
              "bulk_cleanup": "COMPACTED" if any(m.stage.startswith("DOSSIER_COMPACTED-") for m in plan.mutations) else "NOT_REQUESTED",
              "reason": "inactive obligations retired; required evidence and user notes preserved"}
    create_artifact(writer.adapter, writer.root_id, operations_folder_id, f"archive-{key}-complete.json", result, f"archive:{plan.operation_id}:complete")
    return result


def resume_archive(writer: SafeWriter, operations_folder_id: str, operation_id: str) -> dict[str, Any]:
    completed = find_artifact(writer.adapter, writer.root_id, operations_folder_id, f"archive-{sha256_text(operation_id)[:24]}-complete.json")
    if completed:
        return json.loads(completed.content)
    snapshot = find_artifact(writer.adapter, writer.root_id, operations_folder_id, f"archive-{sha256_text(operation_id)[:24]}-intent.json")
    if snapshot is None:
        raise ValidationError("no durable archive intent to resume")
    value = json.loads(snapshot.content)
    value.pop("schema_version")
    value["mutations"] = [ArchiveMutation.from_dict(m) for m in value["mutations"]]
    return execute_archive(writer, operations_folder_id, ArchivePlan(**value))


def compact_recovery_snapshot(writer: SafeWriter, operations_folder_id: str, operation_id: str, *, now: datetime, minimum_age_days: int = 7) -> dict[str, Any]:
    """After verified completion/retention, discard disposable original bulk, keep audit identities.

    This is an explicit maintenance policy action. Never applies to incomplete
    transactions, retained sources or user notes in the canonical capsule.
    """
    if type(minimum_age_days) is not int or minimum_age_days < 1:
        raise ValidationError("recovery retention interval must be a positive number of days")
    key = sha256_text(operation_id)[:24]
    intent = find_artifact(writer.adapter, writer.root_id, operations_folder_id, f"archive-{key}-intent.json")
    completed = find_artifact(writer.adapter, writer.root_id, operations_folder_id, f"archive-{key}-complete.json")
    if intent is None or completed is None:
        raise ValidationError("the only recovery state of an incomplete archive must be retained")
    value = json.loads(intent.content)
    if value.get("compacted"):
        return value
    capsule_mutation = ArchiveMutation.from_dict(value["mutations"][0])
    current = validate_binding(writer.adapter, capsule_mutation.binding, writer.root_id)
    capsule = ArchiveCapsule.parse(current.content.decode("utf-8"))
    if (now - require_timestamp(capsule.archived_at)).days < minimum_age_days:
        raise ValidationError("archive recovery retention window has not elapsed")
    if capsule.topic_id != value["topic_id"]:
        raise ValidationError("canonical archive identity no longer verifies")
    original_capsule = ArchiveCapsule.parse(capsule_mutation.content)
    if (capsule.user_notes != original_capsule.user_notes or
            not set(original_capsule.key_claim_refs).issubset(capsule.key_claim_refs) or
            not set(original_capsule.evidence_refs).issubset(capsule.evidence_refs)):
        raise ValidationError("preserve original recovery while notes/evidence need reconciliation")
    compact = {key: value[key] for key in ("schema_version", "operation_id", "instance_id", "topic_id", "inventory", "represented_record_ids", "deferred_record_ids", "retained_evidence_ids", "retired_queue_ids", "retired_calendar_ids")}
    compact.update(compacted=True, original_intent_sha256=sha256_text(canonical_json(value)), completion_reference=completed.id,
        compacted_at=now.isoformat(), recovery_policy={"minimum_age_days": minimum_age_days},
        mutation_identities=[{"stage": m["stage"], "binding": m["binding"], "input_revision": m["base"]["revision"],
            "input_sha256": ArchiveMutation.from_dict(m).base.sha256, "output_sha256": sha256_text(m["content"])} for m in value["mutations"]])
    binding = Binding(f"data/state/archive-operations/{intent.name}", intent.id, intent.mime_type, writer.root_id)
    writer.replace(binding, pretty_json(compact).encode(), f"{operation_id}:compact-recovery", base=intent)
    return compact


def archive_partition(term: str) -> str:
    return sha256_text(normalize_question(term))[:2]


def build_archive_partitions(entries: list[dict[str, Any]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Derived from compact metadata during maintenance, not rebuilt on every query."""
    partitions: dict[str, dict[str, list[dict[str, Any]]]] = {}
    if len({e["topic_id"] for e in entries}) != len(entries):
        raise ValidationError("archive lookup has duplicate topic identities")
    for entry in entries:
        for token in set(normalize_question(" ".join([entry["title"], *entry.get("aliases", [])])).split()):
            partitions.setdefault(archive_partition(token), {}).setdefault(token, []).append(entry)
    return partitions


def retrieve_archives(query: str, fetch_partition: Callable[[str], dict], fetch_capsule: Callable[[str], str], *, max_partitions: int = 8, max_capsules: int = 5) -> dict[str, Any]:
    if min(max_partitions, max_capsules) < 1:
        raise ValidationError("archive retrieval bounds must be positive")
    words = list(dict.fromkeys(normalize_question(query).split()))
    keys = list(dict.fromkeys(archive_partition(word) for word in words))[:max_partitions]
    matches: dict[str, dict] = {}
    for key in keys:
        partition = fetch_partition(key)
        for word in words:
            if archive_partition(word) == key:
                for entry in partition.get(word, [])[:max_capsules]:
                    matches[entry["topic_id"]] = entry
    selected = sorted(matches.values(), key=lambda e: e["topic_id"])[:max_capsules]
    capsules = []
    bytes_read = 0
    for entry in selected:
        text = fetch_capsule(entry["file_id"])
        bytes_read += len(text.encode("utf-8"))
        capsule = ArchiveCapsule.parse(text)
        if capsule.topic_id != entry["topic_id"]:
            raise ValidationError("archive lookup identity mismatch")
        capsules.append(capsule.to_dict())
    return {"capsules": capsules, "partitions_fetched": len(keys), "capsules_fetched": len(capsules), "capsule_bytes": bytes_read,
            "status": "archived; freshness is the recorded last investigation", "reactivated": False,
            "coverage": "bounded lexical partition lookup; absence is not exhaustive archive search"}
