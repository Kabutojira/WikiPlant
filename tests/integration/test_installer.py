from __future__ import annotations

import unittest
from pathlib import Path

from wikiplant.errors import ValidationError
from wikiplant.fake_drive import FakeDrive
from wikiplant.host import CapabilityProfile, FakeHost, set_instance_tasks_active
from wikiplant.installer import InstallPhase, Installer
from wikiplant.manifest import build_manifest
from wikiplant.setup import SetupInput, consolidated_interview


ROOT = Path(__file__).resolve().parents[2]
COMMIT = "b" * 40


def capabilities(**overrides) -> CapabilityProfile:
    values = dict(
        google_drive_raw_create=True, google_drive_full_read=True, google_drive_content_update=True,
        google_drive_paginated_list=True, private_skill_install=True, scheduled_task_create=True,
        scheduled_task_inspect=True, conditional_write=True, serialized_task_runs=True,
        observed_surface="synthetic", observed_at="2026-01-15T00:00:00+00:00",
    )
    values.update(overrides)
    return CapabilityProfile(**values)


def setup(parent_id: str, name: str = "Domain Alpha") -> SetupInput:
    return SetupInput(
        instance_name=name, primary_topics=[{"name": "Synthetic topic", "aliases": ["test alias"]}],
        purpose="Test a private research instance", projects=["Synthetic project"], constraints=["No real claims"],
        exclusions=["Out-of-scope material"], drive_parent_id=parent_id, daily_time="07:00", weekly_day="monday", weekly_time="05:00",
    )


class InstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = build_manifest(ROOT, "0.1.0", COMMIT)

    def environment(self, *, host_caps=None, auto_install=True):
        drive = FakeDrive()
        parent = drive.create_folder(None, "private-parent", idempotency_key="parent")
        host = FakeHost(host_caps or capabilities(), auto_install_skill=auto_install)
        return drive, parent, host, Installer(ROOT, drive, host, parent.id)

    def test_complete_input_has_no_interview_partial_has_one(self):
        drive, parent, host, installer = self.environment()
        self.assertIsNone(consolidated_interview(setup(parent.id)))
        partial = SetupInput(primary_topics=[{"name": "Synthetic topic"}])
        question = consolidated_interview(partial)
        self.assertIsInstance(question, str)
        self.assertIn("instance name", question)
        self.assertIn("language=en", question)

    def test_resume_every_checkpoint_no_duplicates(self):
        phases = [
            InstallPhase.DISCOVERED,
            InstallPhase.CAPABILITIES_CHECKED, InstallPhase.SETUP_READY, InstallPhase.STORAGE_CREATED,
            InstallPhase.RUNTIME_VERIFIED, InstallPhase.SKILL_CANDIDATE_CREATED, InstallPhase.SKILL_VERIFIED,
            InstallPhase.SEEDED,
        ]
        for phase in phases:
            with self.subTest(phase=phase.name):
                drive, parent, host, installer = self.environment()
                values = setup(parent.id)
                stopped = installer.run(values, self.manifest, COMMIT, seed_results=[{"id": "seed-1"}], stop_after=phase)
                self.assertIn(stopped.phase, {phase.name, InstallPhase.DISCOVERED.name})
                finished = installer.run(values, self.manifest, COMMIT, seed_results=[{"id": "seed-1"}])
                again = installer.run(values, self.manifest, COMMIT, seed_results=[{"id": "seed-1"}])
                self.assertEqual(finished.phase, InstallPhase.ACTIVE_AWAITING_FIRST_RUN.name)
                self.assertEqual(again.root_id, finished.root_id)
                self.assertEqual(len(host.skills), 1)
                self.assertEqual(len(host.tasks), 2)
                self.assertEqual(again.initialization_allowance_consumed, 1)

    def test_lost_create_response_reconciles(self):
        drive, parent, host, installer = self.environment()
        drive.lose_next_create_response = True
        result = installer.run(setup(parent.id), self.manifest, COMMIT)
        self.assertEqual(result.phase, InstallPhase.ACTIVE_AWAITING_FIRST_RUN.name)
        roots = [entry for entry in drive.list_all(parent.id) if entry.name.startswith("WikiPlant-")]
        self.assertEqual(len(roots), 1)

    def test_skill_candidate_is_not_installed_status(self):
        drive, parent, host, installer = self.environment(auto_install=False)
        result = installer.run(setup(parent.id), self.manifest, COMMIT)
        self.assertEqual(result.phase, InstallPhase.AWAITING_HOST_INSTALL.name)
        self.assertIsNone(result.skill_reference)
        self.assertEqual(len(host.skills), 0)
        host.auto_install_skill = True
        resumed = installer.run(setup(parent.id), self.manifest, COMMIT)
        self.assertEqual(resumed.phase, InstallPhase.ACTIVE_AWAITING_FIRST_RUN.name)

    def test_public_destination_blocks_before_private_seed(self):
        drive, parent, host, installer = self.environment()
        drive.public_parents.add(parent.id)
        result = installer.run(setup(parent.id), self.manifest, COMMIT, seed_results=[{"id": "private-seed", "secret": "do not copy"}])
        self.assertEqual(result.phase, InstallPhase.BLOCKED.name)
        payloads = [entry.content for entry in drive.entries.values()]
        self.assertFalse(any(b"do not copy" in payload for payload in payloads))

    def test_missing_scheduling_capability_blocks_truthfully(self):
        drive, parent, host, installer = self.environment(host_caps=capabilities(scheduled_task_create=False))
        result = installer.run(setup(parent.id), self.manifest, COMMIT)
        self.assertEqual(result.phase, InstallPhase.BLOCKED.name)
        self.assertEqual(result.last_completed_phase, InstallPhase.SEEDED.name)
        self.assertEqual(result.task_ids, {})

    def test_five_seed_cap_and_resume(self):
        drive, parent, host, installer = self.environment()
        with self.assertRaises(ValidationError):
            installer.run(setup(parent.id), self.manifest, COMMIT, seed_results=[{"id": f"s{i}"} for i in range(6)])
        result = installer.run(setup(parent.id), self.manifest, COMMIT, seed_results=[{"id": f"s{i}"} for i in range(5)])
        self.assertEqual(result.initialization_allowance_consumed, 5)
        replay = installer.run(setup(parent.id), self.manifest, COMMIT, seed_results=[{"id": f"s{i}"} for i in range(5)])
        self.assertEqual(replay.initialization_allowance_consumed, 5)

    def test_two_instances_are_isolated(self):
        drive = FakeDrive()
        parent_a = drive.create_folder(None, "a", idempotency_key="pa")
        parent_b = drive.create_folder(None, "b", idempotency_key="pb")
        host = FakeHost(capabilities())
        first = Installer(ROOT, drive, host, parent_a.id).run(setup(parent_a.id, "Alpha"), self.manifest, COMMIT)
        second = Installer(ROOT, drive, host, parent_b.id).run(setup(parent_b.id, "Beta"), self.manifest, COMMIT)
        self.assertNotEqual(first.instance_id, second.instance_id)
        self.assertNotEqual(first.root_id, second.root_id)
        self.assertEqual(len(host.skills), 2)
        self.assertEqual(len(host.tasks), 4)

    def test_pause_resume_only_bound_instance_tasks(self):
        drive = FakeDrive()
        parent_a = drive.create_folder(None, "a", idempotency_key="pause-pa")
        parent_b = drive.create_folder(None, "b", idempotency_key="pause-pb")
        host = FakeHost(capabilities())
        first = Installer(ROOT, drive, host, parent_a.id).run(setup(parent_a.id, "Alpha Pause"), self.manifest, COMMIT)
        second = Installer(ROOT, drive, host, parent_b.id).run(setup(parent_b.id, "Beta Pause"), self.manifest, COMMIT)
        set_instance_tasks_active(host, first.task_ids, False)
        first_active = {task.id: task.active for task in host.tasks.values() if task.id in first.task_ids.values()}
        second_active = {task.id: task.active for task in host.tasks.values() if task.id in second.task_ids.values()}
        self.assertTrue(all(not value for value in first_active.values()))
        self.assertTrue(all(second_active.values()))
        set_instance_tasks_active(host, first.task_ids, True)
        self.assertTrue(all(host.set_task_active(task_id, True).active for task_id in first.task_ids.values()))


if __name__ == "__main__":
    unittest.main()
