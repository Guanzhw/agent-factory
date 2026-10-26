"""Real custody/effect persistence with synthetic child admission and stop facts."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from agent_factory.delegated_operations import DELEGATED_OPERATION_PIN, DelegatedOperations
from agent_factory.workflow_operations import OperationCustody
from test_workflow_operations import SQLiteStore


class DelegatedContentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        directory = stack.enter_context(tempfile.TemporaryDirectory())
        self.store = SQLiteStore(Path(directory) / 'content.db')
        stack.callback(self.store.engine.dispose)
        self.store.current_plan['budget'] = {'outputBytes': 65536}
        self.store.sql('CREATE TABLE af_delegation_links(owner_id TEXT,parent_id TEXT,'
            'request_id TEXT,child_id TEXT,plan_id TEXT)')
        self.store.sql("INSERT INTO af_tasks VALUES('child','alice','child-native','plan',FALSE,FALSE)")
        self.store.artifacts = Mock(return_value=[{'id': 'artifact', 'sha256': 'a' * 64}])
        self.group = {'parent': {'nativeStatus': 'running', 'failed': False},
            'children': [], 'allStopped': False, 'unknown': False}

        async def create(owner, parent, goal, mode, request_id, original_operation_id):
            self.store.sql('INSERT INTO af_delegation_links VALUES(:owner,:parent,:request,:child,:plan)',
                owner=owner, parent=parent, request=request_id, child='child', plan='plan')

        self.delegation = SimpleNamespace(store=self.store, create=AsyncMock(side_effect=create))
        self.observer = SimpleNamespace(inspect_subtree=AsyncMock(side_effect=lambda *_: self.group))
        adapter = DelegatedOperations(self.delegation, self.observer, DELEGATED_OPERATION_PIN)
        self.runtimes = {(DELEGATED_OPERATION_PIN['adapterId'], '1', DELEGATED_OPERATION_PIN['configFingerprint']): adapter}
        self.auth = SimpleNamespace(require_member=Mock())
        self.service = self.store.workflow = OperationCustody(self.store, self.auth, runtimes=self.runtimes)
        self.ctx = SimpleNamespace(user_id='alice', session_id='task', run_id='native')

    async def original(self, step='delegated-step'):
        self.group.update(allStopped=False, unknown=False)
        self.group['parent'] = {'nativeStatus': 'running', 'failed': False}
        return await self.service.start(self.ctx, step, 'child', DELEGATED_OPERATION_PIN,
            {'goal': 'measure score', 'mode': 'experiment'})

    def completed(self, content):
        self.group.update(allStopped=True, unknown=False)
        self.group['parent'].update(nativeStatus='completed', content=content)

    def assert_closed(self, record):
        self.assertTrue(record['closed'])
        self.assertFalse(self.service.task_held('task'))
        self.assertEqual({row['status'] for row in self.store.sql('SELECT status FROM af_effects')}, {'DONE'})
        restarted = OperationCustody(self.store, self.auth, runtimes=self.runtimes)
        self.assertEqual(restarted.read('alice', record['id']), record)

    async def test_normal_content_closes_original_and_survives_custody_restart(self):
        cases = ['line one\nline two', 'https://example.invalid/result', '数据\n' * 6000,
            {'token': 'scientific token', 'host': 'subject', 'URL': 'https://example.invalid',
             'not an identifier': [None, True, 2**60, 0.5, {'command': 'reported text'}]}]
        for index, content in enumerate(cases):
            with self.subTest(case=index):
                original = await self.original('case-' + str(index))
                self.completed(content)
                record = await self.service.lookup('alice', original['id'])
                self.assert_closed(record)
                self.assertEqual(record['observation']['state'], 'COMPLETED')
                self.assertEqual(record['observation']['output'], {'taskId': 'child', 'runId': 'child-native',
                    'result': content, 'artifacts': [{'taskId': 'child', 'artifactId': 'artifact', 'sha256': 'a' * 64}]})
                self.assertEqual(await self.service.lookup('alice', original['id']), record)
        self.assertEqual(self.delegation.create.await_count, len(cases))

    async def test_utf8_exact_budget_and_one_byte_over_both_close(self):
        self.store.current_plan['budget']['outputBytes'] = 1024
        exact = '好' * 340 + 'ab'
        self.assertEqual(len(json.dumps(exact, ensure_ascii=False).encode()), 1024)
        for index, content in enumerate((exact, exact + 'c')):
            original = await self.original('size-' + str(index))
            self.completed(content)
            record = await self.service.lookup('alice', original['id'])
            self.assert_closed(record)
            observation = record['observation']
            if index == 0:
                self.assertEqual(observation['state'], 'COMPLETED')
                self.assertEqual(observation['output']['result'], exact)
            else:
                self.assertEqual(observation['state'], 'FAILED')
                self.assertIsNone(observation['output'])
                self.assertEqual(observation['failure']['code'], 'DELEGATED_RESULT_LIMIT')
                self.assertEqual(self.group['parent']['content'], content)
        self.assertEqual(self.delegation.create.await_count, 2)

    async def test_non_json_content_closes_as_failed_without_coercion(self):
        cyclic = []; cyclic.append(cyclic)
        invalid = [{1: 'key'}, ('tuple',), float('nan'), float('inf'), {'set'}, object(), cyclic]
        for index, content in enumerate(invalid):
            with self.subTest(case=index):
                original = await self.original('invalid-' + str(index))
                self.completed(content)
                record = await self.service.lookup('alice', original['id'])
                self.assert_closed(record)
                self.assertEqual(record['observation']['state'], 'FAILED')
                self.assertEqual(record['observation']['failure']['code'], 'DELEGATED_RESULT_INVALID')
                self.assertIsNone(record['observation']['output'])
        self.assertEqual(self.delegation.create.await_count, len(invalid))

    async def test_content_does_not_override_unknown_descendant_stop(self):
        original = await self.original()
        self.completed({'token': 'x' * 70000})
        self.group.update(allStopped=False, unknown=True)
        self.group['children'] = [{'nativeStatus': 'unknown', 'failed': False}]
        for _ in range(2):
            record = await self.service.lookup('alice', original['id'])
            self.assertFalse(record['closed'])
            self.assertEqual(record['observation']['state'], 'UNKNOWN')
            self.assertIsNone(record['observation']['output'])
            self.assertTrue(self.service.task_held('task'))
            self.assertEqual(self.store.sql('SELECT status FROM af_effects')[0]['status'], 'UNKNOWN')
        self.delegation.create.assert_awaited_once()

    async def test_closed_short_record_keeps_original_result_after_restart(self):
        original = await self.original()
        self.completed('original short result')
        record = await self.service.lookup('alice', original['id'])
        self.assert_closed(record)
        self.completed('changed native content')
        self.assertEqual(await self.service.lookup('alice', original['id']), deepcopy(record))
