import contextlib
import copy
from datetime import datetime
import io
import json
import tempfile
import unittest
from pathlib import Path

from panoptes.cli import main
from panoptes.pilot_cycle import (
    PILOT_SCHEMA,
    discover_outstanding_result,
    run_pilot_cycle,
    select_next_unit,
    validate_pilot_contract,
)


REPO = "https://github.com/AlkaiDynamics/Panoptes"
SANDBOX = "sandbox/work-canary-20260928"
BASE_SHA = "5a48edd7296789922f927420cdf634d97a141b7e"


def unit(ident, deps=()):
    return {
        "id": ident,
        "objective": f"Complete {ident}.",
        "acceptance_criteria": [f"{ident} has objective evidence."],
        "exclusions": ["Do not touch main."],
        "depends_on": list(deps),
    }


def contract():
    return {
        "schema_version": PILOT_SCHEMA,
        "project": "Panoptes Work Canary",
        "repository": REPO,
        "sandbox_ref": SANDBOX,
        "execution_owner": "scheduled_work_task",
        "goal": "Prove scheduled Work can cause durable GitHub progress.",
        "authority": ["Panoptes main"],
        "rules": ["Evidence, not task prose, determines success."],
        "units": [
            unit("canary-write"),
            unit("canary-verify-continuation", ["canary-write"]),
            unit("canary-finish", ["canary-verify-continuation"]),
        ],
        "result_storage": {"target_receipt_dir": ".panoptes/results"},
    }


def target(next_sha=BASE_SHA):
    return {
        "schema_version": "panoptes.target-state/v1",
        "project": "Panoptes Work Canary",
        "repository": REPO,
        "checkpoint": {
            "default_branch": "main",
            "default_sha": BASE_SHA,
            "active_work": [
                {
                    "kind": "branch",
                    "ref": SANDBOX,
                    "head_sha": next_sha,
                    "status": "sandbox",
                }
            ],
        },
        "authority": {
            "role": "control_generation_only",
            "executor": "scheduled_work_task",
            "forbid_direct_mutation": True,
        },
        "execution": {
            "ref": SANDBOX,
            "instructions": ["Use only the sandbox branch."],
            "invariants": ["Do not merge or deploy."],
        },
        # pilot-cycle replaces this placeholder independently.
        "next_unit": {
            "id": "placeholder",
            "objective": "placeholder",
            "acceptance_criteria": ["placeholder"],
            "exclusions": [],
        },
    }


def capacity():
    return {
        "schema_version": "panoptes.account-capacity/v1",
        "account": "alkai",
        "status": "AVAILABLE",
        "limit_type": None,
        "observed_at": datetime.now().astimezone().isoformat(),
        "reset_at": None,
        "source": "manual",
        "evidence": "explicit current availability observation for test",
        "observation_freshness": "current",
        "last_probe_at": None,
        "last_probe_result": None,
        "updated_by": "test",
    }


