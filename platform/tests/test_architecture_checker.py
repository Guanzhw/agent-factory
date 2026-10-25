"""Synthetic package trees prove boundary checks without assuming the app split."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

with patch.object(sys, "path", [str(Path(__file__).resolve().parents[2] / "scripts"), *sys.path]):
    from check_architecture import check, main


class ArchitectureCheckerTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = {"source_roots": ["src"], "core": ["core"], "apps": {
            "alpha": {"package": "apps.alpha", "public": ["apps.alpha.api"]},
            "beta": {"package": "apps.beta", "public": ["apps.beta.api"]}},
            "composition_roots": ["src/launch.py"]}
        self.write({"core/__init__.py": "", "core/runtime.py": "from shared import helper",
                    "shared/__init__.py": "", "shared/helper.py": "VALUE = 1",
                    "adapters/__init__.py": "", "adapters/client.py": "from core import runtime",
                    "apps/__init__.py": "", "apps/alpha/__init__.py": "", "apps/beta/__init__.py": "",
                    "apps/alpha/api.py": "from core import runtime\nfrom apps.beta import api",
                    "apps/beta/api.py": "from . import private", "apps/beta/private.py": "VALUE = 2",
                    "launch.py": "from apps.alpha import api\nfrom apps.beta import api as beta"})

    def write(self, files):
        for path, code in files.items():
            target = self.root / "src" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code + "\n", encoding="utf-8")

    def violations(self):
        _, _, violations, gaps = check(self.root, self.config)
        self.assertEqual(gaps, [])
        return {violation.chain for violation in violations}

    def test_legal_public_api_shared_helper_and_exact_composition(self):
        self.assertEqual(self.violations(), set())

    def test_direct_violation_reports_chain_source_line_and_fix(self):
        self.write({"core/runtime.py": "from apps.alpha import api"})
        self.assertIn(("core.runtime", "apps.alpha.api"), self.violations())
        config = self.root / "map.json"
        config.write_text(json.dumps(self.config))
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            status = main(["--root", str(self.root), "--config", str(config)])
        self.assertEqual(status, 1)
        self.assertIn("core.runtime -> apps.alpha.api", errors.getvalue())
        self.assertIn("src/core/runtime.py:1", errors.getvalue())
        self.assertIn("Fix:", errors.getvalue())
        self.assertFalse(json.loads(output.getvalue())["accepted"])

    def test_indirect_core_violation_through_adapter(self):
        self.write({"core/runtime.py": "from adapters import client", "adapters/client.py": "from apps.alpha import api"})
        self.assertIn(("core.runtime", "adapters.client", "apps.alpha.api"), self.violations())

    def test_cross_app_private_direct_and_via_helper(self):
        for code, expected in [("from apps.beta import private", ("apps.alpha.api", "apps.beta.private")),
                               ("from shared import helper", ("apps.alpha.api", "shared.helper", "apps.beta.private"))]:
            with self.subTest(code=code):
                self.write({"apps/alpha/api.py": code, "shared/helper.py": "from apps.beta import private"})
                self.assertIn(expected, self.violations())

    def test_package_initializer_and_reexport_are_dependencies(self):
        self.write({"shared/__init__.py": "from apps.alpha.api import VALUE"})
        self.assertIn(("core.runtime", "shared.helper", "shared", "apps.alpha.api"), self.violations())
        self.write({"core/runtime.py": "from shared import VALUE"})
        self.assertIn(("core.runtime", "shared", "apps.alpha.api"), self.violations())
        self.write({"core/runtime.py": "import shared.missing"})
        self.assertIn(("core.runtime", "shared", "apps.alpha.api"), self.violations())

    def test_relative_imports_in_packages_and_modules(self):
        self.write({"apps/alpha/__init__.py": "from ..beta import private",
                    "apps/alpha/api.py": "from ..beta import private"})
        paths = self.violations()
        self.assertIn(("apps.alpha", "apps.beta.private"), paths)
        self.assertIn(("apps.alpha.api", "apps.beta.private"), paths)

    def test_static_dynamic_import_aliases_and_unresolved_coverage(self):
        for code in ("import importlib as loader\nloader.import_module('apps.beta.private')",
                     "import importlib.util\nimportlib.import_module('apps.beta.private')",
                     "import importlib\nload = importlib.import_module\nload('apps.beta.private')",
                     "from importlib import import_module as load\nload('..beta.private', __package__)",
                     "__import__('apps.beta.private')"):
            with self.subTest(code=code):
                self.write({"apps/alpha/api.py": code})
                self.assertIn(("apps.alpha.api", "apps.beta.private"), self.violations())
        self.write({"apps/alpha/api.py": "from importlib import import_module\nimport_module(module_name)"})
        _, _, _, gaps = check(self.root, self.config)
        self.assertEqual(len(gaps), 1)
        self.assertIn("unresolved dynamic import", gaps[0])
        self.write({"apps/alpha/api.py": "from importlib import import_module\ndef f(import_module):\n    import_module('apps.beta.private')"})
        _, _, violations, gaps = check(self.root, self.config)
        self.assertEqual(violations, [])
        self.assertIn("shadowed import loader", gaps[0])
        self.write({"apps/alpha/api.py": "__import__('private', level=1)"})
        self.assertIn("relative __import__", check(self.root, self.config)[3][0])

    def test_composition_exception_never_covers_callers_or_siblings(self):
        self.write({"launch.py": "from apps.beta import private"})
        self.assertEqual(self.violations(), set())
        self.write({"core/runtime.py": "import launch", "core/launch.py": "from apps.alpha import api"})
        paths = self.violations()
        self.assertIn(("core.runtime", "launch"), paths)
        self.assertIn(("core.launch", "apps.alpha.api"), paths)
        invalid = deepcopy(self.config)
        invalid["composition_roots"] = ["src/*.py"]
        with self.assertRaisesRegex(ValueError, "one exact"):
            check(self.root, invalid)

    def test_stale_or_empty_ownership_cannot_report_success(self):
        for key, value in (("core", []), ("core", ["missing"])):
            with self.subTest(key=key, value=value):
                invalid = {**self.config, key: value}
                with self.assertRaises(ValueError):
                    check(self.root, invalid)
        invalid = deepcopy(self.config)
        invalid["apps"]["alpha"] = {"package": "core", "public": ["core.runtime"]}
        with self.assertRaisesRegex(ValueError, "cannot replace the core"):
            check(self.root, invalid)

    def test_standalone_core_without_apps_keeps_composition_boundary(self):
        self.config['apps'] = {}
        self.write({'launch.py': 'from core import runtime'})
        self.assertEqual(self.violations(), set())
        self.write({'shared/helper.py': 'import launch'})
        self.assertIn(('core.runtime', 'shared.helper', 'launch'), self.violations())

    def test_dynamic_coverage_is_limited_to_owned_code_and_reachable_helpers(self):
        dynamic = "import importlib\nimportlib.import_module(module_name)"
        self.write({"unrelated_test.py": dynamic})
        self.assertEqual(check(self.root, self.config)[3], [])
        self.write({"shared/helper.py": "import unrelated_test"})
        self.assertIn("unrelated_test.py", check(self.root, self.config)[3][0])
        self.write({"shared/helper.py": "VALUE = 1", "apps/alpha/unused_private.py": dynamic})
        self.assertIn("unused_private.py", check(self.root, self.config)[3][0])


if __name__ == "__main__":
    unittest.main()
