import tempfile
import unittest
from pathlib import Path

from panoptes.core import acquire, connect, initialize, snapshot
from panoptes.corpus import campaign, integration_ledger, load_corpus
from panoptes.planner import install, next_task


class CorpusCampaignTests(unittest.TestCase):
    def test_source_evidence_separates_working_framework_from_acceptance(self):
        ledger = integration_ledger()
        self.assertTrue(ledger["local_evidence_paths_checked"])
        self.assertEqual((ledger["selected"], ledger["implemented"], ledger["tested"], ledger["accepted"]), (7, 7, 7, 0))
        self.assertEqual(ledger["contributions"][0]["repository"], "qwadratic/create-mvp")
        self.assertEqual(ledger["contributions"][1]["repository"], "hermes-labs-ai/hermes-blind")
        self.assertEqual(ledger["contributions"][2]["repository"], "ncz-os/mnemos")
        self.assertEqual(ledger["contributions"][3]["repository"], "AmanPriyanshu/GeneticPromptLab")
        self.assertEqual(ledger["contributions"][4]["repository"], "shivangdoshi07/brainstormer")
        self.assertEqual(ledger["contributions"][5]["repository"], "mims-harvard/Qworld")
        self.assertEqual(ledger["contributions"][6]["repository"], "developzir/gepa-mcp")

    def test_bundled_corpus_and_distinct_72_and_360_campaigns(self):
        sources = load_corpus()
        self.assertEqual(len(sources), 434)
        hermes = next(s for s in sources if s["repository"] == "hermes-labs-ai/hermes-blind")
        self.assertEqual(hermes["inspection_status"], "partial_code_inspection")
        self.assertEqual(hermes["pinned_revision"], "61c270933291e2c726d09aaa8f66edc5ab369dce")
        react = next(s for s in sources if s["repository"] == "Hiteshgottapu/ReAct-AI")
        self.assertTrue(react["integration_disposition"].startswith("deferred"))
        forge = next(s for s in sources if s["repository"] == "iamadityakumar/forge")
        self.assertEqual(forge["pinned_revision"], "a80c38545ae09db5e76ecd2f4da91e23f19a39c3")
        self.assertEqual(forge["license"], "UNKNOWN")
        self.assertEqual(forge["integration_disposition"],
                         "deferred_pending_license_and_interception_boundary_review")
        gepa = next(s for s in sources if s["repository"] == "developzir/gepa-mcp")
        self.assertEqual(gepa["pinned_revision"], "398e514bfa456794225219fc9bd433d4f59983e2")
        self.assertEqual(gepa["selection_labels"], ["prompt_optimization"])
        self.assertEqual(len({source["url"] for source in sources}), 434)
        self.assertEqual(next(s for s in sources if s["repository"] == "qwadratic/create-mvp")["inspection_status"], "partial_code_inspection")
        for target in (72, 360):
            draft = campaign(target, sources)
            self.assertEqual(len(draft["candidates"]), target)
            self.assertEqual(len({s["url"] for s in draft["candidates"]}), target)
            self.assertNotIn("wangshengyi-del/PNSA", {s["repository"] for s in draft["candidates"]})
            self.assertNotIn("iamadityakumar/forge", {s["repository"] for s in draft["candidates"]})
            self.assertIn("robzilla1738/supergoal",
                          {source["repository"] for source in draft["candidates"]})
            self.assertIn("developzir/gepa-mcp",
                          {source["repository"] for source in draft["candidates"]})
            self.assertFalse(any(s["integration_disposition"].startswith("deferred")
                                 for s in draft["candidates"]))
            genetic = next(s for s in draft["candidates"]
                           if s["repository"] == "AmanPriyanshu/GeneticPromptLab")
            self.assertEqual(set(genetic["selection_labels"]),
                             {"prompt_optimization", "verification_evaluation"})
            self.assertNotIn("model_training_adaptation", genetic["selection_labels"])
            self.assertEqual(draft["operational_integrations_claimed"], 0)
            self.assertEqual(len(draft["components"]), 2 * target + 1)
            self.assertEqual(len(draft["components"][-1]["deps"]), target)

    def test_deferred_foundation_and_elected_source_cannot_reenter_campaigns(self):
        sources = load_corpus()
        for row in sources:
            if row["repository"] in {"qwadratic/create-mvp", "robzilla1738/supergoal"}:
                row["integration_disposition"] = "deferred_test_boundary_review"
        for target in (72, 360):
            draft = campaign(target, sources)
            self.assertEqual(len(draft["candidates"]), target)
            self.assertFalse({"qwadratic/create-mvp", "robzilla1738/supergoal",
                              "iamadityakumar/forge"} &
                             {row["repository"] for row in draft["candidates"]})

    def test_generated_plan_is_runnable_and_retains_source_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(Path(folder) / "state.sqlite")
            try:
                initialize(db, "72 actual integrations", ["Maintain continuity through blockers"])
                acquire(db, "writer")
                plan = campaign()
                first = install(db, plan["components"], 0, "writer")
                self.assertEqual(first["status"], "ready")
                self.assertEqual(first["task"]["id"], "inspect-source-001")
                self.assertIn(plan["candidates"][0]["repository"], first["prompt"])
                self.assertIn("Maintain continuity", first["prompt"])
                self.assertEqual(snapshot(db)["checkpoint"], 1)
                self.assertEqual(next_task(db)["task"], first["task"])
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
