from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Callable, Mapping

from .errors import CapabilityError, ConflictError, SimulatedLostResponse, ValidationError


def _git_sha(kind: str, payload: bytes) -> str:
    header = f"{kind} {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()  # noqa: S324 - Git object identity


@dataclass(frozen=True)
class FakeRepository:
    id: str
    full_name: str
    private: bool
    archived: bool
    fork: bool
    default_branch: str
    force_push_protected: bool
    deletion_protected: bool


@dataclass(frozen=True)
class FakeTree:
    sha: str
    entries: Mapping[str, str]


@dataclass(frozen=True)
class FakeCommit:
    sha: str
    tree_sha: str
    parents: tuple[str, ...]
    message: str


class FakeGitHub:
    """Deterministic in-memory subset of GitHub's Git object/ref API."""

    def __init__(
        self,
        *,
        repository_id: str = "repo-1",
        full_name: str = "owner/private-wikiplant",
        canonical_ref: str = "refs/heads/wikiplant-data",
        create_canonical_ref: bool = True,
    ) -> None:
        self.repository = FakeRepository(
            repository_id, full_name, True, False, False, "main", True, True
        )
        self.contents_read = True
        self.contents_write = True
        self.ruleset_rejects_updates = False
        self.truncate_next_recursive_tree = False
        self.lose_next_commit_response = False
        self.lose_next_ref_response_before_apply = False
        self.lose_next_ref_response_after_apply = False
        self.lose_next_create_ref_response_before_apply = False
        self.lose_next_create_ref_response_after_apply = False
        self.before_next_ref_update: Callable[[FakeGitHub], None] | None = None
        self.ref_update_calls: list[tuple[str, str, bool]] = []
        self.blobs: dict[str, bytes] = {}
        self.trees: dict[str, FakeTree] = {}
        self.commits: dict[str, FakeCommit] = {}
        self.refs: dict[str, str] = {}
        empty = self.create_tree(repository_id, None, {})
        initial = self.create_commit(repository_id, "wikiplant repository initialized", empty.sha, ())
        self.initial_commit_sha = initial.sha
        self.refs["refs/heads/main"] = initial.sha
        if create_canonical_ref:
            self.refs[canonical_ref] = initial.sha

    def _require_read(self) -> None:
        if not self.contents_read:
            raise CapabilityError("GitHub contents read permission is unavailable")

    def _require_write(self) -> None:
        if not self.contents_write:
            raise CapabilityError("GitHub contents write permission is unavailable")

    def get_repository(self, repository_id: str) -> FakeRepository:
        self._require_read()
        if repository_id != self.repository.id:
            raise ValidationError("GitHub repository identity mismatch")
        return self.repository

    def rename_repository(self, full_name: str) -> None:
        self.repository = FakeRepository(
            self.repository.id, full_name, self.repository.private, self.repository.archived,
            self.repository.fork, self.repository.default_branch,
            self.repository.force_push_protected, self.repository.deletion_protected,
        )

    def set_private(self, value: bool) -> None:
        self.repository = FakeRepository(
            self.repository.id, self.repository.full_name, value, self.repository.archived,
            self.repository.fork, self.repository.default_branch,
            self.repository.force_push_protected, self.repository.deletion_protected,
        )

    def set_archived(self, value: bool) -> None:
        self.repository = FakeRepository(
            self.repository.id, self.repository.full_name, self.repository.private, value,
            self.repository.fork, self.repository.default_branch,
            self.repository.force_push_protected, self.repository.deletion_protected,
        )

    def set_fork(self, value: bool) -> None:
        self.repository = FakeRepository(
            self.repository.id, self.repository.full_name, self.repository.private,
            self.repository.archived, value, self.repository.default_branch,
            self.repository.force_push_protected, self.repository.deletion_protected,
        )

    def set_ref_protection(self, *, force_push: bool, deletion: bool) -> None:
        self.repository = FakeRepository(
            self.repository.id, self.repository.full_name, self.repository.private,
            self.repository.archived, self.repository.fork, self.repository.default_branch,
            force_push, deletion,
        )

    def get_ref(self, repository_id: str, ref: str) -> str:
        self.get_repository(repository_id)
        try:
            return self.refs[ref]
        except KeyError as exc:
            raise ValidationError("bound GitHub ref does not exist") from exc

    def get_blob(self, repository_id: str, sha: str) -> bytes:
        self.get_repository(repository_id)
        try:
            return self.blobs[sha]
        except KeyError as exc:
            raise ValidationError("unknown GitHub blob") from exc

    def get_repository_storage_bytes(self, repository_id: str) -> int:
        self.get_repository(repository_id)
        blob_bytes = sum(len(value) for value in self.blobs.values())
        tree_bytes = sum(len(self._tree_payload(value.entries)) for value in self.trees.values())
        commit_bytes = sum(
            len((
                f"tree {value.tree_sha}\n"
                + "".join(f"parent {parent}\n" for parent in value.parents)
                + f"\n{value.message}\n"
            ).encode())
            for value in self.commits.values()
        )
        return blob_bytes + tree_bytes + commit_bytes

    def create_blob(self, repository_id: str, content: bytes) -> str:
        self.get_repository(repository_id)
        self._require_write()
        sha = _git_sha("blob", content)
        self.blobs.setdefault(sha, bytes(content))
        return sha

    @staticmethod
    def _tree_payload(entries: Mapping[str, str]) -> bytes:
        return "\n".join(f"100644 {path}\0{sha}" for path, sha in sorted(entries.items())).encode()

    def create_tree(
        self, repository_id: str, base_tree_sha: str | None, changes: Mapping[str, str | None]
    ) -> FakeTree:
        self.get_repository(repository_id)
        self._require_write()
        if base_tree_sha is None:
            entries: dict[str, str] = {}
        else:
            try:
                entries = dict(self.trees[base_tree_sha].entries)
            except KeyError as exc:
                raise ValidationError("unknown base Git tree") from exc
        for path, blob_sha in changes.items():
            if blob_sha is None:
                entries.pop(path, None)
            elif blob_sha not in self.blobs:
                raise ValidationError("tree references an unknown blob")
            else:
                entries[path] = blob_sha
        sha = _git_sha("tree", self._tree_payload(entries))
        tree = FakeTree(sha, entries)
        self.trees.setdefault(sha, tree)
        return tree

    def get_tree(
        self, repository_id: str, tree_sha: str, *, recursive: bool = True
    ) -> tuple[FakeTree, bool]:
        self.get_repository(repository_id)
        try:
            tree = self.trees[tree_sha]
        except KeyError as exc:
            raise ValidationError("unknown Git tree") from exc
        truncated = bool(recursive and self.truncate_next_recursive_tree)
        if truncated:
            self.truncate_next_recursive_tree = False
            midpoint = max(1, len(tree.entries) // 2)
            tree = FakeTree(tree.sha, dict(list(sorted(tree.entries.items()))[:midpoint]))
        return tree, truncated

    def list_tree(
        self,
        repository_id: str,
        tree_sha: str,
        *,
        page_token: str | None,
        page_size: int,
    ) -> tuple[list[tuple[str, str]], str | None]:
        self.get_repository(repository_id)
        if page_size <= 0:
            raise ValidationError("tree page size must be positive")
        try:
            entries = sorted(self.trees[tree_sha].entries.items())
        except KeyError as exc:
            raise ValidationError("unknown Git tree") from exc
        start = int(page_token or "0")
        page = entries[start : start + page_size]
        next_token = str(start + page_size) if start + page_size < len(entries) else None
        return page, next_token

    def get_commit(self, repository_id: str, sha: str) -> FakeCommit:
        self.get_repository(repository_id)
        try:
            return self.commits[sha]
        except KeyError as exc:
            raise ValidationError("unknown Git commit") from exc

    def create_commit(
        self, repository_id: str, message: str, tree_sha: str, parents: tuple[str, ...]
    ) -> FakeCommit:
        self.get_repository(repository_id)
        self._require_write()
        if tree_sha not in self.trees or any(parent not in self.commits for parent in parents):
            raise ValidationError("commit references an unknown tree or parent")
        payload = (
            f"tree {tree_sha}\n"
            + "".join(f"parent {parent}\n" for parent in parents)
            + f"\n{message}\n"
        ).encode()
        sha = _git_sha("commit", payload)
        commit = FakeCommit(sha, tree_sha, tuple(parents), message)
        self.commits.setdefault(sha, commit)
        if self.lose_next_commit_response:
            self.lose_next_commit_response = False
            raise SimulatedLostResponse("commit object created; response lost")
        return commit

    def is_ancestor(self, repository_id: str, ancestor: str, descendant: str) -> bool:
        self.get_repository(repository_id)
        pending = [descendant]
        seen: set[str] = set()
        while pending:
            sha = pending.pop()
            if sha == ancestor:
                return True
            if sha in seen:
                continue
            seen.add(sha)
            commit = self.commits.get(sha)
            if commit:
                pending.extend(commit.parents)
        return False

    def update_ref(self, repository_id: str, ref: str, sha: str, *, force: bool) -> str:
        self.get_repository(repository_id)
        self._require_write()
        self.ref_update_calls.append((ref, sha, force))
        if force:
            raise ValidationError("force updates are forbidden")
        if sha not in self.commits:
            raise ValidationError("ref target must be a commit")
        if self.ruleset_rejects_updates:
            raise CapabilityError("GitHub ruleset rejected canonical ref update")
        if self.lose_next_ref_response_before_apply:
            self.lose_next_ref_response_before_apply = False
            raise SimulatedLostResponse("ref update response lost before application")
        hook = self.before_next_ref_update
        if hook is not None:
            self.before_next_ref_update = None
            hook(self)
        current = self.refs.get(ref)
        if current is None:
            raise ValidationError("bound GitHub ref does not exist")
        if not self.is_ancestor(repository_id, current, sha):
            raise ConflictError("non-fast-forward GitHub ref update rejected")
        self.refs[ref] = sha
        if self.lose_next_ref_response_after_apply:
            self.lose_next_ref_response_after_apply = False
            raise SimulatedLostResponse("ref updated; response lost")
        return sha

    def create_ref(self, repository_id: str, ref: str, sha: str) -> str:
        self.get_repository(repository_id)
        self._require_write()
        if ref in self.refs or not ref.startswith("refs/heads/") or sha not in self.commits:
            raise ConflictError("GitHub ref cannot be created at the requested identity")
        if self.lose_next_create_ref_response_before_apply:
            self.lose_next_create_ref_response_before_apply = False
            raise SimulatedLostResponse("ref creation response lost before application")
        self.refs[ref] = sha
        if self.lose_next_create_ref_response_after_apply:
            self.lose_next_create_ref_response_after_apply = False
            raise SimulatedLostResponse("ref created; response lost")
        return sha

    def delete_ref(self, repository_id: str, ref: str) -> None:
        raise ValidationError("canonical ref deletion is forbidden")

    def manual_commit(
        self,
        repository_id: str,
        ref: str,
        changes: Mapping[str, bytes | None],
        *,
        message: str = "manual edit",
    ) -> str:
        base = self.get_ref(repository_id, ref)
        base_commit = self.get_commit(repository_id, base)
        tree_changes: dict[str, str | None] = {}
        for path, content in changes.items():
            tree_changes[path] = None if content is None else self.create_blob(repository_id, content)
        tree = self.create_tree(repository_id, base_commit.tree_sha, tree_changes)
        commit = self.create_commit(repository_id, message, tree.sha, (base,))
        self.update_ref(repository_id, ref, commit.sha, force=False)
        return commit.sha

    def rename_ref(self, old_ref: str, new_ref: str) -> None:
        self.refs[new_ref] = self.refs.pop(old_ref)
