import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from panoptes.cli import main
from panoptes.integrations.genetic_prompt_lab import plan_evolution_round


POPULATION = [
    {"id": f"p{index}", "prompt": f"prompt {index}", "fitness": score}
    for index, score in enumerate((0.1, 0.8, 0.3, 0.7, 0.2, 0.6, 0.4, 0.5), 1)
]


class GeneticPromptLabIntegrationTests(unittest.TestCase):
    def test_source_algorithm_builds_deterministic_provider_neutral_queue(self):
        first = plan_evolution_round(POPULATION, mutation_rate=0.5, seed=17)
        second = plan_evolution_round(POPULATION, mutation_rate=0.5, seed=17)
        self.assertEqual(first, second)
        self.assertEqual([item["id"] for item in first["elites"]], ["p2", "p4", "p6", "p8"])
        self.assertEqual([item["parents"] for item in first["transformation_queue"][:2]],
                         [["p2", "p4"], ["p6", "p8"]])
        self.assertEqual([item["kind"] for item in first["transformation_queue"]].count("fresh_candidate"), 2)
        self.assertEqual(first["planned_population"], 8)
        self.assertFalse(first["inference_executed"])

    def test_cli_emits_same_work_queue_without_model_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "population.json"
            path.write_text(json.dumps({"population": POPULATION}), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                main(["prompt-evolve-plan", str(path), "--seed", "17", "--mutation-rate", "0.5"])
        result = json.loads(output.getvalue())
        self.assertEqual(result, plan_evolution_round(POPULATION, mutation_rate=0.5, seed=17))

    def test_rejects_duplicate_ids_and_nonfinite_scores(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            plan_evolution_round(POPULATION[:4] + [dict(POPULATION[0])])
        bad = [dict(item) for item in POPULATION[:4]]
        bad[0]["fitness"] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            plan_evolution_round(bad)


if __name__ == "__main__":
    unittest.main()