class PilotCycleTests(unittest.TestCase):
    def test_contract_rejects_unknown_dependency_and_cycle(self):
        bad = contract()
        bad["units"][1]["depends_on"] = ["missing"]
        with self.assertRaisesRegex(ValueError, "unknown dependencies"):
            validate_pilot_contract(bad)

        bad = contract()
        bad["units"][0]["depends_on"] = ["canary-verify-continuation"]
        with self.assertRaisesRegex(ValueError, "cycle"):
            validate_pilot_contract(bad)

    def test_selector_is_dependency_ordered_and_independent(self):
        self.assertEqual(select_next_unit(contract(), set())["id"], "canary-write")
        self.assertEqual(
            select_next_unit(contract(), {"canary-write"})["id"],
            "canary-verify-continuation",
        )
        self.assertIsNone(
            select_next_unit(
                contract(),
                {"canary-write", "canary-verify-continuation", "canary-finish"},
            )
        )

    def test_first_cycle_emits_first_contract_unit(self):
        with tempfile.TemporaryDirectory() as folder:
            result = run_pilot_cycle(contract(), target(), None, folder)
        self.assertEqual(result["status"], "next-prompt-ready")
        self.assertEqual(result["selected_next_unit"]["id"], "canary-write")
        self.assertEqual(result["artifact"]["work_item"]["id"], "canary-write")
        self.assertEqual(
            result["state"]["outstanding"]["prompt_id"],
            result["artifact"]["prompt_id"],
        )

    def test_outstanding_without_receipt_waits_without_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            first = run_pilot_cycle(contract(), target(), None, folder)
            before = copy.deepcopy(first["state"])
            waiting = run_pilot_cycle(
                contract(), target(), first["state"], folder
            )
        self.assertEqual(waiting["status"], "waiting-for-executor-result")
        self.assertFalse(waiting["result_discovered"])
        self.assertEqual(waiting["state"], before)
        self.assertEqual(
            waiting["prompt_id"], first["artifact"]["prompt_id"]
        )

    def test_verified_receipt_uses_independent_next_unit_not_executor_proposal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = run_pilot_cycle(contract(), target(), None, root)
            prompt_id = first["artifact"]["prompt_id"]
            receipt_dir = root / ".panoptes" / "results"
            receipt_dir.mkdir(parents=True)
            commit = "c" * 40
            malicious_proposal = {
                "id": "canary-finish",
                "objective": "Skip the dependency.",
                "acceptance_criteria": ["wrong"],
                "exclusions": [],
            }
            receipt = {
                "schema_version": "panoptes.execution-result/v1",
                "prompt_id": prompt_id,
                "completed_unit_id": "canary-write",
                "target_repository": REPO,
                "status": "verified",
                "target_checkpoint": {"commit": commit, "ref": SANDBOX},
                "evidence": ["commit exists", "tests pass"],
                "next_unit": malicious_proposal,
            }
            (receipt_dir / f"{prompt_id}.json").write_text(
                json.dumps(receipt), encoding="utf-8"
            )

            advanced = run_pilot_cycle(
                contract(), target(next_sha=commit), first["state"], root
            )

        self.assertEqual(advanced["status"], "next-prompt-ready")
        self.assertTrue(advanced["result_discovered"])
        self.assertEqual(
            advanced["selected_next_unit"]["id"],
            "canary-verify-continuation",
        )
        self.assertEqual(
            advanced["executor_proposed_next_unit"]["id"], "canary-finish"
        )
        self.assertEqual(
            advanced["artifact"]["work_item"]["id"],
            "canary-verify-continuation",
        )
        applied = advanced["state"]["applied_results"][0]
        self.assertEqual(
            applied["executor_proposed_next_unit"]["id"], "canary-finish"
        )
        self.assertEqual(
            applied["next_unit"]["id"], "canary-verify-continuation"
        )

    def test_blocked_receipt_retries_same_dependency_unit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = run_pilot_cycle(contract(), target(), None, root)
            prompt_id = first["artifact"]["prompt_id"]
            receipt_dir = root / ".panoptes" / "results"
            receipt_dir.mkdir(parents=True)
            receipt = {
                "schema_version": "panoptes.execution-result/v1",
                "prompt_id": prompt_id,
                "completed_unit_id": "canary-write",
                "target_repository": REPO,
                "status": "blocked",
                "target_checkpoint": {"commit": None, "ref": SANDBOX},
                "evidence": ["temporary blocker"],
                "next_unit": unit("canary-finish"),
            }
            (receipt_dir / f"{prompt_id}.json").write_text(
                json.dumps(receipt), encoding="utf-8"
            )
            advanced = run_pilot_cycle(
                contract(), target(), first["state"], root
            )

        self.assertEqual(advanced["selected_next_unit"]["id"], "canary-write")
        self.assertEqual(advanced["artifact"]["work_item"]["id"], "canary-write")
        self.assertNotEqual(
            advanced["artifact"]["prompt_id"], first["artifact"]["prompt_id"]
        )

    def test_wrong_receipt_prompt_id_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = run_pilot_cycle(contract(), target(), None, root)
            prompt_id = first["artifact"]["prompt_id"]
            receipt_dir = root / ".panoptes" / "results"
            receipt_dir.mkdir(parents=True)
            receipt = {
                "schema_version": "panoptes.execution-result/v1",
                "prompt_id": "0" * 64,
            }
            (receipt_dir / f"{prompt_id}.json").write_text(
                json.dumps(receipt), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "does not match"):
                discover_outstanding_result(
                    contract(), first["state"], root
                )

    def test_cli_capacity_gate_happens_before_project_files_are_read(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cap = capacity()
            cap["status"] = "EXHAUSTED"
            cap["limit_type"] = "weekly"
            cap["reset_at"] = "2099-01-01T00:00:00+00:00"
            cap_path = root / "capacity.json"
            cap_path.write_text(json.dumps(cap), encoding="utf-8")
            state_path = root / "state.json"
            output = root / "prompt.json"

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                main([
                    "pilot-cycle",
                    "--capacity", str(cap_path),
                    "--account", "alkai",
                    "--capacity-max-age-seconds", "3600",
                    "--pilot", str(root / "does-not-exist-pilot.json"),
                    "--target", str(root / "does-not-exist-target.json"),
                    "--state", str(state_path),
                    "--target-root", str(root),
                    "--output", str(output),
                ])
            result = json.loads(stdout.getvalue())

        self.assertEqual(result["status"], "capacity-gated")
        self.assertFalse(result["project_state_changed"])
        self.assertFalse(state_path.exists())
        self.assertFalse(output.exists())

    def test_cli_persists_first_cycle_state_and_prompt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cap_path = root / "capacity.json"
            pilot_path = root / "pilot.json"
            target_path = root / "target.json"
            state_path = root / "state.json"
            output = root / "prompt.json"
            cap_path.write_text(json.dumps(capacity()), encoding="utf-8")
            pilot_path.write_text(json.dumps(contract()), encoding="utf-8")
            target_path.write_text(json.dumps(target()), encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                main([
                    "pilot-cycle",
                    "--capacity", str(cap_path),
                    "--account", "alkai",
                    "--capacity-max-age-seconds", "3600",
                    "--pilot", str(pilot_path),
                    "--target", str(target_path),
                    "--state", str(state_path),
                    "--target-root", str(root),
                    "--output", str(output),
                ])
            summary = json.loads(stdout.getvalue())
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            artifact = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(summary["status"], "next-prompt-ready")
        self.assertEqual(summary["selected_next_unit"], "canary-write")
        self.assertEqual(
            persisted["outstanding"]["prompt_id"], artifact["prompt_id"]
        )
        self.assertEqual(artifact["work_item"]["id"], "canary-write")


if __name__ == "__main__":
    unittest.main()
