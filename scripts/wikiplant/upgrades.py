"""Resumable explicit updates over fetched inputs and an observed Work bridge.

Durable intent and phase records are immutable. Canonical migration uses the same
snapshot-bound writer as research. The bridge is not a claimed cloud API.
"""
from __future__ import annotations

import base64
import copy
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Protocol

from .authorization import validate_user_authorization
from .errors import CapabilityError, ConflictError, SimulatedLostResponse, ValidationError
from .releases import ReleaseInfo, Version
from .storage import Binding, FileSnapshot, SafeWriter, create_artifact, expected_mime, find_artifact, inventory, validate_scope
from .util import pretty_json, safe_relative_path, sha256_bytes, sha256_text


PHASES = ("REQUESTED", "TARGET_RESOLVED", "PREFLIGHT_VERIFIED", "WRITERS_QUIESCED", "BACKUP_VERIFIED",
          "RUNTIME_STAGED", "MIGRATION_VALIDATED", "DATA_MIGRATED", "HOST_BINDINGS_VERIFIED", "SMOKE_TESTED",
          "ACTIVATED", "COMPLETE")


def _snapshot(value: FileSnapshot) -> dict:
    result = asdict(value)
    result["content"] = base64.b64encode(value.content).decode("ascii")
    return result


def _restore(value: dict) -> FileSnapshot:
    return FileSnapshot(**{**value, "content": base64.b64decode(value["content"], validate=True)})


@dataclass
class UpgradeState:
    operation_id: str
    instance_id: str
    from_release: str
    to_release: str
    target_identity: str
    stage: str
    intent_reference: str
    receipts: dict[str, dict] = field(default_factory=dict)
    blocked_phase: str | None = None
    error: str | None = None


class UpgradeBridge(Protocol):
    """Reconstruct observations from host state; reconcile uncertain effects first.

    ``reconcile`` raises on unknown outcomes. None means conclusively absent and
    safe to perform. Returned references are actual tool/host observations, never
    desired configuration. Unavailable controls raise CapabilityError.
    """
    def reconcile(self, phase: str, intent: dict) -> dict | None: ...
    def perform(self, phase: str, intent: dict) -> dict: ...


def available_update(current: str, published: str) -> dict:
    candidate = Version.parse(published)
    return {"current": current, "available": published,
            "update_available": not candidate.prerelease and candidate > Version.parse(current), "adopted": False}


