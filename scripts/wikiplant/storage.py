from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .errors import ConflictError, SimulatedLostResponse, ValidationError
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
    if not snapshot.complete:
        raise ValidationError("complete raw read is required before replacement")
    if not snapshot.within_scope:
        raise ValidationError("mapped file is outside approved scope")
    if snapshot.mime_type != binding.mime_type or snapshot.mime_type in NATIVE_LOOKALIKES:
        raise ValidationError("mapped MIME type mismatch or native look-alike")
    return snapshot


def expected_mime(path: str) -> str:
    for suffix, mime in RAW_MIME.items():
        if path.endswith(suffix):
            return mime
    return "text/plain"


class SafeWriter:
    """Journaled exact-ID writes and unique durable intake for one instance."""

    def __init__(self, adapter: DriveAdapter, approved_root_id: str, operations_folder_id: str, inbox_folder_id: str):
        self.adapter = adapter
        self.root_id = approved_root_id
        self.operations_folder_id = operations_folder_id
        self.inbox_folder_id = inbox_folder_id

    def submit_command(self, command: dict, command_id: str) -> FileSnapshot:
        payload = pretty_json(command).encode("utf-8")
        return self.adapter.create_file(
            self.inbox_folder_id,
            f"{command_id}.json",
            "application/json",
            payload,
            idempotency_key=f"command:{command_id}",
        )

    def replace(self, binding: Binding, content: bytes, operation_id: str) -> FileSnapshot:
        before = validate_binding(self.adapter, binding, self.root_id)
        intent = {
            "schema_version": 1,
            "operation_id": operation_id,
            "target_id": binding.file_id,
            "logical_path": binding.logical_path,
            "input_sha256": before.sha256,
            "input_revision": before.revision,
            "output_sha256": sha256_bytes(content),
            "stage": "INTENT_SAVED",
        }
        journal_name = f"operation-{sha256_text(operation_id)[:24]}.json"
        journal_payload = pretty_json(intent).encode()
        try:
            journal = self.adapter.create_file(
                self.operations_folder_id, journal_name, "application/json", journal_payload,
                idempotency_key=f"operation-intent:{operation_id}",
            )
        except SimulatedLostResponse:
            journal = self.adapter.create_file(
                self.operations_folder_id, journal_name, "application/json", journal_payload,
                idempotency_key=f"operation-intent:{operation_id}",
            )
        try:
            self.adapter.replace_content(
                binding.file_id,
                content,
                expected_revision=before.revision,
                operation_id=operation_id,
            )
        except SimulatedLostResponse:
            observed = self.adapter.read_exact(binding.file_id)
            if not observed.complete or observed.sha256 != sha256_bytes(content):
                raise ConflictError("ambiguous write could not be reconciled")
        after = self.adapter.read_exact(binding.file_id)
        if not after.complete or after.sha256 != sha256_bytes(content) or after.id != before.id:
            raise ConflictError("write readback did not verify exact target/content")
        intent["stage"] = "COMPLETE"
        intent["output_revision"] = after.revision
        completed = pretty_json(intent).encode()
        journal_before = self.adapter.read_exact(journal.id)
        try:
            self.adapter.replace_content(
                journal.id, completed, expected_revision=journal_before.revision,
                operation_id=f"{operation_id}:finalize-journal",
            )
        except SimulatedLostResponse:
            if self.adapter.read_exact(journal.id).content != completed:
                raise ConflictError("operation completed but journal finalization is ambiguous")
        return after
