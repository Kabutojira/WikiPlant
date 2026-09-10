from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Iterable

from .config import validate_config
from .errors import CapabilityError, SimulatedLostResponse, ValidationError
from .fake_drive import FakeDrive
from .host import CapabilityProfile, FakeHost
from .manifest import manifest_bytes, verify_manifest
from .schedules import render_task_prompt, task_to_record
from .setup import SetupInput, setup_summary, topic_records
from .skillgen import SkillBinding, generate_skill
from .storage import FOLDER_MIME, expected_mime
from .util import pretty_json, sha256_bytes, sha256_text, slugify
from .yamlio import dumps as yaml_dumps, loads as yaml_loads
from .topics import Topic, TopicRegistry
from .authorization import validate_user_authorization
from .util import require_timestamp
from .calendar import write_calendar


class InstallPhase(IntEnum):
    DISCOVERED = 0
    CAPABILITIES_CHECKED = 1
    SETUP_READY = 2
    STORAGE_CREATED = 3
    RUNTIME_VERIFIED = 4
    SKILL_CANDIDATE_CREATED = 5
    AWAITING_HOST_INSTALL = 6
    SKILL_VERIFIED = 7
    SEEDED = 8
    SCHEDULES_VERIFIED = 9
    ACTIVE_AWAITING_FIRST_RUN = 10
    ACTIVE_VERIFIED = 11
    BLOCKED = 99


@dataclass
class InstallState:
    instance_id: str
    phase: str = InstallPhase.DISCOVERED.name
    last_completed_phase: str = InstallPhase.DISCOVERED.name
    blocked_reason: str | None = None
    root_id: str | None = None
    state_file_id: str | None = None
    config_file_id: str | None = None
    map_file_id: str | None = None
    skill_name: str | None = None
    skill_reference: str | None = None
    task_ids: dict[str, str] = field(default_factory=dict)
    initialization_completed_ids: list[str] = field(default_factory=list)
    initialization_reserved_ids: list[str] = field(default_factory=list)
    initialization_allowance_consumed: int = 0
    first_run_verified: bool = False
    source_identity: dict = field(default_factory=dict)
    setup_sha256: str = ""

    def completed(self, phase: InstallPhase) -> bool:
        if self.phase == InstallPhase.BLOCKED.name:
            return InstallPhase[self.last_completed_phase] >= phase
        return InstallPhase[self.phase] >= phase


