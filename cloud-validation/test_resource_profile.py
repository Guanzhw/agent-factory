"""Offline admission arithmetic tests; these are not live AgentOS load tests."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from resource_profile import (
    CPU_SCALE, GB, MIB, MAX_INPUT_BYTES, ProfileError, check_observed_capacity,
    load_json, validate_profile,
)

HERE = Path(__file__).resolve().parent


class ResourceProfileTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_json(HERE / "profiles/standard-32core-64gb.json")

    def test_both_synthetic_profiles_pass(self):
        for filename in ("standard-32core-64gb.json", "upper-54core-192gb.json"):
            with self.subTest(filename=filename):
                report = validate_profile(load_json(HERE / "profiles" / filename))
                self.assertTrue(report["valid"])
                self.assertFalse(report["capacity_claim"])
                self.assertFalse(report["runtime_verified"])
                self.assertEqual(report["evidence_level"], "synthetic-arithmetic-only")

    def test_decimal_gb_is_not_gib(self):
        report = validate_profile(self.profile)
        self.assertEqual(report["host"]["memory_bytes"], 64 * GB)
        self.assertEqual(report["host"]["memory_mib"], 61035.15625)
        self.assertNotEqual(report["host"]["memory_bytes"], 64 * 1024 * MIB)

    def test_rejects_fit_only_if_gb_is_mistaken_for_gib(self):
        for role in self.profile["reserved"].values():
            role["memory_mib"] = 1
        self.profile["workers"][0]["replicas"] = 1
        self.profile["workers"][0]["tree_budget"]["memory_mib"] = 61440
        with self.assertRaisesRegex(ProfileError, "memory overcommit"):
            validate_profile(self.profile)

    def test_all_infrastructure_is_reserved(self):
        report = validate_profile(self.profile)
        self.assertEqual(set(report["reserved"]), {"os", "postgres", "control"})
        self.assertEqual(report["total_reserved"]["cpu_cores"], 22)
        self.assertEqual(report["total_reserved"]["memory_mib"], 49152)

    def test_host_charges_tree_grants_not_current_inventory(self):
        report = validate_profile(self.profile)
        self.assertEqual(report["worker_tree_grants"]["cpu_cores"], 16)
        self.assertEqual(report["process_inventory"]["cpu_cores"], 14)
        self.assertEqual(report["worker_tree_grants"]["memory_mib"], 32768)
        self.assertEqual(report["process_inventory"]["memory_mib"], 21504)

    def test_cpu_overcommit_is_rejected(self):
        self.profile["workers"][0]["tree_budget"]["cpu_cores"] = 7
        with self.assertRaisesRegex(ProfileError, "CPU overcommit"):
            validate_profile(self.profile)

    def test_memory_overcommit_is_rejected(self):
        self.profile["workers"][0]["replicas"] = 6
        with self.assertRaisesRegex(ProfileError, "memory overcommit"):
            validate_profile(self.profile)

    def test_infrastructure_can_exhaust_host(self):
        self.profile["reserved"]["postgres"]["cpu_cores"] = 32
        with self.assertRaisesRegex(ProfileError, "infrastructure reservations: CPU overcommit"):
            validate_profile(self.profile)

    def test_second_worker_group_also_charged(self):
        extra = deepcopy(self.profile["workers"][0])
        extra["name"] = "second-group"
        self.profile["workers"].append(extra)
        with self.assertRaisesRegex(ProfileError, "host infrastructure.*overcommit"):
            validate_profile(self.profile)

    def test_waiting_does_not_release_any_resources(self):
        waiting = validate_profile(self.profile)
        stack = [self.profile["workers"][0]["process_tree"]]
        while stack:
            node = stack.pop()
            node["state"] = "running"
            stack.extend(node["children"])
        self.assertEqual(waiting, validate_profile(self.profile))

    def test_all_process_kinds_and_nested_browser_accounted(self):
        report = validate_profile(self.profile)
        self.assertEqual(set(report["process_inventory_by_kind"]),
                         {"runtime", "tool", "browser", "mcp", "experiment"})
        self.assertEqual(report["process_inventory_by_kind"]["browser"]["cpu_cores"], 6)
        self.assertEqual(report["workers"][0]["processes_per_replica"], 6)

    def test_nested_cap_is_not_an_additive_grant(self):
        report = validate_profile(self.profile)
        tool = self.profile["workers"][0]["process_tree"]["children"][0]
        del tool["subtree_budget"]
        self.assertEqual(report, validate_profile(self.profile))

    def test_nested_parent_cap_covers_descendant_reservations(self):
        tool = self.profile["workers"][0]["process_tree"]["children"][0]
        tool["subtree_budget"]["cpu_cores"] = 1.5
        with self.assertRaisesRegex(ProfileError, "subtree_budget: CPU overcommit"):
            validate_profile(self.profile)

    def test_nested_budget_never_adds_to_root_grant(self):
        root = self.profile["workers"][0]["process_tree"]
        root["subtree_budget"] = {"cpu_cores": 100, "memory_mib": 100000}
        root["children"][1]["reservation"]["cpu_cores"] = 4
        with self.assertRaisesRegex(ProfileError, "tree_budget: CPU overcommit"):
            validate_profile(self.profile)

    def test_tree_memory_covers_children(self):
        self.profile["workers"][0]["tree_budget"]["memory_mib"] = 1024
        with self.assertRaisesRegex(ProfileError, "tree_budget: memory overcommit"):
            validate_profile(self.profile)

    def test_unknown_fields_rejected_at_every_level(self):
        paths = [(), ("host",), ("runtime",), ("reserved",), ("reserved", "os"),
                 ("workers", 0), ("workers", 0, "tree_budget"),
                 ("workers", 0, "process_tree"),
                 ("workers", 0, "process_tree", "reservation")]
        for path in paths:
            with self.subTest(path=path):
                profile = deepcopy(self.profile)
                target = profile
                for part in path:
                    target = target[part]
                target["unknown"] = 1
                with self.assertRaisesRegex(ProfileError, "unknown fields"):
                    validate_profile(profile)

    def test_all_required_fields_rejected_when_absent(self):
        for key in self.profile:
            with self.subTest(key=key):
                profile = deepcopy(self.profile)
                del profile[key]
                with self.assertRaisesRegex(ProfileError, "missing fields"):
                    validate_profile(profile)

    def test_bad_resource_numbers_rejected(self):
        for number in (-1, 0, True, "2", None, float("inf"), float("nan"),
                       Decimal("NaN"), Decimal("Infinity"), Decimal("1e1000000"),
                       0.0000001, 1_000_001, [], {}):
            with self.subTest(number=str(number)):
                profile = deepcopy(self.profile)
                profile["workers"][0]["tree_budget"]["cpu_cores"] = number
                with self.assertRaises(ProfileError):
                    validate_profile(profile)

    def test_cpu_arithmetic_exact_at_supported_precision(self):
        self.profile["host"]["cpu_cores"] = Decimal("21.999999")
        with self.assertRaisesRegex(ProfileError, "CPU overcommit"):
            validate_profile(self.profile)
        self.profile["host"]["cpu_cores"] = Decimal("22.000000")
        self.assertEqual(validate_profile(self.profile)["unallocated"]["cpu_cores"], 0)

    def test_integer_fields_reject_booleans_fractions_and_nonpositive(self):
        for value in (True, 1.5, -1, 0, "1", float("inf")):
            for field in ("replicas", "memory_mib"):
                with self.subTest(value=value, field=field):
                    profile = deepcopy(self.profile)
                    target = profile["workers"][0]
                    if field == "memory_mib":
                        target = target["tree_budget"]
                    target[field] = value
                    with self.assertRaises(ProfileError):
                        validate_profile(profile)

    def test_schema_purpose_and_runtime_are_pinned(self):
        changes = [("schema_version", 2), ("schema_version", True),
                   ("purpose", "production"), ("version", "latest"),
                   ("engine", "other"), ("persistence", "sqlite"),
                   ("remote_compute_separate", False), ("remote_compute_separate", 1)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                profile = deepcopy(self.profile)
                target = profile if key in profile else profile["runtime"]
                target[key] = value
                with self.assertRaises(ProfileError):
                    validate_profile(profile)

    def test_invalid_container_shapes_rejected(self):
        for key, value in [("workers", []), ("workers", {}), ("host", []),
                           ("reserved", None), ("runtime", "agno")]:
            with self.subTest(key=key, value=value):
                profile = deepcopy(self.profile)
                profile[key] = value
                with self.assertRaises(ProfileError):
                    validate_profile(profile)

    def test_process_identity_type_and_state_rejected(self):
        for key, value in [("name", ""), ("kind", "unknown"), ("kind", []),
                           ("state", "released"), ("children", {})]:
            with self.subTest(key=key, value=value):
                profile = deepcopy(self.profile)
                profile["workers"][0]["process_tree"][key] = value
                with self.assertRaises(ProfileError):
                    validate_profile(profile)

    def test_root_must_be_runtime(self):
        self.profile["workers"][0]["process_tree"]["kind"] = "tool"
        with self.assertRaisesRegex(ProfileError, "root must be runtime"):
            validate_profile(self.profile)

    def test_duplicate_worker_names_rejected(self):
        self.profile["workers"].append(deepcopy(self.profile["workers"][0]))
        with self.assertRaisesRegex(ProfileError, "duplicate worker"):
            validate_profile(self.profile)

    def test_duplicate_process_names_rejected(self):
        root = self.profile["workers"][0]["process_tree"]
        root["children"][0]["name"] = root["name"]
        with self.assertRaisesRegex(ProfileError, "duplicate process"):
            validate_profile(self.profile)

    def test_excessive_tree_depth_rejected(self):
        root = self.profile["workers"][0]["process_tree"]
        for index in range(34):
            child = {"name": f"nested-{index}", "kind": "tool", "state": "waiting",
                     "reservation": {"cpu_cores": 0.01, "memory_mib": 1}, "children": []}
            root["children"] = [child]
            root = child
        with self.assertRaisesRegex(ProfileError, "exceeds depth"):
            validate_profile(self.profile)

    def test_validator_does_not_mutate_input(self):
        before = deepcopy(self.profile)
        validate_profile(self.profile)
        self.assertEqual(before, self.profile)

    def test_capacity_snapshot_comparison(self):
        report = validate_profile(self.profile)
        observed = {"cpu_cores": 32, "memory_bytes": 64 * GB,
                    "source": "sanitized synthetic fixture, not a live measurement"}
        self.assertTrue(check_observed_capacity(report, observed)["fits_observation"])
        for field, value in (("cpu_cores", 31.999999), ("memory_bytes", 64 * GB - 1)):
            with self.subTest(field=field):
                too_small = {**observed, field: value}
                with self.assertRaisesRegex(ProfileError, "overcommit"):
                    check_observed_capacity(report, too_small)

    def test_capacity_snapshot_unknown_and_missing_fields_fail(self):
        report = validate_profile(self.profile)
        for observed in ({}, {"cpu_cores":32,"memory_bytes":64*GB,"source":"test","extra":1}):
            with self.assertRaises(ProfileError):
                check_observed_capacity(report, observed)

    def test_strict_json_rejects_duplicates_constants_and_bad_json(self):
        for content in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}',
                        '{"a":-Infinity}', '[', '\xff'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "bad.json"
                path.write_bytes(content.encode("latin-1"))
                with self.assertRaises(ProfileError):
                    load_json(path)

    def test_missing_and_oversized_files_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            with self.assertRaises(ProfileError):
                load_json(path)
            path.write_bytes(b" " * (MAX_INPUT_BYTES + 1))
            with self.assertRaisesRegex(ProfileError, "input exceeds"):
                load_json(path)

    def test_cli_success_and_failure_exit_codes(self):
        passed = subprocess.run([sys.executable, str(HERE / "resource_profile.py"),
                                 str(HERE / "profiles/standard-32core-64gb.json")],
                                capture_output=True, text=True, check=False)
        self.assertEqual(passed.returncode, 0, passed.stderr)
        self.assertTrue(json.loads(passed.stdout)["valid"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text('{"schema_version":1}')
            failed = subprocess.run([sys.executable, str(HERE / "resource_profile.py"), str(path)],
                                    capture_output=True, text=True, check=False)
        self.assertEqual(failed.returncode, 2)
        self.assertEqual(failed.stdout, "")
        self.assertFalse(json.loads(failed.stderr)["valid"])

    def test_cli_capacity_check_stays_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capacity.json"
            path.write_text(json.dumps({"cpu_cores":32,"memory_bytes":64*GB,"source":"fixture"}))
            result = subprocess.run([sys.executable, str(HERE / "resource_profile.py"),
                                     str(HERE / "profiles/standard-32core-64gb.json"),
                                     "--capacity", str(path)],
                                    capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["capacity_check"]["fits_observation"])


if __name__ == "__main__":
    unittest.main()
