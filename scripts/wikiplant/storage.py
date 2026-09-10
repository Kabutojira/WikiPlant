from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Callable, Protocol

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
STRICT_CONSISTENCY = "strict"
BEST_EFFORT_PERSONAL = "best-effort-personal"
BEST_EFFORT_LOCK_HOURS = 20


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


def initial_lock_record(instance_id: str) -> dict:
    """Return the permanent, unlocked personal-instance lock payload."""
    if not instance_id:
        raise ValidationError("lock instance ID is required")
    return {
        "schema_version": 1,
        "kind": "wikiplant-personal-run-lock",
        "instance_id": instance_id,
        "mode": BEST_EFFORT_PERSONAL,
        "status": "unlocked",
        "owner_token": None,
        "acquired_at": None,
        "expires_at": None,
        "released_at": None,
        "stale_after_hours": BEST_EFFORT_LOCK_HOURS,
        "warning": "Best-effort only: Google Drive lock replacement is not atomic.",
    }


@dataclass(frozen=True)
class LockReceipt:
    lock_file_id: str
    owner_token: str
    acquired_at: str
    expires_at: str
    recovered_stale_lock: bool
    observed_revision: int


class PermanentDriveLock:
    """A deliberately non-atomic, permanent lock record for personal instances.

    This reduces accidental overlap on connectors that expose only read/replace.
    It must never be represented as provider serialization or an atomic lock.
    """

    def __init__(self, adapter: DriveAdapter, binding: Binding, approved_root_id: str, *, instance_id: str):
        self.adapter = adapter
        self.binding = binding
        self.root_id = approved_root_id
        self.instance_id = instance_id
        if binding.mime_type != "application/json":
            raise ValidationError("permanent lock must be a raw JSON file")

    def _read(self) -> tuple[FileSnapshot, dict]:
        snapshot = validate_binding(self.adapter, self.binding, self.root_id)
        try:
            record = json.loads(snapshot.content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConflictError("permanent lock record is unreadable; do not start research") from exc
        expected = initial_lock_record(self.instance_id)
        if (not isinstance(record, dict)
                or record.get("schema_version") != expected["schema_version"]
                or record.get("kind") != expected["kind"]
                or record.get("instance_id") != self.instance_id
                or record.get("mode") != BEST_EFFORT_PERSONAL
                or record.get("stale_after_hours") != BEST_EFFORT_LOCK_HOURS
                or record.get("status") not in {"locked", "unlocked"}):
            raise ConflictError("permanent lock record is invalid or belongs to another instance")
        return snapshot, record

    @staticmethod
    def _now(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValidationError("lock time must include a UTC offset")
        return value.astimezone(timezone.utc)

    def _expiry(self, record: dict) -> datetime:
        acquired = record.get("acquired_at")
        expires = record.get("expires_at")
        if not acquired or not expires:
            raise ConflictError("locked record lacks acquisition/expiry timestamps")
        try:
            acquired_at = datetime.fromisoformat(acquired.replace("Z", "+00:00"))
            expires_at = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise ConflictError("locked record has an invalid timestamp") from exc
        if (acquired_at.tzinfo is None or expires_at.tzinfo is None
                or expires_at != acquired_at + timedelta(hours=BEST_EFFORT_LOCK_HOURS)):
            raise ConflictError("locked record expiry is not exactly 20 hours after acquisition")
        return expires_at.astimezone(timezone.utc)

    def acquire(self, owner_token: str, now: datetime) -> LockReceipt:
        if not owner_token or len(owner_token) > 256:
            raise ValidationError("a bounded nonempty lock owner token is required")
        observed_now = self._now(now)
        before, current = self._read()
        recovered = False
        if current["status"] == "locked":
            expires_at = self._expiry(current)
            if current.get("owner_token") == owner_token and observed_now < expires_at:
                return LockReceipt(before.id, owner_token, current["acquired_at"], current["expires_at"], False, before.revision)
            if observed_now < expires_at:
                raise CapabilityError(f"best-effort personal-instance lock is held until {current['expires_at']}; do not start research")
            recovered = True
        acquired_at = observed_now.isoformat()
        expires_at = (observed_now + timedelta(hours=BEST_EFFORT_LOCK_HOURS)).isoformat()
        payload = initial_lock_record(self.instance_id)
        payload.update({
            "status": "locked",
            "owner_token": owner_token,
            "acquired_at": acquired_at,
            "expires_at": expires_at,
            "released_at": None,
            "recovered_stale_lock": recovered,
        })
        content = pretty_json(payload).encode()
        try:
            self.adapter.replace_content(before.id, content, expected_revision=None,
                                         operation_id=f"{self.instance_id}:personal-lock:acquire:{owner_token}")
        except SimulatedLostResponse:
            pass
        after, verified = self._read()
        if after.id != before.id or after.content != content or verified.get("owner_token") != owner_token:
            raise ConflictError("best-effort lock acquisition lost a race; do not start research")
        return LockReceipt(after.id, owner_token, acquired_at, expires_at, recovered, after.revision)

    def assert_held(self, owner_token: str, now: datetime) -> str:
        observed_now = self._now(now)
        snapshot, record = self._read()
        if record["status"] != "locked" or record.get("owner_token") != owner_token:
            raise CapabilityError("best-effort personal-instance lock ownership was not observed")
        if observed_now >= self._expiry(record):
            raise CapabilityError("best-effort personal-instance lock is older than 20 hours; stop research")
        return f"best-effort-personal-lock:{snapshot.id}:{snapshot.revision}:{owner_token}"

    def release(self, owner_token: str, now: datetime) -> FileSnapshot:
        observed_now = self._now(now)
        before, current = self._read()
        if current["status"] == "unlocked":
            return before
        if current.get("owner_token") != owner_token:
            raise ConflictError("refusing to release a lock owned by another run")
        payload = initial_lock_record(self.instance_id)
        payload.update({
            "released_at": observed_now.isoformat(),
            "last_owner_token": owner_token,
            "last_acquired_at": current.get("acquired_at"),
        })
        content = pretty_json(payload).encode()
        try:
            self.adapter.replace_content(before.id, content, expected_revision=None,
                                         operation_id=f"{self.instance_id}:personal-lock:release:{owner_token}")
        except SimulatedLostResponse:
            pass
        after, verified = self._read()
        if after.content != content or verified["status"] != "unlocked":
            raise ConflictError("best-effort lock release did not verify; later runs must inspect its timestamp")
        return after


class SafeWriter:
    """Journaled exact-ID writes and unique durable intake for one instance."""

    def __init__(self, adapter: DriveAdapter, approved_root_id: str, operations_folder_id: str, inbox_folder_id: str, *,
                 instance_id: str | None = None, consistency_mode: str = STRICT_CONSISTENCY,
                 personal_lock: PermanentDriveLock | None = None, lock_owner_token: str | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.adapter = adapter
        self.root_id = approved_root_id
        self.operations_folder_id = operations_folder_id
        self.inbox_folder_id = inbox_folder_id
        self.instance_id = instance_id or approved_root_id
        self.consistency_mode = consistency_mode
        self.personal_lock = personal_lock
        self.lock_owner_token = lock_owner_token
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        if consistency_mode not in {STRICT_CONSISTENCY, BEST_EFFORT_PERSONAL}:
            raise ValidationError("unknown storage consistency mode")
        if consistency_mode == BEST_EFFORT_PERSONAL and (personal_lock is None or not lock_owner_token):
            raise ValidationError("best-effort personal writer requires a permanent lock and owner token")

    def execution_guard(self) -> str:
        if self.consistency_mode == BEST_EFFORT_PERSONAL:
            assert self.personal_lock is not None and self.lock_owner_token is not None
            return self.personal_lock.assert_held(self.lock_owner_token, self.clock())
        return ""

    def _require_canonical_guard(self) -> None:
        strong = bool(getattr(self.adapter, "conditional_write", False) and getattr(self.adapter, "idempotent_create", False))
        if self.consistency_mode == BEST_EFFORT_PERSONAL:
            self.execution_guard()
            return
        if strong:
            return
        raise CapabilityError("canonical writes require observed conditional writes and unique intent creation; preserve intake")

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
        self._require_canonical_guard()
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
