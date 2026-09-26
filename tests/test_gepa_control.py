import copy
import unittest

from panoptes.integrations.gepa import (
    evaluate_iteration,
    new_run,
    register_retry,
)


class GEPAControlTests(unittest.TestCase):
    def test_iteration_preserves_pareto_front_and_selects_complete_candidate(self):
        state = new_run(
            ["authority", "scope", "evidence"],
            engines=["structured", "interception-reflection"],
            metric_budget=12,
            plateau_patience=2,
            retry_limit=1,
        )
        result = evaluate_iteration(state, [
            {"id": "authority-specialist", "prompt": "A", "scores": {
                "authority": 1.0, "scope": 0.5, "evidence": 0.0}},
            {"id": "evidence-specialist", "prompt": "B", "scores": {
                "authority": 0.5, "scope": 0.5, "evidence": 1.0}},
            {"id": "complete", "prompt": "C", "scores": {
                "authority": 1.0, "scope": 1.0, "evidence": 1.0}},
        ])

        self.assertEqual(result["status"], "converged")
        self.assertEqual(result["selected_candidate"], "complete")
        self.assertEqual(result["frontier"], ["complete"])
        self.assertEqual(result["metric_calls"], 9)
        self.assertEqual(result["stop_reason"], "all_evaluation_slices_satisfied")

    def test_plateau_switches_engine_then_budget_stops_run(self):
        state = new_run(
            ["quality"], engines=["structured", "interception-reflection"],
            metric_budget=3, plateau_patience=1, retry_limit=1,
        )
        state = evaluate_iteration(state, [
            {"id": "seed", "prompt": "A", "scores": {"quality": 0.5}},
        ])
        state = evaluate_iteration(state, [
            {"id": "same", "prompt": "B", "scores": {"quality": 0.5}},
        ])
        self.assertEqual(state["status"], "running")
        self.assertEqual(state["current_engine"], "interception-reflection")
        self.assertEqual(state["engine_switches"], 1)

        state = evaluate_iteration(state, [
            {"id": "still-same", "prompt": "C", "scores": {"quality": 0.5}},
        ])
        self.assertEqual(state["status"], "stopped")
        self.assertEqual(state["stop_reason"], "metric_budget_exhausted")

    def test_retry_state_is_bounded_and_does_not_mutate_input(self):
        original = new_run(
            ["quality"], engines=["structured", "interception-reflection"],
            metric_budget=4, plateau_patience=2, retry_limit=1,
        )
        first = register_retry(original, "candidate", "temporary failure")
        second = register_retry(first, "candidate", "second failure")

        self.assertEqual(original["retry_counts"], {})
        self.assertEqual(first["retry_counts"], {"candidate": 1})
        self.assertEqual(second["retry_counts"], {"candidate": 2})
        self.assertEqual(second["current_engine"], "interception-reflection")
        self.assertEqual(second["engine_switches"], 1)
        self.assertEqual(second["retry_events"][-1]["reason"], "second failure")

    def test_rejects_duplicate_candidate_ids_and_budget_overrun(self):
        state = new_run(["quality"], engines=["structured"], metric_budget=1)
        state = evaluate_iteration(state, [
            {"id": "one", "prompt": "A", "scores": {"quality": 0.5}},
        ])
        with self.assertRaisesRegex(ValueError, "not running"):
            evaluate_iteration(state, [
                {"id": "two", "prompt": "B", "scores": {"quality": 0.5}},
            ])

        running = new_run(["quality"], engines=["structured"], metric_budget=3)
        duplicate = {"id": "same", "prompt": "A", "scores": {"quality": 0.5}}
        with self.assertRaisesRegex(ValueError, "unique"):
            evaluate_iteration(running, [duplicate, copy.deepcopy(duplicate)])


if __name__ == "__main__":
    unittest.main()
