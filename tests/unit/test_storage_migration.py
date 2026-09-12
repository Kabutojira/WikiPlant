from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from wikiplant.authorization import UserAuthorization, request_digest
from wikiplant.errors import ConflictError, ValidationError
from wikiplant.storage import expected_mime
from wikiplant.storage_contract import StorageBinding
from wikiplant.storage_migration import (
    SourceObject, StorageMigrationPhase, StorageMigrationState,
    advance_storage_migration, migration_authorization_target,
    create_storage_migration_state, prepare_storage_migration,
    verify_storage_migration_import,
)
from wikiplant.topics import Topic, TopicRegistry
from wikiplant.util import pretty_json, sha256_bytes
from wikiplant.yamlio import dumps as yaml_dumps, loads as yaml_loads


STAMP = "2026-09-12T12:00:00+00:00"
INSTANCE = "wp-0123456789abcdef"
ROOT = Path(__file__).resolve().parents[2]


def source_files(provider: str) -> dict[str, bytes]:
    storage = ({"provider": "google-drive", "root_folder_id": "drive-root", "consistency_mode": "strict"}
               if provider == "google-drive" else
               {"provider": "github", "repository_id": "R_source", "repository": "fixture/source", "canonical_ref": "refs/heads/wikiplant-data", "root_prefix": "", "consistency_mode": "git-fast-forward",
                "limits": {"max_file_bytes": 512000, "max_transaction_bytes": 8000000,
                           "max_repository_bytes": 500000000, "max_paths_per_transaction": 200}})
    config = yaml_loads((ROOT / "config.example.yml").read_text())
    config["instance"] = {"id": INSTANCE, "name": "Migration fixture", "language": "en", "timezone": "UTC"}
    config["storage"] = storage
    config["runtime"] = {"release_id": "0.3.0", "source_commit": "a" * 40,
                         "manifest_sha256": "b" * 64, "upgrades": "explicit-user-request"}
    config["skill"] = {"per_instance": True, "installed_reference": "skill-fixture", "routing_profile_revision": 1}
    config["primary_topic_ids"] = ["topic-1"]
    config["schedules"] = {"daily": {"local_time": "07:00"}, "weekly": {"weekday": "monday", "local_time": "05:00"}}
    track = UserAuthorization(
        "turn-track", INSTANCE, "track", "topic-1", request_digest("track fixture topic"),
        True, "explicit synthetic tracking request",
    ).to_dict()
    registry = TopicRegistry(INSTANCE, 1, [Topic(
        id="topic-1", label="Fixture topic", classification="user",
        user_anchor_ids=["topic-1"], parent_ids=[], direct_contribution="Explicit fixture scope",
        classification_reason="Authorized fixture", added_at=STAMP, reviewed_at=STAMP,
        scope_revision=1, authorization=track,
    )])
    identity_storage = (
        {"provider": "google-drive", "root_folder_id": "drive-root", "drive_map_file_id": "drive-map",
         "config_file_id": "drive-config"}
        if provider == "google-drive" else
        {"provider": "github", "repository_id": "R_source", "repository": "fixture/source",
         "canonical_ref": "refs/heads/wikiplant-data", "root_prefix": "",
         "repository_visibility": "private", "app_installation_id": "app-source",
         "capability_profile_path": "installation/capability-profile.json", "first_verified_commit": "c" * 40}
    )
    return {
        "config.yml": yaml_dumps(config).encode(),
        "INSTANCE.json": json.dumps({"schema_version": 2, "instance_id": INSTANCE,
                                      "storage": identity_storage, "runtime_release_id": "0.3.0",
                                      "source_commit": "a" * 40}).encode(),
        "data/TOPICS.md": registry.render().encode(),
        "data/wiki/entities/entity-1.md": b"---\nid: entity-1\n---\nUser text stays exact.\n",
        "data/research_queue.csv": b"priority,id\n20,q-stable\n",
        "data/state/research.lock.json": b'{"provider":"drive-only"}\n',
    }


def objects(files: dict[str, bytes], provider: str) -> dict[str, SourceObject]:
    return {path: SourceObject(f"{provider}-id-{index}", "7" if provider == "google-drive" else "a" * 40, expected_mime(path))
            for index, path in enumerate(files)}


