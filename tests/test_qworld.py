"""Behavior tests for the pinned Qworld Recursive Expansion Tree adapter."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from panoptes.integrations.qworld import (
    QWORLD_REVISION,
    advance_criteria_run,
    build_criteria_plan,
    start_criteria_run,
)
from panoptes.planner import validate


ROOT = Path(__file__).resolve().parents[1]
QUESTION = "Does this release preserve user constraints and prove observable behavior?"


class QworldCriteriaPlanTests(unittest.TestCase):
    @staticmethod
    def result_for(state):
        ident = state["next_task"]["id"]
        artifacts = state["artifacts"]
        result = {"run_revision": state["revision"]}
        if ident.startswith("scenario-"):
            result["scenarios"] = artifacts["scenarios"] or [{
                "scenario_id": "s0",
                "scenario_name": "Release review",
                "scenario_description": (
                    "A reviewer must decide whether release evidence proves the stated behavior. "
                    "The decision must preserve the user's constraints. "
                    "The evidence must expose an observable outcome."
                ),
            }]
            return result
        if ident.startswith("perspective-"):
            result["perspectives"] = artifacts["perspectives"] or [
                {"perspective_id": f"p{index}",
                 "perspective_name": name,
                 "perspective_description": description,
                 "scenario_ids": ["s0"]}
                for index, (name, description) in enumerate([
                    ("Evidence fidelity", "Evaluate whether source and behavior evidence match the release claim."),
                    ("Constraint preservation", "Evaluate whether the delivered behavior preserves every user constraint."),
                    ("Failure safety", "Evaluate whether malformed evidence fails closed without advancing acceptance."),
                    ("Reproducibility", "Evaluate whether a reviewer can reproduce the observed outcome independently."),
                ])
            ]
            return result
        result["criteria"] = artifacts["criteria"] or [
            {"criterion_id": "c0", "criterion": "Cites an immutable source revision",
             "points": 8, "reasoning": "Pinned provenance enables reproduction. It also enables independent audit.",
             "perspective_ids": ["p0"]},
            {"criterion_id": "c1", "criterion": "Preserves every authoritative user constraint",
             "points": 7, "reasoning": "Constraints define the required outcome. Losing one invalidates the delivery.",
             "perspective_ids": ["p1"]},
            {"criterion_id": "c2", "criterion": "Rejects malformed or incomplete evidence",
             "points": 6, "reasoning": "Fail-closed behavior prevents false progress. It keeps counts honest.",
             "perspective_ids": ["p2"]},
            {"criterion_id": "c3", "criterion": "Claims acceptance without independent evidence",
             "points": -3, "reasoning": "Unsupported acceptance materially misstates readiness. It defeats independent review.",
             "perspective_ids": ["p3"]},
        ]
        return result

    def test_builds_complete_recursive_expansion_tree(self):
        plan = build_criteria_plan(QUESTION)

        self.assertEqual(plan["question"], QUESTION)
        self.assertEqual(plan["source_revision"], QWORLD_REVISION)
        self.assertEqual(plan["expansion_rounds"], {
            "scenario": 3,
            "perspective": 4,
            "criteria": 3,
        })
        self.assertEqual(len(plan["components"]), 17)
        self.assertEqual(plan["components"][0]["id"], "scenario-ground")
        self.assertEqual(plan["components"][-1]["id"], "score-calibrate")
        self.assertTrue(all(QUESTION in item["desc"] for item in plan["components"]))
        validate(plan["components"])

    def test_expansion_rounds_and_final_gates_are_dependency_ordered(self):
        components = build_criteria_plan(QUESTION)["components"]
        by_id = validate(components)

        self.assertEqual(by_id["scenario-expand-1"]["deps"], ["scenario-ground"])
        self.assertEqual(by_id["scenario-expand-3"]["deps"], ["scenario-expand-2"])
        self.assertEqual(by_id["perspective-expand-4"]["deps"], ["perspective-expand-3"])
        self.assertEqual(by_id["criteria-expand-3"]["deps"], ["criteria-expand-2"])
        self.assertEqual(by_id["criteria-review"]["deps"], ["criteria-expand-3"])
        self.assertEqual(by_id["polarity-check"]["deps"], ["criteria-review"])
        self.assertEqual(by_id["score-calibrate"]["deps"], ["polarity-check"])
        self.assertIn("YES or NO", by_id["criteria-review"]["check"])
        self.assertIn("positive", by_id["score-calibrate"]["check"])

    def test_rejects_missing_or_oversized_question(self):
        for invalid in (None, "", "   ", "x" * 20_001):
            with self.subTest(invalid=type(invalid).__name__):
                with self.assertRaises(ValueError):
                    build_criteria_plan(invalid)
        self.assertEqual(build_criteria_plan("q" * 20_000)["question"], "q" * 20_000)
        escaped = "line one\nquoted \"question\" with \\ slash"
        self.assertEqual(build_criteria_plan(escaped)["question"], escaped)

    def test_cli_emits_same_plan_and_can_write_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "criteria-plan.json"
            result = subprocess.run(
                [sys.executable, "-m", "panoptes.cli", "criteria-plan", QUESTION,
                 "--output", str(target)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["component_count"], 17)
            self.assertEqual(summary["output"], str(target))
            self.assertEqual(json.loads(target.read_text()), build_criteria_plan(QUESTION))

    def test_typed_run_carries_stage_outputs_to_pending_review(self):
        state = start_criteria_run(QUESTION)
        self.assertEqual(state["next_task"]["id"], "scenario-ground")
        while state["status"] == "ready":
            prior_id = state["next_task"]["id"]
            state = advance_criteria_run(state, self.result_for(state))
            if prior_id == "scenario-ground":
                self.assertIn("Release review", state["next_task"]["prompt"])
        self.assertEqual(len(state["completed"]), 17)
        self.assertEqual(state["status"], "pending_review")
        self.assertEqual(state["proposed_rubric"]["criteria"][0]["criterion_id"], "c0")
        self.assertGreater(
            sum(item["points"] for item in state["proposed_rubric"]["criteria"]), 0
        )

    def test_run_rejects_receipts_schema_loss_and_destructive_calibration(self):
        state = start_criteria_run(QUESTION)
        with self.assertRaisesRegex(ValueError, "exactly run_revision and the scenarios"):
            advance_criteria_run(state, {"ok": True})
        with self.assertRaisesRegex(ValueError, "scenario_id"):
            advance_criteria_run(state, {"run_revision": 0, "scenarios": [{
                "scenario_name": "Missing ID",
                "scenario_description": "One sentence. Two sentences. Three sentences.",
            }]})
        with self.assertRaisesRegex(ValueError, "3-5 sentences"):
            advance_criteria_run(state, {"run_revision": 0, "scenarios": [{
                "scenario_id": "s0", "scenario_name": "Generic response",
                "scenario_description": "ok",
            }]})

        while state["status"] == "ready" and state["next_task"]["id"] != "polarity-check":
            state = advance_criteria_run(state, self.result_for(state))
        invalid = copy.deepcopy(self.result_for(state))
        invalid["criteria"][0]["criterion"] = "Changes the original criterion text"
        with self.assertRaisesRegex(ValueError, "change only criterion points"):
            advance_criteria_run(state, invalid)

        state = advance_criteria_run(state, self.result_for(state))
        self.assertEqual(state["next_task"]["id"], "score-calibrate")
        sign_flip = copy.deepcopy(self.result_for(state))
        sign_flip["criteria"][0]["points"] = -1
        sign_flip["criteria"][3]["points"] = 10
        with self.assertRaisesRegex(ValueError, "not criterion polarity"):
            advance_criteria_run(state, sign_flip)
        bad_balance = copy.deepcopy(self.result_for(state))
        for item in bad_balance["criteria"][:3]:
            item["points"] = 1
        bad_balance["criteria"][3]["points"] = -10
        with self.assertRaisesRegex(ValueError, "outweigh negative"):
            advance_criteria_run(state, bad_balance)

    def test_expansion_cannot_drop_or_reorder_existing_items(self):
        state = start_criteria_run(QUESTION)
        state = advance_criteria_run(state, self.result_for(state))
        expanded = copy.deepcopy(self.result_for(state))
        expanded["scenarios"].append({
            "scenario_id": "s1", "scenario_name": "Recovery review",
            "scenario_description": (
                "A reviewer examines recovery after an interrupted run. "
                "The prior evidence must remain intact. "
                "The continuation must resume from the correct stage."
            ),
        })
        state = advance_criteria_run(state, expanded)
        dropped = copy.deepcopy(self.result_for(state))
        dropped["scenarios"] = dropped["scenarios"][:1]
        with self.assertRaisesRegex(ValueError, "preserve existing items"):
            advance_criteria_run(state, dropped)

    def test_run_rejects_tampered_history_artifacts_and_next_task(self):
        state = start_criteria_run(QUESTION)
        state = advance_criteria_run(state, self.result_for(state))

        tampered = copy.deepcopy(state)
        tampered["completed"][0]["id"] = "scenario-expand-1"
        with self.assertRaisesRegex(ValueError, "dependency order"):
            advance_criteria_run(tampered, self.result_for(state))

        tampered = copy.deepcopy(state)
        tampered["artifacts"]["scenarios"][0]["scenario_name"] = "Rewritten"
        with self.assertRaisesRegex(ValueError, "do not match"):
            advance_criteria_run(tampered, self.result_for(state))

        tampered = copy.deepcopy(state)
        tampered["next_task"]["id"] = "score-calibrate"
        with self.assertRaisesRegex(ValueError, "inconsistent ready task"):
            advance_criteria_run(tampered, self.result_for(state))

        stale = self.result_for(state)
        stale["run_revision"] -= 1
        with self.assertRaisesRegex(ValueError, "revision is stale"):
            advance_criteria_run(state, stale)

    def test_cli_advances_persisted_run_and_exposes_validated_context(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "run.json"
            result_path = Path(folder) / "result.json"
            started = subprocess.run(
                [sys.executable, "-m", "panoptes.cli", "criteria-run-start", QUESTION,
                 "--output", str(state_path)],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(started.returncode, 0, started.stderr)
            state = json.loads(state_path.read_text())
            result_path.write_text(json.dumps(self.result_for(state)))
            advanced = subprocess.run(
                [sys.executable, "-m", "panoptes.cli", "criteria-run-advance",
                 str(state_path), str(result_path), "--output", str(state_path)],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(advanced.returncode, 0, advanced.stderr)
            state = json.loads(state_path.read_text())
            self.assertEqual(state["completed"][0]["id"], "scenario-ground")
            self.assertIn("Release review", state["next_task"]["prompt"])

            original = state_path.read_bytes()
            stale = self.result_for(state)
            stale["run_revision"] -= 1
            result_path.write_text(json.dumps(stale))
            rejected = subprocess.run(
                [sys.executable, "-m", "panoptes.cli", "criteria-run-advance",
                 str(state_path), str(result_path), "--output", str(state_path)],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(state_path.read_bytes(), original)
            self.assertFalse(Path(f"{state_path}.lock").exists())

            result_path.write_text(json.dumps(self.result_for(state)))
            lock_path = Path(f"{state_path}.lock")
            lock_path.mkdir()
            locked = subprocess.run(
                [sys.executable, "-m", "panoptes.cli", "criteria-run-advance",
                 str(state_path), str(result_path), "--output", str(state_path)],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertNotEqual(locked.returncode, 0)
            self.assertIn("already locked", locked.stderr)
            self.assertEqual(state_path.read_bytes(), original)
            lock_path.rmdir()


if __name__ == "__main__":
    unittest.main()
