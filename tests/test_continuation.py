"""State transitions that matter to a scheduled continuation."""

import tempfile
import unittest
from pathlib import Path

from panoptes.core import StaleCheckpoint, WriterBusy, acquire, advance, choose_next, connect, initialize, snapshot


class ContinuationTests(unittest.TestCase):
    SAFETY_CONSTRAINT = "Do not merge, deploy, or publish without established authority."

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "state.sqlite3"
        self.db = connect(self.path)
        initialize(self.db, "Build a prompt engine", ["Preserve decisions", self.SAFETY_CONSTRAINT])

    def tearDown(self):
        self.db.close()
        self.folder.cleanup()

    def test_missing_destination_then_correction_and_restart(self):
        acquire(self.db, "writer", now=100)
        first = advance(self.db, "R-001", 0, "writer", "blocked", ["repository absent"], now=101)
        self.assertIn("UNRESOLVED", first["next_prompt"])
        self.assertIn(self.SAFETY_CONSTRAINT, first["next_prompt"])
        self.assertEqual(snapshot(self.db)["checkpoint"], 1)
        self.db.close()
        self.db = connect(self.path)
        acquire(self.db, "writer", now=102)
        corrected = advance(self.db, "R-002", 1, "writer", "verified",
                            ["user supplied Panoptes"], destination="https://github.com/AlkaiDynamics/Panoptes", now=103)
        self.assertIn("AlkaiDynamics/Panoptes", corrected["next_prompt"])
        self.assertIn(self.SAFETY_CONSTRAINT, corrected["next_prompt"])
        self.assertEqual(snapshot(self.db)["constraints"], ["Preserve decisions", self.SAFETY_CONSTRAINT])

    def test_status_prompt_preserves_constraints_exactly(self):
        state = snapshot(self.db)
        prompt = choose_next(state)
        self.assertIn('Authoritative constraints (JSON): ["Preserve decisions",', prompt)
        self.assertIn(self.SAFETY_CONSTRAINT, prompt)

    def test_duplicate_and_stale_runs(self):
        acquire(self.db, "a", now=100)
        result = advance(self.db, "same", 0, "a", "verified", ["artifact"], now=101)
        self.assertEqual(result["checkpoint"], 1)
        self.assertTrue(advance(self.db, "same", 0, "a", "verified", ["artifact"], now=102)["duplicate"])
        with self.assertRaises(ValueError):
            advance(self.db, "same", 0, "a", "verified", ["different artifact"], now=102)
        acquire(self.db, "a", now=103)
        with self.assertRaises(StaleCheckpoint):
            advance(self.db, "different", 0, "a", "verified", ["artifact"], now=104)
        self.assertEqual(snapshot(self.db)["checkpoint"], 1)

    def test_lease_exclusion_and_expiry(self):
        acquire(self.db, "first", ttl=10, now=100)
        with self.assertRaises(WriterBusy):
            acquire(self.db, "second", now=105)
        acquire(self.db, "second", ttl=10, now=110)
        with self.assertRaises(WriterBusy):
            advance(self.db, "old", 0, "first", "verified", ["artifact"], now=111)

    def test_failed_run_is_recorded_without_advancing_checkpoint(self):
        acquire(self.db, "a", now=100)
        failed = advance(self.db, "failure", 0, "a", "failed", ["write failed"], now=101)
        self.assertEqual(failed["checkpoint"], 0)
        self.assertTrue(advance(self.db, "failure", 0, "a", "failed", ["write failed"], now=102)["duplicate"])
        self.assertEqual(snapshot(self.db)["checkpoint"], 0)


if __name__ == "__main__":
    unittest.main()
