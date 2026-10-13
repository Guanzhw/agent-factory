"""Source relocation preserves the private, sealed scientific import namespace."""
from contextlib import nullcontext
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import agent_factory
import agent_factory_research
from agent_factory_research.research_local_driver import _RUNTIME_FILES, _runtime_pins, _runtime_source
from agent_factory_research.research_staging import FilePin


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
        def portable_source_pins(package, names):
            # Real source bytes, but no claim of POSIX descriptor custody. The
            # original function still assembles names across the owned packages.
            result = []
            for name in names:
                source = (package / name).read_bytes()
                result.append(FilePin(name, hashlib.sha256(source).hexdigest(), len(source)))
            return tuple(result)

        if os.name != 'posix':
            with self.assertRaises(ValueError):
                _runtime_pins()  # Unsupported host must not acquire real custody.
        collectors = ('native', 'portable') if os.name == 'posix' else ('portable',)
        for collector in collectors:
            boundary = (patch('agent_factory_research.research_local_driver._package_runtime_pins',
                side_effect=portable_source_pins) if collector == 'portable' else nullcontext())
            with self.subTest(collector=collector), boundary:
                pins = _runtime_pins()
            self.assertEqual(tuple(pin.basename for pin in pins), _RUNTIME_FILES)
            for pin in pins:
                source = _runtime_source(pin.basename).read_bytes()
                self.assertEqual(pin.sha256, hashlib.sha256(source).hexdigest())
                self.assertEqual(pin.size_bytes, len(source))

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
