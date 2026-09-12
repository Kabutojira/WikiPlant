"""Detached, resumable plans for explicitly authorized storage-provider changes.

This module is deliberately provider-call free.  A host workflow obtains complete
exact source bytes, pauses writers, and supplies the observed object metadata.
The result is a bounded import package plus evidence that can be verified before
any skill, schedule, or source-backend state is changed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import IntEnum
import json
from typing import Any, Mapping

from .authorization import validate_user_authorization
from .config import validate_config
from .errors import ConflictError, ValidationError
from .storage_contract import StorageBinding
from .storage import NATIVE_LOOKALIKES, expected_mime
from .github_storage import validate_canonical_text
from .instance import validate_instance_v2
from .util import pretty_json, require_timestamp, safe_relative_path, sha256_bytes, sha256_text
from .yamlio import dumps as yaml_dumps, loads as yaml_loads
from .topics import TopicRegistry


class StorageMigrationPhase(IntEnum):
    AUTHORIZED = 0
    WRITERS_PAUSED = 1
    SOURCE_EXPORTED = 2
    DESTINATION_IMPORTED = 3
    DESTINATION_VERIFIED = 4
    HOST_BINDINGS_VERIFIED = 5
    ACTIVE = 6


@dataclass(frozen=True)
class SourceObject:
    object_id: str
    generation: str
    mime_type: str
    complete: bool = True


@dataclass(frozen=True)
class StorageMigrationPlan:
    migration_id: str
    instance_id: str
    source: StorageBinding
    destination: StorageBinding
    target_release: str
    created_at: str
    authorization: dict[str, Any]
    export_manifest: dict[str, Any]
    import_files: dict[str, bytes]


@dataclass
class StorageMigrationState:
    migration_id: str
    instance_id: str
    plan_sha256: str = ""
    authorization_sha256: str = ""
    source: dict[str, Any] = field(default_factory=dict)
    destination: dict[str, Any] = field(default_factory=dict)
    import_digest: str = ""
    phase: str = StorageMigrationPhase.AUTHORIZED.name
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    imported_generation: str | None = None
    destination_generation: str | None = None
    source_marked_read_only: bool = False

    def to_bytes(self) -> bytes:
        return pretty_json(asdict(self)).encode()

    @classmethod
    def from_bytes(cls, content: bytes) -> "StorageMigrationState":
        try:
            value = json.loads(content)
            state = cls(**value)
            StorageMigrationPhase[state.phase]
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, KeyError) as exc:
            raise ValidationError("storage migration checkpoint is malformed") from exc
        for digest in (state.plan_sha256, state.authorization_sha256, state.import_digest):
            if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise ValidationError("storage migration checkpoint lacks bound digests")
        if not state.source or not state.destination:
            raise ValidationError("storage migration checkpoint lacks provider bindings")
        return state


def migration_authorization_target(source: StorageBinding, destination: StorageBinding, target_release: str) -> str:
    if not target_release:
        raise ValidationError("migration target release is required")
    return (
        f"{source.provider}:{source.container_id}:{source.generation_locator}:{source.logical_root}"
        f"->{destination.provider}:{destination.container_id}:{destination.generation_locator}:{destination.logical_root}"
        f"@{target_release}"
    )


def _validate_binding(binding: StorageBinding) -> None:
    if binding.provider not in {"google-drive", "github"}:
        raise ValidationError("unsupported storage migration provider")
    if not binding.container_id or not binding.generation_locator:
        raise ValidationError("storage migration bindings must be complete")
    if binding.logical_root and safe_relative_path(binding.logical_root) != binding.logical_root:
        raise ValidationError("storage migration logical roots must use canonical POSIX spelling")


def _destination_storage(destination: StorageBinding, details: Mapping[str, Any]) -> dict[str, Any]:
    if destination.provider == "github":
        allowed = {"repository", "consistency_mode", "limits"}
        unknown = set(details) - allowed
        repository = details.get("repository")
        if unknown or not isinstance(repository, str) or "/" not in repository:
            raise ValidationError("GitHub migration requires canonical repository metadata")
        value = {
            "provider": "github",
            "repository_id": destination.container_id,
            "repository": repository,
            "canonical_ref": destination.generation_locator,
            "root_prefix": destination.logical_root,
            "consistency_mode": details.get("consistency_mode", "git-fast-forward"),
        }
        value["limits"] = details.get("limits", {
            "max_file_bytes": 512_000,
            "max_transaction_bytes": 8_000_000,
            "max_repository_bytes": 500_000_000,
            "max_paths_per_transaction": 200,
        })
        return value
    allowed = {"consistency_mode"}
    if set(details) - allowed:
        raise ValidationError("Drive migration metadata contains foreign fields")
    return {
        "provider": "google-drive",
        "root_folder_id": destination.container_id,
        "consistency_mode": details.get("consistency_mode", "strict"),
    }


def _destination_instance_storage(
    destination: StorageBinding,
    details: Mapping[str, Any],
    destination_identity: Mapping[str, Any],
) -> dict[str, Any]:
    if destination.provider == "github":
        required = {
            "repository": str(details.get("repository", "")),
            "repository_visibility": str(destination_identity.get("repository_visibility", "")),
            "app_installation_id": str(destination_identity.get("app_installation_id", "")),
            "capability_profile_path": str(destination_identity.get("capability_profile_path", "")),
            "first_verified_commit": str(destination_identity.get("first_verified_commit", "")),
        }
        if required["repository_visibility"] != "private" or any(not value for value in required.values()):
            raise ValidationError("GitHub destination identity must be complete and private")
        return {
            "provider": "github", "repository_id": destination.container_id,
            "repository": required["repository"], "canonical_ref": destination.generation_locator,
            "root_prefix": destination.logical_root, **{key: value for key, value in required.items() if key != "repository"},
        }
    mapping = {
        "provider": "google-drive", "root_folder_id": destination.container_id,
        "drive_map_file_id": destination.generation_locator,
    }
    for key in ("root_folder_name", "instance_file_id", "config_file_id", "scope_file_id"):
        value = destination_identity.get(key)
        if not isinstance(value, str) or not value:
            raise ValidationError(f"Drive destination identity is missing {key}")
        mapping[key] = value
    return mapping


def prepare_storage_migration(
    *,
    instance_id: str,
    source: StorageBinding,
    destination: StorageBinding,
    source_files: Mapping[str, bytes],
    source_objects: Mapping[str, SourceObject],
    destination_storage_details: Mapping[str, Any],
    destination_identity: Mapping[str, Any],
    target_release: str,
    authorization: dict[str, Any],
    created_at: str,
) -> StorageMigrationPlan:
    """Create a lossless import package; it does not activate the destination."""
    _validate_binding(source)
    _validate_binding(destination)
    if source.provider == destination.provider and source.container_id == destination.container_id:
        raise ValidationError("migration source and destination must differ")
    require_timestamp(created_at, "migration creation time")
    target = migration_authorization_target(source, destination, target_release)
    validate_user_authorization(
        authorization, instance_id=instance_id, operation="migrate-storage", target=target
    )
    if set(source_files) != set(source_objects):
        raise ValidationError("every exported source file requires exact provider metadata")
    if "config.yml" not in source_files or "INSTANCE.json" not in source_files:
        raise ValidationError("migration requires complete canonical configuration and identity")
    if "data/TOPICS.md" not in source_files:
        raise ValidationError("migration requires the authoritative topic registry")

    entries: list[dict[str, Any]] = []
    for path in sorted(source_files):
        if safe_relative_path(path) != path:
            raise ValidationError("migration source path is not canonical")
        content = source_files[path]
        observed = source_objects[path]
        if not isinstance(content, bytes) or not observed.complete:
            raise ValidationError("migration requires complete exact source bytes")
        validate_canonical_text(path, content)
        if not observed.object_id or not observed.generation or not observed.mime_type:
            raise ValidationError("migration source metadata is incomplete")
        if observed.mime_type in NATIVE_LOOKALIKES or observed.mime_type != expected_mime(path):
            raise ValidationError("migration source must use the expected canonical raw MIME type")
        entries.append({
            "path": path, "size": len(content), "sha256": sha256_bytes(content),
            "source_object_id": observed.object_id, "source_generation": observed.generation,
            "source_mime_type": observed.mime_type,
        })

    try:
        config = yaml_loads(source_files["config.yml"].decode())
        identity = json.loads(source_files["INSTANCE.json"])
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValidationError("migration source configuration or identity is malformed") from exc
    if not isinstance(config, dict) or not isinstance(identity, dict):
        raise ValidationError("migration source configuration and identity must be mappings")
    if config.get("instance", {}).get("id") != instance_id or identity.get("instance_id") != instance_id:
        raise ConflictError("migration source belongs to another instance")
    if config.get("storage", {}).get("provider") != source.provider:
        raise ConflictError("migration source provider does not match canonical configuration")
    if config.get("schema_version") != 2 or identity.get("schema_version") != 2:
        raise ValidationError("storage migration requires an already-valid v2 instance")
    validate_instance_v2(identity, expected_instance_id=instance_id)
    registry = TopicRegistry.parse(source_files["data/TOPICS.md"].decode())
    validate_config(config, topic_registry=registry)
    source_storage = config["storage"]
    identity_storage = identity.get("storage")
    if not isinstance(identity_storage, dict) or identity_storage.get("provider") != source.provider:
        raise ConflictError("INSTANCE.json source provider binding is invalid")
    if source.provider == "github":
        expected_source = {
            "repository_id": source.container_id,
            "canonical_ref": source.generation_locator,
            "root_prefix": source.logical_root,
        }
        if any(source_storage.get(key) != value or identity_storage.get(key) != value for key, value in expected_source.items()):
            raise ConflictError("GitHub source binding differs across migration inputs")
    else:
        if (
            source_storage.get("root_folder_id") != source.container_id
            or identity_storage.get("root_folder_id") != source.container_id
            or identity_storage.get("drive_map_file_id") != source.generation_locator
        ):
            raise ConflictError("Drive source binding differs across migration inputs")
    runtime = config.get("runtime", {})
    if (
        runtime.get("release_id") != target_release
        or identity.get("runtime_release_id") != target_release
        or identity.get("source_commit") != runtime.get("source_commit")
    ):
        raise ConflictError("storage migration target release must match the complete installed runtime")

    migration_id = "storage-" + sha256_text(f"{instance_id}\0{target}\0{created_at}")[:20]
    backup_root = f"backups/migrations/{migration_id}"
    imported = dict(source_files)
    imported[f"{backup_root}/source-config.yml"] = source_files["config.yml"]
    imported[f"{backup_root}/source-INSTANCE.json"] = source_files["INSTANCE.json"]
    drive_lock = "data/state/research.lock.json"
    if source.provider == "google-drive" and destination.provider == "github" and drive_lock in imported:
        imported[f"{backup_root}/source-research-lock.json"] = imported.pop(drive_lock)
    provider_artifacts = {
        "installation/skill-binding.json",
        "installation/install-state.json", "installation/task-plans.json",
        "installation/schedule-bindings.json",
    }
    provider_artifacts.add(
        "installation/drive-map.json"
        if source.provider == "google-drive"
        else "installation/capability-profile.json"
    )
    provider_artifacts.update(
        path for path in imported if path.startswith("installation/generated-skill/")
    )
    for path in sorted(provider_artifacts):
        if path in imported:
            imported[f"{backup_root}/source-provider-artifacts/{path}"] = imported.pop(path)

    config = dict(config)
    config["storage"] = _destination_storage(destination, destination_storage_details)
    validate_config(config, topic_registry=registry)
    identity = dict(identity)
    identity["schema_version"] = 2
    identity["storage"] = _destination_instance_storage(
        destination, destination_storage_details, destination_identity
    )
    for obsolete in (
        "drive_root_folder_id", "drive_root_folder_name", "mapping_file_id",
        "config_file_id", "scope_file_id", "instance_file_id",
    ):
        identity.pop(obsolete, None)
    validate_instance_v2(identity, expected_instance_id=instance_id)
    imported["config.yml"] = yaml_dumps(config).encode()
    imported["INSTANCE.json"] = pretty_json(identity).encode()

    export_manifest = {
        "schema_version": 1, "kind": "wikiplant-storage-export",
        "migration_id": migration_id, "instance_id": instance_id,
        "created_at": created_at, "target_release": target_release,
        "source": asdict(source), "destination": asdict(destination),
        "authorization_sha256": sha256_bytes(pretty_json(authorization).encode()),
        "files": entries,
        "import_files": [
            {"path": path, "size": len(content), "sha256": sha256_bytes(content)}
            for path, content in sorted(imported.items())
        ],
        "activation_required": True,
        "source_retention": "read-only-until-explicit-retirement",
    }
    imported[f"{backup_root}/export-manifest.json"] = pretty_json(export_manifest).encode()
    marker_path = f"installation/migrations/{migration_id}.json"
    imported[marker_path] = pretty_json({
        "schema_version": 1, "migration_id": migration_id, "instance_id": instance_id,
        "source": asdict(source), "destination": asdict(destination),
        "authorization": authorization,
        "status": "prepared-not-active", "created_at": created_at,
    }).encode()
    return StorageMigrationPlan(
        migration_id, instance_id, source, destination, target_release, created_at,
        authorization, export_manifest, imported,
    )


def verify_storage_migration_import(plan: StorageMigrationPlan, observed: Mapping[str, bytes]) -> str:
    """Verify the exact staged destination package and return its detached digest."""
    expected = plan.import_files
    if set(observed) != set(expected):
        raise ConflictError("staged migration inventory differs from the prepared package")
    for path, content in expected.items():
        if observed[path] != content:
            raise ConflictError(f"staged migration content differs: {path}")
    return sha256_text(pretty_json({path: sha256_bytes(value) for path, value in sorted(observed.items())}))


def storage_migration_plan_digest(plan: StorageMigrationPlan) -> str:
    return sha256_text(pretty_json({
        "migration_id": plan.migration_id, "instance_id": plan.instance_id,
        "source": asdict(plan.source), "destination": asdict(plan.destination),
        "target_release": plan.target_release, "created_at": plan.created_at,
        "authorization_sha256": sha256_bytes(pretty_json(plan.authorization).encode()),
        "export_manifest_sha256": sha256_bytes(pretty_json(plan.export_manifest).encode()),
        "import_files": {path: sha256_bytes(value) for path, value in sorted(plan.import_files.items())},
    }))


def create_storage_migration_state(plan: StorageMigrationPlan) -> StorageMigrationState:
    import_digest = verify_storage_migration_import(plan, plan.import_files)
    authorization_sha256 = sha256_bytes(pretty_json(plan.authorization).encode())
    return StorageMigrationState(
        migration_id=plan.migration_id, instance_id=plan.instance_id,
        plan_sha256=storage_migration_plan_digest(plan),
        authorization_sha256=authorization_sha256,
        source=asdict(plan.source), destination=asdict(plan.destination),
        import_digest=import_digest,
        evidence={StorageMigrationPhase.AUTHORIZED.name: {
            "authorization_sha256": authorization_sha256,
            "plan_sha256": storage_migration_plan_digest(plan),
        }},
    )


def _require_text_evidence(evidence: Mapping[str, Any], *keys: str) -> None:
    if any(not isinstance(evidence.get(key), str) or not evidence[key] for key in keys):
        raise ValidationError("storage migration checkpoint lacks a required observed receipt")


def _validate_provider_receipt(
    receipt: Any,
    *,
    kind: str,
    state: StorageMigrationState,
    binding: StorageBinding,
    generation: str | None = None,
) -> Mapping[str, Any]:
    if not isinstance(receipt, Mapping):
        raise ValidationError("storage migration requires structured provider receipts")
    expected = {
        "schema_version": 1, "kind": kind, "migration_id": state.migration_id,
        "instance_id": state.instance_id, "provider": binding.provider,
        "container_id": binding.container_id,
        "logical_root": binding.logical_root,
        "generation_locator": binding.generation_locator,
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValidationError("storage migration receipt binding mismatch")
    if generation is not None and receipt.get("generation") != generation:
        raise ValidationError("storage migration receipt generation mismatch")
    _require_text_evidence(receipt, "generation", "operation_id")
    return receipt


def _validate_github_lineage_receipt(
    receipt: Mapping[str, Any], *, ancestor: str, generation: str
) -> None:
    if any(
        not isinstance(value, str) or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
        for value in (ancestor, generation)
    ):
        raise ValidationError("GitHub migration lineage requires immutable 40-hex generations")
    if (
        receipt.get("current_generation") != generation
        or receipt.get("verified_ancestor_generation") != ancestor
        or receipt.get("ancestry_verified") is not True
    ):
        raise ValidationError("GitHub migration receipt lacks verified generation continuity")


def advance_storage_migration(
    state: StorageMigrationState,
    plan: StorageMigrationPlan,
    phase: StorageMigrationPhase,
    evidence: Mapping[str, Any],
    *,
    destination_generation: str | None = None,
    observed_import_files: Mapping[str, bytes] | None = None,
) -> StorageMigrationState:
    """Advance exactly one durable checkpoint; replay with identical evidence is safe."""
    current = StorageMigrationPhase[state.phase]
    if (
        state.migration_id != plan.migration_id
        or state.instance_id != plan.instance_id
        or state.plan_sha256 != storage_migration_plan_digest(plan)
        or state.authorization_sha256 != sha256_bytes(pretty_json(plan.authorization).encode())
        or state.source != asdict(plan.source)
        or state.destination != asdict(plan.destination)
        or state.import_digest != verify_storage_migration_import(plan, plan.import_files)
    ):
        raise ConflictError("migration checkpoint is not bound to this prepared plan")
    if phase == current:
        if state.evidence.get(phase.name) != dict(evidence):
            raise ConflictError("migration checkpoint replay has different evidence")
        return state
    if phase.value != current.value + 1:
        raise ValidationError("storage migration checkpoints cannot be skipped")
    if not evidence:
        raise ValidationError("storage migration checkpoint requires observed evidence")
    if phase >= StorageMigrationPhase.DESTINATION_IMPORTED and not destination_generation:
        destination_generation = state.destination_generation
    if phase >= StorageMigrationPhase.DESTINATION_IMPORTED and not destination_generation:
        raise ValidationError("imported migration checkpoint requires a destination generation")
    if phase == StorageMigrationPhase.WRITERS_PAUSED:
        task_ids = evidence.get("task_ids")
        if (
            not isinstance(task_ids, dict) or set(task_ids) != {"daily", "weekly"}
            or any(not isinstance(value, str) or not value for value in task_ids.values())
            or evidence.get("all_tasks_paused") is not True
        ):
            raise ValidationError("writer pause requires the two observed inactive task bindings")
        _validate_provider_receipt(
            evidence.get("writer_drain_receipt"), kind="writers-paused", state=state,
            binding=plan.source,
        )
    elif phase == StorageMigrationPhase.SOURCE_EXPORTED:
        expected = sha256_bytes(pretty_json(plan.export_manifest).encode())
        if evidence.get("export_manifest_sha256") != expected:
            raise ValidationError("source export evidence does not match the prepared manifest")
        _validate_provider_receipt(
            evidence.get("source_export_receipt"), kind="source-export", state=state,
            binding=plan.source,
        )
    elif phase == StorageMigrationPhase.DESTINATION_IMPORTED:
        if (
            evidence.get("import_digest") != state.import_digest
            or observed_import_files is None
            or verify_storage_migration_import(plan, observed_import_files) != state.import_digest
        ):
            raise ValidationError("destination import evidence does not match the prepared bytes")
        receipt = _validate_provider_receipt(
            evidence.get("import_receipt"), kind="destination-import", state=state,
            binding=plan.destination, generation=destination_generation,
        )
        if plan.destination.provider == "github":
            destination_instance = json.loads(plan.import_files["INSTANCE.json"])
            ancestry_anchor = destination_instance["storage"]["first_verified_commit"]
            if (
                receipt.get("ancestry_anchor") != ancestry_anchor
                or receipt.get("committed_generation") != destination_generation
            ):
                raise ValidationError("GitHub import receipt lacks the verified destination ancestry anchor")
            _validate_github_lineage_receipt(
                receipt, ancestor=ancestry_anchor, generation=destination_generation
            )
    elif phase == StorageMigrationPhase.DESTINATION_VERIFIED:
        if (
            evidence.get("import_digest") != state.import_digest
            or observed_import_files is None
            or verify_storage_migration_import(plan, observed_import_files) != state.import_digest
        ):
            raise ValidationError("destination verification evidence is incomplete")
        receipt = _validate_provider_receipt(
            evidence.get("verification_receipt"), kind="destination-verification", state=state,
            binding=plan.destination, generation=destination_generation,
        )
        if receipt.get("inventory_digest") != state.import_digest or receipt.get("cross_file_validation") != "PASS":
            raise ValidationError("destination verification receipt lacks exact inventory/cross-file proof")
        if plan.destination.provider == "github":
            if not state.imported_generation:
                raise ConflictError("GitHub migration lost its imported generation")
            _validate_github_lineage_receipt(
                receipt, ancestor=state.imported_generation, generation=destination_generation
            )
    elif phase == StorageMigrationPhase.HOST_BINDINGS_VERIFIED:
        task_ids = state.evidence[StorageMigrationPhase.WRITERS_PAUSED.name]["task_ids"]
        if evidence.get("task_ids") != task_ids:
            raise ValidationError("host binding verification changed the two task identities")
        skill = _validate_provider_receipt(
            evidence.get("skill_receipt"), kind="skill-binding", state=state,
            binding=plan.destination, generation=destination_generation,
        )
        _require_text_evidence(skill, "skill_reference")
        if plan.destination.provider == "github":
            if not state.imported_generation:
                raise ConflictError("GitHub migration lost its imported generation")
            _validate_github_lineage_receipt(
                skill, ancestor=state.imported_generation, generation=destination_generation
            )
        task_receipts = evidence.get("task_receipts")
        if not isinstance(task_receipts, Mapping) or set(task_receipts) != {"daily", "weekly"}:
            raise ValidationError("host binding verification requires both structured task receipts")
        for name, task_id in task_ids.items():
            receipt = _validate_provider_receipt(
                task_receipts[name], kind="task-binding", state=state,
                binding=plan.destination, generation=destination_generation,
            )
            if receipt.get("task_id") != task_id:
                raise ValidationError("host task receipt changed a bound task identity")
            if plan.destination.provider == "github":
                _validate_github_lineage_receipt(
                    receipt, ancestor=state.imported_generation, generation=destination_generation
                )
        fresh = _validate_provider_receipt(
            evidence.get("fresh_read_receipt"), kind="fresh-read", state=state,
            binding=plan.destination, generation=destination_generation,
        )
        smoke = _validate_provider_receipt(
            evidence.get("smoke_write_receipt"), kind="smoke-write", state=state,
            binding=plan.destination, generation=destination_generation,
        )
        if smoke.get("replay_verified") is not True:
            raise ValidationError("host smoke write requires an observed replay receipt")
        if plan.destination.provider == "github":
            for receipt in (fresh, smoke):
                _validate_github_lineage_receipt(
                    receipt, ancestor=state.imported_generation, generation=destination_generation
                )
    elif phase == StorageMigrationPhase.ACTIVE:
        activation = _validate_provider_receipt(
            evidence.get("activation_receipt"), kind="activation", state=state,
            binding=plan.destination, generation=destination_generation,
        )
        source_receipt = _validate_provider_receipt(
            evidence.get("source_read_only_receipt"), kind="source-read-only", state=state,
            binding=plan.source,
        )
        expected_task_ids = state.evidence[StorageMigrationPhase.WRITERS_PAUSED.name]["task_ids"]
        if (
            activation.get("task_ids") != expected_task_ids
            or activation.get("tasks_active") is not True
            or source_receipt.get("status") != "MIGRATED_READ_ONLY"
        ):
            raise ValidationError("activation requires observed tasks and retained read-only source")
        if plan.destination.provider == "github":
            if not state.imported_generation:
                raise ConflictError("GitHub migration lost its imported generation")
            _validate_github_lineage_receipt(
                activation, ancestor=state.imported_generation, generation=destination_generation
            )
    state.phase = phase.name
    state.evidence[phase.name] = dict(evidence)
    if phase == StorageMigrationPhase.DESTINATION_IMPORTED:
        state.imported_generation = destination_generation
    state.destination_generation = destination_generation
    state.source_marked_read_only = state.source_marked_read_only or phase == StorageMigrationPhase.ACTIVE
    return state
