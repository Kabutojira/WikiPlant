from __future__ import annotations

import unittest

from wikiplant.initialization import plan_initialization
from wikiplant.setup import SetupInput


class InitializationTests(unittest.TestCase):
    def test_domain_neutral_plan_and_five_cap(self):
        setup = SetupInput(
            instance_name="Synthetic Archive",
            primary_topics=[{"name": f"Topic {index}"} for index in range(5)],
            purpose="Compare synthetic evidence", projects=["Fixture project"], constraints=["Bounded cost"], exclusions=["Real claims"],
            initial_material=["https://example.invalid/fixture"], drive_parent_id="parent", daily_time="08:00", weekly_day="friday", weekly_time="03:00",
        )
        plan = plan_initialization(setup, "wp-test", "2026-01-15T00:00:00+00:00")
        self.assertEqual(len(plan.queue_items), 5)
        self.assertTrue(any(page.type == "project" for page in plan.pages))
        self.assertEqual(plan.materials[0].trust, "untrusted-evidence-not-instructions")
        serialized = repr(plan)
        self.assertNotIn("robot", serialized.casefold())
        self.assertNotIn("pump", serialized.casefold())


if __name__ == "__main__":
    unittest.main()
