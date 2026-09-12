from __future__ import annotations

import json
import unittest
from pathlib import Path

from wikiplant.authorization import UserAuthorization, request_digest
from wikiplant.errors import CapabilityError, ValidationError
from wikiplant.fake_github import FakeGitHub
from wikiplant.github_installer import GitHubInstaller
from wikiplant.github_storage import GitHubStorageAdapter
from wikiplant.host import CapabilityProfile, FakeHost
from wikiplant.installer import InstallPhase
from wikiplant.manifest import build_manifest
from wikiplant.setup import SetupInput, topic_records
from wikiplant.storage_contract import StorageBinding
from wikiplant.yamlio import loads as yaml_loads


ROOT = Path(__file__).resolve().parents[2]


def capabilities(**overrides) -> CapabilityProfile:
    values = dict(
        github_repository_binding=True, github_exact_generation_read=True,
        github_blob_create=True, github_tree_create=True, github_commit_create=True,
        github_non_force_ref_update=True, github_generation_verify=True,
        github_ref_create=True,
        github_ref_protection_observed=True,
        github_repository_size_observed=True,
        github_operation_reconcile=True, github_scheduled_access=True,
        private_skill_install=True, scheduled_task_create=True, scheduled_task_inspect=True,
        observed_surface="synthetic-github-work-bridge",
    )
    values.update(overrides)
    return CapabilityProfile(**values)