class Updater:
    def __init__(self, writer: SafeWriter, state_folder_id: str, backup_folder_id: str,
                 runtime_parent_id: str, bridge: UpgradeBridge):
        self.writer, self.adapter = writer, writer.adapter
        self.state_folder_id, self.backup_folder_id, self.runtime_parent_id = state_folder_id, backup_folder_id, runtime_parent_id
        self.bridge = bridge
        for folder in (state_folder_id, backup_folder_id, runtime_parent_id):
            validate_scope(self.adapter, folder, writer.root_id, folder=True)

    def _name(self, operation_id: str, suffix: str) -> str:
        return "upgrade-" + sha256_text(self.writer.instance_id + ":" + operation_id) + "." + suffix + ".json"

    def _save(self, operation_id: str, suffix: str, payload: dict) -> FileSnapshot:
        return create_artifact(self.adapter, self.writer.root_id, self.state_folder_id,
                               self._name(operation_id, suffix), payload,
                               f"{self.writer.instance_id}:upgrade:{operation_id}:{suffix}")

    def _find(self, operation_id: str, suffix: str) -> FileSnapshot | None:
        return find_artifact(self.adapter, self.writer.root_id, self.state_folder_id, self._name(operation_id, suffix))

    def request(self, operation_id: str, target: ReleaseInfo, *, authorization: dict, from_release: str,
                from_read_schemas: list[int], current_schema: int, manifest: dict, runtime_files: dict[str, bytes],
                bases: dict[str, FileSnapshot], replacements: dict[str, bytes],
                task_ids: dict[str, str], skill_reference: str, capabilities: set[str],
                new_files: dict[str, tuple[str, bytes]] | None = None, channel: str = "stable") -> UpgradeState:
        """Persist one exact approved target and generation inputs before effects."""
        target.validate()
        if target.draft or channel not in {"stable", "prerelease"} or (channel == "stable" and (target.prerelease or Version.parse(target.version).prerelease)):
            raise ValidationError("target is not a published release in the explicitly selected channel")
        validate_user_authorization(authorization, instance_id=self.writer.instance_id, operation="update", target=target.identity)
        if Version.parse(target.version) <= Version.parse(from_release):
            raise ValidationError("requested target is not a newer release")
        if set(task_ids) != {"daily", "weekly"} or len(set(task_ids.values())) != 2 or not all(task_ids.values()) or not skill_reference:
            raise ValidationError("update must bind the existing private skill and two distinct tasks")
        if target.manifest_sha256 != sha256_bytes(pretty_json(manifest).encode()):
            raise ValidationError("approved manifest digest differs from provided payload")
        if (manifest.get("source_commit"), manifest.get("release_id"), manifest.get("repository")) != (target.source_commit, target.version, target.repository):
            raise ValidationError("approved release differs from manifest")
        if manifest.get("schema_version") != 2 or manifest.get("status") != "released" or manifest.get("distribution") != "detached-release-asset":
            raise ValidationError("update requires a released detached v2 manifest")
        if manifest.get("compatibility") != {"read_schemas": list(target.read_schemas), "write_schema": target.write_schema} or manifest.get("migrations") != list(target.migrations) or manifest.get("required_capabilities") != list(target.required_capabilities):
            raise ValidationError("release compatibility claims differ from pinned manifest")
        ok, blockers = target.compatibility(current_schema, capabilities)
        if not ok:
            raise CapabilityError("; ".join(blockers))
        self._verify_payload(manifest, runtime_files)
        if not bases or set(replacements) - set(bases):
            raise ValidationError("all mutable migration outputs require inventoried generation bases")
        required = {"INSTANCE.json", "config.yml", "installation/skill-binding.json", "installation/schedule-bindings.json", "installation/drive-map.json"}
        previous_manifest_path = f"runtime/{from_release}/source-manifest.json"
        required.add(previous_manifest_path)
        if not required <= bases.keys():
            raise ValidationError("backup inventory must include pointers, config, map and host bindings")
        identity = json.loads(bases["INSTANCE.json"].content)
        if identity.get("source_repository") != target.repository:
            raise ValidationError("update repository differs from recorded installation provenance")
        from .yamlio import loads as yaml_loads
        old_config = yaml_loads(bases["config.yml"].content.decode("utf-8"))
        prior_manifest = json.loads(bases[previous_manifest_path].content)
        previous_pin = old_config.get("runtime", {})
        if (old_config.get("schema_version"), previous_pin.get("release_id"), previous_pin.get("manifest_sha256")) != (current_schema, from_release, bases[previous_manifest_path].sha256):
            raise ValidationError("previous runtime/schema must match the bound config and actual source manifest")
        if (identity.get("runtime_release_id"), identity.get("source_commit"), previous_pin.get("source_commit")) != (from_release, prior_manifest.get("source_commit"), prior_manifest.get("source_commit")) or prior_manifest.get("release_id") != from_release:
            raise ValidationError("previous runtime provenance differs across manifest/instance/config")
        prior_reads = [1] if prior_manifest.get("schema_version") == 1 else prior_manifest.get("compatibility", {}).get("read_schemas", [])
        if not prior_reads or from_read_schemas != prior_reads or any(type(value) is not int or value < 1 for value in prior_reads):
            raise ValidationError("rollback compatibility must come from the pinned prior manifest")
        if "installation/drive-map.json" in replacements:
            raise ValidationError("runtime/new-file mapping must be derived from original map, not another replacement")
        for path, base in bases.items():
            safe_relative_path(path)
            if base.mime_type != expected_mime(path):
                raise ValidationError("migration base must be the canonical raw file type")
            # Existing intent is compared below before checking current state on a replay.
            if self._find(operation_id, "intent") is None and validate_scope(self.adapter, base.id, self.writer.root_id) != base:
                raise ConflictError("migration inventory changed before approval was recorded")
        for path, (parent, _) in (new_files or {}).items():
            safe_relative_path(path)
            validate_scope(self.adapter, parent, self.writer.root_id, folder=True)
            if path in bases:
                raise ValidationError("new migration file overlaps an existing canonical target")
            if self._find(operation_id, "intent") is None and any(s.name == path.rsplit("/", 1)[-1] for s in inventory(self.adapter, parent)):
                raise ConflictError("new migration file already exists; resolve exact identity before planning")
        intent = {"schema_version": 2, "operation_id": operation_id, "instance_id": self.writer.instance_id,
                  "root_id": self.writer.root_id, "target": asdict(target), "target_identity": target.identity,
                  "from_release": from_release, "from_read_schemas": from_read_schemas, "current_schema": current_schema,
                  "authorization": authorization, "manifest": manifest, "task_ids": task_ids, "skill_reference": skill_reference, "channel": channel,
                  "bases": {p: _snapshot(s) for p, s in bases.items()},
                  "replacements": {p: base64.b64encode(b).decode() for p, b in replacements.items()},
                  "new_files": {p: {"parent_id": parent, "content": base64.b64encode(b).decode()} for p, (parent, b) in (new_files or {}).items()},
                  "runtime_files": {p: base64.b64encode(b).decode() for p, b in runtime_files.items()}}
        self._save(operation_id, "intent", intent)
        return self.load(operation_id)

    @staticmethod
    def _verify_payload(manifest: dict, files: dict[str, bytes]) -> None:
        from .manifest import DEVELOPMENT_ONLY_PATHS, EXCLUDED_NAMES, MAX_FILE_BYTES, MAX_RUNTIME_BYTES, MAX_RUNTIME_FILES, RUNTIME_PREFIXES, verify_payload_dependency_closure
        if any(type(manifest.get(key)) is not int or not 1 <= manifest[key] <= bound
               for key, bound in (("max_file_bytes", MAX_FILE_BYTES), ("max_total_bytes", MAX_RUNTIME_BYTES))) or not manifest.get("rollback"):
            raise ValidationError("manifest requires finite limits and explicit rollback conditions")
        entries = manifest.get("files", [])
        paths = [entry["path"] for entry in entries]
        if not entries or len(entries) > MAX_RUNTIME_FILES or len(set(paths)) != len(paths) or set(paths) != set(files):
            raise ValidationError("runtime payload inventory mismatch")
        total = 0
        for entry in entries:
            path = safe_relative_path(entry["path"])
            if path in DEVELOPMENT_ONLY_PATHS or not any(path.startswith(p) for p in RUNTIME_PREFIXES) or any(p in EXCLUDED_NAMES for p in path.split("/")) or path.endswith(".pyc"):
                raise ValidationError("runtime payload path is not allowed")
            payload = files[path]
            payload.decode("utf-8")
            if entry.get("encoding") != "utf-8" or type(entry.get("size")) is not int or len(payload) != entry["size"] or len(payload) > manifest["max_file_bytes"] or sha256_bytes(payload) != entry["sha256"]:
                raise ValidationError("runtime payload identity mismatch")
            total += len(payload)
        if total > manifest["max_total_bytes"]:
            raise ValidationError("runtime payload exceeds bound")
        verify_payload_dependency_closure(files)

    def load(self, operation_id: str) -> UpgradeState:
        source = self._find(operation_id, "intent")
        if source is None:
            raise ValidationError("upgrade has no durable approved intent")
        intent = json.loads(source.content)
        if (intent["instance_id"], intent["root_id"], intent["operation_id"]) != (self.writer.instance_id, self.writer.root_id, operation_id):
            raise ValidationError("upgrade state belongs to another instance")
        state = UpgradeState(operation_id, self.writer.instance_id, intent["from_release"], intent["target"]["version"],
                             intent["target_identity"], "REQUESTED", source.id)
        previous_hash = source.sha256
        missing = False
        for phase in PHASES[1:]:
            receipt = self._find(operation_id, phase)
            if receipt is None:
                missing = True
                continue
            value = json.loads(receipt.content)
            if missing or value["previous_sha256"] != previous_hash or value["intent_sha256"] != source.sha256:
                raise ConflictError("upgrade phase chain is incomplete or changed")
            state.receipts[phase], state.stage, previous_hash = value, phase, receipt.sha256
        return state

    def resume(self, operation_id: str, *, stop_after: str | None = None) -> UpgradeState:
        state = self.load(operation_id)
        original = self._find(operation_id, "intent")
        intent = json.loads(original.content)
        if self._find(operation_id, "rollback-intent"):
            state.error, state.blocked_phase = "Rollback recovery has begun; resume rollback or start a new approved update", "ROLLBACK"
            return state
        if state.stage == "COMPLETE":
            return state  # Historical receipt; never reapply migrated bytes.
        validate_user_authorization(intent["authorization"], instance_id=self.writer.instance_id, operation="update", target=intent["target_identity"])
        for phase in PHASES[PHASES.index(state.stage) + 1:]:
            try:
                evidence = self._execute(phase, intent, state)
                previous = original if state.stage == "REQUESTED" else self._find(operation_id, state.stage)
                payload = {"schema_version": 2, "phase": phase, "instance_id": state.instance_id,
                           "operation_id": operation_id, "target_identity": state.target_identity,
                           "intent_sha256": original.sha256, "previous_sha256": previous.sha256, "evidence": evidence}
                self._save(operation_id, phase, payload)
                state = self.load(operation_id)
            except (CapabilityError, ConflictError, ValidationError, RuntimeError) as exc:
                state.blocked_phase, state.error = phase, str(exc)
                if phase == "ACTIVATED":
                    # A host can resume tasks before a failed pointer readback.
                    # Re-establish actual quiescence; never infer it from a flag.
                    try:
                        paused = self.bridge.reconcile("WRITERS_QUIESCED", intent)
                        if paused is None:
                            paused = self.bridge.perform("WRITERS_QUIESCED", intent)
                        self._validate_observation("WRITERS_QUIESCED", paused, intent)
                    except Exception as pause_error:
                        state.error += "; recovery pause remains unverified: " + str(pause_error)
                self._save(operation_id, "blocked-" + phase + "-" + sha256_text(state.error)[:16],
                           {"schema_version": 2, "phase": phase, "error": state.error, "intent_sha256": original.sha256,
                            "status": "recoverable", "instance_id": state.instance_id})
                return state
            if phase == stop_after:
                break
        return state

    def rollback(self, operation_id: str, *, current_data_schema: int, later_bindings: dict[str, Binding]) -> dict:
        """Execute compatibility-gated code/host recovery, never restoring old data.

        The same approved update authorizes routine recovery of that instance.
        Actual host control success remains required from the observed bridge.
        """
        state = self.load(operation_id)
        original = self._find(operation_id, "intent")
        intent = json.loads(original.content)
        complete = self._find(operation_id, "ROLLBACK_COMPLETE")
        if complete:
            return json.loads(complete.content)
        from .yamlio import loads as yaml_loads
        current_config = validate_scope(self.adapter, intent["bases"]["config.yml"]["id"], self.writer.root_id)
        observed_schema = yaml_loads(current_config.content.decode("utf-8")).get("schema_version")
        if type(current_data_schema) is not int or current_data_schema != observed_schema:
            raise CapabilityError("rollback schema differs from fresh authoritative config")
        if current_data_schema not in intent["from_read_schemas"]:
            raise CapabilityError("previous runtime cannot read current schema; remain paused for validated repair")
        saved = self._find(operation_id, "rollback-intent")
        if saved:
            recovery = json.loads(saved.content)
            if recovery["current_data_schema"] != current_data_schema:
                raise ConflictError("rollback data schema changed; re-evaluate recovery")
        else:
            from .storage import validate_binding
            recovery = {"schema_version": 2, "instance_id": self.writer.instance_id, "intent_sha256": original.sha256,
                        "current_data_schema": current_data_schema, "runtime_target": state.from_release,
                        "restore_data": False, "preserved": {path: _snapshot(validate_binding(self.adapter, binding, self.writer.root_id)) for path, binding in later_bindings.items()}}
            saved = self._save(operation_id, "rollback-intent", recovery)
        rollback_intent = {**intent, "rollback": recovery}
        previous = saved
        for phase in ("ROLLBACK_QUIESCED", "ROLLBACK_BINDINGS_VERIFIED", "ROLLBACK_COMPLETE"):
            existing = self._find(operation_id, phase)
            if existing:
                value = json.loads(existing.content)
                if value["previous_sha256"] != previous.sha256 or value["rollback_intent_sha256"] != saved.sha256:
                    raise ConflictError("rollback chain differs from original recovery intent")
                previous = existing
                continue
            observed = self.bridge.reconcile(phase, rollback_intent)
            if observed is None:
                observed = self.bridge.perform(phase, rollback_intent)
            self._validate_observation(phase, observed, rollback_intent)
            if phase in {"ROLLBACK_BINDINGS_VERIFIED", "ROLLBACK_COMPLETE"}:
                old_runtime = json.loads(base64.b64decode(intent["bases"][f"runtime/{intent['from_release']}/source-manifest.json"]["content"]))
                self._verify_runtime_pointers(intent, release_id=intent["from_release"], source_commit=old_runtime["source_commit"],
                                              manifest_sha256=_restore(intent["bases"][f"runtime/{intent['from_release']}/source-manifest.json"]).sha256,
                                              data_schema=current_data_schema)
            for snapshot in recovery["preserved"].values():
                base = _restore(snapshot)
                current = validate_scope(self.adapter, base.id, self.writer.root_id)
                if current.content != base.content or current.mime_type != base.mime_type:
                    raise ConflictError("later data changed during rollback; preserve it and reconcile before completion")
            value = {"schema_version": 2, "instance_id": self.writer.instance_id, "phase": phase,
                     "runtime_target": state.from_release, "restore_data": False,
                     "previous_sha256": previous.sha256, "rollback_intent_sha256": saved.sha256, "evidence": observed}
            previous = self._save(operation_id, phase, value)
        return json.loads(previous.content)

    def _execute(self, phase: str, intent: dict, state: UpgradeState) -> dict:
        op = intent["operation_id"]
        if phase == "TARGET_RESOLVED":
            return {"target": intent["target_identity"], "manifest": intent["target"]["manifest_sha256"]}
        if phase == "BACKUP_VERIFIED":
            backup = create_artifact(self.adapter, self.writer.root_id, self.backup_folder_id, self._name(op, "backup"),
                                     {"schema_version": 2, "instance_id": self.writer.instance_id,
                                      "from_release": intent["from_release"], "files": intent["bases"]}, op + ":backup")
            return {"reference": backup.id, "sha256": backup.sha256, "count": len(intent["bases"])}
        if phase == "RUNTIME_STAGED":
            return self._stage_runtime(intent)
        if phase == "DATA_MIGRATED":
            self._require_drained(intent)
            self._verify_runtime(intent)
            receipts = {}
            staged = state.receipts["RUNTIME_STAGED"]["evidence"]
            runtime_prefix = "runtime/" + intent["target"]["version"] + "/"
            additions = {runtime_prefix + path: {"id": item["id"], "mime_type": expected_mime(path)}
                         for path, item in staged["files"].items()}
            additions[runtime_prefix + "source-manifest.json"] = {"id": staged["manifest_reference"], "mime_type": "application/json"}
            for path, plan in sorted(intent["new_files"].items()):
                created = self._raw_once(plan["parent_id"], path.rsplit("/", 1)[-1], expected_mime(path),
                                         base64.b64decode(plan["content"]), op + ":new:" + path)
                additions[path] = {"id": created.id, "mime_type": created.mime_type}
                receipts[path] = {"id": created.id, "sha256": created.sha256, "created": True}
            for path, encoded in sorted(intent["replacements"].items()):
                base = _restore(intent["bases"][path])
                receipt = self.writer.replace(Binding(path, base.id, base.mime_type, self.writer.root_id),
                                              base64.b64decode(encoded), op + ":migrate:" + path, base=base,
                                              authorization=intent["authorization"])
                if receipt.current.sha256 != receipt.verified_sha256:
                    raise ConflictError("migrated target has subsequent edits; reconcile before activation")
                receipts[path] = {"id": receipt.id, "sha256": receipt.verified_sha256, "receipt": receipt.completion_reference}
            if additions:
                path = "installation/drive-map.json"
                base = _restore(intent["bases"][path])
                mapping = json.loads(base.content)
                if mapping.get("instance_id") != self.writer.instance_id or mapping.get("root_id") != self.writer.root_id:
                    raise ValidationError("migration map belongs to another instance")
                mapping.setdefault("files", {}).update(additions)
                mapping.setdefault("folders", {})[runtime_prefix.rstrip("/")] = staged["root_id"]
                receipt = self.writer.replace(Binding(path, base.id, base.mime_type, self.writer.root_id),
                                              pretty_json(mapping).encode(), op + ":new-map", base=base,
                                              authorization=intent["authorization"])
                receipts[path] = {"id": receipt.id, "sha256": receipt.verified_sha256, "receipt": receipt.completion_reference}
            return {"files": receipts, "count": len(receipts)}
        observation = self.bridge.reconcile(phase, intent)
        # Activation can have resumed tasks before its response/checkpoint was lost.
        # Reconcile that durable outcome before asking for a now-inapplicable drain.
        if phase == "ACTIVATED" and observation is not None:
            self._validate_observation(phase, observation, intent)
            self._verify_runtime_pointers(intent, release_id=intent["target"]["version"], source_commit=intent["target"]["source_commit"],
                                          manifest_sha256=intent["target"]["manifest_sha256"], data_schema=intent["target"]["write_schema"])
            return observation
        if phase in {"HOST_BINDINGS_VERIFIED", "SMOKE_TESTED", "ACTIVATED"}:
            self._verify_migrated(intent)
            self._verify_runtime(intent)
            self._require_drained(intent)
        if observation is None:
            observation = self.bridge.perform(phase, intent)
        self._validate_observation(phase, observation, intent)
        if phase == "ACTIVATED":
            self._verify_runtime_pointers(intent, release_id=intent["target"]["version"], source_commit=intent["target"]["source_commit"],
                                          manifest_sha256=intent["target"]["manifest_sha256"], data_schema=intent["target"]["write_schema"])
        return observation

    def _verify_runtime_pointers(self, intent: dict, *, release_id: str, source_commit: str, manifest_sha256: str, data_schema: int) -> None:
        """Independent canonical reads; a host's boolean activation flag is insufficient."""
        from .yamlio import loads as yaml_loads
        from .storage import validate_binding
        records = {}
        for path in ("config.yml", "INSTANCE.json"):
            base = _restore(intent["bases"][path])
            snapshot = validate_binding(self.adapter, Binding(path, base.id, base.mime_type, self.writer.root_id), self.writer.root_id)
            records[path] = yaml_loads(snapshot.content.decode()) if path.endswith(".yml") else json.loads(snapshot.content)
        config, identity = records["config.yml"], records["INSTANCE.json"]
        expected_pin = {"release_id": release_id, "source_commit": source_commit, "manifest_sha256": manifest_sha256}
        if (config.get("schema_version"), config.get("instance", {}).get("id"), config.get("storage", {}).get("root_folder_id")) != (data_schema, intent["instance_id"], intent["root_id"]):
            raise CapabilityError("canonical config instance/root/schema not verified after host activation")
        if any(config.get("runtime", {}).get(key) != value for key, value in expected_pin.items()):
            raise CapabilityError("canonical config runtime pin differs from activated release")
        if (identity.get("instance_id"), identity.get("root_folder_id"), identity.get("config_file_id"), identity.get("runtime_release_id"), identity.get("source_commit")) != (intent["instance_id"], intent["root_id"], intent["bases"]["config.yml"]["id"], release_id, source_commit):
            raise CapabilityError("canonical INSTANCE runtime/binding pointer differs from activation")

    def _require_drained(self, intent: dict) -> None:
        observed = self.bridge.reconcile("WRITERS_QUIESCED", intent)
        if observed is None:
            raise CapabilityError("writer drain must be observed again before canonical migration/activation")
        self._validate_observation("WRITERS_QUIESCED", observed, intent)

    def _verify_migrated(self, intent: dict) -> None:
        for path, payload in intent["replacements"].items():
            base = _restore(intent["bases"][path])
            current = validate_scope(self.adapter, base.id, self.writer.root_id)
            if current.mime_type != base.mime_type or current.sha256 != sha256_bytes(base64.b64decode(payload)):
                raise ConflictError("migration output no longer matches verified staged plan")
        # Includes newly created files and the derived exact-ID mapping.
        receipt = self._find(intent["operation_id"], "DATA_MIGRATED")
        if receipt:
            for record in json.loads(receipt.content)["evidence"]["files"].values():
                if validate_scope(self.adapter, record["id"], self.writer.root_id).sha256 != record["sha256"]:
                    raise ConflictError("migration receipt no longer matches canonical output")

    def _verify_runtime(self, intent: dict) -> None:
        receipt = self._find(intent["operation_id"], "RUNTIME_STAGED")
        if receipt is None:
            raise ConflictError("runtime staging receipt is absent")
        evidence = json.loads(receipt.content)["evidence"]
        for path, record in evidence["files"].items():
            current = validate_scope(self.adapter, record["id"], self.writer.root_id)
            if current.sha256 != record["sha256"] or current.mime_type != expected_mime(path):
                raise ConflictError("staged runtime changed after verification")
        manifest = validate_scope(self.adapter, evidence["manifest_reference"], self.writer.root_id)
        if manifest.sha256 != intent["target"]["manifest_sha256"]:
            raise ConflictError("staged source manifest changed")

    def _raw_once(self, parent: str, name: str, mime: str, data: bytes, key: str) -> FileSnapshot:
        validate_scope(self.adapter, parent, self.writer.root_id, folder=True)
        matches = [s for s in inventory(self.adapter, parent) if s.name == name]
        if len(matches) > 1:
            raise ConflictError("ambiguous raw migration file")
        if matches:
            value = matches[0]
        else:
            try:
                value = self.adapter.create_file(parent, name, mime, data, idempotency_key=key)
            except SimulatedLostResponse:
                matches = [s for s in inventory(self.adapter, parent) if s.name == name]
                if len(matches) != 1:
                    raise ConflictError("raw migration create outcome unknown")
                value = matches[0]
        value = validate_scope(self.adapter, value.id, self.writer.root_id)
        if value.content != data or value.mime_type != mime:
            raise ConflictError("existing raw migration bytes differ")
        return value

    def _stage_runtime(self, intent: dict) -> dict:
        def folder(parent: str, name: str) -> str:
            matches = [s for s in inventory(self.adapter, parent) if s.name == name]
            if len(matches) > 1:
                raise ConflictError("ambiguous staged runtime folder")
            if matches:
                result = matches[0]
            else:
                try:
                    result = self.adapter.create_folder(parent, name, idempotency_key=intent["operation_id"] + ":folder:" + parent + ":" + name)
                except SimulatedLostResponse:
                    matches = [s for s in inventory(self.adapter, parent) if s.name == name]
                    if len(matches) != 1:
                        raise ConflictError("staged folder outcome unknown")
                    result = matches[0]
            validate_scope(self.adapter, result.id, self.writer.root_id, folder=True)
            return result.id
        root = folder(self.runtime_parent_id, intent["target"]["version"])
        mapping = {}
        for path, encoded in sorted(intent["runtime_files"].items()):
            parts = safe_relative_path(path).split("/")
            parent = root
            for part in parts[:-1]:
                parent = folder(parent, part)
            data = base64.b64decode(encoded)
            matches = [s for s in inventory(self.adapter, parent) if s.name == parts[-1]]
            if len(matches) > 1:
                raise ConflictError("ambiguous staged runtime file")
            if not matches:
                try:
                    value = self.adapter.create_file(parent, parts[-1], expected_mime(path), data,
                                                     idempotency_key=intent["operation_id"] + ":runtime:" + path)
                except SimulatedLostResponse:
                    matches = [s for s in inventory(self.adapter, parent) if s.name == parts[-1]]
                    if len(matches) != 1:
                        raise ConflictError("staged runtime create outcome unknown")
                    value = matches[0]
            else:
                value = matches[0]
            value = validate_scope(self.adapter, value.id, self.writer.root_id)
            if value.content != data or value.mime_type != expected_mime(path):
                raise ConflictError("existing staged runtime bytes differ; do not overwrite")
            mapping[path] = {"id": value.id, "sha256": value.sha256}
        manifest = self._raw_once(root, "source-manifest.json", "application/json", pretty_json(intent["manifest"]).encode(), intent["operation_id"] + ":manifest")
        return {"root_id": root, "files": mapping, "manifest_reference": manifest.id}

    @staticmethod
    def _validate_observation(phase: str, observed: dict, intent: dict) -> None:
        if not isinstance(observed, dict) or not observed.get("reference") or observed.get("instance_id") != intent["instance_id"] or observed.get("target_identity") != intent["target_identity"]:
            raise CapabilityError(f"{phase} lacks actual scoped host/validation observation")
        required = {
            "PREFLIGHT_VERIFIED": ("tools_checked", "ownership_checked", "pending_operations_checked", "backup_space_checked", "migration_path_checked"),
            "WRITERS_QUIESCED": ("tasks_paused", "writers_drained", "exclusive_updater", "intake_preserved"),
            "MIGRATION_VALIDATED": ("detached_snapshot_validated", "references_valid", "counts_reconciled", "customizations_preserved"),
            "HOST_BINDINGS_VERIFIED": ("private_skill_updated", "fresh_invocation_verified", "task_prompts_inspected", "no_duplicate_tasks"),
            "SMOKE_TESTED": ("schema_valid", "references_valid", "counts_reconciled", "raw_readbacks", "wiki_query", "archive_lookup"),
            "ACTIVATED": ("runtime_pointer_verified", "tasks_resumed", "intake_reconciled_once"),
            "COMPLETE": ("update_report_saved", "update_report_readback", "result_published"),
            "ROLLBACK_QUIESCED": ("tasks_paused", "writers_drained", "exclusive_updater", "intake_preserved"),
            "ROLLBACK_BINDINGS_VERIFIED": ("old_runtime_verified", "schema_compatible", "fresh_invocation_verified", "task_prompts_inspected", "runtime_pointer_verified"),
            "ROLLBACK_COMPLETE": ("tasks_resumed", "later_data_preserved", "rollback_report_saved", "rollback_report_readback"),
        }.get(phase, ())
        if any(observed.get(key) is not True for key in required):
            raise CapabilityError(f"{phase} missing verified checks: " + ", ".join(key for key in required if observed.get(key) is not True))
        if phase in {"WRITERS_QUIESCED", "HOST_BINDINGS_VERIFIED", "ACTIVATED"} and observed.get("task_ids") != intent["task_ids"]:
            raise CapabilityError("existing daily/weekly task identity must be preserved or explicitly reconciled")
        if phase == "HOST_BINDINGS_VERIFIED" and observed.get("skill_reference") != intent["skill_reference"]:
            raise CapabilityError("installed private skill identity differs from intended instance")
        if phase == "HOST_BINDINGS_VERIFIED":
            expected = {"instance_id": intent["instance_id"], "root_id": intent["root_id"],
                        "release_id": intent["target"]["version"], "manifest_sha256": intent["target"]["manifest_sha256"],
                        "config_file_id": intent["bases"]["config.yml"]["id"],
                        "map_file_id": intent["bases"]["installation/drive-map.json"]["id"]}
            bindings = observed.get("observed_bindings", {})
            if set(bindings) != {"skill", "daily", "weekly"}:
                raise CapabilityError("fresh skill and both task bindings require inspectable observations")
            for name, actual in bindings.items():
                if any(actual.get(key) != value for key, value in expected.items()) or not re.fullmatch(r"[a-f0-9]{64}", str(actual.get("content_sha256", ""))):
                    raise CapabilityError(f"observed {name} binding differs from pinned instance/runtime")
            if not observed.get("fresh_invocation_reference"):
                raise CapabilityError("installed update requires an actual fresh invocation reference")
        if phase == "MIGRATION_VALIDATED":
            expected_inputs = {path: _restore(value).sha256 for path, value in intent["bases"].items()}
            expected_outputs = {path: sha256_bytes(base64.b64decode(value)) for path, value in intent["replacements"].items()}
            expected_outputs.update({path: sha256_bytes(base64.b64decode(value["content"])) for path, value in intent["new_files"].items()})
            if observed.get("input_hashes") != expected_inputs or observed.get("output_hashes") != expected_outputs:
                raise CapabilityError("detached migration validation is not bound to exact input/output bytes")
        if phase.startswith("ROLLBACK_"):
            if observed.get("task_ids") != intent["task_ids"] or observed.get("runtime_release_id") != intent["from_release"]:
                raise CapabilityError("rollback host observation does not bind the prior runtime and existing tasks")


