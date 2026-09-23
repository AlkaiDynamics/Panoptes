"""Run the pinned upstream Make engine with a real Panoptes corpus adapter."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("make") and shutil.which("jq"), "GNU make and jq required")
class EndToEndPlannerTests(unittest.TestCase):
    def test_goal_through_review_and_tamper_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            (run / "goal.md").write_text((ROOT / "examples/e2e/goal.md").read_text())
            (run / "Makefile").write_text(
                "GOAL := goal.md\nAGENT := python3 -m panoptes.e2e_agent\n"
                f"include {ROOT}/vendor/create-mvp/build.mk\n")
            env = dict(os.environ, PYTHONPATH=str(ROOT))

            def call(*args):
                return subprocess.run(args, cwd=run, env=env, capture_output=True, text=True)

            first = call("make", "-j2")
            self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
            report = (run / "build/report.md").read_text()
            self.assertIn("VERDICT: PASS", report)
            self.assertIn("Implemented/tested/accepted source contributions: 1/1/0", report)
            self.assertEqual(len(list((run / "build").glob("*.done"))), 4)
            second = call("make")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("Nothing to be done", second.stdout)
            light = run / "src/lightweight/artifact.json"
            content = light.read_text()
            light.write_text(content.replace('"candidate_count": 72', '"candidate_count": 71', 1))
            tampered = call("python3", "-m", "panoptes.e2e_agent", "verify", "lightweight")
            self.assertNotEqual(tampered.returncode, 0)
            self.assertIn("failed independent regeneration check", tampered.stderr)


if __name__ == "__main__":
    unittest.main()
