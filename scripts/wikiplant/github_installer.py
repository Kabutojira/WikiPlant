from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .authorization import validate_user_authorization
from .calendar import write_calendar
from .config import validate_config
from .errors import CapabilityError, ConflictError, SimulatedLostResponse, ValidationError
from .github_storage import GitHubLimits, GitHubStorageAdapter
from .host import FakeHost
from .instance import validate_instance_v2
from .installer import InstallPhase
from .manifest import manifest_bytes, verify_manifest
from .schedules import render_task_prompt, task_to_record
from .setup import SetupInput, setup_summary, topic_records
from .skillgen import SkillBinding, generate_skill
from .storage import expected_mime
from .storage_contract import StorageBinding, StorageTransaction
from .topics import Topic, TopicRegistry
from .util import pretty_json, require_timestamp, sha256_bytes, sha256_text
from .yamlio import dumps as yaml_dumps, loads as yaml_loads


DEFAULT_GITHUB_LIMITS = {
    "max_file_bytes": 512_000,
    "max_transaction_bytes": 8_000_000,
    "max_repository_bytes": 500_000_000,
    "max_paths_per_transaction": 200,
}


@dataclass
class GitHubInstallState:
    instance_id: str
    phase: str = InstallPhase.DISCOVERED.name
    last_completed_phase: str = InstallPhase.DISCOVERED.name
    blocked_reason: str | None = None
    repository_id: str = ""
    canonical_ref: str = "refs/heads/wikiplant-data"
    first_verified_commit: str = ""
    skill_name: str | None = None
    skill_reference: str | None = None
    task_ids: dict[str, str] = field(default_factory=dict)
    initialization_completed_ids: list[str] = field(default_factory=list)
    initialization_reserved_ids: list[str] = field(default_factory=list)
    initialization_allowance_consumed: int = 0
    first_run_verified: bool = False
    source_identity: dict[str, str] = field(default_factory=dict)
    setup_sha256: str = ""

    def completed(self, phase: InstallPhase) -> bool:
        if self.phase == InstallPhase.BLOCKED.name:
            return InstallPhase[self.last_completed_phase] >= phase
        return InstallPhase[self.phase] >= phase