def authorization(source, destination, release="0.3.0") -> dict:
    target = migration_authorization_target(source, destination, release)
    return UserAuthorization(
        "turn-migrate", INSTANCE, "migrate-storage", target,
        request_digest("move this WikiPlant storage explicitly"), True,
        "the current user explicitly requested this destination",
    ).to_dict()


def drive_to_github_plan():
    source = StorageBinding("google-drive", "drive-root", "", "drive-map")
    destination = StorageBinding("github", "R_destination", "", "refs/heads/wikiplant-data")
    files = source_files("google-drive")
    return prepare_storage_migration(
        instance_id=INSTANCE, source=source, destination=destination,
        source_files=files, source_objects=objects(files, "google-drive"),
        destination_storage_details={"repository": "fixture/destination"},
        destination_identity={"repository_visibility": "private", "app_installation_id": "app-1",
                              "capability_profile_path": "installation/capability-profile.json",
                              "first_verified_commit": "b" * 40},
        target_release="0.3.0", authorization=authorization(source, destination), created_at=STAMP,
    )


def provider_receipt(kind, plan, binding, generation, **extra):
    receipt = {
        "schema_version": 1, "kind": kind, "migration_id": plan.migration_id,
        "instance_id": plan.instance_id, "provider": binding.provider,
        "container_id": binding.container_id, "logical_root": binding.logical_root,
        "generation_locator": binding.generation_locator, "generation": generation,
        "operation_id": f"{plan.migration_id}:{kind}", **extra,
    }
    if binding == plan.destination and binding.provider == "github":
        receipt.update({
            "ancestry_anchor": json.loads(plan.import_files["INSTANCE.json"])["storage"]["first_verified_commit"],
            "ancestry_verified": True, "committed_generation": generation,
            "current_generation": generation,
            "verified_ancestor_generation": (
                json.loads(plan.import_files["INSTANCE.json"])["storage"]["first_verified_commit"]
                if kind == "destination-import" else "c" * 40
            ),
        })
    return receipt