class Installer:
    """Resumable installer orchestration against explicit Drive/host adapters."""

    def __init__(self, source_root: Path, drive: FakeDrive, host: FakeHost, parent_id: str):
        self.source_root = source_root
        self.drive = drive
        self.host = host
        self.parent_id = parent_id

    def _retry_create(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except SimulatedLostResponse:
            return fn(*args, **kwargs)

    def _derive_instance_id(self, setup: SetupInput) -> str:
        return "wp-" + sha256_text(f"{self.parent_id}\0{setup.instance_name}")[:16]

    def _load_or_create_state(self, setup: SetupInput, manifest: dict) -> InstallState:
        instance_id = self._derive_instance_id(setup)
        source_identity = {key: manifest[key] for key in ("repository", "release_id", "source_commit")}
        source_identity["manifest_sha256"] = sha256_bytes(manifest_bytes(manifest))
        setup_identity = asdict(setup)
        setup_identity.pop("topic_authorizations", None)
        setup_identity.pop("confirmed_at", None)
        setup_hash = sha256_text(pretty_json(setup_identity))
        root = self._retry_create(
            self.drive.create_folder,
            self.parent_id,
            f"WikiPlant-{slugify(setup.instance_name or 'instance')}",
            idempotency_key=f"{instance_id}:root",
        )
        installation = self._retry_create(
            self.drive.create_folder,
            root.id,
            "installation",
            idempotency_key=f"{instance_id}:folder:installation",
        )
        state_file = self._retry_create(
            self.drive.create_file,
            installation.id,
            "install-state.json",
            "application/json",
            b"{}\n",
            idempotency_key=f"{instance_id}:file:installation/install-state.json",
        )
        raw = self.drive.read_exact(state_file.id)
        data = json.loads(raw.content.decode("utf-8"))
        if data.get("instance_id"):
            state = InstallState(**data)
            if state.source_identity != source_identity or state.setup_sha256 != setup_hash:
                raise ValidationError("installation resume cannot change pinned source or approved setup; use explicit update/configure")
        else:
            state = InstallState(instance_id=instance_id, root_id=root.id, state_file_id=state_file.id,
                                 source_identity=source_identity, setup_sha256=setup_hash)
            self._save_state(state)
        if state.instance_id != instance_id or state.root_id != root.id:
            raise ValidationError("ambiguous installation identity")
        return state

    def _save_state(self, state: InstallState) -> None:
        if not state.state_file_id:
            return
        current = self.drive.read_exact(state.state_file_id)
        payload = pretty_json(asdict(state)).encode("utf-8")
        operation_id = f"{state.instance_id}:install-state:{sha256_bytes(payload)}"
        try:
            self.drive.replace_content(state.state_file_id, payload, expected_revision=current.revision, operation_id=operation_id)
        except SimulatedLostResponse:
            observed = self.drive.read_exact(state.state_file_id)
            if observed.content != payload:
                raise

    def _advance(self, state: InstallState, phase: InstallPhase) -> None:
        state.phase = phase.name
        state.last_completed_phase = phase.name
        state.blocked_reason = None
        self._save_state(state)

    def _block(self, state: InstallState, reason: str, last_completed: InstallPhase) -> InstallState:
        state.phase = InstallPhase.BLOCKED.name
        state.last_completed_phase = last_completed.name
        state.blocked_reason = reason
        self._save_state(state)
        return state

    def _folder(self, state: InstallState, parent: str, logical: str) -> str:
        result = self._retry_create(
            self.drive.create_folder,
            parent,
            logical.rsplit("/", 1)[-1],
            idempotency_key=f"{state.instance_id}:folder:{logical}",
        )
        return result.id

    def _file(self, state: InstallState, parent: str, logical: str, content: bytes, mime: str | None = None) -> str:
        name = logical.rsplit("/", 1)[-1]
        result = self._retry_create(
            self.drive.create_file,
            parent,
            name,
            mime or expected_mime(logical),
            content,
            idempotency_key=f"{state.instance_id}:file:{logical}",
        )
        observed = self.drive.read_exact(result.id)
        if not observed.complete or observed.content != content or observed.mime_type != (mime or expected_mime(logical)):
            raise ValidationError(f"create/readback mismatch for {logical}")
        return result.id

    def _provision(self, state: InstallState, setup: SetupInput, manifest: dict[str, Any]) -> dict[str, dict[str, str]]:
        root = state.root_id
        assert root
        folders: dict[str, str] = {"": root}
        folder_paths = [
            "installation", "runtime", f"runtime/{manifest['release_id']}", "data", "data/sources", "data/wiki",
            "data/wiki/entities", "data/wiki/concepts", "data/wiki/projects", "data/wiki/syntheses", "data/research",
            "data/monitoring", "data/reports", "data/state", "data/state/runs", "data/state/operations", "data/state/inbox",
            "data/state/deliveries", "data/state/maintenance", "data/state/calendar", "backups",
            "data/archive", "data/archive/topics", "data/archive/indexes", "data/state/scope-changes",
            "data/state/archive-operations", "data/state/updates",
        ]
        for logical in folder_paths:
            parent_path = logical.rsplit("/", 1)[0] if "/" in logical else ""
            folders[logical] = self._folder(state, folders[parent_path], logical)
        topics = topic_records(setup)
        require_timestamp(setup.confirmed_at, "setup confirmed_at")
        registry = TopicRegistry(state.instance_id, 1, [Topic(
            id=t["id"], label=t["name"], classification="user", user_anchor_ids=[t["id"]], parent_ids=[],
            direct_contribution="Explicit user interest supplied at setup", classification_reason="Approved initial tracking scope",
            added_at=setup.confirmed_at, reviewed_at=setup.confirmed_at, scope_revision=1, aliases=t["aliases"],
            authorization=setup.topic_authorizations[t["id"]], related_page_ids=t["related_page_ids"],
        ) for t in topics])
        config = {
            "schema_version": 2,
            "instance": {"id": state.instance_id, "name": setup.instance_name, "language": setup.language, "timezone": setup.timezone},
            "storage": {"provider": "google-drive", "root_folder_id": root},
            "runtime": {"release_id": manifest["release_id"], "source_commit": manifest["source_commit"], "manifest_sha256": sha256_bytes(manifest_bytes(manifest)), "upgrades": "explicit-user-request"},
            "skill": {"per_instance": True, "installed_reference": None, "routing_profile_revision": 1},
            "primary_topic_ids": [t["id"] for t in topics],
            "schedules": {"daily": {"local_time": setup.daily_time}, "weekly": {"weekday": setup.weekly_day, "local_time": setup.weekly_time}},
            "initialization": {"max_research_attempts": 5},
            "queue": {"normal_daily_attempts": 5, "urgent_daily_attempts_total": 10, "urgent_priority": 0, "max_attempts_per_item": 3},
            "expansion": {"child_priority_increment": 20, "max_children_per_research": 3, "preserve_expansion_priority": True},
            "main_topic_refresh": {"enabled": True, "outside_queue_budget": True, "max_search_queries_per_topic": 4, "max_source_fetches_per_topic": 8, "lookback_overlap_hours": 12},
            "exploration": {"allow_adjacent_topics": True},
            "topic_governance": {"max_active_adjacent_topics": 30, "max_active_peripheral_topics": 15,
                                 "peripheral_expiry": "next_weekly_maintenance", "archive_summary_target_words": [100, 200]},
            "queue_admission": {"max_active_automatic_items": 50, "max_new_automatic_roots_per_day": 5,
                                "revalidate_pending_after_days": 14, "automatic_candidate_deferral_days": 30},
            "adversarial_review": {"validation_lane_slot": 5, "max_queries_per_investigation": 2},
            "maintenance": {"max_semantic_pages_per_week": 30},
            "reports": {"delivery": "native-task-result", "upcoming_days": 7, "include_quiet_day_report": True},
            "sources": {"retention": "metadata-and-permitted-extracts", "retain_full_text": False},
        }
        validate_config(config, topic_registry=registry)
        scope = (
            f"# {setup.instance_name}\n\n## Purpose\n\n{setup.purpose}\n\n## Projects\n\n" +
            "\n".join(f"- {v}" for v in setup.projects) + "\n\n## Constraints\n\n" +
            "\n".join(f"- {v}" for v in setup.constraints) + "\n\n## Exclusions\n\n" +
            "\n".join(f"- {v}" for v in (setup.exclusions or [])) + "\n"
        )
        files: dict[str, dict[str, str]] = {}
        initial = {
            "config.yml": yaml_dumps(config).encode(),
            "data/SCOPE.md": scope.encode(),
            "data/TOPICS.md": registry.render().encode(),
            "data/research_queue.csv": b"priority,id,expansion_priority,kind,question,topic_id,related_page_ids,parent_ids,lineage_root_id,origin,origin_ref,created_at,not_before,due_at,status,attempts,priority_reason,urgency_reason,dedup_key,refresh_occurrence_id\n",
            "data/calendar.csv": write_calendar([]).encode(),
            "data/wiki/index.md": b"# Wiki index\n\nNo pages have been created yet.\n",
            "data/wiki/log.md": b"# Wiki change log\n",
            "installation/setup-summary.md": setup_summary(setup).encode(),
            "installation/capability-profile.json": pretty_json(asdict(self.host.capabilities)).encode(),
        }
        for logical, content in initial.items():
            parent_path = logical.rsplit("/", 1)[0] if "/" in logical else ""
            file_id = self._file(state, folders[parent_path], logical, content)
            files[logical] = {"id": file_id, "mime_type": expected_mime(logical)}
        state.config_file_id = files["config.yml"]["id"]
        instance_record = {
            "schema_version": 1, "instance_id": state.instance_id, "root_folder_id": root,
            "config_file_id": state.config_file_id, "drive_map_file_id": None,
            "runtime_release_id": manifest["release_id"], "source_commit": manifest["source_commit"],
            "created_by": "wikiplant-repository-bootstrap",
            "source_repository": manifest.get("repository", ""),
        }
        instance_id = self._file(state, root, "INSTANCE.json", pretty_json(instance_record).encode())
        files["INSTANCE.json"] = {"id": instance_id, "mime_type": "application/json"}
        mapping = {"schema_version": 1, "instance_id": state.instance_id, "root_id": root, "files": files, "folders": folders}
        map_id = self._file(state, folders["installation"], "installation/drive-map.json", pretty_json(mapping).encode())
        state.map_file_id = map_id
        files["installation/drive-map.json"] = {"id": map_id, "mime_type": "application/json"}
        instance_record["drive_map_file_id"] = map_id
        current = self.drive.read_exact(instance_id)
        self.drive.replace_content(instance_id, pretty_json(instance_record).encode(), expected_revision=current.revision, operation_id=f"{state.instance_id}:bind-instance")
        current_map = self.drive.read_exact(map_id)
        self.drive.replace_content(map_id, pretty_json(mapping).encode(), expected_revision=current_map.revision, operation_id=f"{state.instance_id}:bind-map")
        return mapping

    def _read_map(self, state: InstallState) -> dict[str, Any]:
        assert state.map_file_id
        return json.loads(self.drive.read_exact(state.map_file_id).content.decode())

    def _replace_payload(self, file_id: str, payload: bytes, operation_id: str) -> None:
        current = self.drive.read_exact(file_id)
        try:
            self.drive.replace_content(file_id, payload, expected_revision=current.revision, operation_id=operation_id)
        except SimulatedLostResponse:
            if self.drive.read_exact(file_id).content != payload:
                raise

    def _update_map_file(self, state: InstallState, mapping: dict[str, Any], additions: dict[str, dict[str, str]]) -> None:
        mapping["files"].update(additions)
        assert state.map_file_id
        self._replace_payload(state.map_file_id, pretty_json(mapping).encode(), f"{state.instance_id}:map:{sha256_text(pretty_json(mapping))}")

    def _copy_runtime(self, state: InstallState, manifest: dict[str, Any], mapping: dict[str, Any]) -> None:
        release_folder = mapping["folders"][f"runtime/{manifest['release_id']}"]
        runtime_folders: dict[str, str] = {"": release_folder}
        for item in manifest["files"]:
            relative = item["path"]
            parent_parts = relative.split("/")[:-1]
            current_path = ""
            parent_id = release_folder
            for part in parent_parts:
                current_path = f"{current_path}/{part}".strip("/")
                if current_path not in runtime_folders:
                    runtime_folders[current_path] = self._folder(state, parent_id, f"runtime/{manifest['release_id']}/{current_path}")
                parent_id = runtime_folders[current_path]
            content = (self.source_root / relative).read_bytes()
            logical = f"runtime/{manifest['release_id']}/{relative}"
            self._file(state, parent_id, logical, content)
        self._file(state, release_folder, f"runtime/{manifest['release_id']}/source-manifest.json", manifest_bytes(manifest), "application/json")

    def _binding(self, state: InstallState, manifest: dict[str, Any]) -> SkillBinding:
        assert state.root_id and state.config_file_id and state.map_file_id
        return SkillBinding(state.instance_id, state.root_id, state.config_file_id, state.map_file_id, manifest["release_id"], sha256_bytes(manifest_bytes(manifest)))

    def run(
        self,
        setup: SetupInput,
        manifest: dict[str, Any],
        resolved_commit: str,
        *,
        seed_results: Iterable[dict[str, Any]] = (),
        verify_first_run: bool = False,
        stop_after: InstallPhase | None = None,
    ) -> InstallState:
        setup.validate_complete()
        for topic in topic_records(setup):
            grant = setup.topic_authorizations.get(topic["id"], {})
            validate_user_authorization(grant, instance_id=self._derive_instance_id(setup), operation="track", target=topic["id"])
        require_timestamp(setup.confirmed_at, "setup confirmed_at")
        if setup.drive_parent_id != self.parent_id:
            raise ValidationError("approved Drive destination does not match installer parent")
        verify_manifest(self.source_root, manifest, resolved_commit=resolved_commit)
        # Sharing and capabilities are mutable external state, never a reusable
        # checkpoint. Recheck BEFORE writing even an installation record.
        fresh_state = InstallState(instance_id=self._derive_instance_id(setup))
        if not self.host.capabilities.storage_ready():
            return self._block(fresh_state, "Google Drive raw create/full-read/content-update/pagination capabilities are required", InstallPhase.DISCOVERED)
        ancestor = self.parent_id
        visited = set()
        while ancestor:
            if ancestor in visited:
                raise ValidationError("Drive destination ancestry cycle")
            visited.add(ancestor)
            snapshot = self.drive.read_exact(ancestor)
            if not snapshot.complete or not snapshot.within_scope:
                return self._block(fresh_state, "destination scope/sharing cannot be verified", InstallPhase.DISCOVERED)
            if ancestor in self.drive.public_parents:
                return self._block(fresh_state, "approved Drive destination inherits broad/public sharing", InstallPhase.DISCOVERED)
            ancestor = snapshot.parent_id
        state = self._load_or_create_state(setup, manifest)
        if state.phase == InstallPhase.BLOCKED.name:
            state.phase = state.last_completed_phase
            state.blocked_reason = None
        if stop_after == InstallPhase.DISCOVERED:
            return state
        if not state.completed(InstallPhase.CAPABILITIES_CHECKED):
            if not self.host.capabilities.storage_ready():
                return self._block(state, "Google Drive raw create/full-read/content-update/pagination capabilities are required", InstallPhase.DISCOVERED)
            self._advance(state, InstallPhase.CAPABILITIES_CHECKED)
        if stop_after == InstallPhase.CAPABILITIES_CHECKED:
            return state
        if not state.completed(InstallPhase.SETUP_READY):
            self._advance(state, InstallPhase.SETUP_READY)
        if stop_after == InstallPhase.SETUP_READY:
            return state
        if not state.completed(InstallPhase.STORAGE_CREATED):
            mapping = self._provision(state, setup, manifest)
            self._advance(state, InstallPhase.STORAGE_CREATED)
        else:
            mapping = self._read_map(state)
        if stop_after == InstallPhase.STORAGE_CREATED:
            return state
        if not state.completed(InstallPhase.RUNTIME_VERIFIED):
            self._copy_runtime(state, manifest, mapping)
            self._advance(state, InstallPhase.RUNTIME_VERIFIED)
        if stop_after == InstallPhase.RUNTIME_VERIFIED:
            return state
        binding = self._binding(state, manifest)
        generated = generate_skill(setup.instance_name or "WikiPlant", binding, topic_records(setup))
        installation_folder = mapping["folders"]["installation"]
        if not state.completed(InstallPhase.SKILL_CANDIDATE_CREATED):
            skill_folder = self._folder(state, installation_folder, "installation/generated-skill")
            agents_folder = self._folder(state, skill_folder, "installation/generated-skill/agents")
            skill_file_id = self._file(state, skill_folder, "installation/generated-skill/SKILL.md", generated.skill_md.encode())
            ui_file_id = self._file(state, agents_folder, "installation/generated-skill/agents/openai.yaml", generated.openai_yaml.encode(), "application/yaml")
            self._update_map_file(state, mapping, {
                "installation/generated-skill/SKILL.md": {"id": skill_file_id, "mime_type": "text/markdown"},
                "installation/generated-skill/agents/openai.yaml": {"id": ui_file_id, "mime_type": "application/yaml"},
            })
            state.skill_name = generated.name
            self._advance(state, InstallPhase.SKILL_CANDIDATE_CREATED)
        if stop_after == InstallPhase.SKILL_CANDIDATE_CREATED:
            return state
        if not state.skill_reference:
            reference = self.host.install_skill(generated.name, generated.skill_md)
            if reference is None:
                state.phase = InstallPhase.AWAITING_HOST_INSTALL.name
                state.last_completed_phase = InstallPhase.SKILL_CANDIDATE_CREATED.name
                state.blocked_reason = "complete the host's private skill installation control, then continue installation"
                self._save_state(state)
                return state
            state.skill_reference = reference
            skill_binding_id = self._file(state, installation_folder, "installation/skill-binding.json", pretty_json({
                "schema_version": 1, "instance_id": state.instance_id, "skill_name": generated.name,
                "installed_reference": reference, "routing_profile_revision": 1, "status": "verified",
            }).encode(), "application/json")
            self._update_map_file(state, mapping, {"installation/skill-binding.json": {"id": skill_binding_id, "mime_type": "application/json"}})
            assert state.config_file_id
            config_snapshot = self.drive.read_exact(state.config_file_id)
            config = yaml_loads(config_snapshot.content.decode())
            config["skill"]["installed_reference"] = reference
            config_payload = yaml_dumps(config).encode()
            self._replace_payload(state.config_file_id, config_payload, f"{state.instance_id}:config:skill-install")
            self._advance(state, InstallPhase.SKILL_VERIFIED)
        if stop_after == InstallPhase.SKILL_VERIFIED:
            return state
        if not state.completed(InstallPhase.SEEDED):
            seed_list = list(seed_results)
            seed_ids = [str(result.get("id") or f"init-{index}") for index, result in enumerate(seed_list, 1)]
            if len(seed_ids) != len(set(seed_ids)):
                raise ValidationError("duplicate initial investigation identity")
            if len(seed_list) > 5 or len(set(state.initialization_reserved_ids) | set(state.initialization_completed_ids) | set(seed_ids)) > 5:
                raise ValidationError("initialization may complete at most five investigations")
            research_folder = mapping["folders"]["data/research"]
            for index, result in enumerate(seed_list, 1):
                rid = str(result.get("id") or f"init-{index}")
                if rid in state.initialization_completed_ids:
                    continue
                if rid not in state.initialization_reserved_ids:
                    state.initialization_reserved_ids.append(rid)
                    state.initialization_allowance_consumed += 1
                    self._save_state(state)
                payload = dict(result)
                payload.update({"id": rid, "origin": "initialization", "status": "complete"})
                self._file(state, research_folder, f"data/research/{rid}.json", pretty_json(payload).encode(), "application/json")
                state.initialization_completed_ids.append(rid)
                self._save_state(state)
            self._advance(state, InstallPhase.SEEDED)
        if stop_after == InstallPhase.SEEDED:
            return state
        if not state.completed(InstallPhase.SCHEDULES_VERIFIED):
            daily_template = (self.source_root / "cron/daily.prompt.md.template").read_text()
            weekly_template = (self.source_root / "cron/weekly.prompt.md.template").read_text()
            scope_summary = ", ".join(t["name"] for t in setup.primary_topics)
            prompts = {
                "daily": render_task_prompt(daily_template, operation="daily", skill_name=generated.name, binding=binding, scope_summary=scope_summary),
                "weekly": render_task_prompt(weekly_template, operation="weekly", skill_name=generated.name, binding=binding, scope_summary=scope_summary),
            }
            schedules = {"daily": f"daily {setup.daily_time}", "weekly": f"weekly {setup.weekly_day} {setup.weekly_time}"}
            plan_id = self._file(state, installation_folder, "installation/task-plans.json", pretty_json({
                kind: {"title": f"{setup.instance_name} WikiPlant {kind}", "schedule": schedules[kind], "timezone": setup.timezone, "prompt": prompts[kind]}
                for kind in ("daily", "weekly")
            }).encode(), "application/json")
            self._update_map_file(state, mapping, {"installation/task-plans.json": {"id": plan_id, "mime_type": "application/json"}})
            for kind in ("daily", "weekly"):
                task = self.host.create_task(f"{state.instance_id}:{kind}", f"{setup.instance_name} WikiPlant {kind}", prompts[kind], schedules[kind], setup.timezone)
                if task is None:
                    return self._block(state, "save and inspect the prepared native daily and weekly tasks, then continue installation", InstallPhase.SEEDED)
                state.task_ids[kind] = task.id
            self._file(state, installation_folder, "installation/schedule-bindings.json", pretty_json({k: task_to_record(self.host.tasks[f"{state.instance_id}:{k}"]) for k in state.task_ids}).encode(), "application/json")
            self._advance(state, InstallPhase.SCHEDULES_VERIFIED)
        if not state.completed(InstallPhase.ACTIVE_AWAITING_FIRST_RUN):
            self._advance(state, InstallPhase.ACTIVE_AWAITING_FIRST_RUN)
        if verify_first_run:
            state.first_run_verified = True
            self._advance(state, InstallPhase.ACTIVE_VERIFIED)
        return state
