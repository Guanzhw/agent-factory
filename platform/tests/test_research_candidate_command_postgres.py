"""Actual top-level stop command over PG/native/guardian fixture custody.

Only target reconstruction is injected: the fixture deliberately uses synthetic
stdlib programs and a mock device rather than source-bound Torch/NVIDIA inputs.
Journal, database lookup, state reopening, compute/native stop and receipt writes
run unchanged. This is integration wiring evidence, not a cold-restart GPU run.
"""
from dataclasses import replace
import importlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from agent_factory.research_runtime_profile import registrations, publish_research_application
from agent_factory.usage_ledger import UsageLedger
import test_research_local_postgres as fixture


@unittest.skipUnless(sys.platform == 'linux' and os.getenv('FACTORY_TEST_DATABASE_URL'),
                     'Requires disposable PostgreSQL and Linux guardian')
class CandidateCommandPostgresTests(unittest.TestCase):
    setUp = fixture.ResearchLocalPostgresTests.setUp
    cleanup = fixture.ResearchLocalPostgresTests.cleanup
    request = fixture.ResearchLocalPostgresTests.request
    post = fixture.ResearchLocalPostgresTests.post
    task = fixture.ResearchLocalPostgresTests.task
    detail = fixture.ResearchLocalPostgresTests.detail
    until = fixture.ResearchLocalPostgresTests.until

    def test_top_level_recover_stops_actual_original_compute_and_native_ticket(self):
        # Register a normal training reference through existing trusted APIs;
        # neither the original provider nor any custody guard is replaced.
        target = self.runtime.resources.targets['local']
        self.runtime.resources.targets['training'] = target
        adapters = registrations(target_ref='training', comparison_manifest=self.manifest,
                                 adapter_suffix='-candidate-training')
        for entry in adapters:
            self.store.execution_bindings.register(entry.kind, entry.adapter_id, entry.revision, entry.factory,
                tool_name=entry.tool_name, connection_kind=entry.connection_kind,
                required_capabilities=entry.required_capabilities, permissions=entry.permissions,
                demo_only=entry.demo_only, validator=entry.validator, connection_adapter_ref=entry.connection_adapter_ref)
        original_price = self.store.settings.usage_pricing[0]
        self.store.usage_ledger = UsageLedger(self.store,
            prices=(*self.store.usage_ledger.prices,
                    replace(original_price, adapter_id=original_price.adapter_id + '-candidate-training')),
            policy=self.store.settings.usage_policy)
        self.application = publish_research_application(self.state, target_ref='training',
            comparison_manifest=self.manifest, author='manager', reviewer='bob', adapter_suffix='-candidate-training')
        invocation = 'candidate-' + uuid4().hex[:16]
        proposal = self.post('/compositions/proposals', {'goal': 'Synthetic top-level stop command',
            'mode': 'controlled-fixture', 'applicationRef': {key: self.application[key] for key in ('id', 'version', 'sha256')}})
        plan = self.post('/compositions/proposals/' + proposal['id'] + '/accept')
        review = self.post('/plan-reviews', {'planId': plan['id']})
        self.post('/plan-reviews/' + review['id'] + '/decision', {'approved': True}, owner='manager')
        task = self.post('/instances', {'planId': plan['id'], 'requestId': invocation + ':training:instance'})
        self.until(lambda: self.detail(task['id']), lambda detail: detail['job']['status'] == 'waiting_approval')
        lease = self.portal.call(self.runtime.submit, 'alice', task['id'])
        self.assertNotEqual(lease['state'], 'RECLAIMED')
        original = self.store.task(task['id'], 'alice')
        scripts = str(Path(__file__).resolve().parents[2] / 'scripts')
        with patch.object(sys, 'path', [scripts, *sys.path]):
            journal_module = importlib.import_module('research_candidate_recovery')
            command = importlib.import_module('research_candidate_recover_command')
            reconstruction = importlib.import_module('research_candidate_reopen')
            baseline = importlib.import_module('run_research_baseline')
            workspace = Path(self.store.settings.workspace)
            baseline.write_private(workspace / 'command-dsn', self.store.settings.db_url.encode())
            baseline.write_private(workspace / 'training-recovery.json', b'{"stage":"training"}')
            identity = {'configSha256': 'a' * 64, 'candidateSha256': 'b' * 64, 'baselineManifestSha256': 'c' * 64}
            path = workspace / 'command-journal.json'
            with journal_module.CandidateJournal(path, identity=identity, total_seconds=90) as journal:
                journal.begin_stage('training')
                journal.record_progress('training', {'phase': 'PROCESS_SUBMITTED',
                    'requestId': invocation + ':training', 'taskId': task['id'], 'planId': original['plan_id'],
                    'nativeRunId': original['run_id'], 'leaseId': lease['id'], 'providerJobId': lease['providerJobId']})
            config = {'workspace': str(workspace), 'requestId': invocation}
            inputs = {'identity': identity, 'baselineConfig': {'databaseUrlFile': str(workspace / 'command-dsn')}}
            with journal_module.CandidateJournal(path, identity=identity) as journal, \
                    patch.object(reconstruction, 'reconstruct_research_target', return_value={'target': target}) as reconstruct:
                report = command.recover(config, inputs, journal)
                reconstruct.assert_called_once()
                self.assertTrue(report['cleanupConfirmed'], report)
                self.assertEqual(report['stages']['training']['status'], 'STOPPED')
                self.assertEqual(report['newAttempts'], 0)
                saved = journal.snapshot()['stages']['training']
                self.assertEqual(saved['progress']['leaseId'], lease['id'])
                self.assertEqual(saved['progress']['nativeRunId'], original['run_id'])
            settled = self.runtime.resources.inspect('alice', lease['id'])
            self.assertEqual(settled['state'], 'RECLAIMED')
            self.assertFalse(settled['capacityHeld'])
            self.assertTrue(settled['stopEvidence']['allStopped'])
            self.assertEqual(settled['gpuEvidence']['state'], 'RELEASED')
            self.assertEqual(self.store.native_db.get_job(original['run_id'], strict=True)['status'], 'cancelled')
            self.assertTrue(self.store.task(task['id'], 'alice')['terminal'])
            self.assertEqual(len(self.store.sql('SELECT id FROM af_tasks')), 1)
            self.assertEqual(len(self.store.sql('SELECT id FROM af_process_allocations')), 1)
            evidence = list(workspace.glob('recovery-*.json'))
            self.assertEqual(len(evidence), 1)
            self.assertEqual(json.loads(evidence[0].read_bytes()), report)
            self.assertFalse((self.work / 'release').exists())
