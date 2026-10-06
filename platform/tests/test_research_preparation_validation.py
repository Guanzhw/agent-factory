"""Synthetic 8192-token preparation construction; no DB, child process or ML."""
import base64
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import Mock, patch

from agent_factory import research_bootstrap_assembly as assembly
from agent_factory.process_enforcement import ProcessLimits
from agent_factory.research_preparation_harness import tokenizer_payload
from agent_factory.research_preparation_provider import PreparationProvider


def synthetic_tokenizer(total):
    """Exactly total vocabulary entries including one required special token."""
    rows = [[base64.b64encode(bytes([i]) if i < 256 else b'merge' + i.to_bytes(4, 'little')).decode(), i]
            for i in range(total - 1)]
    return json.dumps({'schema': 1, 'pat_str': '.', 'mergeable_ranks': rows,
        'special_tokens': {'<|reserved_0|>': total - 1}}, separators=(',', ':')).encode()


class PreparationVocabularyTests(unittest.TestCase):
    def test_8192_total_entries_produce_32768_bytes_including_special_zero(self):
        raw = synthetic_tokenizer(8192)
        header, content = tokenizer_payload(raw)
        self.assertLess(len(raw), 1024**2)
        self.assertEqual(header, {'token_bytes': {'dtype': 'I32', 'shape': [8192], 'data_offsets': [0, 32768]}})
        self.assertEqual(len(content), 32768)
        self.assertEqual(content[-4:], b'\0' * 4)

    def test_8192_mergeable_plus_one_special_is_8193_and_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '^PREPARATION_VOCAB_LIMIT$'):
            tokenizer_payload(synthetic_tokenizer(8193))


@unittest.skipUnless(sys.platform == 'linux', 'Real bounded provider constructor requires Linux')
class PreparationConstructionTests(unittest.TestCase):
    def test_real_driver_provider_and_settings_construction_at_vocabulary_boundary(self):
        for total in (8192, 8193):
            with self.subTest(total=total), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                program, custody = workspace / 'program', workspace / 'custody'
                program.mkdir(mode=0o700); custody.mkdir(mode=0o700)
                info = program.stat()
                bootstrap, store = Mock(), Mock()
                state = {'store': store, 'auth': Mock()}
                app = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(factory=state)))
                with patch.object(assembly, 'Store', return_value=bootstrap) as store_constructor, \
                     patch.object(assembly, 'create_app', return_value=app) as application_constructor, \
                     patch('subprocess.Popen', side_effect=AssertionError('Construction must not launch')):
                    arguments: dict[str, Any] = dict(db_url='postgresql+psycopg://synthetic-unused/unused', workspace=workspace,
                        program_root=program, program_identity={'device': info.st_dev, 'inode': info.st_ino},
                        custody_root=custody, executable='/synthetic/not-executed-python', executable_sha256='a' * 64,
                        tokenizer_json=synthetic_tokenizer(total), preparation_manifest_sha256='b' * 64)
                    if total == 8193:
                        with self.assertRaisesRegex(ValueError, '^PREPARATION_VOCAB_LIMIT$'):
                            assembly.prepare_application(**arguments)
                        application_constructor.assert_not_called()
                        bootstrap.engine.dispose.assert_called_once()
                    else:
                        result = assembly.prepare_application(**arguments)
                        application_constructor.assert_called_once()
                        self.assertIsInstance(result['target'].provider, PreparationProvider)
                        self.assertEqual(result['target'].provider.limits,
                                         ProcessLimits(cpu_seconds=1, address_space_mb=128,
                                                       file_size_bytes=65536, wall_seconds=5))
                        self.assertEqual(result['settings'].runtime_tool_contract, 'research-bootstrap-v1')
                        self.assertFalse(result['target'].synthetic_fixture)
                        self.assertEqual(result['target'].max_seconds, 5)
                        self.assertEqual(result['target'].provider.driver.raw, arguments['tokenizer_json'])
                        bootstrap.engine.dispose.assert_not_called()
                    store_constructor.assert_called_once()
                    bootstrap.sql.assert_not_called()
                    store.sql.assert_not_called()
                    bootstrap.engine.connect.assert_not_called()
                    self.assertEqual(list(program.iterdir()), [])
                    self.assertEqual(list(custody.iterdir()), [])

    def test_assembly_cleanup_preserves_driver_failure_stage(self):
        from test_research_baseline_runner import runner
        diagnostics = runner.Diagnostics()
        bootstrap = Mock()
        bootstrap.engine.dispose.side_effect = RuntimeError('synthetic private cleanup detail')
        with patch.object(assembly, 'Store', return_value=bootstrap), \
             patch.object(assembly, 'PreparationDriver', side_effect=ValueError('synthetic private driver detail')), \
             patch.object(assembly, 'create_app') as create:
            try:
                assembly.prepare_application(db_url='postgresql+psycopg://synthetic-unused/unused',
                    workspace=Path('/synthetic'), program_root=Path('/synthetic/program'), program_identity={},
                    custody_root=Path('/synthetic/custody'), executable='/synthetic/python',
                    executable_sha256='a' * 64, tokenizer_json=b'{}', preparation_manifest_sha256='b' * 64,
                    diagnostics=diagnostics)
            except RuntimeError as error:
                diagnostics.capture(error)
            else:
                self.fail('cleanup failure must propagate')
            create.assert_not_called()
        self.assertEqual(diagnostics.failure, {'schema': 1, 'kind': 'RESEARCH_BASELINE_DIAGNOSTIC',
            'stage': 'PREPARATION_DRIVER', 'errorCode': 'VALIDATION_REJECTED',
            'secondaryStage': 'PREPARATION_ASSEMBLY_CLEANUP', 'secondaryErrorCode': 'RUNTIME_ERROR'})
