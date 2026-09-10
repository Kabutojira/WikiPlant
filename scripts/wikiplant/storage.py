from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Protocol

from .errors import CapabilityError, ConflictError, SimulatedLostResponse, ValidationError
from .util import pretty_json, safe_relative_path, sha256_bytes, sha256_text


FOLDER_MIME = "application/vnd.google-apps.folder"
RAW_MIME = {
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".yml": "application/yaml",
    ".yaml": "application/yaml",
    ".py": "text/x-python",
}
NATIVE_LOOKALIKES = {"application/vnd.google-apps.document", "application/vnd.google-apps.spreadsheet"}


@dataclass(frozen=True)
class FileSnapshot:
    id: str
    name: str
    parent_id: str | None
    mime_type: str
    content: bytes
    revision: int
    complete: bool
    within_scope: bool

    @property
    def sha256(self) -> str:
        return sha256_bytes(self.content)


class DriveAdapter(Protocol):
    def create_folder(self, parent_id: str | None, name: str, *, idempotency_key: str) -> FileSnapshot: ...
    def create_file(self, parent_id: str, name: str, mime_type: str, content: bytes, *, idempotency_key: str) -> FileSnapshot: ...
    def read_exact(self, file_id: str) -> FileSnapshot: ...
    def replace_content(self, file_id: str, content: bytes, *, expected_revision: int | None, operation_id: str) -> FileSnapshot: ...
    def list_children(self, parent_id: str, *, page_token: str | None, page_size: int) -> tuple[list[FileSnapshot], str | None]: ...


@dataclass(frozen=True)
class Binding:
    logical_path: str
    file_id: str
    mime_type: str
    root_id: str


def validate_binding(adapter: DriveAdapter, binding: Binding, approved_root_id: str) -> FileSnapshot:
    safe_relative_path(binding.logical_path)
    if binding.root_id != approved_root_id:
        raise ValidationError("binding root does not match this instance")
    snapshot = adapter.read_exact(binding.file_id)
    validate_scope(adapter, snapshot.id, approved_root_id)
    if not snapshot.complete:
        raise ValidationError("complete raw read is required before replacement")
    if not snapshot.within_scope:
        raise ValidationError("mapped file is outside approved scope")
    if snapshot.mime_type != binding.mime_type or snapshot.mime_type in NATIVE_LOOKALIKES:
        raise ValidationError("mapped MIME type mismatch or native look-alike")
    return snapshot


def validate_scope(adapter: DriveAdapter, file_id: str, root_id: str, *, folder: bool = False) -> FileSnapshot:
    """Observe ancestry by ID; a provider's broad account scope is insufficient."""
    snapshot = adapter.read_exact(file_id)
    if folder and snapshot.mime_type != FOLDER_MIME:
        raise ValidationError("destination must be a folder")
    current = snapshot
    visited: set[str] = set()
    while True:
        if current.id in visited or not current.within_scope or not current.complete:
            raise ValidationError("incomplete or invalid scoped ancestry")
        visited.add(current.id)
        if current.id == root_id:
            return snapshot
        if not current.parent_id:
            raise ValidationError("file is not inside the bound instance")
        current = adapter.read_exact(current.parent_id)
        if current.mime_type != FOLDER_MIME:
            raise ValidationError("ancestry contains a non-folder")


def inventory(adapter: DriveAdapter, folder_id: str) -> list[FileSnapshot]:
    found: list[FileSnapshot] = []
    token = None
    seen = set()
    while True:
        page, token = adapter.list_children(folder_id, page_token=token, page_size=100)
        found.extend(page)
        if token is None:
            return found
        if token in seen:
            raise ValidationError("inventory pagination did not advance")
        seen.add(token)


