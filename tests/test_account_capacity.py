import contextlib
import copy
from datetime import datetime
import io
import json
import tempfile
import unittest
from pathlib import Path

from panoptes.account_capacity import (
    SCHEMA_VERSION,
    evaluate_capacity_gate,
    validate_capacity_state,
)
from panoptes.cli import main


def state(
    status="AVAILABLE",
    *,
    account="alkai",
    limit_type=None,
    reset_at=None,
    freshness="current",
    observed_at="2026-09-26T09:20:00-07:00",
):
    return {
        "schema_version": SCHEMA_VERSION,
        "account": account,
        "status": status,
        "limit_type": limit_type,
        "observed_at": observed_at,
        "reset_at": reset_at,
        "source": "manual",
        "evidence": f"explicit {status.lower()} observation",
        "observation_freshness": freshness,
        "last_probe_at": None,
        "last_probe_result": None,
        "updated_by": "manual",
    }


class AccountCapacityTests(unittest.TestCase):
    def test_available_allows_normal_panoptes_work(self):
        decision = evaluate_capacity_gate(
            state(),
            account="alkai",
            now=datetime.fromisoformat("2026-09-26T09:30:00-07:00"),
            max_age_seconds=600,
        )
        self.assertTrue(decision["admit_work"])
        self.assertTrue(decision["allow_panoptes"])
        self.assertEqual(decision["mode"], "normal")
        self.assertEqual(decision["recommended_model"], "Sol")
        self.assertEqual(decision["recommended_reasoning"], "high")

    def test_degraded_allows_cheaper_panoptes_work(self):
        decision = evaluate_capacity_gate(
            state("DEGRADED"),
            account="alkai",
            now=datetime.fromisoformat("2026-09-26T09:30:00-07:00"),
            max_age_seconds=600,
        )
        self.assertTrue(decision["admit_work"])
        self.assertTrue(decision["allow_panoptes"])
        self.assertEqual(decision["mode"], "degraded")
        self.assertEqual(decision["recommended_reasoning"], "low")

    def test_exhausted_before_reset_blocks_everything(self):
        decision = evaluate_capacity_gate(
            state(
                "EXHAUSTED",
                limit_type="weekly",
                reset_at="2026-09-28T14:20:00-07:00",
            ),
            account="alkai",
            now=datetime.fromisoformat("2026-09-26T09:30:00-07:00"),
            max_age_seconds=600,
        )
        self.assertFalse(decision["admit_work"])
        self.assertFalse(decision["allow_panoptes"])
        self.assertEqual(decision["mode"], "blocked")
        self.assertEqual(
            decision["reason"], "explicit_capacity_exhausted_until_reset"
        )

    def test_elapsed_reset_authorizes_probe_not_panoptes(self):
        record = state(
            "EXHAUSTED",
            limit_type="weekly",
            reset_at="2026-09-28T14:20:00-07:00",
        )
        before = copy.deepcopy(record)
        decision = evaluate_capacity_gate(
            record,
            account="alkai",
            now=datetime.fromisoformat("2026-09-28T14:25:00-07:00"),
            max_age_seconds=600,
        )
        self.assertTrue(decision["admit_work"])
        self.assertFalse(decision["allow_panoptes"])
        self.assertEqual(decision["effective_status"], "PROBE_AVAILABLE")
        self.assertEqual(decision["mode"], "probe")
        self.assertEqual(decision["recommended_model"], "Sol")
        self.assertEqual(decision["recommended_reasoning"], "low")
        self.assertEqual(record, before)

    def test_explicit_probe_available_does_not_admit_panoptes(self):
        decision = evaluate_capacity_gate(
            state("PROBE_AVAILABLE"),
            account="alkai",
            now=datetime.fromisoformat("2026-09-28T14:25:00-07:00"),
            max_age_seconds=600,
        )
        self.assertTrue(decision["admit_work"])
        self.assertFalse(decision["allow_panoptes"])
        self.assertEqual(decision["mode"], "probe")

    def test_stale_observation_fails_closed(self):
        decision = evaluate_capacity_gate(
            state("AVAILABLE", freshness="stale"),
            account="alkai",
            now=datetime.fromisoformat("2026-09-26T09:30:00-07:00"),
            max_age_seconds=600,
        )
        self.assertFalse(decision["admit_work"])
        self.assertFalse(decision["allow_panoptes"])
        self.assertEqual(
            decision["reason"], "capacity_observation_not_current"
        )

    def test_active_observation_age_boundary_and_future(self):
        now = datetime.fromisoformat("2026-09-26T09:30:00-07:00")
        for status in ("AVAILABLE", "DEGRADED"):
            with self.subTest(status=status):
                at_boundary = evaluate_capacity_gate(
                    state(status), account="alkai", now=now, max_age_seconds=600)
                self.assertTrue(at_boundary["allow_panoptes"])
                expired = evaluate_capacity_gate(
                    state(status, observed_at="2026-09-26T09:19:59-07:00"),
                    account="alkai", now=now, max_age_seconds=600)
                self.assertFalse(expired["allow_panoptes"])
                self.assertFalse(expired["admit_work"])
                self.assertEqual(expired["reason"], "capacity_observation_expired")
                future = evaluate_capacity_gate(
                    state(status, observed_at="2026-09-26T09:30:01-07:00"),
                    account="alkai", now=now, max_age_seconds=600)
                self.assertFalse(future["allow_panoptes"])
                self.assertEqual(future["reason"], "capacity_observation_future_dated")

    def test_invalid_max_age_fails_closed(self):
        for invalid in (0, -1, True, 1.5):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "positive integer"):
                evaluate_capacity_gate(state(), account="alkai",
                                       now=datetime.fromisoformat("2026-09-26T09:30:00-07:00"),
                                       max_age_seconds=invalid)

    def test_expired_control_run_does_not_read_or_write_project_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            capacity = root / "capacity.json"
            capacity.write_text(json.dumps(state(observed_at="2020-01-01T00:00:00+00:00")), encoding="utf-8")
            control = root / "control.json"
            output = root / "prompt.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                main(["control-run", "--capacity", str(capacity), "--account", "alkai",
                      "--capacity-max-age-seconds", "600",
                      "--target", str(root / "missing-target.json"),
                      "--state", str(control), "--output", str(output)])
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["capacity"]["reason"], "capacity_observation_expired")
            self.assertFalse(result["project_state_changed"])
            self.assertFalse(control.exists())
            self.assertFalse(output.exists())

    def test_accounts_cannot_be_cross_applied(self):
        with self.assertRaisesRegex(ValueError, "different account"):
            evaluate_capacity_gate(
                state(account="alkai"),
                account="zhenrez",
                now=datetime.fromisoformat("2026-09-26T09:30:00-07:00"),
                max_age_seconds=600,
            )

    def test_exhausted_requires_explicit_limit_type(self):
        with self.assertRaisesRegex(ValueError, "requires limit_type"):
            validate_capacity_state(state("EXHAUSTED"))

    def test_unknown_source_is_rejected(self):
        record = state()
        record["source"] = "work-failure"
        with self.assertRaisesRegex(ValueError, "source"):
            validate_capacity_state(record)

    def test_cli_capacity_gate_is_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "capacity.json"
            record = state(
                "EXHAUSTED",
                limit_type="weekly",
                reset_at="2026-09-28T14:20:00-07:00",
            )
            path.write_text(json.dumps(record), encoding="utf-8")
            before = path.read_bytes()
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                main([
                    "capacity-gate",
                    "--state",
                    str(path),
                    "--account",
                    "alkai",
                    "--capacity-max-age-seconds", "600",
                    "--now",
                    "2026-09-26T09:30:00-07:00",
                ])
            result = json.loads(stdout.getvalue())
            self.assertFalse(result["allow_panoptes"])
            self.assertEqual(path.read_bytes(), before)

    def test_control_run_blocks_before_project_state_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            capacity = root / "capacity.json"
            target = root / "target.json"
            control_state = root / "control.json"
            output = root / "next-prompt.json"
            capacity.write_text(
                json.dumps(state(
                    "EXHAUSTED",
                    limit_type="weekly",
                    reset_at="2099-01-01T00:00:00+00:00",
                )),
                encoding="utf-8",
            )
            target.write_text("{}", encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                main([
                    "control-run",
                    "--capacity",
                    str(capacity),
                    "--account",
                    "alkai",
                    "--capacity-max-age-seconds", "600",
                    "--target",
                    str(target),
                    "--state",
                    str(control_state),
                    "--output",
                    str(output),
                ])

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "capacity-gated")
            self.assertFalse(result["project_state_changed"])
            self.assertFalse(control_state.exists())
            self.assertFalse(output.exists())

    def test_control_run_requires_account_capacity_before_project_read(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            control_state = root / "control.json"
            output = root / "next-prompt.json"
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    main([
                        "control-run",
                        "--target", str(root / "missing-target.json"),
                        "--state", str(control_state),
                        "--output", str(output),
                    ])
            self.assertNotEqual(raised.exception.code, 0)
            self.assertFalse(control_state.exists())
            self.assertFalse(output.exists())

    def test_control_run_probe_only_does_not_touch_project_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            capacity = root / "capacity.json"
            control_state = root / "control.json"
            output = root / "next-prompt.json"
            capacity.write_text(json.dumps(state("PROBE_AVAILABLE")), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                main([
                    "control-run", "--capacity", str(capacity),
                    "--account", "alkai",
                    "--capacity-max-age-seconds", "600",
                    "--target", str(root / "missing-target.json"),
                    "--state", str(control_state),
                    "--output", str(output),
                ])
            self.assertEqual(json.loads(stdout.getvalue())["status"], "capacity-gated")
            self.assertFalse(control_state.exists())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
