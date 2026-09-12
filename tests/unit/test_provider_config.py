from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from wikiplant.config import validate_config
from wikiplant.errors import ValidationError
from wikiplant.host import CapabilityProfile
from wikiplant.setup import SetupInput, consolidated_interview, setup_summary
from wikiplant.skillgen import SkillBinding, generate_skill
from wikiplant.yamlio import loads


ROOT = Path(__file__).resolve().parents[2]


def github_config() -> dict:
    config = loads((ROOT / "config.example.yml").read_text(encoding="utf-8"))
    config["storage"] = {
        "provider": "github",
        "repository_id": "R_kgDOExample",
        "repository": "fixture-owner/private-wikiplant",
        "canonical_ref": "refs/heads/wikiplant-data",
        "root_prefix": "",
        "consistency_mode": "git-fast-forward",
        "limits": {
            "max_file_bytes": 512_000,
            "max_transaction_bytes": 8_000_000,
            "max_repository_bytes": 500_000_000,
            "max_paths_per_transaction": 200,
        },
    }
    return config


class ProviderConfigTests(unittest.TestCase):
    def test_drive_remains_default_and_legacy_v1_uses_drive_shape(self):
        config = loads((ROOT / "config.example.yml").read_text(encoding="utf-8"))
        self.assertEqual(config["storage"]["provider"], "google-drive")
        validate_config(config, activated=False)
        legacy = copy.deepcopy(config)
        legacy["schema_version"] = 1
        legacy["storage"].pop("provider")
        legacy["primary_topics"] = []
        legacy.pop("primary_topic_ids")
        validate_config(legacy, activated=False)

    def test_github_config_accepts_complete_tagged_binding(self):
        validate_config(github_config(), activated=False)

    def test_provider_fields_cannot_be_mixed(self):
        github = github_config()
        github["storage"]["root_folder_id"] = "drive-root"
        with self.assertRaisesRegex(ValidationError, "another provider"):
            validate_config(github, activated=False)
        drive = loads((ROOT / "config.example.yml").read_text(encoding="utf-8"))
        drive["storage"]["repository_id"] = "foreign"
        with self.assertRaisesRegex(ValidationError, "another provider"):
            validate_config(drive, activated=False)

    def test_github_binding_requires_full_ref_and_bounded_limits(self):
        config = github_config()
        config["storage"]["canonical_ref"] = "main"
        with self.assertRaisesRegex(ValidationError, "full branch ref"):
            validate_config(config, activated=False)
        config = github_config()
        config["storage"]["limits"]["max_transaction_bytes"] = 100
        with self.assertRaisesRegex(ValidationError, "max_file_bytes"):
            validate_config(config, activated=False)

    def test_capabilities_are_selected_by_provider(self):
        drive = CapabilityProfile(
            google_drive_raw_create=True, google_drive_full_read=True,
            google_drive_content_update=True, google_drive_paginated_list=True,
        )
        self.assertTrue(drive.storage_ready())
        self.assertFalse(drive.storage_ready("github"))
        github = CapabilityProfile(
            github_repository_binding=True, github_exact_generation_read=True,
            github_blob_create=True, github_tree_create=True, github_commit_create=True,
            github_non_force_ref_update=True,
            github_ref_create=True,
            github_ref_protection_observed=True,
            github_repository_size_observed=True,
            github_generation_verify=True, github_operation_reconcile=True,
            github_scheduled_access=True,
        )
        self.assertTrue(github.storage_ready("github"))
        self.assertFalse(github.storage_ready("google-drive"))
        self.assertEqual(github.missing_storage_capabilities("github"), ())

    def test_github_setup_requests_link_and_discloses_retention(self):
        setup = SetupInput(storage_provider="github")
        question = consolidated_interview(setup)
        self.assertIn("private GitHub repository link", question or "")
        self.assertNotIn("Google Drive destination", question or "")
        complete = SetupInput(
            instance_name="Fixture", primary_topics=[{"name": "Synthetic topic"}],
            purpose="Synthetic test", exclusions=[], storage_provider="github",
            github_repository_url="https://github.com/fixture/private-wiki",
            daily_time="07:00", weekly_day="monday", weekly_time="05:00",
        )
        complete.validate_complete()
        summary = setup_summary(complete)
        self.assertIn("git-fast-forward", summary)
        self.assertIn("Git history retains prior content", summary)

    def test_github_skill_contains_only_github_binding(self):
        binding = SkillBinding.github(
            instance_id="wp-abcdef1234567890", repository_id="R_kgDOExample",
            repository="fixture/private-wiki", canonical_ref="refs/heads/wikiplant-data",
            release_id="0.2.1", runtime_manifest_sha256="f" * 64,
            first_verified_commit="a" * 40,
        )
        generated = generate_skill("Fixture", binding, [{"name": "Synthetic topic"}])
        self.assertIn("`storage_provider`: `github`", generated.skill_md)
        self.assertIn("`repository_id`: `R_kgDOExample`", generated.skill_md)
        self.assertIn("`canonical_ref`: `refs/heads/wikiplant-data`", generated.skill_md)
        self.assertIn("BLOCKED_GITHUB_WRITE_CAPABILITY", generated.skill_md)
        self.assertNotIn("drive_root_id", generated.skill_md)

    def test_instance_schema_has_legacy_and_tagged_provider_variants(self):
        schema = json.loads((ROOT / "schemas/instance.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_version"]["enum"], [1, 2])
        storage = schema["properties"]["storage"]
        providers = {variant["properties"]["provider"]["const"] for variant in storage["oneOf"]}
        self.assertEqual(providers, {"google-drive", "github"})


if __name__ == "__main__":
    unittest.main()
