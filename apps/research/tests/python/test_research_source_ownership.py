"""Source relocation preserves the private, sealed scientific import namespace."""
import hashlib
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import agent_factory
import agent_factory_research
from agent_factory_research.research_local_driver import _RUNTIME_FILES, _runtime_pins, _runtime_source


class ScientificSourceOwnershipTests(unittest.TestCase):
    def test_sources_resolve_to_their_owned_packages(self):
        self.assertEqual(_runtime_source('store.py').parent, Path(agent_factory.__file__).parent)
        self.assertEqual(_runtime_source('research_interpreter.py'),
                         Path(agent_factory.__file__).parent / 'interpreter_identity.py')
        self.assertEqual(_runtime_source('research_torch_runtime.py').parent,
                         Path(agent_factory_research.__file__).parent)
        with self.assertRaises(ValueError):
            _runtime_source('../store.py')

    def test_source_pins_preserve_the_original_sealed_file_names(self):
        pins = _runtime_pins()
        self.assertEqual(tuple(pin.basename for pin in pins), _RUNTIME_FILES)
        interpreter = next(pin for pin in pins if pin.basename == 'research_interpreter.py')
        source = _runtime_source(interpreter.basename).read_bytes()
        self.assertEqual(interpreter.sha256, hashlib.sha256(source).hexdigest())
        self.assertEqual(interpreter.size_bytes, len(source))

    def test_scientific_dependency_closure_imports_in_original_private_namespace(self):
        # Import only the stdlib scientific wrapper; never initialize Torch,
        # launch training, resolve a credential or contact an external runtime.
        files = ('__init__.py', 'research_torch_runtime.py', 'research_checkpoint.py',
                 'research_evaluation.py', 'research_assessment.py', 'research_manifest.py', 'research_profile.py')
        with TemporaryDirectory() as directory:
            package = Path(directory) / 'agent_factory'
            package.mkdir()
            for name in files:
                (package / name).write_bytes(_runtime_source(name).read_bytes())
            code = ('import sys\nsys.path.insert(0, ' + repr(directory) + ')\n'
                'from agent_factory.research_torch_runtime import decode_tokenizer_json\n'
                'assert callable(decode_tokenizer_json)\n'
                'assert "torch" not in sys.modules\n'
                'assert "agent_factory_research" not in sys.modules\n')
            completed = subprocess.run([sys.executable, '-I', '-B', '-c', code],
                check=False, capture_output=True, text=True, timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_sealed_process_identity_imports_as_package_and_standalone(self):
        with TemporaryDirectory() as directory:
            package = Path(directory) / 'agent_factory'
            package.mkdir()
            for name in ('__init__.py', 'process_enforcement.py', 'research_interpreter.py'):
                (package / name).write_bytes(_runtime_source(name).read_bytes())
            for module_name, source_root in (
                ('agent_factory.process_enforcement', directory), ('process_enforcement', str(package))):
                code = ('import importlib,sys\nsys.path.insert(0, ' + repr(source_root) + ')\n'
                    'module=importlib.import_module(' + repr(module_name) + ')\n'
                    'identity=module.interpreter_module()\n'
                    'assert identity.__name__.endswith("research_interpreter")\n'
                    'assert callable(identity.validate_interpreter_contract)\n'
                    'assert "agent_factory_research" not in sys.modules\n')
                with self.subTest(module=module_name):
                    completed = subprocess.run([sys.executable, '-I', '-B', '-c', code],
                        check=False, capture_output=True, text=True, timeout=10)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