def rollback_plan(state: UpgradeState, *, prior_read_schemas: list[int], current_data_schema: int,
                  later_record_ids: list[str]) -> dict:
    compatible = current_data_schema in prior_read_schemas
    return {"schema_version": 2, "instance_id": state.instance_id, "operation_id": state.operation_id,
            "runtime_target": state.from_release, "status": "ready_for_verified_host_rebind" if compatible else "blocked_incompatible_schema",
            "preserve_record_ids": list(later_record_ids), "restore_data": False,
            "required": ["pause_and_drain", "read_current_data", "verify_old_runtime", "verify_host_bindings", "smoke_test"] if compatible else ["validated_reverse_migration_or_forward_repair"],
            "paused_until_verified": True}


@dataclass
class InstanceImage:
    """Legacy detached export value, never a live update executor."""
    instance_id: str
    runtime_release_id: str
    runtime_files: dict[str, bytes]
    data_files: dict[str, bytes]
    config: dict
    skill_binding_release: str
    schedule_binding_release: str
    paused: bool = False


def apply_upgrade(*args, **kwargs):
    raise CapabilityError("image-only upgrades cannot verify durable writes or host bindings; use Updater")


def rollback_runtime(*args, **kwargs):
    raise CapabilityError("image-only rollback cannot prove schema compatibility or host state; use rollback_plan and verified recovery")


def export_private_raw(image: InstanceImage) -> dict[str, object]:
    return copy.deepcopy({"instance_id": image.instance_id, "runtime_release_id": image.runtime_release_id,
                          "config": image.config, "runtime_files": image.runtime_files, "data_files": image.data_files})
