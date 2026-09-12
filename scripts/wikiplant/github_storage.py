from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping, Protocol

from .errors import CapabilityError, ConflictError, SimulatedLostResponse, ValidationError
from .authorization import validate_user_authorization
from .config import validate_config
from .instance import validate_instance_v2
from .storage import expected_mime
from .storage_contract import ObjectSnapshot, StorageBinding, StorageTransaction, TransactionReceipt
from .topics import TopicRegistry
from .util import safe_relative_path, sha256_bytes, sha256_text
from .yamlio import dumps as yaml_dumps, loads as yaml_loads


CANONICAL_TEXT_SUFFIXES = (".md", ".csv", ".json", ".yml", ".yaml", ".py", ".template")


def validate_canonical_text(logical_path: str, content: bytes) -> None:
    if not logical_path.endswith(CANONICAL_TEXT_SUFFIXES):
        raise ValidationError("GitHub canonical storage accepts only approved raw text file types")
    try:
        content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("GitHub canonical storage requires UTF-8 content") from exc


class GitHubGitAPI(Protocol):
    def get_repository(self, repository_id: str): ...
    def get_ref(self, repository_id: str, ref: str) -> str: ...
    def get_commit(self, repository_id: str, sha: str): ...
    def get_tree(self, repository_id: str, tree_sha: str, *, recursive: bool = True): ...
    def list_tree(self, repository_id: str, tree_sha: str, *, page_token: str | None, page_size: int): ...
    def get_blob(self, repository_id: str, sha: str) -> bytes: ...
    def get_repository_storage_bytes(self, repository_id: str) -> int: ...
    def create_blob(self, repository_id: str, content: bytes) -> str: ...
    def create_tree(self, repository_id: str, base_tree_sha: str | None, changes: Mapping[str, str | None]): ...
    def create_commit(self, repository_id: str, message: str, tree_sha: str, parents: tuple[str, ...]): ...
    def update_ref(self, repository_id: str, ref: str, sha: str, *, force: bool) -> str: ...
    def create_ref(self, repository_id: str, ref: str, sha: str) -> str: ...
    def is_ancestor(self, repository_id: str, ancestor: str, descendant: str) -> bool: ...


@dataclass(frozen=True)
class GitHubLimits:
    max_file_bytes: int = 512_000
    max_transaction_bytes: int = 8_000_000
    max_repository_bytes: int = 500_000_000
    max_paths_per_transaction: int = 200
    max_inventory_paths: int = 10_000
    inventory_page_size: int = 100
    max_conflict_retries: int = 3
    max_history_walk: int = 10_000