def find_artifact(adapter: DriveAdapter, root_id: str, folder_id: str, name: str) -> FileSnapshot | None:
    validate_scope(adapter, folder_id, root_id, folder=True)
    matches = [f for f in inventory(adapter, folder_id) if f.name == name]
    if len(matches) > 1:
        raise ConflictError("ambiguous immutable artifact identity")
    if not matches:
        return None
    value = validate_scope(adapter, matches[0].id, root_id)
    if value.mime_type != "application/json":
        raise ValidationError("immutable artifact must be raw JSON")
    return value


def create_artifact(adapter: DriveAdapter, root_id: str, folder_id: str, name: str, payload: dict, key: str) -> FileSnapshot:
    """Create immutable evidence; reconcile uncertain responses by inventory, never blind retry."""
    safe_relative_path(name)
    if "/" in name:
        raise ValidationError("artifact name must be a single component")
    content = pretty_json(payload).encode()
    observed = find_artifact(adapter, root_id, folder_id, name)
    if observed is None:
        try:
            observed = adapter.create_file(folder_id, name, "application/json", content, idempotency_key=key)
        except SimulatedLostResponse:
            observed = find_artifact(adapter, root_id, folder_id, name)
            if observed is None:
                raise ConflictError("create outcome unknown; reconcile before a later retry")
    observed = validate_scope(adapter, observed.id, root_id)
    if observed.parent_id != folder_id or observed.name != name or observed.mime_type != "application/json" or observed.content != content:
        raise ConflictError("immutable artifact ID reused with different intent")
    return observed


def create_raw_file(adapter: DriveAdapter, root_id: str, folder_id: str, name: str,
                    mime: str, content: bytes, key: str) -> FileSnapshot:
    """Immutable raw deliverable with scoped inventory/readback reconciliation."""
    validate_scope(adapter, folder_id, root_id, folder=True)
    safe_relative_path(name)
    if "/" in name or mime in NATIVE_LOOKALIKES or mime == FOLDER_MIME:
        raise ValidationError("invalid raw artifact name or MIME")
    def lookup():
        matches = [f for f in inventory(adapter, folder_id) if f.name == name]
        if len(matches) > 1:
            raise ConflictError("ambiguous raw artifact; reconcile duplicates")
        return validate_scope(adapter, matches[0].id, root_id) if matches else None
    observed = lookup()
    if observed is None:
        try:
            observed = adapter.create_file(folder_id, name, mime, content, idempotency_key=key)
        except SimulatedLostResponse:
            observed = lookup()
            if observed is None:
                raise ConflictError("raw create remains ambiguous")
    observed = validate_scope(adapter, observed.id, root_id)
    if observed.parent_id != folder_id or observed.name != name or observed.mime_type != mime or observed.content != content:
        raise ConflictError("raw artifact identity/content conflict")
    return observed


@dataclass(frozen=True)
class WriteReceipt:
    operation_id: str
    target_id: str
    verified_sha256: str
    verified_revision: int
    completion_reference: str
    current: FileSnapshot
    replayed: bool = False

    @property
    def id(self) -> str:
        return self.target_id

    @property
    def content(self) -> bytes:
        """Current bytes; compare current.sha256 to verified_sha256 for historical receipt."""
        return self.current.content


def expected_mime(path: str) -> str:
    for suffix, mime in RAW_MIME.items():
        if path.endswith(suffix):
            return mime
    return "text/plain"


