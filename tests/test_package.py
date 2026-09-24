"""Protect third-party license inclusion in wheel package data."""

import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackageTests(unittest.TestCase):
    def test_vendored_scaffold_keeps_mit_notice_in_package_data(self):
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("_vendor/HERMES_LICENSE",
                      metadata["tool"]["setuptools"]["package-data"]["panoptes"])
        self.assertIn("_vendor/GENETIC_PROMPT_LAB_LICENSE",
                      metadata["tool"]["setuptools"]["package-data"]["panoptes"])
        self.assertIn("_vendor/BRAINSTORMER_NOTICE",
                      metadata["tool"]["setuptools"]["package-data"]["panoptes"])
        notice = (ROOT / "panoptes/_vendor/HERMES_LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", notice)
        self.assertIn("Hermes Labs", notice)
        genetic_notice = (ROOT / "panoptes/_vendor/GENETIC_PROMPT_LAB_LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", genetic_notice)
        self.assertIn("Aman Priyanshu", genetic_notice)
        brainstormer_notice = (ROOT / "panoptes/_vendor/BRAINSTORMER_NOTICE").read_text(encoding="utf-8")
        self.assertIn("Apache License 2.0", brainstormer_notice)
        self.assertIn("cbe68eb23715a024b46af60fbaab00d28fcb49b5", brainstormer_notice)


if __name__ == "__main__":
    unittest.main()
