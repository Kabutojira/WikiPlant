from __future__ import annotations

import json
from pathlib import Path
import unittest

from wikiplant.authorization import UserAuthorization, request_digest
from wikiplant.errors import CapabilityError, ConflictError, ValidationError
from wikiplant.fake_github import FakeGitHub
from wikiplant.github_storage import GitHubLimits, GitHubStorageAdapter
from wikiplant.storage_contract import StorageBinding, StorageTransaction
from wikiplant.topics import Topic, TopicRegistry
from wikiplant.util import sha256_bytes
from wikiplant.yamlio import dumps as yaml_dumps, loads as yaml_loads


ROOT = Path(__file__).resolve().parents[2]
INSTANCE = "wp-0123456789abcdef"
NEW_INSTANCE = "wp-1111111111111111"
FOREIGN_INSTANCE = "wp-2222222222222222"
STAMP = "2026-09-12T12:00:00+00:00"


class GitHubStorageTests(unittest.TestCase):
    def setUp(self):
        self.github = FakeGitHub()
        self.repo_id = self.github.repository.id
        self.ref = "refs/heads/wikiplant-data"
        self.anchor = self.github.initial_commit_sha
        self.github.manual_commit(
            self.repo_id,
            self.ref,
            {
                "INSTANCE.json": self.instance_bytes(INSTANCE),
                "config.yml": self.config_bytes(INSTANCE),
                "data/TOPICS.md": self.topic_bytes(INSTANCE),
                "data/wiki/a.md": b"alpha\n",
                "data/wiki/b.md": b"beta\n",
            },
            message="seed",
        )
        self.binding = StorageBinding("github", self.repo_id, "", self.ref)
        self.adapter = GitHubStorageAdapter(
            self.github, self.binding, instance_id=INSTANCE,
            expected_repository="owner/private-wikiplant",
            ancestry_anchor=self.anchor,
        )

    def instance_bytes(
        self, instance_id, *, repository="owner/private-wikiplant",
        repository_id=None, ref=None, anchor=None,
    ):
        return json.dumps({
            "schema_version": 2,
            "instance_id": instance_id,
            "runtime_release_id": "0.3.0",
            "source_commit": "a" * 40,
            "storage": {
                "provider": "github", "repository_id": repository_id or self.repo_id,
                "repository": repository, "canonical_ref": ref or self.ref, "root_prefix": "",
                "repository_visibility": "private", "app_installation_id": "app-fixture",
                "capability_profile_path": "installation/capability-profile.json",
                "first_verified_commit": anchor or self.anchor,
            },
        }).encode()

    def config_bytes(
        self, instance_id, *, repository="owner/private-wikiplant",
        repository_id=None, ref=None,
    ):
        config = yaml_loads((ROOT / "config.example.yml").read_text())
        config["instance"] = {
            "id": instance_id, "name": "GitHub storage fixture",
            "language": "en", "timezone": "UTC",
        }
        config["storage"] = {
            "provider": "github", "repository_id": repository_id or self.repo_id,
            "repository": repository, "canonical_ref": ref or self.ref,
            "root_prefix": "", "consistency_mode": "git-fast-forward",
            "limits": {
                "max_file_bytes": 512_000, "max_transaction_bytes": 8_000_000,
                "max_repository_bytes": 500_000_000, "max_paths_per_transaction": 200,
            },
        }
        config["runtime"] = {
            "release_id": "0.3.0", "source_commit": "a" * 40,
            "manifest_sha256": "b" * 64, "upgrades": "explicit-user-request",
        }
        config["skill"]["installed_reference"] = "skill-fixture"
        config["primary_topic_ids"] = ["topic-1"]
        config["schedules"] = {
            "daily": {"local_time": "07:00"},
            "weekly": {"weekday": "monday", "local_time": "05:00"},
        }
        return yaml_dumps(config).encode()

    def topic_bytes(self, instance_id):
        grant = UserAuthorization(
            "turn-track", instance_id, "track", "topic-1",
            request_digest("track the synthetic GitHub fixture topic"), True,
            "explicit synthetic tracking request",
        ).to_dict()
        registry = TopicRegistry(instance_id, 1, [Topic(
            id="topic-1", label="Fixture topic", classification="user",
            user_anchor_ids=["topic-1"], parent_ids=[],
            direct_contribution="Explicit fixture scope",
            classification_reason="Authorized fixture", added_at=STAMP,
            reviewed_at=STAMP, scope_revision=1, authorization=grant,
        )])
        return registry.render().encode()

    def transaction(self, operation_id="op-1", *, writes=None, deletes=()):
        writes = writes or {
            "data/wiki/a.md": b"alpha changed\n",
            "data/wiki/b.md": b"beta changed\n",
        }
        base = self.adapter.current_generation()
        targets = set(writes) | set(deletes)
        entries = {item.logical_path: item for item in self.adapter.inventory(generation=base)}
        expected = {path: entries[path].content_hash if path in entries else None for path in targets}
        return StorageTransaction(
            instance_id=INSTANCE,
            operation_id=operation_id,
            base_generation=base,
            original_intent={"action": "synthetic update", "version": 1},
            writes=writes,
            deletes=tuple(deletes),
            expected_input_hashes=expected,
            authorization_reference="turn:test",
        )

    def test_exact_generation_read_and_truncated_inventory_fallback(self):
        base = self.adapter.current_generation()
        self.github.truncate_next_recursive_tree = True
        inventory = self.adapter.inventory(generation=base)
        self.assertEqual(
            {item.logical_path for item in inventory},
            {"INSTANCE.json", "config.yml", "data/TOPICS.md", "data/wiki/a.md", "data/wiki/b.md"},
        )
        a = self.adapter.read_exact("data/wiki/a.md", generation=base)
        self.assertEqual(a.content, b"alpha\n")
        self.assertEqual(a.generation_id, base)
        self.assertEqual(a.content_hash, sha256_bytes(a.content))

    def test_bootstrap_atomically_binds_an_initialized_empty_private_repository(self):
        github = FakeGitHub(repository_id="repo-empty")
        binding = StorageBinding("github", "repo-empty", "", self.ref)
        adapter = GitHubStorageAdapter(
            github, binding, instance_id=NEW_INSTANCE,
            expected_repository="owner/private-wikiplant",
            ancestry_anchor=github.initial_commit_sha,
        )
        empty_head = adapter.current_generation()
        initial = {
            "INSTANCE.json": self.instance_bytes(
                NEW_INSTANCE, repository_id="repo-empty", anchor=github.initial_commit_sha
            ),
            "config.yml": self.config_bytes(NEW_INSTANCE, repository_id="repo-empty"),
            "data/TOPICS.md": self.topic_bytes(NEW_INSTANCE),
            "data/SCOPE.md": b"# Scope\n",
        }
        receipt = adapter.bootstrap(
            initial, expected_generation=empty_head, operation_id="install-wp-new"
        )
        commit = github.get_commit("repo-empty", receipt.committed_generation)
        self.assertEqual(commit.parents, (empty_head,))
        self.assertEqual(adapter.read_exact("data/SCOPE.md").content, b"# Scope\n")
        self.assertIn(
            "data/state/operations/bootstrap-",
            "\n".join(item.logical_path for item in adapter.inventory()),
        )
        later = github.manual_commit(
            "repo-empty", self.ref, {"data/wiki/later.md": b"later\n"}, message="later"
        )
        replay = adapter.bootstrap(
            initial, expected_generation=empty_head, operation_id="install-wp-new"
        )
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.committed_generation, receipt.committed_generation)
        self.assertEqual(replay.current_generation, later)

    def test_bootstrap_rejects_nonempty_or_mismatched_instance(self):
        github = FakeGitHub(repository_id="repo-empty")
        binding = StorageBinding("github", "repo-empty", "", self.ref)
        adapter = GitHubStorageAdapter(
            github, binding, instance_id=NEW_INSTANCE,
            expected_repository="owner/private-wikiplant",
            ancestry_anchor=github.initial_commit_sha,
        )
        base = adapter.current_generation()
        with self.assertRaises(ValidationError):
            adapter.bootstrap(
                {"INSTANCE.json": json.dumps({
                    "instance_id": "other", "storage": {
                        "provider": "github", "repository_id": "repo-empty",
                        "repository": "owner/private-wikiplant",
                        "canonical_ref": self.ref, "root_prefix": "",
                        "repository_visibility": "private", "app_installation_id": "app-fixture",
                        "capability_profile_path": "installation/capability-profile.json",
                        "first_verified_commit": github.initial_commit_sha,
                    },
                }).encode()},
                expected_generation=base,
                operation_id="bad",
            )
        github.manual_commit("repo-empty", self.ref, {"README.md": b"occupied"})
        with self.assertRaises(ConflictError):
            adapter.bootstrap(
                {
                    "INSTANCE.json": self.instance_bytes(
                        NEW_INSTANCE, repository_id="repo-empty",
                        anchor=github.initial_commit_sha,
                    ),
                    "config.yml": self.config_bytes(NEW_INSTANCE, repository_id="repo-empty"),
                    "data/TOPICS.md": self.topic_bytes(NEW_INSTANCE),
                },
                expected_generation=base,
                operation_id="occupied",
            )

    def test_atomic_multi_file_transaction_has_one_visibility_commit(self):
        transaction = self.transaction(deletes=("data/wiki/b.md",), writes={
            "data/wiki/a.md": b"new alpha\n",
            "data/wiki/c.md": b"new gamma\n",
        })
        receipt = self.adapter.commit_transaction(transaction)
        committed = self.github.get_commit(self.repo_id, receipt.committed_generation)
        self.assertEqual(len(committed.parents), 1)
        self.assertEqual(self.adapter.read_exact("data/wiki/a.md").content, b"new alpha\n")
        self.assertEqual(self.adapter.read_exact("data/wiki/c.md").content, b"new gamma\n")
        with self.assertRaises(ValidationError):
            self.adapter.read_exact("data/wiki/b.md")
        self.assertTrue(self.adapter.verify_generation(receipt))
        self.assertTrue(all(force is False for _, _, force in self.github.ref_update_calls))

    def test_two_sibling_commits_allow_exactly_one_non_force_update(self):
        base = self.adapter.current_generation()
        base_commit = self.github.get_commit(self.repo_id, base)
        blob_a = self.github.create_blob(self.repo_id, b"writer-a")
        blob_b = self.github.create_blob(self.repo_id, b"writer-b")
        tree_a = self.github.create_tree(self.repo_id, base_commit.tree_sha, {"data/wiki/a.md": blob_a})
        tree_b = self.github.create_tree(self.repo_id, base_commit.tree_sha, {"data/wiki/b.md": blob_b})
        commit_a = self.github.create_commit(self.repo_id, "writer a", tree_a.sha, (base,))
        commit_b = self.github.create_commit(self.repo_id, "writer b", tree_b.sha, (base,))
        self.github.update_ref(self.repo_id, self.ref, commit_a.sha, force=False)
        with self.assertRaises(ConflictError):
            self.github.update_ref(self.repo_id, self.ref, commit_b.sha, force=False)
        self.assertEqual(self.github.get_ref(self.repo_id, self.ref), commit_a.sha)

    def test_forced_overlap_rebases_intent_and_preserves_unrelated_manual_edit(self):
        transaction = self.transaction(writes={"data/wiki/a.md": b"agent edit\n"})
        intent = self.adapter._json_bytes(self.adapter._intent_record(transaction))
        self.adapter._ensure_intent(transaction, intent)
        manual_sha: list[str] = []

        def overlap(github):
            manual_sha.append(github.manual_commit(
                self.repo_id,
                self.ref,
                {"data/wiki/manual.md": b"user note\n"},
                message="manual concurrent edit",
            ))

        self.github.before_next_ref_update = overlap
        receipt = self.adapter.commit_transaction(transaction)
        committed = self.github.get_commit(self.repo_id, receipt.committed_generation)
        self.assertEqual(committed.parents, (manual_sha[0],))
        self.assertEqual(self.adapter.read_exact("data/wiki/manual.md").content, b"user note\n")
        self.assertEqual(self.adapter.read_exact("data/wiki/a.md").content, b"agent edit\n")

    def test_conflicting_overlap_preserves_durable_intent_and_never_overwrites(self):
        transaction = self.transaction(writes={"data/wiki/a.md": b"agent edit\n"})
        intent = self.adapter._json_bytes(self.adapter._intent_record(transaction))
        self.adapter._ensure_intent(transaction, intent)
        self.github.manual_commit(
            self.repo_id, self.ref, {"data/wiki/a.md": b"manual wins\n"}, message="manual conflict"
        )
        with self.assertRaises(ConflictError):
            self.adapter.commit_transaction(transaction)
        intent_path, completion_path = self.adapter._operation_paths(transaction.operation_id)
        self.assertEqual(self.adapter.read_exact(intent_path).content, intent)
        with self.assertRaises(ValidationError):
            self.adapter.read_exact(completion_path)
        self.assertEqual(self.adapter.read_exact("data/wiki/a.md").content, b"manual wins\n")

    def test_lost_response_before_and_after_ref_publication_reconciles(self):
        before = self.transaction("lost-before", writes={"data/wiki/a.md": b"before handled\n"})
        self.github.lose_next_ref_response_before_apply = True
        before_receipt = self.adapter.commit_transaction(before)
        self.assertEqual(self.adapter.read_exact("data/wiki/a.md").content, b"before handled\n")
        self.assertTrue(self.adapter.verify_generation(before_receipt))

        after = self.transaction("lost-after", writes={"data/wiki/b.md": b"after handled\n"})
        self.github.lose_next_ref_response_after_apply = True
        after_receipt = self.adapter.commit_transaction(after)
        self.assertEqual(self.adapter.read_exact("data/wiki/b.md").content, b"after handled\n")
        self.assertTrue(self.adapter.verify_generation(after_receipt))

    def test_lost_commit_response_does_not_treat_orphan_as_completion(self):
        transaction = self.transaction("lost-object", writes={"data/wiki/a.md": b"object retry\n"})
        starting_commits = set(self.github.commits)
        self.github.lose_next_commit_response = True
        receipt = self.adapter.commit_transaction(transaction)
        new_commits = set(self.github.commits) - starting_commits
        self.assertGreaterEqual(len(new_commits), 2)  # durable intent plus completion
        self.assertIn(receipt.committed_generation, new_commits)
        self.assertTrue(self.github.is_ancestor(self.repo_id, receipt.committed_generation, self.adapter.current_generation()))

    def test_unpublished_orphan_commit_is_not_a_completed_operation(self):
        transaction = self.transaction("orphan", writes={"data/wiki/a.md": b"orphan output\n"})
        base = self.adapter.current_generation()
        base_commit = self.github.get_commit(self.repo_id, base)
        blob = self.github.create_blob(self.repo_id, b"orphan output\n")
        tree = self.github.create_tree(self.repo_id, base_commit.tree_sha, {"data/wiki/a.md": blob})
        orphan = self.github.create_commit(self.repo_id, "unpublished orphan", tree.sha, (base,))
        self.assertFalse(self.github.is_ancestor(self.repo_id, orphan.sha, self.adapter.current_generation()))
        self.assertIsNone(self.adapter.reconcile_operation(transaction))

    def test_replay_returns_historical_receipt_after_newer_manual_commit(self):
        transaction = self.transaction(writes={"data/wiki/a.md": b"completed\n"})
        first = self.adapter.commit_transaction(transaction)
        newer = self.github.manual_commit(
            self.repo_id, self.ref, {"data/wiki/manual.md": b"later\n"}, message="later manual edit"
        )
        replay = self.adapter.commit_transaction(transaction)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.committed_generation, first.committed_generation)
        self.assertEqual(replay.current_generation, newer)
        self.assertEqual(self.adapter.read_exact("data/wiki/manual.md").content, b"later\n")

    def test_operation_id_collision_is_rejected(self):
        first = self.transaction("same-op", writes={"data/wiki/a.md": b"first\n"})
        self.adapter.commit_transaction(first)
        collision = StorageTransaction(
            instance_id=INSTANCE,
            operation_id="same-op",
            base_generation=first.base_generation,
            original_intent={"action": "different"},
            writes={"data/wiki/a.md": b"second\n"},
            deletes=(),
            expected_input_hashes={"data/wiki/a.md": sha256_bytes(b"alpha\n")},
        )
        with self.assertRaises(ConflictError):
            self.adapter.commit_transaction(collision)

    def test_repository_ref_and_permission_guards_fail_closed(self):
        self.github.rename_repository("new-owner/renamed-private-wikiplant")
        with self.assertRaises(ConflictError):
            self.adapter.read_exact("data/wiki/a.md")
        self.github.rename_repository("owner/private-wikiplant")
        self.github.set_private(False)
        with self.assertRaises(CapabilityError):
            self.adapter.current_generation()
        self.github.set_private(True)
        self.github.set_archived(True)
        with self.assertRaises(CapabilityError):
            self.adapter.current_generation()
        self.github.set_archived(False)
        self.github.contents_write = False
        with self.assertRaises(CapabilityError):
            self.adapter.commit_transaction(self.transaction())

    def test_explicit_immutable_id_repository_rename_repair(self):
        self.github.rename_repository("new-owner/renamed-private-wikiplant")
        with self.assertRaises(ConflictError):
            self.adapter.current_generation()
        repair = GitHubStorageAdapter(
            self.github, self.binding, instance_id=INSTANCE,
            expected_repository="owner/private-wikiplant", ancestry_anchor=self.anchor,
            allow_repository_rename_repair=True,
        )
        target = f"{self.repo_id}:owner/private-wikiplant->new-owner/renamed-private-wikiplant"
        grant = UserAuthorization(
            "turn-rename", INSTANCE, "repair-github-repository-locator", target,
            request_digest("repair this renamed repository binding"), True,
            "explicit current-user repository rename repair",
        ).to_dict()
        receipt = repair.repair_repository_locator(
            "new-owner/renamed-private-wikiplant", grant, operation_id="repair-rename-1"
        )
        self.assertTrue(repair.verify_generation(receipt))
        instance = json.loads(repair.read_exact("INSTANCE.json").content)
        self.assertEqual(instance["storage"]["repository"], "new-owner/renamed-private-wikiplant")
        self.assertIn("new-owner/renamed-private-wikiplant", repair.read_exact("config.yml").content.decode())

    def test_repository_rename_repair_requires_observed_ref_publication(self):
        self.github.rename_repository("new-owner/renamed-private-wikiplant")
        repair = GitHubStorageAdapter(
            self.github, self.binding, instance_id=INSTANCE,
            expected_repository="owner/private-wikiplant", ancestry_anchor=self.anchor,
            allow_repository_rename_repair=True,
        )
        target = f"{self.repo_id}:owner/private-wikiplant->new-owner/renamed-private-wikiplant"
        grant = UserAuthorization(
            "turn-rename-noop", INSTANCE, "repair-github-repository-locator", target,
            request_digest("repair this renamed repository binding"), True,
            "explicit current-user repository rename repair",
        ).to_dict()
        original_update = self.github.update_ref

        def false_success(repository_id, ref, sha, *, force):
            return sha

        self.github.update_ref = false_success
        try:
            with self.assertRaises(ConflictError):
                repair.repair_repository_locator(
                    "new-owner/renamed-private-wikiplant", grant,
                    operation_id="repair-rename-noop",
                )
        finally:
            self.github.update_ref = original_update
        self.assertEqual(repair.expected_repository, "owner/private-wikiplant")

    def test_repository_rename_repair_validates_full_old_generation_before_publish(self):
        malformed = json.loads(self.adapter.read_exact("INSTANCE.json").content)
        malformed.pop("schema_version")
        poisoned_head = self.github.manual_commit(
            self.repo_id, self.ref,
            {"INSTANCE.json": json.dumps(malformed).encode()},
            message="malformed old identity",
        )
        self.github.rename_repository("new-owner/renamed-private-wikiplant")
        repair = GitHubStorageAdapter(
            self.github, self.binding, instance_id=INSTANCE,
            expected_repository="owner/private-wikiplant", ancestry_anchor=self.anchor,
            allow_repository_rename_repair=True,
        )
        target = f"{self.repo_id}:owner/private-wikiplant->new-owner/renamed-private-wikiplant"
        grant = UserAuthorization(
            "turn-rename-invalid", INSTANCE, "repair-github-repository-locator", target,
            request_digest("repair this renamed repository binding"), True,
            "explicit current-user repository rename repair",
        ).to_dict()
        with self.assertRaises(ValidationError):
            repair.repair_repository_locator(
                "new-owner/renamed-private-wikiplant", grant,
                operation_id="repair-rename-invalid",
            )
        self.assertEqual(self.github.get_ref(self.repo_id, self.ref), poisoned_head)

    def test_manual_unsafe_path_or_incomplete_v2_contract_blocks_reads(self):
        self.github.manual_commit(
            self.repo_id, self.ref, {"../outside.md": b"poison\n"},
            message="unsafe manual path",
        )
        with self.assertRaises(ValidationError):
            self.adapter.inventory()

        github = FakeGitHub(repository_id="schema-poison")
        github.manual_commit(
            "schema-poison", self.ref,
            {
                "INSTANCE.json": json.dumps({
                    "instance_id": INSTANCE,
                    "storage": {
                        "provider": "github", "repository_id": "schema-poison",
                        "repository": github.repository.full_name,
                        "canonical_ref": self.ref, "root_prefix": "",
                        "repository_visibility": "private",
                        "app_installation_id": "app-fixture",
                        "capability_profile_path": "installation/capability-profile.json",
                        "first_verified_commit": github.initial_commit_sha,
                    },
                }).encode(),
                "config.yml": self.config_bytes(
                    INSTANCE, repository_id="schema-poison",
                    repository=github.repository.full_name,
                ),
                "data/TOPICS.md": self.topic_bytes(INSTANCE),
            },
            message="incomplete identity schema",
        )
        poisoned = GitHubStorageAdapter(
            github, StorageBinding("github", "schema-poison", "", self.ref),
            instance_id=INSTANCE, expected_repository=github.repository.full_name,
            ancestry_anchor=github.initial_commit_sha,
        )
        with self.assertRaises(ValidationError):
            poisoned.read_exact("config.yml")

    def test_branch_rename_ruleset_and_cross_instance_block(self):
        self.github.rename_ref(self.ref, "refs/heads/renamed")
        with self.assertRaises(ValidationError):
            self.adapter.current_generation()
        self.github.rename_ref("refs/heads/renamed", self.ref)
        self.github.ruleset_rejects_updates = True
        with self.assertRaises(CapabilityError):
            self.adapter.commit_transaction(self.transaction())
        self.github.ruleset_rejects_updates = False
        with self.assertRaises(ValidationError):
            GitHubStorageAdapter(
                self.github, self.binding, instance_id=FOREIGN_INSTANCE,
                expected_repository="owner/private-wikiplant",
                ancestry_anchor=self.anchor,
            ).read_exact("data/wiki/a.md")

    def test_manual_instance_or_config_rebinding_blocks_canonical_work(self):
        self.github.manual_commit(
            self.repo_id, self.ref,
            {"config.yml": self.config_bytes(INSTANCE, repository="other/private")},
            message="unsafe config rebind",
        )
        with self.assertRaises(ValidationError):
            self.adapter.read_exact("data/wiki/a.md")

    def test_transaction_cannot_publish_foreign_binding_files(self):
        transaction = self.transaction(writes={"INSTANCE.json": self.instance_bytes(FOREIGN_INSTANCE)})
        with self.assertRaises(ValidationError):
            self.adapter.commit_transaction(transaction)
        transaction = self.transaction(writes={"config.yml": self.config_bytes(INSTANCE, repository="other/private")})
        with self.assertRaises(ValidationError):
            self.adapter.commit_transaction(transaction)

    def test_external_history_rewrite_outside_anchor_fails_closed(self):
        tree = self.github.create_tree(self.repo_id, None, {})
        unrelated = self.github.create_commit(self.repo_id, "unrelated root", tree.sha, ())
        self.github.refs[self.ref] = unrelated.sha  # simulate an out-of-band force rewrite
        with self.assertRaises(ConflictError):
            self.adapter.current_generation()

    def test_in_lineage_rewind_and_missing_ref_protection_fail_closed(self):
        earlier = self.adapter.current_generation()
        newer = self.github.manual_commit(
            self.repo_id, self.ref, {"data/wiki/a.md": b"newer\n"}, message="newer"
        )
        self.assertEqual(self.adapter.current_generation(), newer)
        self.github.refs[self.ref] = earlier  # simulate provider violating its protection
        with self.assertRaises(ConflictError):
            self.adapter.current_generation()

        github = FakeGitHub(repository_id="unprotected")
        github.set_ref_protection(force_push=False, deletion=True)
        with self.assertRaises(CapabilityError):
            GitHubStorageAdapter(
                github, StorageBinding("github", "unprotected", "", self.ref),
                instance_id=INSTANCE, expected_repository=github.repository.full_name,
                ancestry_anchor=github.initial_commit_sha,
            )

    def test_binary_unsupported_and_oversized_intent_are_rejected(self):
        for path, content in (("data/wiki/binary.png", b"text"), ("data/wiki/bad.md", b"\xff")):
            with self.subTest(path=path), self.assertRaises(ValidationError):
                self.adapter.commit_transaction(self.transaction(writes={path: content}))
        limited = GitHubStorageAdapter(
            self.github, self.binding, instance_id=INSTANCE,
            expected_repository="owner/private-wikiplant", ancestry_anchor=self.anchor,
            limits=GitHubLimits(max_file_bytes=400, max_transaction_bytes=400),
        )
        transaction = self.transaction(writes={"data/wiki/a.md": b"ok\n"})
        transaction = StorageTransaction(
            **{**transaction.__dict__, "original_intent": {"large": "x" * 1_000}}
        )
        with self.assertRaises(CapabilityError):
            limited.commit_transaction(transaction)

    def test_commit_cannot_exceed_cumulative_repository_bound(self):
        current_total = sum(len(item.content) for item in self.adapter.inventory())
        repository_limit = 10_000
        padding_size = repository_limit - current_total - 10
        self.assertGreater(padding_size, 0)
        self.github.manual_commit(
            self.repo_id, self.ref, {"data/wiki/padding.md": b"x" * padding_size},
            message="fill synthetic repository",
        )
        limited = GitHubStorageAdapter(
            self.github, self.binding, instance_id=INSTANCE,
            expected_repository="owner/private-wikiplant", ancestry_anchor=self.anchor,
            limits=GitHubLimits(
                max_file_bytes=10_000, max_transaction_bytes=10_000,
                max_repository_bytes=repository_limit,
            ),
        )
        with self.assertRaises(CapabilityError):
            limited.commit_transaction(self.transaction(
                "over-capacity", writes={"data/wiki/new.md": b"new content\n"}
            ))

    def test_fork_repository_is_rejected(self):
        self.github.set_fork(True)
        with self.assertRaises(CapabilityError):
            GitHubStorageAdapter(
                self.github, self.binding, instance_id=INSTANCE,
                expected_repository="owner/private-wikiplant",
                ancestry_anchor=self.anchor,
            )

    def test_manual_merge_commit_blocks_canonical_work(self):
        transaction = self.transaction("after-merge", writes={"data/wiki/a.md": b"blocked\n"})
        head = self.adapter.current_generation()
        head_commit = self.github.get_commit(self.repo_id, head)
        merge = self.github.create_commit(
            self.repo_id, "unexpected merge", head_commit.tree_sha, (head, head_commit.parents[0])
        )
        self.github.update_ref(self.repo_id, self.ref, merge.sha, force=False)
        with self.assertRaises(ConflictError):
            self.adapter.commit_transaction(transaction)

    def test_oversized_transaction_and_force_or_rewind_are_rejected(self):
        limited = GitHubStorageAdapter(
            self.github,
            self.binding,
            instance_id=INSTANCE,
            expected_repository="owner/private-wikiplant",
            ancestry_anchor=self.anchor,
            limits=GitHubLimits(max_file_bytes=4, max_transaction_bytes=6),
        )
        with self.assertRaises(CapabilityError):
            limited.commit_transaction(self.transaction(writes={"data/wiki/a.md": b"too large"}))
        with self.assertRaises(ValidationError):
            self.github.update_ref(self.repo_id, self.ref, self.adapter.current_generation(), force=True)
        with self.assertRaises(ValidationError):
            self.github.delete_ref(self.repo_id, self.ref)

    def test_limits_accept_the_config_storage_limit_shape(self):
        limits = GitHubLimits(**{
            "max_file_bytes": 512_000,
            "max_transaction_bytes": 8_000_000,
            "max_repository_bytes": 500_000_000,
            "max_paths_per_transaction": 200,
        })
        self.assertEqual(limits.max_paths_per_transaction, 200)

    def test_noncanonical_paths_and_invalid_expected_hashes_are_rejected(self):
        transaction = self.transaction(writes={"data//wiki/a.md": b"unsafe alias\n"})
        with self.assertRaises(ValidationError):
            self.adapter.commit_transaction(transaction)
        transaction = self.transaction(writes={"data/wiki/a.md": b"new\n"})
        invalid = StorageTransaction(
            **{**transaction.__dict__, "expected_input_hashes": {"data/wiki/a.md": "not-a-hash"}}
        )
        with self.assertRaises(ValidationError):
            self.adapter.commit_transaction(invalid)

    def test_immutable_intake_is_idempotent_and_collision_safe(self):
        receipt = self.adapter.persist_immutable_intake(
            "data/state/inbox/command-1.json",
            b'{"command":"keep me"}\n',
            instance_id=INSTANCE,
            operation_id="intake-1",
            authorization_reference="turn:1",
        )
        replay = self.adapter.persist_immutable_intake(
            "data/state/inbox/command-1.json",
            b'{"command":"keep me"}\n',
            instance_id=INSTANCE,
            operation_id="intake-1",
            authorization_reference="turn:1",
        )
        self.assertTrue(replay.replayed)
        self.assertEqual(receipt.committed_generation, replay.committed_generation)
        with self.assertRaises(ConflictError):
            self.adapter.persist_immutable_intake(
                "data/state/inbox/command-1.json",
                b'{"command":"replace me"}\n',
                instance_id=INSTANCE,
                operation_id="intake-2",
            )


if __name__ == "__main__":
    unittest.main()
