import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from panoptes.cli import main
from panoptes.corpus import campaign
from panoptes.integrations.brainstormer import plan_to_excalidraw


SAMPLE = [
    {"id": "source", "desc": "Read source evidence", "deps": [], "check": "Pinned"},
    {"id": "adapter", "desc": "Build the adapter", "deps": ["source"], "check": "Works"},
    {"id": "audit", "desc": "Audit the behavior", "deps": ["adapter"], "check": "Accepted"},
]


class BrainstormerIntegrationTests(unittest.TestCase):
    def test_projects_component_dag_to_deterministic_excalidraw_skeletons(self):
        first = plan_to_excalidraw(SAMPLE)
        second = plan_to_excalidraw(SAMPLE)
        self.assertEqual(first, second)
        self.assertEqual(first["format"], "excalidraw-element-skeletons")
        self.assertEqual(first["source_revision"], "cbe68eb23715a024b46af60fbaab00d28fcb49b5")
        nodes = [item for item in first["elements"] if item["type"] != "arrow"]
        arrows = [item for item in first["elements"] if item["type"] == "arrow"]
        self.assertEqual([node["id"] for node in nodes], ["source", "adapter", "audit"])
        self.assertEqual([node["y"] for node in nodes], [100, 270, 440])
        self.assertEqual(nodes[-1]["type"], "diamond")
        self.assertEqual(len(arrows), 2)
        self.assertEqual(arrows[0]["start"]["id"], "source")
        self.assertEqual(arrows[0]["end"]["id"], "adapter")

    def test_real_lightweight_campaign_has_every_task_and_dependency(self):
        components = campaign(72)["components"]
        result = plan_to_excalidraw(components)
        nodes = [item for item in result["elements"] if item["type"] != "arrow"]
        arrows = [item for item in result["elements"] if item["type"] == "arrow"]
        self.assertEqual(len(nodes), 145)
        self.assertEqual(len(arrows), 144)
        self.assertEqual(result["component_count"], 145)
        self.assertEqual(result["dependency_count"], 144)
        expected_edges = {(dependency, component["id"])
                          for component in components for dependency in component["deps"]}
        emitted_edges = {(arrow["start"]["id"], arrow["end"]["id"])
                         for arrow in arrows}
        self.assertEqual(emitted_edges, expected_edges)
        self.assertEqual(len(emitted_edges), len(arrows))
        first_label = next(node["label"]["text"] for node in nodes
                           if node["id"] == "inspect-source-001")
        qworld_label = next(node["label"]["text"] for node in nodes
                            if "mims-harvard/Qworld" in node["label"]["text"])
        self.assertIn("qwadratic/create-mvp", first_label)
        self.assertIn("Inspect Source", qworld_label)

    def test_master_campaign_layout_is_bounded_and_fully_wired(self):
        components = campaign(360)["components"]
        result = plan_to_excalidraw(components)
        nodes = [item for item in result["elements"] if item["type"] != "arrow"]
        arrows = [item for item in result["elements"] if item["type"] == "arrow"]
        self.assertEqual((len(nodes), len(arrows)), (721, 720))
        self.assertLessEqual(max(node["x"] + node["width"] for node in nodes), 4200)
        expected_edges = {(dependency, component["id"])
                          for component in components for dependency in component["deps"]}
        self.assertEqual({(arrow["start"]["id"], arrow["end"]["id"])
                          for arrow in arrows}, expected_edges)

    def test_cli_writes_same_projection_and_invalid_graph_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "plan.json"
            output = Path(folder) / "diagram.json"
            source.write_text(json.dumps({"components": SAMPLE}), encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                main(["plan-diagram", str(source), "--output", str(output)])
            emitted = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(emitted, plan_to_excalidraw(SAMPLE))
            self.assertEqual(json.loads(stdout.getvalue())["output"], str(output))

            original = source.read_text(encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different paths"):
                main(["plan-diagram", str(source), "--output", str(source)])
            self.assertEqual(source.read_text(encoding="utf-8"), original)

        invalid = [dict(SAMPLE[0], deps=["missing"])]
        with self.assertRaisesRegex(ValueError, "missing dependency"):
            plan_to_excalidraw(invalid)

    def test_node_and_edge_ids_cannot_collide(self):
        graph = [
            {"id": "a", "desc": "A", "deps": [], "check": "A"},
            {"id": "b", "desc": "B", "deps": ["a"], "check": "B"},
            {"id": "arrow-a-to-b", "desc": "Valid component ID", "deps": [], "check": "C"},
        ]
        element_ids = [item["id"] for item in plan_to_excalidraw(graph)["elements"]]
        self.assertEqual(len(element_ids), len(set(element_ids)))


if __name__ == "__main__":
    unittest.main()
