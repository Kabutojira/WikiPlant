from __future__ import annotations

import unittest

from wikiplant.errors import ConflictError, SimulatedLostResponse, ValidationError
from wikiplant.fake_drive import FakeDrive
from wikiplant.records import Command
from wikiplant.intake import durable_intake
from wikiplant.authorization import UserAuthorization, request_digest
from wikiplant.storage import Binding, SafeWriter, validate_binding


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.drive = FakeDrive()
        self.root = self.drive.create_folder(None, "instance", idempotency_key="root")
        self.ops = self.drive.create_folder(self.root.id, "operations", idempotency_key="ops")
        self.inbox = self.drive.create_folder(self.root.id, "inbox", idempotency_key="inbox")

    def test_exact_id_raw_roundtrip_unicode_and_identity(self):
        raw = self.drive.create_file(self.root.id, "page.md", "text/markdown", "manual α\n".encode(), idempotency_key="raw")
        lookalike = self.drive.create_file(self.root.id, "page.md", "application/vnd.google-apps.document", b"converted", idempotency_key="lookalike")
        binding = Binding("data/wiki/page.md", raw.id, "text/markdown", self.root.id)
        observed = validate_binding(self.drive, binding, self.root.id)
        writer = SafeWriter(self.drive, self.root.id, self.ops.id, self.inbox.id)
        updated = writer.replace(binding, observed.content + "addition β\n".encode(), "op-1", base=observed)
        self.assertEqual(updated.id, raw.id)
        self.assertEqual(self.drive.read_exact(lookalike.id).content, b"converted")
        self.assertIn("manual α", updated.content.decode())

    def test_truncated_read_and_moved_file_block(self):
        raw = self.drive.create_file(self.root.id, "page.md", "text/markdown", b"abcdef", idempotency_key="raw")
        binding = Binding("data/wiki/page.md", raw.id, "text/markdown", self.root.id)
        self.drive.truncate_reads.add(raw.id)
        with self.assertRaises(ValidationError):
            validate_binding(self.drive, binding, self.root.id)
        self.drive.truncate_reads.clear()
        self.drive.move_outside_scope(raw.id)
        with self.assertRaises(ValidationError):
            validate_binding(self.drive, binding, self.root.id)

    def test_missing_permission_blocks_exact_read(self):
        raw = self.drive.create_file(self.root.id, "private.md", "text/markdown", b"private", idempotency_key="private")
        self.drive.denied_ids.add(raw.id)
        with self.assertRaises(ValidationError):
            self.drive.read_exact(raw.id)

    def test_pagination_exhaustion(self):
        for index in range(7):
            self.drive.create_file(self.root.id, f"f{index}.json", "application/json", b"{}", idempotency_key=f"f{index}")
        self.assertEqual(len(self.drive.list_all(self.root.id, page_size=2)), 9)

    def test_write_lost_response_reconciles_without_duplicate(self):
        raw = self.drive.create_file(self.root.id, "page.md", "text/markdown", b"old", idempotency_key="raw")
        binding = Binding("data/wiki/page.md", raw.id, "text/markdown", self.root.id)
        self.drive.lose_next_write_response = True
        writer = SafeWriter(self.drive, self.root.id, self.ops.id, self.inbox.id)
        result = writer.replace(binding, b"new", "op-1", base=raw)
        self.assertEqual(result.content, b"new")
        self.assertEqual(self.drive.read_exact(raw.id).revision, 2)

    def test_overlap_conflict_preserves_durable_command(self):
        raw = self.drive.create_file(self.root.id, "queue.csv", "text/csv", b"header\n", idempotency_key="queue")
        grant = UserAuthorization("synthetic-turn-1", "wp-test", "add", "note-1", request_digest("Add keep me"), True, "Explicit add directive")
        command = Command("cmd-1", "wp-test", "add", grant.to_dict(), "keep me", "2026-01-15T00:00:00+00:00", target="note-1")
        receipt, command_id = durable_intake(self.drive, self.inbox.id, command, approved_root_id=self.root.id, expected_instance_id="wp-test")
        before = self.drive.read_exact(raw.id)
        self.drive.external_edit(raw.id, b"header\nmanual\n")
        with self.assertRaises(ConflictError):
            self.drive.replace_content(raw.id, b"header\ndaily\n", expected_revision=before.revision, operation_id="daily-op")
        self.assertEqual(receipt, "ACCEPTED_PENDING_MERGE")
        self.assertIn(b"keep me", self.drive.read_exact(command_id).content)
        self.assertIn(b"manual", self.drive.read_exact(raw.id).content)

    def test_create_lost_response_is_idempotent(self):
        self.drive.lose_next_create_response = True
        with self.assertRaises(SimulatedLostResponse):
            self.drive.create_file(self.root.id, "report.md", "text/markdown", b"report", idempotency_key="report-key")
        observed = self.drive.create_file(self.root.id, "report.md", "text/markdown", b"report", idempotency_key="report-key")
        matches = [entry for entry in self.drive.list_all(self.root.id) if entry.name == "report.md"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(observed.content, b"report")


if __name__ == "__main__":
    unittest.main()
