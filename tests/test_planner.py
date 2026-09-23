import tempfile
import unittest
from pathlib import Path

from panoptes.core import StaleCheckpoint, acquire, connect, initialize, snapshot
from panoptes.planner import complete, install, next_task, validate


PLAN = [
    {"id": "contract", "desc": "Confirm 72 repository minimum", "deps": [], "check": "User constraint recorded"},
    {"id": "catalog", "desc": "Pin candidate sources", "deps": ["contract"], "check": "Sources have immutable revisions"},
    {"id": "adapter", "desc": "Build one working adapter", "deps": ["catalog"], "check": "Real input/output test passes"},
    {"id": "review", "desc": "Audit adapter", "deps": ["adapter"], "check": "Independent review passes"},
    {"id": "docs", "desc": "Document runbook", "deps": ["contract"], "check": "Operator can reproduce run"},
]


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.folder.name) / "db.sqlite3")
        initialize(self.db, "Integrate 72 distinct supplied repositories", ["Keep alarms enabled through blockers"])

    def tearDown(self):
        self.db.close()
        self.folder.cleanup()

    def write(self):
        return acquire(self.db, "writer")["checkpoint"]

    def test_real_graph_progress_and_restart(self):
        install(self.db, PLAN, self.write(), "writer")
        self.assertEqual(next_task(self.db)["task"]["id"], "contract")
        with self.assertRaises(ValueError):
            complete(self.db, "adapter", "verified", ["test"], self.write(), "writer")
        complete(self.db, "contract", "verified", ["user message"], snapshot(self.db)["checkpoint"], "writer")
        self.assertEqual(next_task(self.db)["task"]["id"], "catalog")
        self.db.close()
        self.db = connect(Path(self.folder.name) / "db.sqlite3")
        complete(self.db, "catalog", "blocked", ["no source pin"], self.write(), "writer")
        self.assertEqual(next_task(self.db)["task"]["id"], "docs")
        complete(self.db, "docs", "verified", ["reproduction transcript"], self.write(), "writer")
        self.assertEqual(next_task(self.db)["status"], "planning_fallback")
        self.assertIn("Keep the next run enabled", next_task(self.db)["prompt"])

    def test_gates_and_cycles(self):
        install(self.db, PLAN, self.write(), "writer")
        self.write()
        with self.assertRaises(StaleCheckpoint):
            complete(self.db, "contract", "verified", ["evidence"], 0, "writer")
        with self.assertRaises(ValueError):
            complete(self.db, "contract", "verified", [], snapshot(self.db)["checkpoint"], "writer")
        self.assertEqual(snapshot(self.db)["checkpoint"], 1)
        cycle = [{"id": "a", "desc": "a", "deps": ["b"], "check": "check"},
                 {"id": "b", "desc": "b", "deps": ["a"], "check": "check"}]
        with self.assertRaisesRegex(ValueError, "cycle"):
            validate(cycle)


if __name__ == "__main__":
    unittest.main()
