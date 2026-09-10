from __future__ import annotations

import base64
import json
import subprocess
import sys
import unittest
from dataclasses import asdict

from wikiplant.authorization import UserAuthorization, request_digest
from wikiplant.errors import CapabilityError, ConflictError, SimulatedLostResponse, ValidationError
from wikiplant.fake_drive import FakeDrive, WeakDrive, _Entry
from wikiplant.releases import ReleaseInfo
from wikiplant.storage import Binding, SafeWriter, create_artifact, find_artifact
from wikiplant.upgrades import PHASES, Updater, rollback_plan
from wikiplant.util import pretty_json, sha256_bytes
from wikiplant.yamlio import dumps as yaml_dumps, loads as yaml_loads


CHECKS = {
    "PREFLIGHT_VERIFIED": "tools_checked ownership_checked pending_operations_checked backup_space_checked migration_path_checked",
    "WRITERS_QUIESCED": "tasks_paused writers_drained exclusive_updater intake_preserved",
    "MIGRATION_VALIDATED": "detached_snapshot_validated references_valid counts_reconciled customizations_preserved",
    "HOST_BINDINGS_VERIFIED": "private_skill_updated fresh_invocation_verified task_prompts_inspected no_duplicate_tasks",
    "SMOKE_TESTED": "schema_valid references_valid counts_reconciled raw_readbacks wiki_query archive_lookup",
    "ACTIVATED": "runtime_pointer_verified tasks_resumed intake_reconciled_once",
    "COMPLETE": "update_report_saved update_report_readback result_published",
    "ROLLBACK_QUIESCED": "tasks_paused writers_drained exclusive_updater intake_preserved",
    "ROLLBACK_BINDINGS_VERIFIED": "old_runtime_verified schema_compatible fresh_invocation_verified task_prompts_inspected runtime_pointer_verified",
    "ROLLBACK_COMPLETE": "tasks_resumed later_data_preserved rollback_report_saved rollback_report_readback",
}


def reconstruct(drive):
    # Persist bytes and IDs, but deliberately forget fake global idempotency tables.
    serialized = json.dumps({key: {**asdict(value), "content": base64.b64encode(value.content).decode()}
                             for key, value in drive.entries.items()})
    restored = type(drive)()
    restored.entries = {key: _Entry(**{**value, "content": base64.b64decode(value["content"])})
                        for key, value in json.loads(serialized).items()}
    restored._counter = drive._counter
    return restored


