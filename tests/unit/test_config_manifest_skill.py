from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from wikiplant.config import validate_config
from wikiplant.errors import ValidationError
from wikiplant.manifest import build_manifest, manifest_bytes, verify_manifest
from wikiplant.skillgen import SkillBinding, generate_skill
from wikiplant.setup import SetupInput, topic_records
from wikiplant.yamlio import dumps, loads


ROOT = Path(__file__).resolve().parents[2]


class ConfigManifestSkillTests(unittest.TestCase):
    def test_yaml_roundtrip_and_provider_fields_do_not_mix(self):
        config = loads((ROOT / "config.example.yml").read_text())
        validate_config(config, activated=False)
        restored = loads(dumps(config))
        self.assertEqual(restored, config)
        config["storage"]["provider"] = "github"
        with self.assertRaisesRegex(ValidationError, "another provider"):
            validate_config(config, activated=False)

    def test_malicious_topic_is_inert_quoted_data(self):
        value = {"topic": "x: !!python/object/apply:os.system ['bad']", "formula": "=IMPORTDATA(\"secret\")"}
        encoded = dumps(value)
        self.assertEqual(loads(encoded), value)
        with self.assertRaises(ValidationError):
            loads("topic: !!python/object/apply:os.system\n")

    def test_manifest_reproducible_and_tamper_fails(self):
        commit = "c" * 40
        first = build_manifest(ROOT, "0.1.0", commit)
        second = build_manifest(ROOT, "0.1.0", commit)
        self.assertEqual(manifest_bytes(first), manifest_bytes(second))
        self.assertNotIn("conditional_write", first["required_capabilities"])
        self.assertNotIn("idempotent_create", first["required_capabilities"])
        self.assertNotIn("serialized_execution", first["required_capabilities"])
        self.assertTrue({"raw_create", "raw_full_read", "raw_content_update", "paginated_inventory"} <= set(first["required_capabilities"]))
        verify_manifest(ROOT, first, resolved_commit=commit)
        tampered = json.loads(manifest_bytes(first))
        tampered["files"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValidationError):
            verify_manifest(ROOT, tampered, resolved_commit=commit)

    def test_manifest_rejects_unsafe_path_and_commit_mismatch(self):
        commit = "d" * 40
        manifest = build_manifest(ROOT, "0.1.0", commit)
        manifest["files"][0]["path"] = "../secret"
        with self.assertRaises(ValidationError):
            verify_manifest(ROOT, manifest, resolved_commit=commit)
        with self.assertRaises(ValidationError):
            verify_manifest(ROOT, build_manifest(ROOT, "0.1.0", commit), resolved_commit="e" * 40)

    def test_personalized_skill_is_bound_and_topic_rich(self):
        binding = SkillBinding("wp-abcdef1234567890", "root-1", "config-1", "map-1", "0.1.0", "f" * 64)
        generated = generate_skill("Alpha Research", binding, [{"name": "Synthetic optics", "aliases": ["test photonics"]}], ["Fixture Entity"])
        self.assertTrue(generated.name.startswith("wikiplant-alpha-research-"))
        self.assertIn("Synthetic optics", generated.description)
        self.assertIn("save, track, and research", generated.description)
        self.assertIn("wp-abcdef1234567890", generated.skill_md)
        self.assertIn("drive_root_id", generated.skill_md)
        self.assertIn("display_name", generated.openai_yaml)

    def test_topics_do_not_expand_primary_scope_implicitly(self):
        setup = SetupInput(primary_topics=[{"name": "Alpha", "aliases": ["A"]}])
        records = topic_records(setup)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], "Alpha")


if __name__ == "__main__":
    unittest.main()