class StorageMigrationTests(unittest.TestCase):
    def test_drive_to_github_is_lossless_and_archives_drive_only_state(self):
        source = StorageBinding("google-drive", "drive-root", "", "drive-map")
        destination = StorageBinding("github", "R_destination", "", "refs/heads/wikiplant-data")
        files = source_files("google-drive")
        plan = drive_to_github_plan()
        self.assertEqual(plan.import_files["data/wiki/entities/entity-1.md"], files["data/wiki/entities/entity-1.md"])
        self.assertEqual(plan.import_files["data/research_queue.csv"], files["data/research_queue.csv"])
        self.assertNotIn("data/state/research.lock.json", plan.import_files)
        backup = f"backups/migrations/{plan.migration_id}/source-research-lock.json"
        self.assertEqual(plan.import_files[backup], files["data/state/research.lock.json"])
        self.assertEqual(yaml_loads(plan.import_files["config.yml"].decode())["storage"]["provider"], "github")
        self.assertEqual(json.loads(plan.import_files["INSTANCE.json"])["storage"]["repository_id"], "R_destination")
        self.assertTrue(verify_storage_migration_import(plan, dict(plan.import_files)))

    def test_github_to_drive_preserves_data_and_uses_exact_drive_binding(self):
        source = StorageBinding("github", "R_source", "", "refs/heads/wikiplant-data")
        destination = StorageBinding("google-drive", "new-drive-root", "", "new-drive-map")
        files = source_files("github")
        plan = prepare_storage_migration(
            instance_id=INSTANCE, source=source, destination=destination,
            source_files=files, source_objects=objects(files, "github"),
            destination_storage_details={"consistency_mode": "strict"},
            destination_identity={"root_folder_name": "WikiPlant migrated", "instance_file_id": "id-instance",
                                  "config_file_id": "id-config", "scope_file_id": "id-scope"},
            target_release="0.3.0", authorization=authorization(source, destination), created_at=STAMP,
        )
        config = yaml_loads(plan.import_files["config.yml"].decode())
        self.assertEqual(config["storage"]["root_folder_id"], "new-drive-root")
        self.assertNotIn("map_file_id", config["storage"])
        self.assertEqual(
            json.loads(plan.import_files["INSTANCE.json"])["storage"]["drive_map_file_id"],
            "new-drive-map",
        )
        self.assertEqual(plan.import_files["data/wiki/entities/entity-1.md"], files["data/wiki/entities/entity-1.md"])

    def test_incomplete_export_or_changed_import_fails_closed(self):
        source = StorageBinding("google-drive", "drive-root", "", "drive-map")
        destination = StorageBinding("github", "R_destination", "", "refs/heads/wikiplant-data")
        files = source_files("google-drive")
        metadata = objects(files, "google-drive")
        metadata["config.yml"] = SourceObject("id", "7", "application/yaml", False)
        kwargs = dict(
            instance_id=INSTANCE, source=source, destination=destination, source_files=files,
            source_objects=metadata, destination_storage_details={"repository": "fixture/destination"},
            destination_identity={"repository_visibility": "private", "app_installation_id": "app-1",
                                  "capability_profile_path": "installation/capability-profile.json", "first_verified_commit": "b" * 40},
            target_release="0.3.0", authorization=authorization(source, destination), created_at=STAMP,
        )
        with self.assertRaises(ValidationError):
            prepare_storage_migration(**kwargs)
        kwargs["source_objects"] = objects(files, "google-drive")
        plan = prepare_storage_migration(**kwargs)
        changed = dict(plan.import_files)
        changed["data/wiki/entities/entity-1.md"] = b"changed"
        with self.assertRaises(ConflictError):
            verify_storage_migration_import(plan, changed)

    def test_destination_instance_anchor_and_profile_are_schema_validated(self):
        source = StorageBinding("google-drive", "drive-root", "", "drive-map")
        destination = StorageBinding("github", "R_destination", "", "refs/heads/wikiplant-data")
        files = source_files("google-drive")
        base = dict(
            instance_id=INSTANCE, source=source, destination=destination,
            source_files=files, source_objects=objects(files, "google-drive"),
            destination_storage_details={"repository": "fixture/destination"},
            target_release="0.3.0", authorization=authorization(source, destination), created_at=STAMP,
        )
        for identity in (
            {"repository_visibility": "private", "app_installation_id": "app-1",
             "capability_profile_path": "installation/capability-profile.json", "first_verified_commit": "bad"},
            {"repository_visibility": "private", "app_installation_id": "app-1",
             "capability_profile_path": "wrong.json", "first_verified_commit": "b" * 40},
        ):
            with self.subTest(identity=identity), self.assertRaises(ValidationError):
                prepare_storage_migration(**base, destination_identity=identity)

    def test_every_checkpoint_round_trips_and_replays_only_identically(self):
        plan = drive_to_github_plan()
        state = create_storage_migration_state(plan)
        generation = None
        task_ids = {"daily": "task-daily", "weekly": "task-weekly"}
        evidence = {
            StorageMigrationPhase.WRITERS_PAUSED: {
                "task_ids": task_ids, "all_tasks_paused": True,
                "writer_drain_receipt": provider_receipt(
                    "writers-paused", plan, plan.source, "source-generation"
                ),
            },
            StorageMigrationPhase.SOURCE_EXPORTED: {
                "export_manifest_sha256": sha256_bytes(pretty_json(plan.export_manifest).encode()),
                "source_export_receipt": provider_receipt(
                    "source-export", plan, plan.source, "source-generation"
                ),
            },
            StorageMigrationPhase.DESTINATION_IMPORTED: {
                "import_digest": state.import_digest,
                "import_receipt": provider_receipt(
                    "destination-import", plan, plan.destination, "c" * 40
                ),
            },
            StorageMigrationPhase.DESTINATION_VERIFIED: {
                "import_digest": state.import_digest,
                "verification_receipt": provider_receipt(
                    "destination-verification", plan, plan.destination, "c" * 40,
                    inventory_digest=state.import_digest, cross_file_validation="PASS",
                ),
            },
            StorageMigrationPhase.HOST_BINDINGS_VERIFIED: {
                "task_ids": task_ids,
                "skill_receipt": provider_receipt(
                    "skill-binding", plan, plan.destination, "c" * 40,
                    skill_reference="skill-1",
                ),
                "task_receipts": {
                    name: provider_receipt(
                        "task-binding", plan, plan.destination, "c" * 40, task_id=task_id
                    ) for name, task_id in task_ids.items()
                },
                "fresh_read_receipt": provider_receipt(
                    "fresh-read", plan, plan.destination, "c" * 40
                ),
                "smoke_write_receipt": provider_receipt(
                    "smoke-write", plan, plan.destination, "c" * 40,
                    replay_verified=True,
                ),
            },
            StorageMigrationPhase.ACTIVE: {
                "activation_receipt": provider_receipt(
                    "activation", plan, plan.destination, "c" * 40,
                    task_ids=task_ids, tasks_active=True,
                ),
                "source_read_only_receipt": provider_receipt(
                    "source-read-only", plan, plan.source, "source-generation",
                    status="MIGRATED_READ_ONLY",
                ),
            },
        }
        for phase in list(StorageMigrationPhase)[1:]:
            if phase >= StorageMigrationPhase.DESTINATION_IMPORTED:
                generation = "c" * 40
            state = advance_storage_migration(
                state, plan, phase, evidence[phase], destination_generation=generation,
                observed_import_files=(plan.import_files if phase in {
                    StorageMigrationPhase.DESTINATION_IMPORTED,
                    StorageMigrationPhase.DESTINATION_VERIFIED,
                } else None),
            )
            state = StorageMigrationState.from_bytes(state.to_bytes())
            copy_before = copy.deepcopy(state)
            self.assertEqual(advance_storage_migration(state, plan, phase, evidence[phase]), copy_before)
        self.assertEqual(state.phase, StorageMigrationPhase.ACTIVE.name)
        self.assertTrue(state.source_marked_read_only)

    def test_checkpoint_skip_and_wrong_authorization_are_rejected(self):
        plan = drive_to_github_plan()
        state = create_storage_migration_state(plan)
        with self.assertRaises(ValidationError):
            advance_storage_migration(state, plan, StorageMigrationPhase.SOURCE_EXPORTED, {"observed": True})
        source = StorageBinding("google-drive", "drive-root", "", "drive-map")
        destination = StorageBinding("github", "R_destination", "", "refs/heads/wikiplant-data")
        bad = authorization(source, destination)
        bad["target"] = "another destination"
        files = source_files("google-drive")
        with self.assertRaises(ValidationError):
            prepare_storage_migration(
                instance_id=INSTANCE, source=source, destination=destination,
                source_files=files, source_objects=objects(files, "google-drive"),
                destination_storage_details={"repository": "fixture/destination"},
                destination_identity={"repository_visibility": "private", "app_installation_id": "app-1",
                                      "capability_profile_path": "installation/capability-profile.json", "first_verified_commit": "b" * 40},
                target_release="0.3.0", authorization=bad, created_at=STAMP,
            )

    def test_receipts_bind_full_location_and_github_import_lineage(self):
        plan = drive_to_github_plan()
        state = create_storage_migration_state(plan)
        paused = {
            "task_ids": {"daily": "task-daily", "weekly": "task-weekly"},
            "all_tasks_paused": True,
            "writer_drain_receipt": provider_receipt(
                "writers-paused", plan, plan.source, "source-generation"
            ),
        }
        state = advance_storage_migration(
            state, plan, StorageMigrationPhase.WRITERS_PAUSED, paused
        )
        exported = {
            "export_manifest_sha256": sha256_bytes(pretty_json(plan.export_manifest).encode()),
            "source_export_receipt": provider_receipt(
                "source-export", plan, plan.source, "source-generation"
            ),
        }
        state = advance_storage_migration(
            state, plan, StorageMigrationPhase.SOURCE_EXPORTED, exported
        )
        generation = "c" * 40
        receipt = provider_receipt(
            "destination-import", plan, plan.destination, generation
        )
        for field, value in (
            ("generation_locator", "refs/heads/another"),
            ("logical_root", "another-root"),
            ("verified_ancestor_generation", "d" * 40),
        ):
            poisoned = dict(receipt)
            poisoned[field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                advance_storage_migration(
                    copy.deepcopy(state), plan, StorageMigrationPhase.DESTINATION_IMPORTED,
                    {"import_digest": state.import_digest, "import_receipt": poisoned},
                    destination_generation=generation,
                    observed_import_files=plan.import_files,
                )


if __name__ == "__main__":
    unittest.main()