class PersistedHostFixture:
    """Synthetic host model with independently persisted skills/tasks/receipts."""
    def __init__(self, drive, root, folder, host_id, *, unavailable=None, lose_after=None, skip_pointer_updates=False):
        self.drive, self.root, self.folder, self.host_id = drive, root, folder, host_id
        self.unavailable, self.lose_after = unavailable, lose_after
        self.skip_pointer_updates = skip_pointer_updates

    def reconcile(self, phase, intent):
        if phase == "WRITERS_QUIESCED":
            host = json.loads(self.drive.read_exact(self.host_id).content)
            if not host["paused"] or host["active_writers"]:
                return None
        if phase == "ACTIVATED" and json.loads(self.drive.read_exact(self.host_id).content)["paused"]:
            return None  # A recovery pause invalidates the earlier active-state observation.
        found = find_artifact(self.drive, self.root, self.folder, phase + ".json")
        return json.loads(found.content) if found else None

    def perform(self, phase, intent):
        if self.unavailable == phase:
            raise CapabilityError("private skill update control unavailable" if phase == "HOST_BINDINGS_VERIFIED" else "host control unavailable")
        host = json.loads(self.drive.read_exact(self.host_id).content)
        if phase == "WRITERS_QUIESCED":
            if host["active_writers"]:
                raise CapabilityError("task pause did not drain existing writers")
            host["paused"] = True
        if phase == "HOST_BINDINGS_VERIFIED":
            host["skill_release"] = intent["target"]["version"]
            host["task_releases"] = {k: intent["target"]["version"] for k in intent["task_ids"]}
        if phase == "ACTIVATED":
            host["paused"] = False
            host["active_release"] = intent["target"]["version"]
            host["merged_intake"] = list(dict.fromkeys(host["intake"]))
        if phase == "ROLLBACK_QUIESCED":
            host["paused"] = True
        if phase == "ROLLBACK_BINDINGS_VERIFIED":
            host["skill_release"] = intent["from_release"]
            host["task_releases"] = {k: intent["from_release"] for k in intent["task_ids"]}
            host["active_release"] = intent["from_release"]
        if phase == "ROLLBACK_COMPLETE":
            host["paused"] = False
        if phase in {"ACTIVATED", "ROLLBACK_BINDINGS_VERIFIED"} and not self.skip_pointer_updates:
            config_id, instance_id = intent["bases"]["config.yml"]["id"], intent["bases"]["INSTANCE.json"]["id"]
            config = yaml_loads(self.drive.read_exact(config_id).content.decode())
            instance = json.loads(self.drive.read_exact(instance_id).content)
            if phase == "ACTIVATED":
                runtime = {"release_id": intent["target"]["version"], "source_commit": intent["target"]["source_commit"], "manifest_sha256": intent["target"]["manifest_sha256"]}
            else:
                runtime = yaml_loads(base64.b64decode(intent["bases"]["config.yml"]["content"]).decode())["runtime"]
            config["runtime"] = runtime
            instance.update(runtime_release_id=runtime["release_id"], source_commit=runtime["source_commit"])
            self.drive.external_edit(config_id, yaml_dumps(config).encode())
            self.drive.external_edit(instance_id, pretty_json(instance).encode())
        host["effects"][phase] = host["effects"].get(phase, 0) + 1
        self.drive.external_edit(self.host_id, pretty_json(host).encode())
        payload = {"instance_id": intent["instance_id"], "target_identity": intent["target_identity"],
                   "reference": self.host_id, "task_ids": intent["task_ids"], "skill_reference": intent["skill_reference"],
                   **{field: True for field in CHECKS[phase].split()}}
        if phase.startswith("ROLLBACK_"):
            payload["runtime_release_id"] = intent["from_release"]
        if phase == "HOST_BINDINGS_VERIFIED":
            binding = {"instance_id": intent["instance_id"], "root_id": intent["root_id"], "release_id": host["skill_release"],
                       "manifest_sha256": intent["target"]["manifest_sha256"], "config_file_id": intent["bases"]["config.yml"]["id"],
                       "map_file_id": intent["bases"]["installation/drive-map.json"]["id"], "content_sha256": sha256_bytes(pretty_json(host).encode())}
            payload["observed_bindings"] = {name: dict(binding) for name in ("skill", "daily", "weekly")}
            payload["fresh_invocation_reference"] = "synthetic-invocation-record"
        if phase == "MIGRATION_VALIDATED":
            payload["input_hashes"] = {path: sha256_bytes(base64.b64decode(value["content"])) for path, value in intent["bases"].items()}
            payload["output_hashes"] = {path: sha256_bytes(base64.b64decode(value)) for path, value in intent["replacements"].items()}
            payload["output_hashes"].update({path: sha256_bytes(base64.b64decode(value["content"])) for path, value in intent["new_files"].items()})
        create_artifact(self.drive, self.root, self.folder, phase + ".json", payload, phase)
        if self.lose_after == phase:
            raise SimulatedLostResponse("host action completed; response lost")
        return payload