class GitHubInstaller:
    """Resumable, network-free orchestration for a host-supplied GitHub bridge.

    The ``api`` object represents observed provider actions. This helper never
    obtains credentials or performs network calls itself.
    """

    state_path = "installation/install-state.json"

    def __init__(
        self,
        source_root: Path,
        api,
        host: FakeHost,
        *,
        repository_id: str,
        app_installation_id: str,
        canonical_ref: str = "refs/heads/wikiplant-data",
        ancestry_anchor: str | None = None,
    ) -> None:
        if not app_installation_id:
            raise ValidationError("GitHub installation requires an observed app installation identity")
        self.source_root = source_root
        self.api = api
        self.host = host
        self.repository_id = repository_id
        self.app_installation_id = app_installation_id
        self.canonical_ref = canonical_ref
        self.ancestry_anchor = ancestry_anchor

    def derive_instance_id(self, setup: SetupInput) -> str:
        return "wp-" + sha256_text(f"github\0{self.repository_id}\0{setup.instance_name}")[:16]

    @staticmethod
    def _repository_from_url(url: str) -> str:
        match = re.fullmatch(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?", url)
        if not match:
            raise ValidationError("GitHub destination must be a normal github.com repository link")
        return f"{match.group(1)}/{match.group(2)}"

    def _limits(self) -> GitHubLimits:
        return GitHubLimits(
            max_file_bytes=DEFAULT_GITHUB_LIMITS["max_file_bytes"],
            max_transaction_bytes=DEFAULT_GITHUB_LIMITS["max_transaction_bytes"],
            max_repository_bytes=DEFAULT_GITHUB_LIMITS["max_repository_bytes"],
            max_paths_per_transaction=DEFAULT_GITHUB_LIMITS["max_paths_per_transaction"],
            max_inventory_paths=20_000,
        )

    def _adapter(self, instance_id: str, repository: str) -> GitHubStorageAdapter:
        if self.ancestry_anchor is None:
            raise ValidationError("GitHub installer lacks a trusted repository ancestry anchor")
        return GitHubStorageAdapter(
            self.api,
            StorageBinding("github", self.repository_id, "", self.canonical_ref),
            instance_id=instance_id,
            limits=self._limits(),
            expected_repository=repository,
            ancestry_anchor=self.ancestry_anchor,
        )

    def _source_identity(self, manifest: dict[str, Any]) -> dict[str, str]:
        identity = {key: str(manifest[key]) for key in ("repository", "release_id", "source_commit")}
        identity["manifest_sha256"] = sha256_bytes(manifest_bytes(manifest))
        return identity

    @staticmethod
    def _setup_hash(setup: SetupInput) -> str:
        value = asdict(setup)
        value.pop("topic_authorizations", None)
        value.pop("confirmed_at", None)
        return sha256_text(pretty_json({"schema_version": 1, "setup": value}))

    @staticmethod
    def _state_bytes(state: GitHubInstallState) -> bytes:
        return pretty_json(asdict(state)).encode()

    def _read_state(self, adapter: GitHubStorageAdapter) -> GitHubInstallState:
        try:
            value = json.loads(adapter.read_exact(self.state_path).content)
            state = GitHubInstallState(**value)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise ConflictError("GitHub installation state is malformed") from exc
        if (
            state.instance_id != adapter.instance_id
            or state.repository_id != self.repository_id
            or state.canonical_ref != self.canonical_ref
            or state.first_verified_commit != self.ancestry_anchor
        ):
            raise ConflictError("GitHub installation state binding mismatch")
        return state

    @staticmethod
    def _topics(instance_id: str, setup: SetupInput) -> tuple[list[dict[str, Any]], TopicRegistry]:
        records = topic_records(setup)
        require_timestamp(setup.confirmed_at, "setup confirmed_at")
        registry = TopicRegistry(instance_id, 1, [Topic(
            id=value["id"], label=value["name"], classification="user",
            user_anchor_ids=[value["id"]], parent_ids=[],
            direct_contribution="Explicit user interest supplied at setup",
            classification_reason="Approved initial tracking scope",
            added_at=setup.confirmed_at, reviewed_at=setup.confirmed_at,
            scope_revision=1, aliases=value["aliases"],
            authorization=setup.topic_authorizations[value["id"]],
            related_page_ids=value["related_page_ids"],
        ) for value in records])
        return records, registry

    def _config(self, state: GitHubInstallState, setup: SetupInput, manifest: dict[str, Any], repository: str) -> dict[str, Any]:
        config = {
            "schema_version": 2,
            "instance": {"id": state.instance_id, "name": setup.instance_name, "language": setup.language, "timezone": setup.timezone},
            "storage": {
                "provider": "github", "repository_id": self.repository_id,
                "repository": repository, "canonical_ref": self.canonical_ref,
                "root_prefix": "", "consistency_mode": "git-fast-forward",
                "limits": dict(DEFAULT_GITHUB_LIMITS),
            },
            "runtime": {"release_id": manifest["release_id"], "source_commit": manifest["source_commit"],
                        "manifest_sha256": sha256_bytes(manifest_bytes(manifest)), "upgrades": "explicit-user-request"},
            "skill": {"per_instance": True, "installed_reference": None, "routing_profile_revision": 1},
            "primary_topic_ids": [value["id"] for value in topic_records(setup)],
            "schedules": {"daily": {"local_time": setup.daily_time}, "weekly": {"weekday": setup.weekly_day, "local_time": setup.weekly_time}},
            "initialization": {"max_research_attempts": 5},
            "queue": {"normal_daily_attempts": 5, "urgent_daily_attempts_total": 10, "urgent_priority": 0, "max_attempts_per_item": 3},
            "expansion": {"child_priority_increment": 20, "max_children_per_research": 3, "preserve_expansion_priority": True},
            "main_topic_refresh": {"enabled": True, "outside_queue_budget": True, "max_search_queries_per_topic": 4,
                                   "max_source_fetches_per_topic": 8, "lookback_overlap_hours": 12},
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
        return config

    def _binding(self, state: GitHubInstallState, manifest: dict[str, Any], repository: str) -> SkillBinding:
        return SkillBinding.github(
            instance_id=state.instance_id, repository_id=self.repository_id,
            repository=repository, canonical_ref=self.canonical_ref,
            release_id=manifest["release_id"],
            runtime_manifest_sha256=sha256_bytes(manifest_bytes(manifest)),
            first_verified_commit=self.ancestry_anchor or "",
        )

    def _initial_files(
        self,
        state: GitHubInstallState,
        setup: SetupInput,
        manifest: dict[str, Any],
        repository: str,
        first_verified_commit: str,
    ) -> dict[str, bytes]:
        topics, registry = self._topics(state.instance_id, setup)
        config = self._config(state, setup, manifest, repository)
        validate_config(config, topic_registry=registry)
        binding = self._binding(state, manifest, repository)
        generated = generate_skill(setup.instance_name or "WikiPlant", binding, topics)
        state.skill_name = generated.name
        state.phase = InstallPhase.SKILL_CANDIDATE_CREATED.name
        state.last_completed_phase = InstallPhase.SKILL_CANDIDATE_CREATED.name
        scope = (
            f"# {setup.instance_name}\n\n## Purpose\n\n{setup.purpose}\n\n## Projects\n\n"
            + "\n".join(f"- {value}" for value in setup.projects)
            + "\n\n## Constraints\n\n" + "\n".join(f"- {value}" for value in setup.constraints)
            + "\n\n## Exclusions\n\n" + "\n".join(f"- {value}" for value in (setup.exclusions or [])) + "\n"
        )
        instance_record = {
                "schema_version": 2, "instance_id": state.instance_id,
                "storage": {
                    "provider": "github", "repository_id": self.repository_id,
                    "repository": repository, "canonical_ref": self.canonical_ref,
                    "root_prefix": "", "repository_visibility": "private",
                    "app_installation_id": self.app_installation_id,
                    "capability_profile_path": "installation/capability-profile.json",
                    "first_verified_commit": first_verified_commit,
                },
                "runtime_release_id": manifest["release_id"], "source_commit": manifest["source_commit"],
                "created_by": "wikiplant-repository-bootstrap", "source_repository": manifest.get("repository", ""),
        }
        validate_instance_v2(instance_record, expected_instance_id=state.instance_id)
        files = {
            "INSTANCE.json": pretty_json(instance_record).encode(),
            "config.yml": yaml_dumps(config).encode(),
            self.state_path: self._state_bytes(state),
            "installation/capability-profile.json": pretty_json(asdict(self.host.capabilities)).encode(),
            "installation/setup-summary.md": setup_summary(setup).encode(),
            "installation/generated-skill/SKILL.md": generated.skill_md.encode(),
            "installation/generated-skill/agents/openai.yaml": generated.openai_yaml.encode(),
            "data/SCOPE.md": scope.encode(),
            "data/TOPICS.md": registry.render().encode(),
            "data/research_queue.csv": b"priority,id,expansion_priority,kind,question,topic_id,related_page_ids,parent_ids,lineage_root_id,origin,origin_ref,created_at,not_before,due_at,status,attempts,priority_reason,urgency_reason,dedup_key,refresh_occurrence_id\n",
            "data/calendar.csv": write_calendar([]).encode(),
            "data/wiki/index.md": b"# Wiki index\n\nNo pages have been created yet.\n",
            "data/wiki/log.md": b"# Wiki change log\n",
            f"runtime/{manifest['release_id']}/source-manifest.json": manifest_bytes(manifest),
        }
        for entry in manifest["files"]:
            logical = f"runtime/{manifest['release_id']}/{entry['path']}"
            files[logical] = (self.source_root / entry["path"]).read_bytes()
        return files

    def _commit_files(
        self,
        adapter: GitHubStorageAdapter,
        state: GitHubInstallState,
        writes: dict[str, bytes],
        *,
        operation_id: str,
        intent: dict[str, Any],
    ) -> None:
        base = adapter.current_generation()
        inventory = {item.logical_path: item for item in adapter.inventory(generation=base)}
        expected = {path: inventory[path].content_hash if path in inventory else None for path in writes}
        transaction = StorageTransaction(
            instance_id=state.instance_id, operation_id=operation_id,
            base_generation=base, original_intent=intent, writes=writes,
            deletes=(), expected_input_hashes=expected,
        )
        adapter.commit_transaction(transaction)

    def _save_state(self, adapter: GitHubStorageAdapter, state: GitHubInstallState, operation_id: str) -> None:
        self._commit_files(adapter, state, {self.state_path: self._state_bytes(state)},
                           operation_id=operation_id, intent={"kind": "install-state", "phase": state.phase})

    def _advance(self, adapter: GitHubStorageAdapter, state: GitHubInstallState, phase: InstallPhase) -> None:
        state.phase = phase.name
        state.last_completed_phase = phase.name
        state.blocked_reason = None
        self._save_state(adapter, state, f"{state.instance_id}:install-state:{phase.name}")

    def _block(self, adapter: GitHubStorageAdapter | None, state: GitHubInstallState, reason: str) -> GitHubInstallState:
        state.phase = InstallPhase.BLOCKED.name
        state.blocked_reason = reason
        if adapter is not None:
            try:
                self._save_state(adapter, state, f"{state.instance_id}:install-blocked:{sha256_text(reason)}")
            except (CapabilityError, ConflictError, ValidationError):
                pass
        return state

    def run(
        self,
        setup: SetupInput,
        manifest: dict[str, Any],
        resolved_commit: str,
        *,
        seed_results: Iterable[dict[str, Any]] = (),
        first_run_receipt: Mapping[str, Any] | None = None,
    ) -> GitHubInstallState:
        setup.validate_complete()
        if setup.storage_provider != "github":
            raise ValidationError("GitHubInstaller requires storage_provider=github")
        seeds = list(seed_results)
        if any(not isinstance(value, dict) for value in seeds):
            raise ValidationError("initialization results must be mappings")
        seed_ids = [str(value.get("id") or f"init-{index}") for index, value in enumerate(seeds, 1)]
        if (
            len(seeds) > 5
            or len(seed_ids) != len(set(seed_ids))
            or any(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", value) is None for value in seed_ids)
        ):
            raise ValidationError("initialization may reserve at most five unique investigations")
        verify_manifest(self.source_root, manifest, resolved_commit=resolved_commit)
        instance_id = self.derive_instance_id(setup)
        source_identity = self._source_identity(manifest)
        setup_hash = self._setup_hash(setup)
        transient = GitHubInstallState(
            instance_id=instance_id, repository_id=self.repository_id,
            canonical_ref=self.canonical_ref, source_identity=source_identity,
            setup_sha256=setup_hash,
        )
        missing = self.host.capabilities.missing_storage_capabilities("github")
        if missing:
            return self._block(None, transient, "BLOCKED_GITHUB_WRITE_CAPABILITY: " + ", ".join(missing))
        repository = self.api.get_repository(self.repository_id)
        requested_repository = self._repository_from_url(setup.github_repository_url or "")
        if repository.full_name.casefold() != requested_repository.casefold():
            raise ValidationError("GitHub repository URL does not match immutable repository binding")
        if not repository.private or repository.archived or getattr(repository, "fork", False):
            raise CapabilityError("GitHub destination must be a dedicated private, active, non-fork repository")
        try:
            canonical_head = self.api.get_ref(self.repository_id, self.canonical_ref)
        except ValidationError:
            default_ref = f"refs/heads/{repository.default_branch}"
            canonical_head = self.api.get_ref(self.repository_id, default_ref)
            default_commit = self.api.get_commit(self.repository_id, canonical_head)
            default_tree, truncated = self.api.get_tree(
                self.repository_id, default_commit.tree_sha, recursive=True
            )
            if truncated or default_tree.entries:
                raise ConflictError("GitHub canonical ref is absent and the default branch is not empty")
            try:
                self.api.create_ref(self.repository_id, self.canonical_ref, canonical_head)
            except SimulatedLostResponse:
                try:
                    observed_ref = self.api.get_ref(self.repository_id, self.canonical_ref)
                except ValidationError as exc:
                    raise ConflictError("GitHub canonical-ref creation outcome is unknown") from exc
                if observed_ref != canonical_head:
                    raise ConflictError("GitHub canonical ref was created at an unexpected generation")
        if self.ancestry_anchor is None:
            current_commit = self.api.get_commit(self.repository_id, canonical_head)
            current_tree, truncated = self.api.get_tree(
                self.repository_id, current_commit.tree_sha, recursive=True
            )
            if truncated or current_tree.entries:
                raise ConflictError("resuming a nonempty GitHub instance requires its trusted ancestry anchor")
            self.ancestry_anchor = canonical_head
        if not self.api.is_ancestor(self.repository_id, self.ancestry_anchor, canonical_head):
            raise ConflictError("GitHub canonical ref no longer descends from the trusted ancestry anchor")
        transient.first_verified_commit = self.ancestry_anchor
        adapter = self._adapter(instance_id, repository.full_name)
        try:
            state = self._read_state(adapter)
        except ValidationError:
            initial_head = adapter.current_generation()
            files = self._initial_files(transient, setup, manifest, repository.full_name, initial_head)
            adapter.bootstrap(files, expected_generation=initial_head, operation_id=f"{instance_id}:bootstrap")
            state = self._read_state(adapter)
        if state.source_identity != source_identity or state.setup_sha256 != setup_hash:
            raise ConflictError("installation resume cannot change pinned source or approved setup")
        if state.phase == InstallPhase.BLOCKED.name:
            state.phase = state.last_completed_phase
            state.blocked_reason = None
        topics, _ = self._topics(instance_id, setup)
        binding = self._binding(state, manifest, repository.full_name)
        generated = generate_skill(setup.instance_name or "WikiPlant", binding, topics)

        if not state.completed(InstallPhase.SKILL_VERIFIED):
            reference = self.host.install_skill(generated.name, generated.skill_md)
            if reference is None:
                state.phase = InstallPhase.AWAITING_HOST_INSTALL.name
                state.blocked_reason = "complete the host's private skill installation control, then continue installation"
                self._save_state(adapter, state, f"{instance_id}:awaiting-skill")
                return state
            state.skill_reference = reference
            config = yaml_loads(adapter.read_exact("config.yml").content.decode())
            config["skill"]["installed_reference"] = reference
            state.phase = InstallPhase.SKILL_VERIFIED.name
            state.last_completed_phase = InstallPhase.SKILL_VERIFIED.name
            self._commit_files(adapter, state, {
                "config.yml": yaml_dumps(config).encode(),
                "installation/skill-binding.json": pretty_json({
                    "schema_version": 2, "instance_id": instance_id,
                    "storage_provider": "github", "repository_id": self.repository_id,
                    "canonical_ref": self.canonical_ref, "skill_name": generated.name,
                    "installed_reference": reference, "routing_profile_revision": 1,
                    "status": "verified",
                }).encode(),
                self.state_path: self._state_bytes(state),
            }, operation_id=f"{instance_id}:skill-verified", intent={"kind": "skill-install", "skill_name": generated.name})

        if not state.completed(InstallPhase.SEEDED):
            writes: dict[str, bytes] = {}
            for index, result in enumerate(seeds, 1):
                research_id = str(result.get("id") or f"init-{index}")
                if research_id in state.initialization_completed_ids:
                    continue
                if research_id not in state.initialization_reserved_ids:
                    if len(set(state.initialization_reserved_ids) | set(state.initialization_completed_ids) | {research_id}) > 5:
                        raise ValidationError("initialization allowance is already consumed")
                    state.initialization_reserved_ids.append(research_id)
                    state.initialization_allowance_consumed += 1
                payload = dict(result)
                payload.update({"id": research_id, "origin": "initialization", "status": "complete"})
                writes[f"data/research/{research_id}.json"] = pretty_json(payload).encode()
                state.initialization_completed_ids.append(research_id)
            state.phase = InstallPhase.SEEDED.name
            state.last_completed_phase = InstallPhase.SEEDED.name
            writes[self.state_path] = self._state_bytes(state)
            self._commit_files(adapter, state, writes, operation_id=f"{instance_id}:seed",
                               intent={"kind": "initial-seed", "research_ids": seed_ids})

        if not state.completed(InstallPhase.SCHEDULES_VERIFIED):
            daily_template = (self.source_root / "cron/daily.prompt.md.template").read_text()
            weekly_template = (self.source_root / "cron/weekly.prompt.md.template").read_text()
            scope_summary = ", ".join(value["name"] for value in topics)
            prompts = {
                "daily": render_task_prompt(daily_template, operation="daily", skill_name=generated.name, binding=binding, scope_summary=scope_summary),
                "weekly": render_task_prompt(weekly_template, operation="weekly", skill_name=generated.name, binding=binding, scope_summary=scope_summary),
            }
            schedules = {"daily": f"daily {setup.daily_time}", "weekly": f"weekly {setup.weekly_day} {setup.weekly_time}"}
            tasks = {}
            for kind in ("daily", "weekly"):
                task = self.host.create_task(f"{instance_id}:{kind}", f"{setup.instance_name} WikiPlant {kind}",
                                             prompts[kind], schedules[kind], setup.timezone)
                if task is None:
                    return self._block(adapter, state, "save and inspect the prepared native daily and weekly tasks, then continue installation")
                tasks[kind] = task
                state.task_ids[kind] = task.id
            state.phase = InstallPhase.SCHEDULES_VERIFIED.name
            state.last_completed_phase = InstallPhase.SCHEDULES_VERIFIED.name
            self._commit_files(adapter, state, {
                "installation/task-plans.json": pretty_json({kind: {
                    "title": f"{setup.instance_name} WikiPlant {kind}", "schedule": schedules[kind],
                    "timezone": setup.timezone, "prompt": prompts[kind],
                } for kind in tasks}).encode(),
                "installation/schedule-bindings.json": pretty_json({kind: task_to_record(task) for kind, task in tasks.items()}).encode(),
                self.state_path: self._state_bytes(state),
            }, operation_id=f"{instance_id}:schedules-verified", intent={"kind": "schedule-bindings", "task_ids": state.task_ids})

        if not state.completed(InstallPhase.ACTIVE_AWAITING_FIRST_RUN):
            self._advance(adapter, state, InstallPhase.ACTIVE_AWAITING_FIRST_RUN)
        if first_run_receipt is not None and not state.first_run_verified:
            expected = {
                "storage_provider": "github",
                "repository_id": self.repository_id,
                "canonical_ref": self.canonical_ref,
                "status": "complete",
                "scheduled": True,
            }
            if (
                not isinstance(first_run_receipt, Mapping)
                or any(first_run_receipt.get(key) != value for key, value in expected.items())
                or first_run_receipt.get("task_id") not in state.task_ids.values()
                or first_run_receipt.get("observed_generation") != adapter.current_generation()
            ):
                raise ValidationError("first-run activation requires a bound observed scheduled receipt")
            require_timestamp(first_run_receipt.get("observed_at"), "first-run observation")
            state.first_run_verified = True
            self._advance(adapter, state, InstallPhase.ACTIVE_VERIFIED)
        return state