class SafeWriter:
    """Journaled exact-ID writes and unique durable intake for one instance."""

    def __init__(self, adapter: DriveAdapter, approved_root_id: str, operations_folder_id: str, inbox_folder_id: str, *, instance_id: str | None = None):
        self.adapter = adapter
        self.root_id = approved_root_id
        self.operations_folder_id = operations_folder_id
        self.inbox_folder_id = inbox_folder_id
        self.instance_id = instance_id or approved_root_id

    def submit_command(self, command: dict, command_id: str) -> FileSnapshot:
        if command.get("instance_id") != self.instance_id:
            raise ValidationError("command instance mismatch")
        from .records import Command
        Command(**command).validate()
        return create_artifact(self.adapter, self.root_id, self.inbox_folder_id,
                               f"command-{sha256_text(command_id)}.json", command,
                               f"{self.instance_id}:command:{command_id}")

    def replace(self, binding: Binding, content: bytes, operation_id: str, *, base: FileSnapshot,
                authorization: dict | None = None) -> WriteReceipt:
        if not operation_id:
            raise ValidationError("operation ID is required")
        if not getattr(self.adapter, "conditional_write", False) or not getattr(self.adapter, "idempotent_create", False):
            raise CapabilityError("canonical writes require observed conditional writes and unique intent creation; preserve intake")
        before = validate_binding(self.adapter, binding, self.root_id)
        validate_scope(self.adapter, self.operations_folder_id, self.root_id, folder=True)
        if (base.id != binding.file_id or base.mime_type != binding.mime_type or not base.complete or not base.within_scope):
            raise ValidationError("invalid generation base snapshot")
        stem = f"operation-{sha256_text(operation_id)}"
        original = find_artifact(self.adapter, self.root_id, self.operations_folder_id, stem + ".intent.json")
        intent = {
            "schema_version": 2,
            "instance_id": self.instance_id,
            "root_id": self.root_id,
            "operation_id": operation_id,
            "target_id": binding.file_id,
            "logical_path": binding.logical_path,
            "input_sha256": base.sha256,
            "input_revision": base.revision,
            "input_parent_id": base.parent_id,
            "output_sha256": sha256_bytes(content),
            "authorization": authorization,
            "stage": "INTENT_SAVED",
        }
        if original and json.loads(original.content) != intent:
            raise ConflictError("operation ID was already bound to a different original intent")
        completed = find_artifact(self.adapter, self.root_id, self.operations_folder_id, stem + ".complete.json")
        if completed:
            if original is None:
                raise ConflictError("completion has no original intent")
            result = json.loads(completed.content)
            if (result.get("intent_sha256") != original.sha256 or result.get("stage") != "COMPLETE"
                    or any(result.get(key) != intent[key] for key in ("schema_version", "operation_id", "instance_id", "target_id", "output_sha256"))
                    or type(result.get("output_revision")) is not int):
                raise ConflictError("completion identity does not match original intent")
            return WriteReceipt(operation_id, binding.file_id, result["output_sha256"], result["output_revision"], completed.id, before, True)
        if not original and (before.sha256 != base.sha256 or before.revision != base.revision or before.parent_id != base.parent_id):
            raise ConflictError("target changed since content was generated")
        journal = create_artifact(self.adapter, self.root_id, self.operations_folder_id,
                                  stem + ".intent.json", intent, f"{self.instance_id}:intent:{operation_id}")
        if before.sha256 != intent["output_sha256"]:
            if before.sha256 != base.sha256 or before.revision != base.revision or before.parent_id != base.parent_id:
                raise ConflictError("unfinished operation conflicts with later target edits")
            try:
                self.adapter.replace_content(binding.file_id, content, expected_revision=base.revision,
                                             operation_id=f"{self.instance_id}:{operation_id}")
            except SimulatedLostResponse:
                pass  # The following independent read reconciles the actual target.
        after = validate_binding(self.adapter, binding, self.root_id)
        if not after.complete or after.sha256 != sha256_bytes(content) or after.id != before.id:
            raise ConflictError("write readback did not verify exact target/content")
        result = {"schema_version": 2, "operation_id": operation_id, "instance_id": self.instance_id,
                  "target_id": after.id, "intent_sha256": journal.sha256, "output_sha256": after.sha256,
                  "output_revision": after.revision, "stage": "COMPLETE"}
        completed = create_artifact(self.adapter, self.root_id, self.operations_folder_id,
                                    stem + ".complete.json", result, f"{self.instance_id}:complete:{operation_id}")
        return WriteReceipt(operation_id, after.id, after.sha256, after.revision, completed.id, after)
