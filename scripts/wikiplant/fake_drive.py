from __future__ import annotations

from dataclasses import dataclass

from .errors import ConflictError, SimulatedLostResponse, ValidationError
from .storage import FOLDER_MIME, NATIVE_LOOKALIKES, FileSnapshot
from .util import sha256_bytes


@dataclass
class _Entry:
    id: str
    name: str
    parent_id: str | None
    mime_type: str
    content: bytes = b""
    revision: int = 1
    within_scope: bool = True


class FakeDrive:
    """In-memory Drive with IDs, revisions, pagination, and failure injection."""

    def __init__(self) -> None:
        self.conditional_write = True
        self.idempotent_create = True
        self.entries: dict[str, _Entry] = {}
        self.idempotency: dict[str, str] = {}
        self.applied_operations: dict[str, str] = {}
        self.lose_next_create_response = False
        self.lose_next_write_response = False
        self.truncate_reads: set[str] = set()
        self.denied_ids: set[str] = set()
        self.public_parents: set[str] = set()
        self._counter = 0

    def _id(self) -> str:
        self._counter += 1
        return f"drv-{self._counter:06d}"

    def _snapshot(self, entry: _Entry) -> FileSnapshot:
        complete = entry.id not in self.truncate_reads
        content = entry.content if complete else entry.content[: max(1, len(entry.content) // 2)]
        return FileSnapshot(entry.id, entry.name, entry.parent_id, entry.mime_type, content, entry.revision, complete, entry.within_scope)

    def create_folder(self, parent_id: str | None, name: str, *, idempotency_key: str) -> FileSnapshot:
        return self._create(parent_id, name, FOLDER_MIME, b"", idempotency_key)

    def create_file(self, parent_id: str, name: str, mime_type: str, content: bytes, *, idempotency_key: str) -> FileSnapshot:
        if parent_id not in self.entries or self.entries[parent_id].mime_type != FOLDER_MIME:
            raise ValidationError("file parent must be an existing folder")
        return self._create(parent_id, name, mime_type, content, idempotency_key)

    def _create(self, parent_id: str | None, name: str, mime_type: str, content: bytes, key: str) -> FileSnapshot:
        if key in self.idempotency:
            return self.read_exact(self.idempotency[key])
        entry = _Entry(self._id(), name, parent_id, mime_type, content)
        self.entries[entry.id] = entry
        self.idempotency[key] = entry.id
        result = self._snapshot(entry)
        if self.lose_next_create_response:
            self.lose_next_create_response = False
            raise SimulatedLostResponse("create applied; response lost")
        return result

    def read_exact(self, file_id: str) -> FileSnapshot:
        if file_id in self.denied_ids:
            raise ValidationError("Drive permission denied")
        try:
            return self._snapshot(self.entries[file_id])
        except KeyError as exc:
            raise ValidationError(f"unknown Drive id: {file_id}") from exc

    def replace_content(self, file_id: str, content: bytes, *, expected_revision: int | None, operation_id: str) -> FileSnapshot:
        if file_id in self.denied_ids:
            raise ValidationError("Drive permission denied")
        entry = self.entries.get(file_id)
        if entry is None:
            raise ValidationError("unknown Drive id")
        if entry.mime_type in NATIVE_LOOKALIKES or entry.mime_type == FOLDER_MIME:
            raise ValidationError("canonical raw content cannot target a native look-alike/folder")
        if not entry.within_scope:
            raise ValidationError("mapped file moved outside approved instance scope")
        digest = sha256_bytes(content)
        if operation_id in self.applied_operations:
            if self.applied_operations[operation_id] != (file_id, digest):
                raise ConflictError("operation id was already used for different content")
            return self._snapshot(entry)
        if expected_revision is not None and entry.revision != expected_revision:
            raise ConflictError("revision precondition failed")
        entry.content = content
        entry.revision += 1
        self.applied_operations[operation_id] = (file_id, digest)
        result = self._snapshot(entry)
        if self.lose_next_write_response:
            self.lose_next_write_response = False
            raise SimulatedLostResponse("write applied; response lost")
        return result

    def list_children(self, parent_id: str, *, page_token: str | None = None, page_size: int = 100) -> tuple[list[FileSnapshot], str | None]:
        children = sorted((entry for entry in self.entries.values() if entry.parent_id == parent_id), key=lambda entry: (entry.name, entry.id))
        start = int(page_token or "0")
        selected = children[start : start + page_size]
        next_token = str(start + page_size) if start + page_size < len(children) else None
        return [self._snapshot(entry) for entry in selected], next_token

    def list_all(self, parent_id: str, page_size: int = 100) -> list[FileSnapshot]:
        output: list[FileSnapshot] = []
        token: str | None = None
        while True:
            page, token = self.list_children(parent_id, page_token=token, page_size=page_size)
            output.extend(page)
            if token is None:
                return output

    def move_outside_scope(self, file_id: str) -> None:
        self.entries[file_id].within_scope = False

    def external_edit(self, file_id: str, content: bytes) -> None:
        entry = self.entries[file_id]
        entry.content = content
        entry.revision += 1


class WeakDrive(FakeDrive):
    """No conditional writes or global idempotency table: never a safe canonical writer."""

    def __init__(self) -> None:
        super().__init__()
        self.conditional_write = False
        self.idempotent_create = False

    def _create(self, parent_id, name, mime_type, content, key):
        self.idempotency.clear()
        return super()._create(parent_id, name, mime_type, content, key)

    def replace_content(self, file_id, content, *, expected_revision, operation_id):
        self.applied_operations.clear()
        return super().replace_content(file_id, content, expected_revision=None, operation_id=operation_id)
