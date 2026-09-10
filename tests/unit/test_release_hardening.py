from __future__ import annotations

import json
import subprocess
import tempfile
import tomllib
import unittest
from dataclasses import replace
from pathlib import Path

from wikiplant.cli import package
from wikiplant import __version__
from wikiplant.errors import ValidationError
from wikiplant.manifest import build_manifest, manifest_bytes, verify_dependency_closure, verify_manifest
from wikiplant.releases import ReleaseCheckState, ReleaseCheckStore, ReleaseInfo, Version, check_releases
from wikiplant.fake_drive import FakeDrive
from wikiplant.storage import Binding, SafeWriter
from wikiplant.upgrades import available_update
from wikiplant.util import sha256_bytes


ROOT = Path(__file__).resolve().parents[2]


def release(version="0.10.0", **kwargs):
    return ReleaseInfo("Kabutojira/WikiPlant", "release-" + version, version, "v" + version,
                       "a" * 40, "b" * 64, "2026-09-10T01:00:00+00:00", **kwargs)


class ReleaseHardeningTests(unittest.TestCase):
    def test_development_version_metadata_agrees(self):
        version = (ROOT / "VERSION").read_text().strip()
        self.assertEqual(tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"], version)
        self.assertEqual(__version__, version)
        Version.parse(version)

    def check(self, state, releases, **kwargs):
        return check_releases(state, releases, week_key=kwargs.pop("week_key", "2026-W37"),
                              checked_at=kwargs.pop("checked_at", "2026-09-10T02:00:00+00:00"), schema=2,
                              capabilities=set(), complete=kwargs.pop("complete", True), fresh=kwargs.pop("fresh", True), **kwargs)

    def test_semver_channel_and_ordering(self):
        self.assertTrue(available_update("0.9.0", "0.10.0")["update_available"])
        for version in ("0.8.0", "0.9.0", "0.10.0-beta.1"):
            self.assertFalse(available_update("0.9.0", version)["update_available"])
        versions = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"]
        self.assertEqual(sorted(reversed(versions), key=Version.parse), versions)
        for invalid in ("1.0", "01.0.0", "1.0.0-01", "1.0.0-alpha..x"):
            with self.assertRaises(ValidationError):
                Version.parse(invalid)

    def test_weekly_dedup_reconstruction_and_incompatible_notice(self):
        state = ReleaseCheckState("wp-test", "Kabutojira/WikiPlant", "0.9.0")
        newest = release("0.11.0", required_capabilities=("unavailable",))
        notices = self.check(state, [release(), newest, release("9.0.0", draft=True), release("1.0.0-rc.1", prerelease=True)])
        self.assertEqual(len(notices), 1)
        self.assertFalse(notices[0]["compatible"])
        self.assertEqual(state.newest_stable, "0.11.0")
        self.assertEqual(state.newest_compatible, "0.10.0")
        self.assertIsNone(notices[0]["notification_observed"])
        restored = ReleaseCheckState.from_dict(json.loads(json.dumps(state.to_dict())))
        self.assertEqual(self.check(restored, [release(), newest], week_key="2026-W38", checked_at="2026-09-17T02:00:00+00:00"), [])
        self.assertFalse(next(iter(restored.notices.values()))["result_published"])

    def test_failure_is_not_up_to_date_retry_is_bounded(self):
        state = ReleaseCheckState("wp-test", "Kabutojira/WikiPlant", "0.9.0")
        self.check(state, None, error="rate limited")
        self.assertEqual(state.outcome, "failed")
        self.assertIsNone(state.last_successful_check)
        self.check(state, [], checked_at="2026-09-10T02:10:00+00:00")
        self.assertEqual(state.outcome, "failed")
        self.assertEqual(state.attempts["2026-W37"], 1)
        self.check(state, [], checked_at="2026-09-10T03:00:00+00:00")
        self.assertEqual(state.outcome, "no_release")

    def test_changed_known_identity_is_security_alert(self):
        state = ReleaseCheckState("wp-test", "Kabutojira/WikiPlant", "0.9.0")
        self.check(state, [release()])
        self.check(state, [replace(release(), source_commit="c" * 40)], week_key="2026-W38")
        self.assertEqual(state.outcome, "security_alert")
        self.assertIn("identity changed", state.error)
        self.assertEqual(state.successful_week, "2026-W37")

    def test_partial_and_stale_inventories_never_claim_success(self):
        for flags in ({"complete": False}, {"fresh": False}):
            state = ReleaseCheckState("wp-test", "Kabutojira/WikiPlant", "0.9.0")
            self.check(state, [release()], **flags)
            self.assertEqual(state.outcome, "failed")
            self.assertFalse(state.notices)

    def test_manifest_detached_and_dependency_closure(self):
        manifest = build_manifest(ROOT, "0.2.0", "a" * 40)
        self.assertEqual(manifest["distribution"], "detached-release-asset")
        self.assertNotIn("release/runtime-manifest.json", [v["path"] for v in manifest["files"]])
        verify_manifest(ROOT, manifest, resolved_commit="a" * 40)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            for entry in manifest["files"]:
                path = target / entry["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((ROOT / entry["path"]).read_bytes())
            verify_manifest(target, manifest, resolved_commit="a" * 40)
            result = subprocess.run(["python", "-I", "-c", "import sys, pkgutil, importlib; sys.path.insert(0,sys.argv[1]); import wikiplant; [importlib.import_module(m.name) for m in pkgutil.walk_packages(wikiplant.__path__, 'wikiplant.')]", str(target / "scripts")], cwd=folder, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            paths = {v["path"] for v in manifest["files"]}
            paths.remove("scripts/wikiplant/releases.py")
            with self.assertRaises(ValidationError):
                verify_dependency_closure(target, paths)

    def test_published_manifest_mirror_matches_release_asset_identity(self):
        path = ROOT / "release/published/wikiplant-0.2.0.manifest.json"
        payload = path.read_bytes()
        self.assertEqual(sha256_bytes(payload), "1850a15a1a53247930b0716f5966caa478942a2758cfd266c924945337dcba50")
        manifest = json.loads(payload)
        self.assertEqual(manifest["source_commit"], "d3afb1aafaef16dd807117bd44548b9f3f57fba6")
        self.assertEqual(manifest["status"], "released")
        self.assertNotIn(path.relative_to(ROOT).as_posix(), {entry["path"] for entry in manifest["files"]})
        verify_manifest(ROOT, manifest, resolved_commit=manifest["source_commit"])

    def test_install_handoff_never_asks_user_to_manufacture_manifest(self):
        install = (ROOT / "INSTALL.md").read_text()
        readme = (ROOT / "README.md").read_text()
        self.assertIn("manifest_mirror", install)
        self.assertIn("Do not ask the user to create, copy, paste, upload or convert a manifest", install)
        self.assertIn("@Google Drive", readme)
        self.assertIn("<google-drive-folder-link>", readme)

    def test_publishing_manifest_requires_real_committed_payloads(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(SystemExit):
                package(ROOT, "a" * 40, output=Path(folder) / "release.json")
            draft = package(ROOT, "a" * 40, draft=True, output=Path(folder) / "draft.json")
            self.assertEqual(json.loads(draft.read_bytes())["status"], "draft")

    def test_notice_saved_before_publish_and_failed_publication_remains_pending(self):
        drive = FakeDrive()
        root = drive.create_folder(None, "synthetic", idempotency_key="root").id
        folders = {name: drive.create_folder(root, name, idempotency_key=name).id for name in ("state", "notices", "ops", "inbox")}
        snapshot = drive.create_file(folders["state"], "checks.json", "application/json", b"{}", idempotency_key="state-file")
        writer = SafeWriter(drive, root, folders["ops"], folders["inbox"], instance_id="wp-test")
        binding = Binding("data/state/updates/checks.json", snapshot.id, snapshot.mime_type, root)
        store = ReleaseCheckStore(writer, binding, folders["notices"], repository="Kabutojira/WikiPlant", installed_version="0.9.0")
        state, notices = store.check([release()], week_key="2026-W37", checked_at="2026-09-10T02:00:00+00:00", schema=2, capabilities=set(), complete=True, fresh=True)
        notice = notices[0]
        self.assertTrue(drive.read_exact(notice["saved_reference"]).complete)
        def fail(*args):
            raise RuntimeError("native host unavailable")
        with self.assertRaises(RuntimeError):
            store.publish(notice["id"], publish_result=fail, reconcile_result=lambda key: None)
        fresh = ReleaseCheckStore(writer, binding, folders["notices"], repository="Kabutojira/WikiPlant", installed_version="0.9.0")
        self.assertFalse(fresh.load()[1].notices[notice["id"]]["result_published"])
        published = fresh.publish(notice["id"], publish_result=lambda key, payload: "observed-native-result", reconcile_result=lambda key: None)
        self.assertTrue(published["result_published"])
        self.assertIsNone(published["notification_observed"])
        self.assertEqual(fresh.publish(notice["id"], publish_result=fail, reconcile_result=fail)["publication_reference"], "observed-native-result")


if __name__ == "__main__":
    unittest.main()
