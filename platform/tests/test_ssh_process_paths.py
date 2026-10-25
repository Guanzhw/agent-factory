"""Remote POSIX contracts; PureWindowsPath also exercises them on Linux CI."""
from dataclasses import asdict, fields
import hashlib
from pathlib import PureWindowsPath
import unittest
from unittest.mock import patch

from agent_factory.process_enforcement import (
    ProcessEnforcementError, ProcessLimits, ProcessSpec,
    ResearchProcessLimits, ResearchProcessSpec, UvResearchProcessSpec,
)
from agent_factory.resources import ComputePool
from agent_factory.ssh_operation_runtime import SSHTrainingProfile
from agent_factory.ssh_process_contract import MAX_REQUEST_BYTES, encoded, specification


class SSHProcessPathTests(unittest.TestCase):
    def research(self, directory='/private/work'):
        return ResearchProcessSpec('/bin/train', 'a' * 64, (), path_style='posix',
            working_directory=directory, working_directory_identity=(1, 2),
            environment=tuple((name, '1') for name in (
                'HF_HUB_OFFLINE', 'HF_DATASETS_OFFLINE', 'TRANSFORMERS_OFFLINE', 'PYTHONNOUSERSITE')))

    def test_remote_reconstruction_uses_posix_on_windows_controller(self):
        original = self.research()
        with patch('agent_factory.process_enforcement.Path', PureWindowsPath):
            remote = self.research()
            restored, limits = specification(asdict(remote), asdict(ResearchProcessLimits()))
        self.assertIs(type(restored), ResearchProcessSpec)
        self.assertEqual(asdict(restored), asdict(original))
        self.assertEqual(limits, ResearchProcessLimits())
        self.assertNotIn('path_style', {field.name for field in fields(restored)})

    def test_dynamic_inputs_preserve_remote_semantics_and_profile_identity(self):
        original = SSHTrainingProfile(self.research(), ResearchProcessLimits(), '/runtime/python',
            ComputePool('configured', 2, 2048, 1024),
            input_schema={'type': 'object', 'properties': {'condition': {'type': 'string', 'maxLength': 64}},
                          'required': ['condition'], 'additionalProperties': False},
            input_argument='--experiment-json')
        expected_inputs, expected = original.prepare({'condition': 'baseline'})
        with patch('agent_factory.process_enforcement.Path', PureWindowsPath):
            actual_inputs, actual = original.prepare({'condition': 'baseline'})
            rebuilt, _ = specification(asdict(original.spec), asdict(original.limits))
            remote = SSHTrainingProfile(rebuilt, original.limits, original.interpreter,
                original.pool, original.input_schema, original.input_argument)
        self.assertEqual(actual_inputs, expected_inputs)
        self.assertEqual(asdict(actual), asdict(expected))
        self.assertEqual(actual.argv, ('--experiment-json', '{"condition":"baseline"}'))
        self.assertEqual(remote.fingerprint, original.fingerprint)

    def test_remote_rejects_relative_and_windows_drive_paths(self):
        for value in ('bin/train', 'C:/train', 'C:train', r'C:\train'):
            with self.subTest(path=value):
                with self.assertRaises(ProcessEnforcementError):
                    ProcessSpec(value, 'a' * 64, (), path_style='posix')
                with self.assertRaises(ProcessEnforcementError):
                    self.research(value)

    def test_default_native_validation_and_serialized_shape_stay_unchanged(self):
        with patch('agent_factory.process_enforcement.Path', PureWindowsPath):
            with self.assertRaises(ProcessEnforcementError):
                ProcessSpec('/bin/train', 'a' * 64, ())
            remote = ProcessSpec('/bin/train', 'a' * 64, (), path_style='posix')
            restored, _ = specification(asdict(remote), asdict(ProcessLimits()))
        self.assertIs(type(restored), ProcessSpec)
        self.assertEqual(asdict(restored), {'executable': '/bin/train', 'sha256': 'a' * 64, 'argv': ()})
        self.assertEqual(hashlib.sha256(encoded(
            {'spec': asdict(restored), 'limits': asdict(ProcessLimits())}, MAX_REQUEST_BYTES)).hexdigest(),
            '313210579f52cf9b0abe407cfc63029fc5443192be3ff095d3950be58f995257')

    def test_unknown_style_and_uv_remote_extension_are_rejected(self):
        with self.assertRaises(ProcessEnforcementError):
            ProcessSpec('/bin/train', 'a' * 64, (), path_style='other')
        with self.assertRaises(ProcessEnforcementError):
            UvResearchProcessSpec(**asdict(self.research()), path_style='posix')
