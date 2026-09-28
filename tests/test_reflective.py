import asyncio
import contextlib
import copy
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from panoptes.cli import main
from panoptes.control import run_invocation
from panoptes.reflective import progress_reflection
from test_control import ARCHOTRAZ_REPO, target_state, unit


class Backend:
    def __init__(self):
        self.calls = []
        self.answer = None

    async def submit(self, request, *, key, metadata, checkpoint):
        self.calls.append((request, key, metadata, checkpoint))
        return "interception-request-1"

    async def result(self, request_id, *, checkpoint):
        assert request_id == "interception-request-1"
        assert checkpoint == self.calls[0][3]
        return self.answer


def next_checkpoint():
    first, state, _ = run_invocation(None, target_state())
    sha = "b" * 40
    next_work = unit("snapshot-lineage")
    result = {
        "schema_version": "panoptes.execution-result/v1",
        "prompt_id": first["prompt_id"],
        "completed_unit_id": first["work_item"]["id"],
        "target_repository": ARCHOTRAZ_REPO,
        "status": "verified",
        "target_checkpoint": {"commit": sha, "ref": "sandbox/pilot"},
        "evidence": ["one behavior test passed", "commit " + sha],
        "next_unit": next_work,
    }
    target = target_state(active_sha=sha, next_unit=next_work)
    second, state, _ = run_invocation(state, target, result)
    return first, second, state, target


class ReflectionTests(unittest.TestCase):
    def test_cli_holds_second_prompt_until_validated_reflection(self):
        backend = Backend()
        with tempfile.TemporaryDirectory() as folder, patch(
            "panoptes.cli.InterceptionBackend.from_connection", return_value=backend
        ):
            root = Path(folder)
            capacity = root / "capacity.json"
            capacity.write_text(json.dumps({
                "schema_version": "panoptes.account-capacity/v1", "account": "alkai",
                "status": "AVAILABLE", "limit_type": None,
                "observed_at": datetime.now().astimezone().isoformat(),
                "reset_at": None, "source": "manual", "evidence": "test observation",
                "observation_freshness": "current", "last_probe_at": None,
                "last_probe_result": None, "updated_by": "test",
            }))
            target_path, state_path = root / "target.json", root / "state.json"
            output, result_path = root / "prompt.json", root / "result.json"
            args = ["control-run", "--capacity", str(capacity), "--account", "alkai",
                    "--capacity-max-age-seconds", "3600", "--target", str(target_path),
                    "--state", str(state_path), "--output", str(output),
                    "--reflect-connection", str(root / "connection.json")]
            target_path.write_text(json.dumps(target_state()))
            with contextlib.redirect_stdout(io.StringIO()):
                main(args)
            first = json.loads(output.read_text())
            self.assertEqual(len(backend.calls), 0)
            next_work, sha = unit("snapshot-lineage"), "b" * 40
            result_path.write_text(json.dumps({
                "schema_version": "panoptes.execution-result/v1",
                "prompt_id": first["prompt_id"], "completed_unit_id": first["work_item"]["id"],
                "target_repository": ARCHOTRAZ_REPO, "status": "verified",
                "target_checkpoint": {"commit": sha, "ref": "sandbox/pilot"},
                "evidence": ["behavior check passed"], "next_unit": next_work,
            }))
            target_path.write_text(json.dumps(target_state(active_sha=sha, next_unit=next_work)))
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                main([*args, "--result", str(result_path)])
            self.assertEqual(json.loads(stdout.getvalue())["status"], "waiting-for-reflection")
            self.assertEqual(json.loads(output.read_text())["prompt_id"], first["prompt_id"])
            waiting = state_path.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                main(args)
            self.assertEqual(state_path.read_bytes(), waiting)
            backend.answer = {"role": "assistant", "content": json.dumps({
                "failure_analysis": "Prior evidence is narrow.",
                "proposed_change": "Check restart behavior.",
                "test_focus": "Run save/reopen check.",
            })}
            with contextlib.redirect_stdout(io.StringIO()):
                main(args)
            second = json.loads(output.read_text())
            self.assertNotEqual(second["prompt_id"], first["prompt_id"])
            self.assertEqual(len(json.loads(state_path.read_text())["applied_results"]), 1)
            self.assertEqual(len(backend.calls), 1)
            complete_state = state_path.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                main(args)
            self.assertEqual(state_path.read_bytes(), complete_state)

    def test_submit_wait_complete_and_replay_without_second_request(self):
        first, base, state, target = next_checkpoint()
        backend = Backend()
        waiting, artifact, status = asyncio.run(progress_reflection(state, target, backend))
        self.assertEqual((artifact, status), (None, "waiting"))
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(backend.calls[0][3]["prompt_id"], base["prompt_id"])
        self.assertIn("one behavior test passed", backend.calls[0][0]["messages"][1]["content"])
        still_waiting, artifact, status = asyncio.run(progress_reflection(waiting, target, backend))
        self.assertEqual((artifact, status), (None, "waiting"))
        self.assertEqual(waiting, still_waiting)
        backend.answer = {"role": "assistant", "content": json.dumps({
            "failure_analysis": "The previous check missed restart behavior.",
            "proposed_change": "Inspect restart behavior in the next bounded unit.",
            "test_focus": "Save, reopen, and compare the exact receipt.",
        })}
        completed, reflected, status = asyncio.run(progress_reflection(waiting, target, backend))
        self.assertEqual(status, "completed")
        self.assertEqual(completed["completed_prompt_ids"], [first["prompt_id"]])
        self.assertEqual(len(completed["applied_results"]), 1)
        self.assertEqual(completed["run_sequence"], 2)
        self.assertNotEqual(reflected["prompt_id"], base["prompt_id"])
        self.assertEqual(reflected["base_prompt_id"], base["prompt_id"])
        self.assertEqual(reflected["result_contract"]["template"]["prompt_id"], reflected["prompt_id"])
        self.assertIn("Save, reopen", reflected["prompt"])
        self.assertEqual(reflected["optimization"]["reflection"], "interception_candidate_untested")
        repeated, same, status = asyncio.run(progress_reflection(completed, target, backend))
        self.assertEqual((repeated, same, status), (completed, reflected, "completed"))
        self.assertEqual(len(backend.calls), 1)

    def test_malformed_answer_does_not_advance_or_modify_waiting_state(self):
        _, _, state, target = next_checkpoint()
        backend = Backend()
        waiting, _, _ = asyncio.run(progress_reflection(state, target, backend))
        original = copy.deepcopy(waiting)
        backend.answer = {"role": "assistant", "content": "not JSON"}
        with self.assertRaisesRegex(ValueError, "must be JSON"):
            asyncio.run(progress_reflection(waiting, target, backend))
        self.assertEqual(waiting, original)

    def test_changed_checkpoint_cannot_consume_old_result(self):
        _, _, state, target = next_checkpoint()
        backend = Backend()
        waiting, _, _ = asyncio.run(progress_reflection(state, target, backend))
        waiting["reflection"]["checkpoint"]["previous_result_hash"] = "wrong"
        with self.assertRaisesRegex(ValueError, "checkpoint"):
            asyncio.run(progress_reflection(waiting, target, backend))
