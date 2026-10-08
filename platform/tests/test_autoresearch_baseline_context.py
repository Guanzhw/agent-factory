"""Preflight order and original database isolation; no database or ML execution."""
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

# unittest discovery supplies platform/tests, not the sibling scripts directory.
# Pin the repository script; its fixed sibling imports need that same directory.
_scripts = Path(__file__).resolve().parents[2] / 'scripts'
sys.path.insert(0, str(_scripts))
_spec = importlib.util.spec_from_file_location('tested_autoresearch_baseline_context',
                                               _scripts / 'autoresearch_baseline_context.py')
assert _spec and _spec.loader
subject = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = subject
_spec.loader.exec_module(subject)
from agent_factory.research_local_driver import ScientificRuntimePin


class BaselineContextTests(unittest.TestCase):
    def factory(self):
        # Pin validation itself is tested against real private files elsewhere.
        pin = object.__new__(ScientificRuntimePin)
        return subject.BaselineServiceFactory(
            baseline_database_url='postgresql://fixture@localhost/original',
            controller_database_url='postgresql://fixture@localhost/controller', scientific_runtime=pin)

    def test_same_database_different_credentials_or_host_cannot_be_controller(self):
        for route in ('postgresql://different@localhost/original',
                      'postgresql://fixture@alias/original'):
            with self.subTest(route=route), self.assertRaisesRegex(ValueError, subject._ERROR):
                subject.BaselineServiceFactory(
                    baseline_database_url='postgresql://fixture@localhost/original',
                    controller_database_url=route, scientific_runtime=object.__new__(ScientificRuntimePin))

    def test_policy_failure_precedes_any_service_constructor_and_disposes_engine(self):
        engine = Mock()
        captured = {'originalConfig': {'workspace': '/synthetic'},
                    'contract': {'comparisonManifest': {}}}
        with patch.object(subject, 'create_engine', return_value=engine), \
             patch.object(subject, 'database_preflight', return_value={'status': 'BLOCKED'}), \
             patch.object(subject, 'open_state') as opened, \
             patch.object(subject, 'anchor_database') as anchor:
            with self.assertRaisesRegex(ValueError, subject._ERROR), self.factory()(captured):
                self.fail('must not yield')
            opened.assert_not_called(); anchor.assert_not_called()
        engine.dispose.assert_called_once()

    def test_both_original_targets_and_evaluation_service_use_original_store(self):
        events = []
        original_store = SimpleNamespace(storage=object())
        provider_state = object()
        state = {'store': original_store, 'auth': object(), 'resources': object()}
        @contextmanager
        def opened(settings, *, full_verification=False):
            events.append(('open', full_verification))
            self.assertEqual(settings.db_url, 'postgresql://fixture@localhost/original')
            yield state if full_verification else provider_state
        def reopen(actual_state, config, snapshot, **kwargs):
            self.assertIs(actual_state, provider_state)
            self.assertIs(kwargs['scientific_runtime'], factory._scientific_runtime)
            self.assertFalse(kwargs['candidate'])
            return {'target': snapshot}
        captured = {'originalConfig': {'workspace': '/synthetic'}, 'receipt': {},
            'contract': {'comparisonManifest': {'evaluator': {}}},
            'snapshots': {'training': object(), 'evaluation': object()}}
        factory = self.factory()
        settings = subject.Settings(db_url='postgresql://fixture@localhost/original',
                                    temporary_policy='admin-review', max_workers=1)
        checkpoints = Mock()
        with patch.object(subject, 'create_engine'), \
             patch.object(subject, 'database_preflight', side_effect=lambda *args: events.append(('policy',)) or {'status': 'PASS'}), \
             patch.object(subject, 'anchor_database', side_effect=lambda *args: events.append(('lineage',))), \
             patch.object(subject, 'manifest_fingerprint', return_value='a'*64), \
             patch.object(subject, 'open_state', side_effect=opened), \
             patch.object(subject, 'reconstruct_research_target', side_effect=reopen) as rebuilt, \
             patch.object(subject, 'research_settings', return_value=settings), \
             patch.object(subject, 'process_settings', return_value=settings), \
             patch.object(subject, 'registrations', return_value=[]), \
             patch.object(subject, 'ResearchCheckpointStore', return_value=checkpoints), \
             patch.object(subject, 'ResearchEvaluationService') as service:
            with factory(captured) as result:
                self.assertIs(result, service.return_value)
            self.assertEqual(rebuilt.call_count, 2)
            self.assertIs(service.call_args.args[0], original_store)
            self.assertIs(service.call_args.kwargs['checkpoint_reader'], checkpoints.identity)
        self.assertEqual(events, [('policy',), ('lineage',), ('open', False), ('open', True)])
