from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class StorageBinding:
    """Provider-neutral identity for exactly one authoritative store."""

    provider: str
    container_id: str
    logical_root: str
    generation_locator: str


@dataclass(frozen=True)
class ObjectSnapshot:
    logical_path: str
    content: bytes
    media_type: str
    content_hash: str
    provider_revision: str
    generation_id: str
    complete: bool = True
    within_scope: bool = True


@dataclass(frozen=True)
class StorageTransaction:
    """A mutation bound to an immutable generation and original intent.

    Every target path must have an expected input hash. ``None`` means that the
    path was observed absent at ``base_generation``.
    """

    instance_id: str
    operation_id: str
    base_generation: str
    original_intent: Mapping[str, Any]
    writes: Mapping[str, bytes]
    deletes: tuple[str, ...]
    expected_input_hashes: Mapping[str, str | None]
    authorization_reference: str | None = None


@dataclass(frozen=True)
class TransactionReceipt:
    operation_id: str
    base_generation: str
    committed_generation: str
    current_generation: str
    changed_paths_and_hashes: Mapping[str, str | None]
    verification_reference: str
    replayed: bool = False


class StorageAdapter(Protocol):
    binding: StorageBinding

    def current_generation(self) -> str: ...

    def read_exact(self, logical_path: str, *, generation: str | None = None) -> ObjectSnapshot: ...

    def inventory(self, *, generation: str | None = None) -> list[ObjectSnapshot]: ...

    def persist_immutable_intake(
        self,
        logical_path: str,
        content: bytes,
        *,
        instance_id: str,
        operation_id: str,
        authorization_reference: str | None = None,
    ) -> TransactionReceipt: ...

    def commit_transaction(self, transaction: StorageTransaction) -> TransactionReceipt: ...

    def reconcile_operation(self, transaction: StorageTransaction) -> TransactionReceipt | None: ...

    def verify_generation(self, receipt: TransactionReceipt) -> bool: ...