class UpgradeHardeningTests(unittest.TestCase):
    def fixture(self, drive_type=FakeDrive, prior_read_schemas=(1,)):
        drive = drive_type()
        root = drive.create_folder(None, "synthetic", idempotency_key="root").id
        folders = {name: drive.create_folder(root, name, idempotency_key=name).id
                   for name in ("operations", "inbox", "state", "backups", "runtime", "host", "data")}
        bases = {}
        old_manifest = pretty_json({"schema_version": 2, "release_id": "0.1.0", "source_commit": "c" * 40,
                                    "compatibility": {"read_schemas": list(prior_read_schemas), "write_schema": 1}}).encode()
        old_config = {"schema_version": 1, "instance": {"id": "wp-test"}, "storage": {"root_folder_id": root}, "user_override": "keep", "runtime": {"release_id": "0.1.0", "source_commit": "c" * 40,
                                                                                 "manifest_sha256": sha256_bytes(old_manifest)}}
        values = {"INSTANCE.json": pretty_json({"instance_id": "wp-test", "source_repository": "Kabutojira/WikiPlant",
                                                 "runtime_release_id": "0.1.0", "source_commit": "c" * 40, "root_folder_id": root}).encode(),
                  "config.yml": yaml_dumps(old_config).encode(), "installation/skill-binding.json": b"{}",
                  "installation/schedule-bindings.json": b"{}", "installation/drive-map.json": pretty_json({"instance_id": "wp-test", "root_id": root, "files": {}}).encode(),
                  "data/research_queue.csv": b"priority,id,attempts\n10,keep,3\n", "runtime/0.1.0/source-manifest.json": old_manifest}
        for path, content in values.items():
            bases[path] = drive.create_file(root, path.rsplit("/", 1)[-1], "application/yaml" if path.endswith("yml") else "text/csv" if path.endswith("csv") else "application/json", content, idempotency_key=path)
        identity = json.loads(bases["INSTANCE.json"].content)
        identity["config_file_id"] = bases["config.yml"].id
        drive.external_edit(bases["INSTANCE.json"].id, pretty_json(identity).encode())
        bases["INSTANCE.json"] = drive.read_exact(bases["INSTANCE.json"].id)
        host_id = drive.create_file(folders["host"], "model.json", "application/json", pretty_json({
            "paused": False, "active_writers": [], "active_release": "0.1.0", "skill_release": "0.1.0",
            "task_releases": {"daily": "0.1.0", "weekly": "0.1.0"}, "effects": {}, "intake": ["pending-user-1"], "merged_intake": []}).encode(), idempotency_key="host-model").id
        runtime = {"scripts/wikiplant/__init__.py": b"# synthetic runtime\n"}
        manifest = {"schema_version": 2, "release_id": "0.2.0", "repository": "Kabutojira/WikiPlant", "source_commit": "a" * 40,
                    "status": "released", "distribution": "detached-release-asset", "compatibility": {"read_schemas": [2], "write_schema": 2},
                    "max_file_bytes": 512000, "max_total_bytes": 8000000, "rollback": "Previous reader must accept current schema",
                    "migrations": ["1_to_2"], "required_capabilities": [], "files": [{"path": p, "encoding": "utf-8", "size": len(b), "sha256": sha256_bytes(b)} for p, b in runtime.items()]}
        target = ReleaseInfo("Kabutojira/WikiPlant", "release-2", "0.2.0", "v0.2.0", "a" * 40,
                             sha256_bytes(pretty_json(manifest).encode()), "2026-09-10T00:00:00+00:00", migrations=("1_to_2",))
        grant = UserAuthorization("turn-1", "wp-test", "update", target.identity, request_digest("update this wiki to 0.2.0"), True, "affirmative user update").to_dict()
        options = dict(authorization=grant, from_release="0.1.0", from_read_schemas=list(prior_read_schemas), current_schema=1,
                       manifest=manifest, runtime_files=runtime, bases=bases,
                       replacements={"config.yml": yaml_dumps({**old_config, "schema_version": 2}).encode()}, task_ids={"daily": "task-d", "weekly": "task-w"},
                       skill_reference="skill-private", capabilities=set(), new_files={"data/TOPICS.md": (folders["data"], b"# synthetic registry\n")})
        return drive, root, folders, host_id, target, options

    def updater(self, drive, root, folders, host_id, **kwargs):
        writer = SafeWriter(drive, root, folders["operations"], folders["inbox"], instance_id="wp-test")
        return Updater(writer, folders["state"], folders["backups"], folders["runtime"], PersistedHostFixture(drive, root, folders["host"], host_id, **kwargs))

    def test_every_phase_reconstructs_and_preserves_actual_records(self):
        for phase in PHASES:
            with self.subTest(phase=phase):
                drive, root, folders, host_id, target, options = self.fixture()
                updater = self.updater(drive, root, folders, host_id)
                updater.request("upgrade-1", target, **options)
                if phase != "REQUESTED":
                    first = updater.resume("upgrade-1", stop_after=phase)
                    self.assertIsNone(first.error, first.error)
                drive = reconstruct(drive)
                result = self.updater(drive, root, folders, host_id).resume("upgrade-1")
                self.assertEqual(result.stage, "COMPLETE", result.error)
                actual_config = yaml_loads(drive.read_exact(options["bases"]["config.yml"].id).content.decode())
                self.assertEqual(actual_config["schema_version"], 2)
                self.assertEqual(actual_config["runtime"]["release_id"], "0.2.0")
                self.assertEqual(actual_config["user_override"], "keep")
                self.assertEqual(drive.read_exact(options["bases"]["data/research_queue.csv"].id).content, options["bases"]["data/research_queue.csv"].content)
                host = json.loads(drive.read_exact(host_id).content)
                self.assertEqual(host["active_release"], "0.2.0")
                self.assertEqual(host["merged_intake"], ["pending-user-1"])
                self.assertTrue(all(count == 1 for count in host["effects"].values()))
                mapping = json.loads(drive.read_exact(options["bases"]["installation/drive-map.json"].id).content)
                self.assertEqual(drive.read_exact(mapping["files"]["data/TOPICS.md"]["id"]).content, b"# synthetic registry\n")

    def test_completed_replay_returns_history_without_overwriting_later_data(self):
        drive, root, folders, host_id, target, options = self.fixture()
        updater = self.updater(drive, root, folders, host_id)
        updater.request("upgrade-1", target, **options)
        self.assertEqual(updater.resume("upgrade-1").stage, "COMPLETE")
        config_id = options["bases"]["config.yml"].id
        drive.external_edit(config_id, b"schema_version: 2\nuser_override: newer\n")
        new_data = drive.create_file(folders["data"], "later-note.md", "text/markdown", b"later saved note", idempotency_key="later")
        restored = self.updater(reconstruct(drive), root, folders, host_id)
        self.assertEqual(restored.resume("upgrade-1").stage, "COMPLETE")
        self.assertIn(b"newer", restored.adapter.read_exact(config_id).content)
        self.assertEqual(restored.adapter.read_exact(new_data.id).content, b"later saved note")
        plan = rollback_plan(restored.load("upgrade-1"), prior_read_schemas=[1], current_data_schema=2, later_record_ids=[new_data.id])
        self.assertEqual(plan["status"], "blocked_incompatible_schema")
        self.assertFalse(plan["restore_data"])
        compatible = rollback_plan(restored.load("upgrade-1"), prior_read_schemas=[1, 2], current_data_schema=2, later_record_ids=[new_data.id])
        self.assertEqual(compatible["status"], "ready_for_verified_host_rebind")
        self.assertEqual(compatible["preserve_record_ids"], [new_data.id])

    def test_lost_host_responses_and_missing_update_control(self):
        for phase in (key for key in CHECKS if not key.startswith("ROLLBACK_")):
            with self.subTest(phase=phase):
                drive, root, folders, host_id, target, options = self.fixture()
                updater = self.updater(drive, root, folders, host_id, lose_after=phase)
                updater.request("upgrade-1", target, **options)
                with self.assertRaises(SimulatedLostResponse):
                    updater.resume("upgrade-1")
                drive = reconstruct(drive)
                recovered = self.updater(drive, root, folders, host_id).resume("upgrade-1")
                self.assertEqual(recovered.stage, "COMPLETE", recovered.error)
                self.assertEqual(json.loads(drive.read_exact(host_id).content)["effects"][phase], 1)
        drive, root, folders, host_id, target, options = self.fixture()
        updater = self.updater(drive, root, folders, host_id, unavailable="HOST_BINDINGS_VERIFIED")
        updater.request("upgrade-1", target, **options)
        blocked = updater.resume("upgrade-1")
        self.assertEqual(blocked.blocked_phase, "HOST_BINDINGS_VERIFIED")
        self.assertTrue(json.loads(drive.read_exact(host_id).content)["paused"])
        recovered = self.updater(reconstruct(drive), root, folders, host_id).resume("upgrade-1")
        self.assertEqual(recovered.stage, "COMPLETE", recovered.error)
        self.assertNotEqual(blocked.stage, "COMPLETE")

    def test_stale_plan_and_weak_writer_fail_closed(self):
        for weak in (False, True):
            drive, root, folders, host_id, target, options = self.fixture(WeakDrive if weak else FakeDrive)
            updater = self.updater(drive, root, folders, host_id)
            updater.request("upgrade-1", target, **options)
            if not weak:
                drive.external_edit(options["bases"]["config.yml"].id, b"manual changed")
            blocked = updater.resume("upgrade-1")
            self.assertEqual(blocked.blocked_phase, "DATA_MIGRATED")
            self.assertNotEqual(blocked.stage, "COMPLETE")
            if not weak:
                self.assertEqual(drive.read_exact(options["bases"]["config.yml"].id).content, b"manual changed")

    def test_authorization_and_original_target_cannot_be_replaced(self):
        drive, root, folders, host_id, target, options = self.fixture()
        updater = self.updater(drive, root, folders, host_id)
        wrong = {**options, "authorization": {**options["authorization"], "quoted": True}}
        with self.assertRaises(ValidationError):
            updater.request("upgrade-1", target, **wrong)
        updater.request("upgrade-1", target, **options)
        altered = {**options, "replacements": {"config.yml": b"different intent"}}
        with self.assertRaises(ConflictError):
            updater.request("upgrade-1", target, **altered)

    def test_resume_in_fresh_python_process_uses_only_serialized_drive_records(self):
        drive, root, folders, host_id, target, options = self.fixture()
        updater = self.updater(drive, root, folders, host_id)
        updater.request("upgrade-1", target, **options)
        self.assertEqual(updater.resume("upgrade-1", stop_after="DATA_MIGRATED").stage, "DATA_MIGRATED")
        payload = {"root": root, "folders": folders, "host_id": host_id, "counter": drive._counter,
                   "entries": {key: {**asdict(value), "content": base64.b64encode(value.content).decode()}
                               for key, value in drive.entries.items()}}
        code = """import sys,json,base64
from wikiplant.fake_drive import FakeDrive,_Entry
from tests.integration.test_upgrade_hardening import UpgradeHardeningTests
p=json.load(sys.stdin)
d=FakeDrive()
d.entries={k:_Entry(**{**v,'content':base64.b64decode(v['content'])}) for k,v in p['entries'].items()}
d._counter=p['counter']
u=UpgradeHardeningTests().updater(d,p['root'],p['folders'],p['host_id'])
s=u.resume('upgrade-1')
print(json.dumps({'stage':s.stage,'error':s.error,'host':json.loads(d.read_exact(p['host_id']).content)}))
"""
        completed = subprocess.run([sys.executable, "-c", code], input=json.dumps(payload), text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        actual = json.loads(completed.stdout)
        self.assertEqual(actual["stage"], "COMPLETE", actual["error"])
        self.assertEqual(actual["host"]["active_release"], "0.2.0")
        self.assertEqual(actual["host"]["merged_intake"], ["pending-user-1"])

    def test_rollback_executes_host_recovery_without_restoring_later_data(self):
        drive, root, folders, host_id, target, options = self.fixture(prior_read_schemas=(1, 2))
        updater = self.updater(drive, root, folders, host_id)
        updater.request("upgrade-1", target, **options)
        self.assertEqual(updater.resume("upgrade-1").stage, "COMPLETE")
        later = drive.create_file(folders["data"], "later.md", "text/markdown", b"newer research", idempotency_key="later")
        binding = Binding("data/later.md", later.id, later.mime_type, root)
        result = updater.rollback("upgrade-1", current_data_schema=2, later_bindings={"data/later.md": binding})
        self.assertEqual(result["phase"], "ROLLBACK_COMPLETE")
        self.assertEqual(drive.read_exact(later.id).content, b"newer research")
        self.assertEqual(json.loads(drive.read_exact(host_id).content)["active_release"], "0.1.0")
        self.assertEqual(drive.read_exact(options["bases"]["config.yml"].id).content, options["replacements"]["config.yml"])
        replay = self.updater(reconstruct(drive), root, folders, host_id)
        self.assertEqual(replay.rollback("upgrade-1", current_data_schema=2, later_bindings={})["phase"], "ROLLBACK_COMPLETE")
        self.assertEqual(replay.resume("upgrade-1").blocked_phase, "ROLLBACK")

    def test_tampered_staged_runtime_and_false_binding_receipts_block_activation(self):
        drive, root, folders, host_id, target, options = self.fixture()
        updater = self.updater(drive, root, folders, host_id)
        updater.request("upgrade-1", target, **options)
        staged = updater.resume("upgrade-1", stop_after="RUNTIME_STAGED")
        entry = next(iter(staged.receipts["RUNTIME_STAGED"]["evidence"]["files"].values()))
        drive.external_edit(entry["id"], b"changed execution code")
        blocked = self.updater(reconstruct(drive), root, folders, host_id).resume("upgrade-1")
        self.assertEqual(blocked.blocked_phase, "DATA_MIGRATED")
        self.assertIn("staged runtime changed", blocked.error)
        self.assertEqual(drive.read_exact(options["bases"]["config.yml"].id).content, options["bases"]["config.yml"].content)
        intent = json.loads(updater._find("upgrade-1", "intent").content)
        with self.assertRaises(CapabilityError):
            Updater._validate_observation("HOST_BINDINGS_VERIFIED", {"instance_id": "wp-test", "target_identity": target.identity,
                "reference": "arbitrary-file", "task_ids": options["task_ids"], "skill_reference": "skill-private",
                **{key: True for key in CHECKS["HOST_BINDINGS_VERIFIED"].split()}}, intent)

    def test_rollback_compatibility_is_bound_to_prior_manifest_and_current_schema(self):
        drive, root, folders, host_id, target, options = self.fixture()
        updater = self.updater(drive, root, folders, host_id)
        with self.assertRaises(ValidationError):
            updater.request("upgrade-1", target, **{**options, "from_read_schemas": [1, 2]})
        updater.request("upgrade-1", target, **options)
        self.assertEqual(updater.resume("upgrade-1").stage, "COMPLETE")
        for wrong_schema in (1, 2):
            with self.assertRaises(CapabilityError):
                updater.rollback("upgrade-1", current_data_schema=wrong_schema, later_bindings={})

    def test_boolean_host_activation_without_raw_pointer_changes_is_not_success(self):
        drive, root, folders, host_id, target, options = self.fixture()
        updater = self.updater(drive, root, folders, host_id, skip_pointer_updates=True)
        updater.request("upgrade-1", target, **options)
        result = updater.resume("upgrade-1")
        self.assertEqual(result.blocked_phase, "ACTIVATED")
        self.assertEqual(result.stage, "SMOKE_TESTED")
        self.assertIn("canonical config runtime pin", result.error)
        self.assertTrue(json.loads(drive.read_exact(host_id).content)["paused"])
        recovered = self.updater(reconstruct(drive), root, folders, host_id).resume("upgrade-1")
        self.assertEqual(recovered.stage, "COMPLETE", recovered.error)


if __name__ == "__main__":
    unittest.main()