class GitHubInstallerTests(unittest.TestCase):
    def environment(self, *, caps=None, auto_install=True, create_canonical_ref=True):
        github = FakeGitHub(
            repository_id="R_fixture", full_name="fixture/private-wiki",
            create_canonical_ref=create_canonical_ref,
        )
        host = FakeHost(caps or capabilities(), auto_install_skill=auto_install)
        installer = GitHubInstaller(
            ROOT, github, host, repository_id=github.repository.id,
            app_installation_id="app-installation-fixture",
        )
        setup = SetupInput(
            instance_name="Synthetic Research", primary_topics=[{"name": "Synthetic optics"}],
            purpose="Test evidence-linked research", exclusions=[], storage_provider="github",
            github_repository_url="https://github.com/fixture/private-wiki",
            daily_time="07:00", weekly_day="monday", weekly_time="05:00",
            confirmed_at="2026-09-12T10:00:00+00:00",
        )
        instance_id = installer.derive_instance_id(setup)
        setup.topic_authorizations = {record["id"]: UserAuthorization(
            "turn-setup", instance_id, "track", record["id"],
            request_digest("track synthetic optics"), True, "explicit fixture setup",
        ).to_dict() for record in topic_records(setup)}
        manifest = build_manifest(ROOT, "0.3.0", "a" * 40)
        return github, host, installer, setup, manifest

    def adapter(self, github, instance_id):
        return GitHubStorageAdapter(
            github, StorageBinding("github", github.repository.id, "", "refs/heads/wikiplant-data"),
            instance_id=instance_id, expected_repository=github.repository.full_name,
            ancestry_anchor=github.initial_commit_sha,
        )

    def test_full_install_and_resume_are_bound_and_idempotent(self):
        github, host, installer, setup, manifest = self.environment()
        state = installer.run(setup, manifest, "a" * 40, seed_results=[{"id": "seed-1", "finding": "synthetic"}])
        self.assertEqual(state.phase, InstallPhase.ACTIVE_AWAITING_FIRST_RUN.name)
        self.assertEqual(len(host.skills), 1)
        self.assertEqual(len(host.tasks), 2)
        adapter = self.adapter(github, state.instance_id)
        config = yaml_loads(adapter.read_exact("config.yml").content.decode())
        self.assertEqual(config["storage"]["provider"], "github")
        self.assertNotIn("root_folder_id", config["storage"])
        identity = json.loads(adapter.read_exact("INSTANCE.json").content)
        self.assertEqual(identity["storage"]["repository_id"], github.repository.id)
        self.assertIn("storage provider `github`", host.tasks[f"{state.instance_id}:daily"].prompt)
        self.assertNotIn("Drive root", host.tasks[f"{state.instance_id}:daily"].prompt)
        self.assertNotIn("app-installation-fixture", host.tasks[f"{state.instance_id}:daily"].prompt)
        self.assertNotIn(setup.purpose, host.tasks[f"{state.instance_id}:daily"].prompt)
        head = adapter.current_generation()
        replay = installer.run(setup, manifest, "a" * 40, seed_results=[{"id": "seed-1", "finding": "synthetic"}])
        self.assertEqual(replay.task_ids, state.task_ids)
        self.assertEqual(adapter.current_generation(), head)
        self.assertTrue(all(force is False for _, _, force in github.ref_update_calls))

    def test_missing_write_capability_blocks_before_repository_mutation(self):
        github, host, installer, setup, manifest = self.environment(caps=capabilities(github_commit_create=False))
        head = github.get_ref(github.repository.id, "refs/heads/wikiplant-data")
        state = installer.run(setup, manifest, "a" * 40)
        self.assertEqual(state.phase, InstallPhase.BLOCKED.name)
        self.assertIn("BLOCKED_GITHUB_WRITE_CAPABILITY", state.blocked_reason or "")
        self.assertEqual(github.get_ref(github.repository.id, "refs/heads/wikiplant-data"), head)

    def test_private_nonfork_repository_and_exact_url_are_required(self):
        github, host, installer, setup, manifest = self.environment()
        github.set_fork(True)
        with self.assertRaises(CapabilityError):
            installer.run(setup, manifest, "a" * 40)
        github.set_fork(False)
        setup.github_repository_url = "https://github.com/fixture/another"
        with self.assertRaises(ValidationError):
            installer.run(setup, manifest, "a" * 40)

    def test_missing_canonical_ref_is_created_from_an_empty_default_branch(self):
        github, host, installer, setup, manifest = self.environment(create_canonical_ref=False)
        state = installer.run(setup, manifest, "a" * 40)
        self.assertEqual(state.phase, InstallPhase.ACTIVE_AWAITING_FIRST_RUN.name)
        self.assertIn("refs/heads/wikiplant-data", github.refs)
        self.assertTrue(github.is_ancestor(
            github.repository.id, github.initial_commit_sha,
            github.refs["refs/heads/wikiplant-data"],
        ))

    def test_lost_canonical_ref_creation_response_is_reconciled(self):
        github, host, installer, setup, manifest = self.environment(create_canonical_ref=False)
        github.lose_next_create_ref_response_after_apply = True
        state = installer.run(setup, manifest, "a" * 40)
        self.assertEqual(state.phase, InstallPhase.ACTIVE_AWAITING_FIRST_RUN.name)
        self.assertIn("refs/heads/wikiplant-data", github.refs)

    def test_host_skill_handoff_is_resumable(self):
        github, host, installer, setup, manifest = self.environment(auto_install=False)
        state = installer.run(setup, manifest, "a" * 40)
        self.assertEqual(state.phase, InstallPhase.AWAITING_HOST_INSTALL.name)
        host.auto_install_skill = True
        awaiting = installer.run(setup, manifest, "a" * 40)
        github_adapter = self.adapter(github, awaiting.instance_id)
        receipt = {
            "storage_provider": "github", "repository_id": github.repository.id,
            "canonical_ref": "refs/heads/wikiplant-data", "status": "complete",
            "scheduled": True, "task_id": awaiting.task_ids["daily"],
            "observed_generation": github_adapter.current_generation(),
            "observed_at": "2026-09-13T07:00:00+00:00",
        }
        resumed = installer.run(setup, manifest, "a" * 40, first_run_receipt=receipt)
        self.assertEqual(resumed.phase, InstallPhase.ACTIVE_VERIFIED.name)
        self.assertTrue(resumed.first_run_verified)

    def test_seed_limit_and_foreign_drive_fields_fail_closed(self):
        github, host, installer, setup, manifest = self.environment()
        head = github.get_ref(github.repository.id, "refs/heads/wikiplant-data")
        with self.assertRaises(ValidationError):
            installer.run(setup, manifest, "a" * 40, seed_results=[{"id": f"s{i}"} for i in range(6)])
        self.assertEqual(github.get_ref(github.repository.id, "refs/heads/wikiplant-data"), head)
        self.assertFalse(host.skills)
        self.assertFalse(host.tasks)
        setup.drive_parent_id = "foreign-drive"
        with self.assertRaises(ValidationError):
            setup.validate_complete()


if __name__ == "__main__":
    unittest.main()
