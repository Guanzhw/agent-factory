import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import HTTPException

from agent_factory.application_runs import ApplicationRuns


class OriginalToolResultsTests(unittest.TestCase):
    def setUp(self):
        pin = {'id': 'cli-material', 'version': 1, 'sha256': 'material-hash'}
        runtime = {'adapterId': 'original-adapter', 'revision': '1',
                   'config': {'operationSha256': 'operation-hash'}}
        self.plan = {'materials': [{**pin, 'kind': 'tool', 'runtimeBinding': runtime}],
                     'materialRefs': [pin], 'tools': ['measure'],
                     'executionBindings': {'tools': [{**runtime, 'materialRef': pin,
                         'toolName': 'measure', 'connection': {'ref': 'private-connection'}}]}}
        self.operation = {'operationRef': {'id': 'operation', 'version': 1, 'sha256': 'operation-hash'},
                          'runtimeBinding': runtime,
                          'descriptor': {'transport': 'cli', 'toolName': 'measure'}}
        self.rows = [self.receipt('run:personal-tool:original')]
        self.store = Mock()
        self.store.task.side_effect = lambda identifier, owner: self.task(identifier, owner)
        self.store.plan.return_value = self.plan
        self.store.effects.return_value = self.rows
        self.store.personal_tools.operations.by_adapter.side_effect = lambda _: self.operation
        self.auth = Mock()
        self.service = ApplicationRuns(SimpleNamespace(store=self.store, auth=self.auth))

    @staticmethod
    def receipt(key, status='DONE', outcome='completed'):
        return {'effect_key': key, 'status': status,
                'result': {'outcome': outcome, 'output': {'metric': 7, 'private': 'not-shared'}}}

    @staticmethod
    def task(identifier, owner):
        if owner != 'alice':
            raise HTTPException(404, 'Task not found')
        return {'id': 'task', 'run_id': 'run', 'plan_id': 'plan'}

    def read(self, owner='alice', task='task', run='run'):
        return self.service.tool_results(owner, task, run)

    def test_original_result_is_private_detached_and_only_reads(self):
        result = self.read()
        self.assertEqual(result['receipts'][0]['effectKey'], 'run:personal-tool:original')
        self.assertEqual(result['receipts'][0]['output']['metric'], 7)
        self.assertNotIn('connection', result['binding'])
        result['receipts'][0]['output']['metric'] = 99
        self.assertEqual(self.rows[0]['result']['output']['metric'], 7)
        self.assertEqual([call[0] for call in self.store.mock_calls],
                         ['task', 'plan', 'personal_tools.operations.by_adapter', 'effects'])
        self.auth.require_member.assert_called_once_with('alice')

    def test_owner_run_alias_and_mismatched_identity_cannot_read_effects(self):
        for args in [('bob', 'task', 'run'), ('alice', 'run', 'run'),
                     ('alice', 'task', 'other'), ('alice', 'task', '')]:
            with self.subTest(args=args), self.assertRaises(HTTPException) as error:
                self.read(*args)
            self.assertEqual(error.exception.status_code, 404)
        self.store.effects.assert_not_called()

    def test_disabled_member_does_not_read_task(self):
        self.auth.require_member.side_effect = HTTPException(403, 'disabled')
        with self.assertRaises(HTTPException):
            self.read()
        self.store.task.assert_not_called()

    def test_multiple_tools_cannot_be_inferred_from_one_successful_receipt(self):
        self.plan['materials'].append({**self.plan['materials'][0], 'id': 'second'})
        with self.assertRaises(HTTPException) as error:
            self.read()
        self.assertEqual(error.exception.status_code, 409)
        self.store.effects.assert_not_called()

    def test_unsupported_or_mismatched_provenance_is_rejected(self):
        original_plan, original_operation = copy.deepcopy(self.plan), copy.deepcopy(self.operation)
        mutations = [lambda: self.plan.update(nativeComponent={'id': 'workflow'}),
                     lambda: self.plan.update(remoteHandoff={'receiver': 'elsewhere'}),
                     lambda: self.plan.update(tools=['measure', 'hidden']),
                     lambda: self.plan['executionBindings']['tools'][0].update(revision='2'),
                     lambda: self.plan['materialRefs'].clear(),
                     lambda: self.operation['descriptor'].update(transport='mcp'),
                     lambda: self.operation['operationRef'].update(sha256='changed')]
        for mutate in mutations:
            self.plan.clear()
            self.plan.update(copy.deepcopy(original_plan))
            self.operation = copy.deepcopy(original_operation)
            mutate()
            with self.subTest(mutation=mutate), self.assertRaises(HTTPException):
                self.read()
        self.plan.clear()
        self.plan.update(original_plan)
        self.store.personal_tools.operations.by_adapter.side_effect = lambda _: None
        with self.assertRaises(HTTPException):
            self.read()
        self.store.effects.assert_not_called()

    def test_only_original_successful_personal_tool_receipts_are_returned(self):
        self.rows.extend([self.receipt('other:personal-tool:call'), self.receipt('run:model:call'),
                          self.receipt('run:personal-tool:unknown', 'UNKNOWN'),
                          self.receipt('run:personal-tool:failed', outcome='failed'),
                          self.receipt('run:personal-tool:cancelled', 'CANCELLED', 'cancelled')])
        self.assertEqual([item['effectKey'] for item in self.read()['receipts']],
                         ['run:personal-tool:original'])


if __name__ == '__main__':
    unittest.main()
