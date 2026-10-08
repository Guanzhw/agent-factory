"""Offline provenance checks never fetch or execute upstream."""
import hashlib
import unittest
from unittest.mock import patch
from agent_factory.research_profile import source_profile, verify_upstream_source


class ResearchProfileTests(unittest.TestCase):
    def test_profile_is_inert_and_defensively_copied(self):
        profile = source_profile()
        self.assertEqual(profile["trainingBudgetSeconds"], 300)
        self.assertFalse(profile["executionVerified"])
        self.assertIn("runtime_kernel_revision_and_license", profile["executionBlockers"])
        profile["sourceSha256"].clear()
        self.assertEqual(len(source_profile()["sourceSha256"]), 6)

    def test_missing_extra_and_forged_bytes_rejected(self):
        forged = {name: b"forged" for name in source_profile()["sourceSha256"]}
        for files in ({}, forged, {**forged, "extra.py": b"x"},
                      {name: digest for name, digest in source_profile()["sourceSha256"].items()}):
            with self.subTest(files=list(files)), self.assertRaisesRegex(ValueError, "RESEARCH_SOURCE_INVALID"):
                verify_upstream_source(files)

    def test_success_hashes_supplied_bytes_without_opening_paths(self):
        files = {name: ("synthetic:" + name).encode() for name in source_profile()["sourceSha256"]}
        pins = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
        with patch("agent_factory.research_profile.SOURCE_SHA256", pins), patch("builtins.open", side_effect=AssertionError):
            result = verify_upstream_source(files)
        self.assertEqual(result["sourceSha256"], pins)
        self.assertFalse(result["executionVerified"])
