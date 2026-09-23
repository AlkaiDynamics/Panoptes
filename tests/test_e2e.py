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
    def test_scaffold_change_invalidates_only_audit(self):
        working = ROOT / "examples/e2e"
        initial = subprocess.run(["make", "-j2"], cwd=working, capture_output=True, text=True)
        self.assertEqual(initial.returncode, 0, initial.stderr)
        dry = subprocess.run(
            ["make", "-n", "-W", "../../panoptes/_vendor/hermes_scaffold.py"],
            cwd=working, capture_output=True, text=True)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn("panoptes.e2e_agent build audit", dry.stdout)
        self.assertIn("panoptes.e2e_agent review", dry.stdout)
        self.assertNotIn("panoptes.e2e_agent build lightweight", dry.stdout)

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
            self.assertIn("Implemented/tested/accepted source contributions: 2/2/0", report)
            self.assertEqual(len(list((run / "build").glob("*.done"))), 4)
            import json
            continuation = json.loads((run / "src/audit/artifact.json").read_text())["next_prompt"]
            self.assertIn("Next task [inspect-source-003]", continuation)
            self.assertIn("Hiteshgottapu/ReAct-AI", continuation)
            self.assertIn("Independent audit of existing unaccepted", continuation)
            audit = json.loads((run / "src/audit/artifact.json").read_text())["audit_collection_prompt"]
            self.assertIn("qwadratic/create-mvp", audit)
            self.assertIn("61c270933291e2c726d09aaa8f66edc5ab369dce", audit)
            self.assertIn("source revision", audit.lower())
            self.assertIn("return INSUFFICIENT EVIDENCE", audit)
            self.assertIn("python -m unittest discover -s tests -v", audit)
            self.assertIn("score audit-evidence.json", audit)
            from panoptes.corpus import integration_ledger
            evidence = run / "audit-evidence.json"
            evidence.write_text(json.dumps({"contributions": [
                {"url": item["url"], "source_revision": item["source_revision"],
                 "source_excerpt": "def wrap" if "hermes-blind" in item["url"] else "SHELL := /bin/bash",
                 "test_excerpt": "VERIFIED: audit", "collected_by": "test fixture only"}
                for item in integration_ledger()["contributions"]
            ]}))
            score = call("python3", "-m", "panoptes.e2e_agent", "score", str(evidence))
            self.assertEqual(score.returncode, 0, score.stderr)
            self.assertTrue(score.stdout.startswith("[HERMES-BLIND]"))
            self.assertIn("Score using only quoted evidence", score.stdout)
            self.assertIn("SHELL := /bin/bash", score.stdout)
            self.assertIn("submitted evidence is not independent", score.stdout)
            evidence.write_text(json.dumps({"contributions": []}))
            empty_score = call("python3", "-m", "panoptes.e2e_agent", "score", str(evidence))
            self.assertNotEqual(empty_score.returncode, 0)
            from panoptes._vendor.hermes_scaffold import wrap
            self.assertEqual(wrap("Audit evidence", variant="null"), "Audit evidence")
            self.assertEqual(wrap("Audit evidence", variant="v1"), "[HERMES-BLIND]\n"
                             "If you have prior exposure to this target or its author, "
                             "state it in one line.\nScore using only quoted evidence from "
                             "the target text below.\nUnknown or thin evidence = hedge; "
                             "do not confabulate.\n[/HERMES-BLIND]\n\nAudit evidence")
            with self.assertRaises(ValueError):
                wrap("Audit evidence", variant="unsupported")
            second = call("make")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("Nothing to be done", second.stdout)
            light = run / "src/lightweight/artifact.json"
            content = light.read_text()
            light.write_text(content.replace('"candidate_count": 72', '"candidate_count": 71', 1))
            tampered = call("python3", "-m", "panoptes.e2e_agent", "verify", "lightweight")
            self.assertNotEqual(tampered.returncode, 0)
            self.assertIn("failed independent regeneration check", tampered.stderr)
            audit_artifact = run / "src/audit/artifact.json"
            current_audit = audit_artifact.read_text()
            audit_artifact.write_text(current_audit.replace(
                "EVIDENCE COLLECTION REQUEST", "FABRICATED AUDIT", 1))
            audit_tampered = call("python3", "-m", "panoptes.e2e_agent", "verify", "audit")
            self.assertNotEqual(audit_tampered.returncode, 0)
            self.assertIn("failed independent regeneration check", audit_tampered.stderr)


if __name__ == "__main__":
    unittest.main()