class GitHubStorageAdapter:
    """Git object adapter with a sole-parent, non-force publication protocol."""

    provider = "github"

    def __init__(
        self,
        api: GitHubGitAPI,
        binding: StorageBinding,
        *,
        instance_id: str,
        expected_repository: str,
        ancestry_anchor: str,
        limits: GitHubLimits | None = None,
        allow_repository_rename_repair: bool = False,
    ):
        if binding.provider != "github":
            raise ValidationError("GitHub adapter requires a GitHub storage binding")
        if (not binding.container_id or not instance_id
                or any(character in binding.container_id + instance_id for character in "\r\n")):
            raise ValidationError("repository and instance identities are required")
        if not re.fullmatch(
            r"refs/heads/(?![./])(?!.*(?:\.\.|//|@\{|\.lock$))[A-Za-z0-9._/-]*[A-Za-z0-9_-]",
            binding.generation_locator,
        ):
            raise ValidationError("canonical GitHub ref must be a full refs/heads ref")
        root = binding.logical_root.strip("/")
        if root:
            if root != binding.logical_root or safe_relative_path(root) != root:
                raise ValidationError("GitHub logical root must be a canonical relative path")
        self.api = api
        self.binding = StorageBinding(
            binding.provider, binding.container_id, root, binding.generation_locator
        )
        self.instance_id = instance_id
        self.expected_repository = expected_repository
        if (
            not isinstance(self.expected_repository, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.expected_repository)
        ):
            raise ValidationError("GitHub adapter requires the bound owner/name repository locator")
        if not isinstance(ancestry_anchor, str) or re.fullmatch(r"[a-f0-9]{40}", ancestry_anchor) is None:
            raise ValidationError("GitHub adapter requires a trusted 40-hex ancestry anchor")
        self.ancestry_anchor = ancestry_anchor
        self._last_seen_generation: str | None = None
        self._binding_validated_generations: set[str] = set()
        self._content_validated_generations: set[str] = set()
        self.allow_repository_rename_repair = allow_repository_rename_repair
        self.limits = limits or GitHubLimits()
        numeric_limits = (
            self.limits.max_file_bytes,
            self.limits.max_transaction_bytes,
            self.limits.max_repository_bytes,
            self.limits.max_paths_per_transaction,
            self.limits.max_inventory_paths,
            self.limits.inventory_page_size,
            self.limits.max_history_walk,
        )
        if any(type(value) is not int or value < 1 for value in numeric_limits):
            raise ValidationError("GitHub storage limits must be positive integers")
        if not (
            self.limits.max_file_bytes
            <= self.limits.max_transaction_bytes
            <= self.limits.max_repository_bytes
        ):
            raise ValidationError("GitHub byte limits must be monotonically bounded")
        if type(self.limits.max_conflict_retries) is not int or self.limits.max_conflict_retries < 0:
            raise ValidationError("GitHub conflict retry bound must be a nonnegative integer")
        try:
            self._validate_repository()
        except ConflictError:
            if not self.allow_repository_rename_repair:
                raise
            self._validate_repository_safety(self.api.get_repository(self.binding.container_id))

    @staticmethod
    def _validate_repository_safety(repo) -> None:
        if not repo.private:
            raise CapabilityError("GitHub operational repository must be private")
        if repo.archived:
            raise CapabilityError("GitHub operational repository must not be archived")
        if getattr(repo, "fork", False):
            raise CapabilityError("GitHub operational repository must not be a fork")
        if not getattr(repo, "force_push_protected", False) or not getattr(repo, "deletion_protected", False):
            raise CapabilityError("GitHub canonical ref requires observed force-push and deletion protection")

    def _validate_repository(self) -> None:
        repo = self.api.get_repository(self.binding.container_id)
        self._validate_repository_safety(repo)
        if repo.full_name.casefold() != self.expected_repository.casefold():
            raise ConflictError("bound GitHub repository locator changed")

    def repair_repository_locator(
        self,
        new_repository: str,
        authorization: dict[str, Any],
        *,
        operation_id: str,
    ) -> TransactionReceipt:
        """Explicit immutable-ID recovery for a legitimate owner/name rename."""
        if not self.allow_repository_rename_repair:
            raise CapabilityError("repository rename repair was not enabled for this explicit operation")
        repo = self.api.get_repository(self.binding.container_id)
        self._validate_repository_safety(repo)
        if (
            not isinstance(new_repository, str)
            or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", new_repository) is None
            or repo.full_name.casefold() != new_repository.casefold()
            or repo.full_name.casefold() == self.expected_repository.casefold()
        ):
            raise ValidationError("repository rename repair must match the observed immutable repository")
        target = f"{self.binding.container_id}:{self.expected_repository}->{new_repository}"
        validate_user_authorization(
            authorization, instance_id=self.instance_id,
            operation="repair-github-repository-locator", target=target,
        )
        head = self.api.get_ref(self.binding.container_id, self.binding.generation_locator)
        if not self.api.is_ancestor(self.binding.container_id, self.ancestry_anchor, head):
            raise ConflictError("renamed repository no longer descends from the trusted ancestry anchor")
        # Validate the complete old binding and canonical generation before any
        # Git object is created or the ref is moved.  The repository locator in
        # INSTANCE/config is expected to remain the old value until this repair.
        self._assert_instance(head)
        entries = self._tree_entries(head)
        instance_path = self._provider_path("INSTANCE.json")
        config_path = self._provider_path("config.yml")
        if instance_path not in entries or config_path not in entries:
            raise ValidationError("repository rename repair requires both canonical binding files")
        instance = json.loads(self.api.get_blob(self.binding.container_id, entries[instance_path]))
        config = yaml_loads(self.api.get_blob(self.binding.container_id, entries[config_path]).decode())
        if not isinstance(instance, dict) or instance.get("instance_id") != self.instance_id:
            raise ValidationError("repository rename repair found a foreign INSTANCE.json")
        if not isinstance(config, dict) or config.get("instance", {}).get("id") != self.instance_id:
            raise ValidationError("repository rename repair found a foreign config.yml")
        self._validate_instance_record(instance)
        self._validate_config_record(config)
        instance = dict(instance)
        instance["storage"] = dict(instance["storage"])
        instance["storage"]["repository"] = new_repository
        config = dict(config)
        config["storage"] = dict(config["storage"])
        config["storage"]["repository"] = new_repository
        marker_path = f"data/state/operations/repository-rename-{sha256_text(operation_id)}.complete.json"
        marker = self._json_bytes({
            "schema_version": 1, "kind": "wikiplant-repository-rename-repair",
            "instance_id": self.instance_id, "operation_id": operation_id,
            "repository_id": self.binding.container_id, "old_repository": self.expected_repository,
            "new_repository": new_repository, "base_generation": head,
            "authorization_sha256": sha256_bytes(self._json_bytes(authorization)),
        })
        changes = {
            "INSTANCE.json": self._json_bytes(instance),
            "config.yml": yaml_dumps(config).encode(),
            marker_path: marker,
        }
        candidate = self._create_commit(
            f"wikiplant repository rename {sha256_text(operation_id)}", head, changes
        )
        try:
            self.api.update_ref(
                self.binding.container_id, self.binding.generation_locator, candidate, force=False
            )
        except SimulatedLostResponse:
            pass
        observed = self.api.get_ref(self.binding.container_id, self.binding.generation_locator)
        if not self.api.is_ancestor(self.binding.container_id, candidate, observed):
            raise ConflictError("repository rename repair was not published on the canonical ref")
        observed_entries = self._tree_entries(observed)
        for logical_path, expected_content in changes.items():
            observed_sha = observed_entries.get(self._provider_path(logical_path))
            if (
                observed_sha is None
                or self.api.get_blob(self.binding.container_id, observed_sha) != expected_content
            ):
                raise ConflictError("repository rename repair failed exact canonical-ref verification")
        self.expected_repository = new_repository
        self._last_seen_generation = observed
        self._binding_validated_generations.clear()
        self._content_validated_generations.clear()
        self._assert_instance(observed)
        changed = {path: sha256_bytes(content) for path, content in changes.items()}
        return TransactionReceipt(
            operation_id, head, candidate, observed, changed,
            f"{self.binding.container_id}:{self.binding.generation_locator}:{candidate}",
        )

    def _provider_path(self, logical_path: str) -> str:
        path = safe_relative_path(logical_path)
        if path != logical_path:
            raise ValidationError("logical path must use canonical POSIX spelling")
        return f"{self.binding.logical_root}/{path}" if self.binding.logical_root else path

    def _logical_path(self, provider_path: str) -> str | None:
        root = self.binding.logical_root
        if not root:
            return provider_path
        prefix = root + "/"
        return provider_path[len(prefix) :] if provider_path.startswith(prefix) else None

    def _operation_paths(self, operation_id: str) -> tuple[str, str]:
        digest = sha256_text(operation_id)
        return (
            f"data/state/operations/operation-{digest}.intent.json",
            f"data/state/operations/operation-{digest}.complete.json",
        )

    @staticmethod
    def _json_bytes(value: Mapping[str, Any]) -> bytes:
        try:
            return (
                json.dumps(
                    value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            ).encode()
        except (TypeError, ValueError) as exc:
            raise ValidationError("original intent must be JSON serializable") from exc

    def current_generation(self) -> str:
        self._validate_repository()
        head = self.api.get_ref(self.binding.container_id, self.binding.generation_locator)
        if not self.api.is_ancestor(self.binding.container_id, self.ancestry_anchor, head):
            raise ConflictError("canonical GitHub ref no longer descends from the trusted ancestry anchor")
        if self._last_seen_generation is not None and not self.api.is_ancestor(
            self.binding.container_id, self._last_seen_generation, head
        ):
            raise ConflictError("canonical GitHub ref moved backward or to a sibling generation")
        self._last_seen_generation = head
        return head

    def bootstrap(
        self,
        initial_files: Mapping[str, bytes],
        *,
        expected_generation: str,
        operation_id: str,
    ) -> TransactionReceipt:
        """Atomically bind an initialized-but-empty dedicated repository.

        Bootstrap is deliberately separate from ordinary writes because an empty
        repository cannot yet pass the INSTANCE.json binding check. It accepts no
        pre-existing paths under the logical root; a replay is allowed only after
        the exact requested initial files can be observed under the bound instance.
        """
        self._validate_repository()
        if (not operation_id or len(operation_id) > 256 or "\r" in operation_id
                or "\n" in operation_id or not expected_generation or not initial_files):
            raise ValidationError("bootstrap operation ID and initial files are required")
        normalized: dict[str, bytes] = {}
        for path, content in initial_files.items():
            if not isinstance(content, bytes):
                raise ValidationError("bootstrap content must be bytes")
            canonical = safe_relative_path(path)
            if canonical != path or canonical in normalized:
                raise ValidationError("bootstrap paths must be unique canonical POSIX paths")
            validate_canonical_text(canonical, content)
            normalized[canonical] = content
        if any(len(value) > self.limits.max_file_bytes for value in normalized.values()):
            raise CapabilityError("GitHub bootstrap contains an oversized blob")
        instance_bytes = normalized.get("INSTANCE.json")
        if instance_bytes is None:
            raise ValidationError("GitHub bootstrap requires INSTANCE.json")
        try:
            instance = json.loads(instance_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("bootstrap INSTANCE.json is not valid JSON") from exc
        if not isinstance(instance, dict) or instance.get("instance_id") != self.instance_id:
            raise ValidationError("bootstrap INSTANCE.json does not match bound instance")
        validate_instance_v2(instance, expected_instance_id=self.instance_id)
        self._validate_instance_record(instance)
        config_bytes = normalized.get("config.yml")
        if config_bytes is None:
            raise ValidationError("GitHub bootstrap requires config.yml")
        try:
            config = yaml_loads(config_bytes.decode())
        except (UnicodeDecodeError, TypeError, ValueError) as exc:
            raise ValidationError("bootstrap config.yml is not valid YAML") from exc
        if not isinstance(config, dict) or config.get("instance", {}).get("id") != self.instance_id:
            raise ValidationError("bootstrap config.yml does not match bound instance")
        topics_bytes = normalized.get("data/TOPICS.md")
        if topics_bytes is None:
            raise ValidationError("GitHub bootstrap requires authoritative data/TOPICS.md")
        try:
            registry = TopicRegistry.parse(topics_bytes.decode())
        except (UnicodeDecodeError, TypeError, ValueError) as exc:
            raise ValidationError("bootstrap data/TOPICS.md is invalid") from exc
        validate_config(config, topic_registry=registry)
        self._validate_config_record(config)
        bootstrap_marker_path = (
            f"data/state/operations/bootstrap-{sha256_text(operation_id)}.complete.json"
        )
        if bootstrap_marker_path in normalized:
            raise ValidationError("bootstrap payload cannot supply its own completion marker")
        requested_hashes = {
            path: sha256_bytes(content) for path, content in sorted(normalized.items())
        }
        marker = self._json_bytes({
            "schema_version": 1,
            "kind": "wikiplant-storage-bootstrap",
            "stage": "COMPLETE",
            "instance_id": self.instance_id,
            "operation_id": operation_id,
            "base_generation": expected_generation,
            "initial_paths_and_hashes": requested_hashes,
        })
        if len(marker) > self.limits.max_file_bytes:
            raise CapabilityError("GitHub bootstrap marker exceeds configured blob bound")
        normalized[bootstrap_marker_path] = marker
        if len(normalized) > self.limits.max_paths_per_transaction:
            raise CapabilityError("GitHub bootstrap exceeds configured path bound")
        if sum(len(value) for value in normalized.values()) > self.limits.max_transaction_bytes:
            raise CapabilityError("GitHub bootstrap exceeds configured byte bound")
        if sum(len(value) for value in normalized.values()) > self.limits.max_repository_bytes:
            raise CapabilityError("GitHub bootstrap exceeds configured repository byte bound")
        changed = {path: sha256_bytes(content) for path, content in sorted(normalized.items())}
        for _ in range(self.limits.max_conflict_retries + 1):
            head = self.current_generation()
            entries = self._tree_entries(head)
            scoped_entries = {
                logical: blob_sha
                for provider_path, blob_sha in entries.items()
                if (logical := self._logical_path(provider_path)) is not None
            }
            if scoped_entries:
                marker_sha = scoped_entries.get(bootstrap_marker_path)
                marker_matches = (
                    marker_sha is not None
                    and self.api.get_blob(self.binding.container_id, marker_sha) == marker
                )
                if marker_matches and all(
                    path in scoped_entries
                    and sha256_bytes(self.api.get_blob(self.binding.container_id, scoped_entries[path])) == digest
                    for path, digest in changed.items()
                ):
                    self._assert_instance(head)
                    committed = self._path_introduction(head, bootstrap_marker_path, marker)
                    if committed is None:
                        raise ConflictError("bootstrap completion is not reachable from canonical ref")
                    return TransactionReceipt(
                        operation_id, expected_generation, committed, head, changed,
                        f"{self.binding.container_id}:{self.binding.generation_locator}:{committed}", True,
                    )
                raise ConflictError("GitHub bootstrap destination is not empty")
            if head != expected_generation:
                raise ConflictError("GitHub bootstrap base generation changed")
            try:
                candidate = self._create_commit(
                    f"wikiplant bootstrap {sha256_text(operation_id)}", head, normalized
                )
            except SimulatedLostResponse:
                continue
            try:
                if not self._publish(candidate):
                    continue
            except ConflictError:
                continue
            current = self.current_generation()
            if not self.api.is_ancestor(self.binding.container_id, candidate, current):
                continue
            self._assert_instance(current)
            receipt = TransactionReceipt(
                operation_id, expected_generation, candidate, current, changed,
                f"{self.binding.container_id}:{self.binding.generation_locator}:{candidate}",
            )
            if not self.verify_generation(receipt):
                raise ConflictError("GitHub bootstrap failed exact verification")
            return receipt
        raise ConflictError("GitHub bootstrap exceeded conflict retry bound")

    def _tree_entries(self, generation: str) -> dict[str, str]:
        commit = self.api.get_commit(self.binding.container_id, generation)
        tree, truncated = self.api.get_tree(self.binding.container_id, commit.tree_sha, recursive=True)
        if not truncated:
            if len(tree.entries) > self.limits.max_inventory_paths:
                raise CapabilityError("GitHub tree inventory exceeds configured bound")
            return dict(tree.entries)
        entries: dict[str, str] = {}
        token: str | None = None
        seen: set[str] = set()
        while True:
            page, next_token = self.api.list_tree(
                self.binding.container_id,
                commit.tree_sha,
                page_token=token,
                page_size=self.limits.inventory_page_size,
            )
            for path, blob_sha in page:
                if path in entries:
                    raise ValidationError("GitHub tree inventory contained a duplicate path")
                entries[path] = blob_sha
                if len(entries) > self.limits.max_inventory_paths:
                    raise CapabilityError("GitHub tree inventory exceeds configured bound")
            if next_token is None:
                return entries
            if next_token in seen:
                raise ValidationError("GitHub tree pagination did not advance")
            seen.add(next_token)
            token = next_token

    def _validate_instance_record(self, record: Mapping[str, Any]) -> None:
        storage = record.get("storage")
        expected = {
            "provider": "github",
            "repository_id": self.binding.container_id,
            "repository": self.expected_repository,
            "canonical_ref": self.binding.generation_locator,
            "root_prefix": self.binding.logical_root,
        }
        if not isinstance(storage, dict) or any(storage.get(key) != value for key, value in expected.items()):
            raise ValidationError("GitHub INSTANCE.json storage binding mismatch")
        if (
            storage.get("first_verified_commit") != self.ancestry_anchor
            or storage.get("repository_visibility") != "private"
            or storage.get("capability_profile_path") != "installation/capability-profile.json"
            or not isinstance(storage.get("app_installation_id"), str)
            or not storage["app_installation_id"]
        ):
            raise ValidationError("GitHub INSTANCE.json immutable capability/ancestry binding mismatch")

    def _validate_config_record(self, record: Mapping[str, Any]) -> None:
        storage = record.get("storage")
        expected = {
            "provider": "github",
            "repository_id": self.binding.container_id,
            "repository": self.expected_repository,
            "canonical_ref": self.binding.generation_locator,
            "root_prefix": self.binding.logical_root,
            "consistency_mode": "git-fast-forward",
        }
        if not isinstance(storage, dict) or any(storage.get(key) != value for key, value in expected.items()):
            raise ValidationError("GitHub config.yml storage binding mismatch")

    def _assert_instance(self, generation: str) -> None:
        if generation in self._binding_validated_generations:
            return
        entries = self._tree_entries(generation)
        for provider_path in entries:
            logical = self._logical_path(provider_path)
            if logical is None:
                continue
            try:
                canonical = safe_relative_path(logical)
            except (TypeError, ValidationError) as exc:
                raise ValidationError("GitHub generation contains an unsafe canonical path") from exc
            if canonical != logical or not logical.endswith(CANONICAL_TEXT_SUFFIXES):
                raise ValidationError("GitHub generation contains an unsupported canonical path")
        path = self._provider_path("INSTANCE.json")
        blob_sha = entries.get(path)
        if blob_sha is None:
            raise ValidationError("GitHub generation lacks bound INSTANCE.json")
        instance_bytes = self.api.get_blob(self.binding.container_id, blob_sha)
        if len(instance_bytes) > self.limits.max_file_bytes:
            raise CapabilityError("GitHub INSTANCE.json exceeds configured exact-read bound")
        try:
            record = json.loads(instance_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("GitHub INSTANCE.json is not valid JSON") from exc
        if not isinstance(record, dict) or record.get("instance_id") != self.instance_id:
            raise ValidationError("GitHub generation belongs to another instance")
        validate_instance_v2(record, expected_instance_id=self.instance_id)
        self._validate_instance_record(record)
        config_sha = entries.get(self._provider_path("config.yml"))
        if config_sha is None:
            raise ValidationError("GitHub generation lacks bound config.yml")
        config_bytes = self.api.get_blob(self.binding.container_id, config_sha)
        if len(config_bytes) > self.limits.max_file_bytes:
            raise CapabilityError("GitHub config.yml exceeds configured exact-read bound")
        try:
            config = yaml_loads(config_bytes.decode())
        except (UnicodeDecodeError, TypeError, ValueError) as exc:
            raise ValidationError("GitHub config.yml is not valid YAML") from exc
        if not isinstance(config, dict) or config.get("instance", {}).get("id") != self.instance_id:
            raise ValidationError("GitHub config.yml belongs to another instance")
        topics_sha = entries.get(self._provider_path("data/TOPICS.md"))
        if topics_sha is None:
            raise ValidationError("GitHub generation lacks authoritative data/TOPICS.md")
        topics_bytes = self.api.get_blob(self.binding.container_id, topics_sha)
        if len(topics_bytes) > self.limits.max_file_bytes:
            raise CapabilityError("GitHub TOPICS.md exceeds configured exact-read bound")
        try:
            registry = TopicRegistry.parse(topics_bytes.decode())
        except (UnicodeDecodeError, TypeError, ValueError) as exc:
            raise ValidationError("GitHub data/TOPICS.md is invalid") from exc
        validate_config(config, topic_registry=registry)
        self._validate_config_record(config)
        self._binding_validated_generations.add(generation)

    def _assert_generation_content(self, generation: str) -> None:
        if generation in self._content_validated_generations:
            return
        self._assert_instance(generation)
        entries = self._tree_entries(generation)
        repository_bytes = 0
        for provider_path, observed_sha in entries.items():
            logical = self._logical_path(provider_path)
            if logical is None:
                continue
            observed_content = self.api.get_blob(self.binding.container_id, observed_sha)
            validate_canonical_text(logical, observed_content)
            if len(observed_content) > self.limits.max_file_bytes:
                raise CapabilityError("GitHub generation contains an oversized canonical blob")
            repository_bytes += len(observed_content)
        if repository_bytes > self.limits.max_repository_bytes:
            raise CapabilityError("GitHub generation exceeds the configured current-tree byte bound")
        self._content_validated_generations.add(generation)

    def read_exact(self, logical_path: str, *, generation: str | None = None) -> ObjectSnapshot:
        self._validate_repository()
        observed_generation = generation or self.current_generation()
        self._assert_instance(observed_generation)
        path = self._provider_path(logical_path)
        entries = self._tree_entries(observed_generation)
        try:
            blob_sha = entries[path]
        except KeyError as exc:
            raise ValidationError(f"logical path does not exist: {logical_path}") from exc
        content = self.api.get_blob(self.binding.container_id, blob_sha)
        validate_canonical_text(logical_path, content)
        if len(content) > self.limits.max_file_bytes:
            raise CapabilityError("GitHub blob exceeds configured exact-read bound")
        return ObjectSnapshot(
            safe_relative_path(logical_path),
            content,
            expected_mime(logical_path),
            sha256_bytes(content),
            blob_sha,
            observed_generation,
        )

    def inventory(self, *, generation: str | None = None) -> list[ObjectSnapshot]:
        self._validate_repository()
        observed_generation = generation or self.current_generation()
        self._assert_instance(observed_generation)
        entries = self._tree_entries(observed_generation)
        result: list[ObjectSnapshot] = []
        repository_bytes = 0
        for provider_path, blob_sha in sorted(entries.items()):
            logical_path = self._logical_path(provider_path)
            if logical_path is None:
                continue
            content = self.api.get_blob(self.binding.container_id, blob_sha)
            validate_canonical_text(logical_path, content)
            repository_bytes += len(content)
            if repository_bytes > self.limits.max_repository_bytes:
                raise CapabilityError("GitHub inventory exceeds configured repository byte bound")
            if len(content) > self.limits.max_file_bytes:
                raise CapabilityError("GitHub inventory blob exceeds configured bound")
            result.append(ObjectSnapshot(
                logical_path, content, expected_mime(logical_path), sha256_bytes(content),
                blob_sha, observed_generation,
            ))
        self._content_validated_generations.add(observed_generation)
        return result

    def _validate_transaction(self, transaction: StorageTransaction) -> None:
        if transaction.instance_id != self.instance_id:
            raise ValidationError("transaction instance mismatch")
        if (not transaction.operation_id or len(transaction.operation_id) > 256
                or "\r" in transaction.operation_id or "\n" in transaction.operation_id
                or not transaction.base_generation):
            raise ValidationError("transaction operation and base generation are required")
        write_paths = set(transaction.writes)
        delete_paths = set(transaction.deletes)
        targets = write_paths | delete_paths
        if write_paths & delete_paths:
            raise ValidationError("a path cannot be written and deleted in one transaction")
        if not targets or len(targets) > self.limits.max_paths_per_transaction:
            raise ValidationError("transaction path count is outside configured bounds")
        if set(transaction.expected_input_hashes) != targets:
            raise ValidationError("every transaction target requires exactly one expected input hash")
        if any(
            digest is not None
            and (not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None)
            for digest in transaction.expected_input_hashes.values()
        ):
            raise ValidationError("expected input hashes must be lowercase SHA-256 values or null")
        intent_path, complete_path = self._operation_paths(transaction.operation_id)
        for path in targets:
            if safe_relative_path(path) != path or len(path.encode()) > 1024:
                raise ValidationError("transaction paths must use canonical POSIX spelling")
            if path in {intent_path, complete_path} or path.startswith("data/state/operations/operation-"):
                raise ValidationError("transaction cannot replace its operation records")
        if any(not isinstance(value, bytes) for value in transaction.writes.values()):
            raise ValidationError("transaction write content must be bytes")
        for path, content in transaction.writes.items():
            validate_canonical_text(path, content)
        if "INSTANCE.json" in write_paths or {"INSTANCE.json", "config.yml"} & delete_paths:
            raise ValidationError("ordinary transactions cannot rewrite INSTANCE.json or delete provider binding files")
        if "config.yml" in transaction.writes:
            try:
                config = yaml_loads(transaction.writes["config.yml"].decode())
            except (UnicodeDecodeError, TypeError, ValueError) as exc:
                raise ValidationError("replacement config.yml is not valid YAML") from exc
            if not isinstance(config, dict) or config.get("instance", {}).get("id") != self.instance_id:
                raise ValidationError("replacement config.yml belongs to another instance")
            self._validate_config_record(config)
        size = sum(len(value) for value in transaction.writes.values())
        if size > self.limits.max_transaction_bytes:
            raise CapabilityError("GitHub transaction exceeds configured byte bound")
        if any(len(value) > self.limits.max_file_bytes for value in transaction.writes.values()):
            raise CapabilityError("GitHub transaction contains an oversized blob")
        intent_bytes = self._json_bytes(self._intent_record(transaction))
        completion_bytes = self._json_bytes(
            self._completion_record(transaction, sha256_bytes(intent_bytes))
        )
        if any(len(value) > self.limits.max_file_bytes for value in (intent_bytes, completion_bytes)):
            raise CapabilityError("GitHub operation record exceeds configured blob bound")
        if size + len(completion_bytes) > self.limits.max_transaction_bytes:
            raise CapabilityError("GitHub completion transaction exceeds configured byte bound")

    def _intent_record(self, transaction: StorageTransaction) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "wikiplant-storage-intent",
            "instance_id": transaction.instance_id,
            "operation_id": transaction.operation_id,
            "base_generation": transaction.base_generation,
            "original_intent": transaction.original_intent,
            "writes": {path: sha256_bytes(content) for path, content in sorted(transaction.writes.items())},
            "deletes": sorted(transaction.deletes),
            "expected_input_hashes": dict(sorted(transaction.expected_input_hashes.items())),
            "authorization_reference": transaction.authorization_reference,
        }

    def _read_optional(self, logical_path: str, generation: str) -> bytes | None:
        entries = self._tree_entries(generation)
        blob_sha = entries.get(self._provider_path(logical_path))
        return None if blob_sha is None else self.api.get_blob(self.binding.container_id, blob_sha)

    def _assert_expected_inputs(self, transaction: StorageTransaction, generation: str) -> None:
        entries = self._tree_entries(generation)
        for logical_path, expected in transaction.expected_input_hashes.items():
            blob_sha = entries.get(self._provider_path(logical_path))
            actual = None if blob_sha is None else sha256_bytes(self.api.get_blob(self.binding.container_id, blob_sha))
            if actual != expected:
                raise ConflictError(f"GitHub input changed since generation base: {logical_path}")

    def _create_commit(self, message: str, parent: str, changes: Mapping[str, bytes | None]) -> str:
        self._assert_repository_capacity(parent, changes)
        parent_commit = self.api.get_commit(self.binding.container_id, parent)
        tree_changes: dict[str, str | None] = {}
        for logical_path, content in changes.items():
            provider_path = self._provider_path(logical_path)
            tree_changes[provider_path] = (
                None if content is None else self.api.create_blob(self.binding.container_id, content)
            )
        tree = self.api.create_tree(self.binding.container_id, parent_commit.tree_sha, tree_changes)
        commit = self.api.create_commit(self.binding.container_id, message, tree.sha, (parent,))
        if self.api.get_repository_storage_bytes(self.binding.container_id) > self.limits.max_repository_bytes:
            raise CapabilityError("GitHub object creation exceeded the configured repository history bound")
        return commit.sha

    def _assert_repository_capacity(self, generation: str, changes: Mapping[str, bytes | None]) -> None:
        retained_bytes = self.api.get_repository_storage_bytes(self.binding.container_id)
        prospective_bytes = sum(
            len(content) + len(logical_path.encode()) + 96
            for logical_path, content in changes.items() if content is not None
        ) + 1024
        if retained_bytes + prospective_bytes > self.limits.max_repository_bytes:
            raise CapabilityError("GitHub commit would exceed configured repository history byte bound")
        entries = self._tree_entries(generation)
        total = 0
        for provider_path, blob_sha in entries.items():
            if self._logical_path(provider_path) is not None:
                total += len(self.api.get_blob(self.binding.container_id, blob_sha))
        for logical_path, content in changes.items():
            prior_sha = entries.get(self._provider_path(logical_path))
            if prior_sha is not None:
                total -= len(self.api.get_blob(self.binding.container_id, prior_sha))
            if content is not None:
                total += len(content)
        if total > self.limits.max_repository_bytes:
            raise CapabilityError("GitHub commit would exceed configured current-tree byte bound")

    def _publish(self, candidate: str) -> bool:
        try:
            self.api.update_ref(
                self.binding.container_id,
                self.binding.generation_locator,
                candidate,
                force=False,
            )
        except SimulatedLostResponse:
            current = self.current_generation()
            return self.api.is_ancestor(self.binding.container_id, candidate, current)
        return True

    def _ensure_intent(self, transaction: StorageTransaction, intent_bytes: bytes) -> str:
        intent_path, _ = self._operation_paths(transaction.operation_id)
        for _ in range(self.limits.max_conflict_retries + 1):
            head = self.current_generation()
            self._assert_instance(head)
            self._assert_generation_content(head)
            self._assert_linear_history(head)
            existing = self._read_optional(intent_path, head)
            if existing is not None:
                if existing != intent_bytes:
                    raise ConflictError("operation ID is already bound to a different original intent")
                return head
            if not self.api.is_ancestor(self.binding.container_id, transaction.base_generation, head):
                raise ConflictError("transaction base is not an ancestor of canonical head")
            self._assert_expected_inputs(transaction, head)
            message = f"wikiplant intent {sha256_text(transaction.operation_id)}"
            try:
                candidate = self._create_commit(message, head, {intent_path: intent_bytes})
            except SimulatedLostResponse:
                # The object is not publication. Reconcile only through the ref, then retry.
                reconciled = self._read_optional(intent_path, self.current_generation())
                if reconciled is not None:
                    if reconciled != intent_bytes:
                        raise ConflictError("operation intent collision after uncertain response")
                    return self.current_generation()
                continue
            try:
                if self._publish(candidate):
                    return candidate
            except ConflictError:
                continue
        raise ConflictError("GitHub intent publication exceeded conflict retry bound")

    def _completion_record(self, transaction: StorageTransaction, intent_hash: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "wikiplant-storage-completion",
            "stage": "COMPLETE",
            "instance_id": transaction.instance_id,
            "operation_id": transaction.operation_id,
            "base_generation": transaction.base_generation,
            "intent_sha256": intent_hash,
            "changed_paths_and_hashes": {
                **{path: sha256_bytes(content) for path, content in sorted(transaction.writes.items())},
                **{path: None for path in sorted(transaction.deletes)},
            },
        }

    def _path_introduction(self, head: str, logical_path: str, content: bytes) -> str | None:
        cursor = head
        for _ in range(self.limits.max_history_walk):
            commit = self.api.get_commit(self.binding.container_id, cursor)
            observed = self._read_optional(logical_path, cursor)
            if observed == content:
                parent_has = bool(
                    commit.parents and self._read_optional(logical_path, commit.parents[0]) == content
                )
                if not parent_has:
                    return cursor
            if not commit.parents:
                return None
            if len(commit.parents) != 1:
                raise ConflictError("canonical GitHub history contains a merge commit")
            cursor = commit.parents[0]
        raise CapabilityError("GitHub completion search exceeded configured history bound")

    def _completion_commit(self, transaction: StorageTransaction, head: str, completion_bytes: bytes) -> str | None:
        _, complete_path = self._operation_paths(transaction.operation_id)
        return self._path_introduction(head, complete_path, completion_bytes)

    def _assert_linear_history(self, head: str) -> None:
        cursor = head
        for _ in range(self.limits.max_history_walk):
            commit = self.api.get_commit(self.binding.container_id, cursor)
            if len(commit.parents) > 1:
                raise ConflictError("canonical GitHub history contains a merge commit")
            if not commit.parents:
                return
            cursor = commit.parents[0]
        raise CapabilityError("GitHub history exceeds configured verification bound")

    def reconcile_operation(self, transaction: StorageTransaction) -> TransactionReceipt | None:
        self._validate_transaction(transaction)
        head = self.current_generation()
        self._assert_instance(head)
        self._assert_linear_history(head)
        intent_path, complete_path = self._operation_paths(transaction.operation_id)
        intent_bytes = self._json_bytes(self._intent_record(transaction))
        observed_intent = self._read_optional(intent_path, head)
        if observed_intent is None:
            return None
        if observed_intent != intent_bytes:
            raise ConflictError("operation ID is already bound to a different original intent")
        completion = self._completion_record(transaction, sha256_bytes(intent_bytes))
        completion_bytes = self._json_bytes(completion)
        observed_completion = self._read_optional(complete_path, head)
        if observed_completion is None:
            return None
        if observed_completion != completion_bytes:
            raise ConflictError("operation completion does not match durable intent")
        committed = self._completion_commit(transaction, head, completion_bytes)
        if committed is None or not self.api.is_ancestor(self.binding.container_id, committed, head):
            raise ConflictError("operation completion is not reachable from canonical ref")
        receipt = TransactionReceipt(
            transaction.operation_id,
            transaction.base_generation,
            committed,
            head,
            completion["changed_paths_and_hashes"],
            f"{self.binding.container_id}:{self.binding.generation_locator}:{committed}",
            True,
        )
        if not self.verify_generation(receipt):
            raise ConflictError("historical GitHub completion failed exact verification")
        return receipt

    def commit_transaction(self, transaction: StorageTransaction) -> TransactionReceipt:
        self._validate_repository()
        self._validate_transaction(transaction)
        self._assert_generation_content(self.current_generation())
        replay = self.reconcile_operation(transaction)
        if replay is not None:
            return replay
        intent_bytes = self._json_bytes(self._intent_record(transaction))
        self._ensure_intent(transaction, intent_bytes)
        intent_hash = sha256_bytes(intent_bytes)
        completion = self._completion_record(transaction, intent_hash)
        completion_bytes = self._json_bytes(completion)
        _, complete_path = self._operation_paths(transaction.operation_id)
        changes: dict[str, bytes | None] = dict(transaction.writes)
        changes.update({path: None for path in transaction.deletes})
        changes[complete_path] = completion_bytes
        for _ in range(self.limits.max_conflict_retries + 1):
            replay = self.reconcile_operation(transaction)
            if replay is not None:
                return replay
            head = self.current_generation()
            self._assert_instance(head)
            self._assert_generation_content(head)
            self._assert_linear_history(head)
            self._assert_expected_inputs(transaction, head)
            message = f"wikiplant commit {sha256_text(transaction.operation_id)}"
            try:
                candidate = self._create_commit(message, head, changes)
            except SimulatedLostResponse:
                # An orphan commit is not success. A deterministic retry may reuse it.
                replay = self.reconcile_operation(transaction)
                if replay is not None:
                    return replay
                continue
            try:
                published = self._publish(candidate)
            except ConflictError:
                continue
            if not published:
                continue
            current = self.current_generation()
            if not self.api.is_ancestor(self.binding.container_id, candidate, current):
                continue
            receipt = TransactionReceipt(
                transaction.operation_id,
                transaction.base_generation,
                candidate,
                current,
                completion["changed_paths_and_hashes"],
                f"{self.binding.container_id}:{self.binding.generation_locator}:{candidate}",
            )
            if not self.verify_generation(receipt):
                raise ConflictError("GitHub transaction publication failed exact verification")
            return receipt
        replay = self.reconcile_operation(transaction)
        if replay is not None:
            return replay
        raise ConflictError("GitHub transaction exceeded conflict retry bound")

    def verify_generation(self, receipt: TransactionReceipt) -> bool:
        if not self.api.is_ancestor(
            self.binding.container_id, receipt.committed_generation, self.current_generation()
        ):
            return False
        entries = self._tree_entries(receipt.committed_generation)
        for logical_path, expected in receipt.changed_paths_and_hashes.items():
            blob_sha = entries.get(self._provider_path(logical_path))
            if expected is None:
                if blob_sha is not None:
                    return False
            elif blob_sha is None or sha256_bytes(self.api.get_blob(self.binding.container_id, blob_sha)) != expected:
                return False
        return True

    def persist_immutable_intake(
        self,
        logical_path: str,
        content: bytes,
        *,
        instance_id: str,
        operation_id: str,
        authorization_reference: str | None = None,
    ) -> TransactionReceipt:
        generation = self.current_generation()
        intent_path, _ = self._operation_paths(operation_id)
        prior_intent = self._read_optional(intent_path, generation)
        if prior_intent is not None:
            try:
                record = json.loads(prior_intent)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ConflictError("durable intake intent is unreadable") from exc
            expected_intent = {"kind": "immutable-intake", "logical_path": logical_path}
            expected_output = sha256_bytes(content)
            if (
                not isinstance(record, dict)
                or record.get("instance_id") != instance_id
                or record.get("operation_id") != operation_id
                or record.get("original_intent") != expected_intent
                or record.get("writes") != {logical_path: expected_output}
                or record.get("deletes") != []
                or record.get("authorization_reference") != authorization_reference
            ):
                raise ConflictError("immutable intake operation ID collision")
            transaction = StorageTransaction(
                instance_id=instance_id,
                operation_id=operation_id,
                base_generation=record["base_generation"],
                original_intent=expected_intent,
                writes={logical_path: content},
                deletes=(),
                expected_input_hashes=record["expected_input_hashes"],
                authorization_reference=authorization_reference,
            )
            replay = self.reconcile_operation(transaction)
            if replay is None:
                return self.commit_transaction(transaction)
            return replay
        try:
            existing = self.read_exact(logical_path, generation=generation)
        except ValidationError as exc:
            if "does not exist" not in str(exc):
                raise
            expected = None
        else:
            if existing.content != content:
                raise ConflictError("immutable intake path already contains different content")
            expected = existing.content_hash
        transaction = StorageTransaction(
            instance_id=instance_id,
            operation_id=operation_id,
            base_generation=generation,
            original_intent={"kind": "immutable-intake", "logical_path": logical_path},
            writes={logical_path: content},
            deletes=(),
            expected_input_hashes={logical_path: expected},
            authorization_reference=authorization_reference,
        )
        return self.commit_transaction(transaction)
