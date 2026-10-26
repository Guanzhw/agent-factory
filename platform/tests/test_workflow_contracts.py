"""Pure commitments/observation safety; no adapters executed or external effects."""
from copy import deepcopy
import unittest

from agent_factory.workflow_contracts import (DELEGATED_OPERATION_ADAPTER, ERROR, WorkflowContext, validate_failure_json,
    validate_runtime_observation)




def observation(state='COMPLETED', handle=True):
    return {'schema': 1, 'operationId': 'original-operation',
        'handle': {'adapterId': 'trusted-science', 'revision': '1', 'id': 'original-handle'} if handle else None,
        'state': state, 'allStopped': state in {'COMPLETED','FAILED','CANCELLED'},
        'output': {'score': 0.5} if state == 'COMPLETED' else None,
        'failure': {'schema':1, 'code':'INPUT_INVALID', 'messageCode':'CHECK_INPUT', 'retryable':False}
                   if state == 'FAILED' else None}


def validate(value, **kwargs):
    return validate_runtime_observation(value, 'original-operation', 'trusted-science', '1', **kwargs)


class WorkflowContractTests(unittest.TestCase):



    def test_failure_json_never_admits_exception_text_retry_or_extra_payload(self):
        base = observation('FAILED')['failure']
        self.assertEqual(validate_failure_json(base), base)
        for changes in ({'message':'raw error'}, {'retryable':True}, {'code':'raw error'}, {'schema':True}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, ERROR):
                validate_failure_json({**base, **changes})

    def test_each_state_requires_conservative_custody_shape(self):
        for state in ('RUNNING','WAITING','COMPLETED','FAILED','UNKNOWN','CANCELLED'):
            value = observation(state)
            self.assertEqual(validate(value), value)
            changed = deepcopy(value); changed['allStopped'] = not value['allStopped']
            with self.subTest(state=state), self.assertRaisesRegex(ValueError, ERROR):
                validate(changed)
        self.assertIsNone(validate(observation('UNKNOWN', handle=False))['handle'])
        for state in ('RUNNING','WAITING','COMPLETED','FAILED','CANCELLED'):
            with self.assertRaisesRegex(ValueError, ERROR):
                validate(observation(state, handle=False))

    def test_original_handle_operation_adapter_are_not_replaceable(self):
        previous = observation()['handle']
        for field, value in (('id','different'), ('adapterId','different'), ('revision','2')):
            changed = observation(); changed['handle'][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, ERROR):
                validate(changed, previous_handle=previous)
        with self.assertRaisesRegex(ValueError, ERROR):
            validate(observation('UNKNOWN', handle=False), previous_handle=previous)
        changed = observation(); changed['operationId'] = 'different'
        with self.assertRaisesRegex(ValueError, ERROR): validate(changed)
        changed = observation('FAILED'); changed['failure'] = None
        with self.assertRaisesRegex(ValueError, ERROR): validate(changed)
        changed = observation('RUNNING'); changed['output'] = {'unconfirmed':True}
        with self.assertRaisesRegex(ValueError, ERROR): validate(changed)



    def test_context_owner_and_opaque_original_coordinates(self):
        self.assertEqual(WorkflowContext('work','run','用户@example','step','a'*64).owner_id, '用户@example')
        for owner in ('', 'bad\nowner'):
            with self.assertRaisesRegex(ValueError, ERROR):
                WorkflowContext('work','run',owner,'step','a'*64)

    def test_output_is_bounded_inert_and_detached(self):
        value = observation()
        copied = validate(value)
        copied['output']['score'] = 9
        self.assertEqual(value['output']['score'], .5)
        for output in ({'endpoint':'https://example.invalid'}, {'api_key':'synthetic'},
                       {'data':'x'*4097}, {'score':float('nan')}, {'items':list(range(65))}):
            value = observation(); value['output'] = output
            with self.assertRaisesRegex(ValueError, ERROR):
                validate(value)
        value = observation(); value['authorityGranted'] = True
        with self.assertRaisesRegex(ValueError, ERROR):
            validate(value)

    def test_delegated_body_has_separate_capacity_without_relaxing_metadata(self):
        adapter, revision = DELEGATED_OPERATION_ADAPTER
        value = observation()
        value['handle']['adapterId'] = adapter
        value['output'] = {'taskId': 'child', 'runId': 'child-run', 'artifacts': [],
            'result': {'token': 'https://example.invalid\n' + '数' * 20000, 'values': list(range(100))}}
        checked = validate_runtime_observation(value, 'original-operation', adapter, revision)
        self.assertEqual(checked, value)
        checked['output']['result']['values'].append('detached')
        self.assertEqual(len(value['output']['result']['values']), 100)
        for patch in ({'host': 'not data'}, {'taskId': 'https://example.invalid'},
                      {'artifacts': [{'url': 'https://example.invalid'}]},
                      {'artifacts': ['x' * 4096] * 5}, {'result': 'x' * 1048575}):
            changed = deepcopy(value); changed['output'].update(patch)
            with self.subTest(patch=list(patch)), self.assertRaisesRegex(ValueError, ERROR):
                validate_runtime_observation(changed, 'original-operation', adapter, revision)
        value['output']['result'] = 'x' * (1048576 - 2)
        self.assertEqual(validate_runtime_observation(value, 'original-operation', adapter, revision), value)
        for other_adapter, other_revision in (('trusted-science', '1'), (adapter, '2')):
            value['handle'].update(adapterId=other_adapter, revision=other_revision)
            with self.assertRaisesRegex(ValueError, ERROR):
                validate_runtime_observation(value, 'original-operation', other_adapter, other_revision)

    def test_delegated_reader_uses_the_same_body_depth_bound(self):
        adapter, revision = DELEGATED_OPERATION_ADAPTER
        value = observation()
        value['handle']['adapterId'] = adapter
        for depth in (64, 65, 500):
            content = 'leaf'
            for _ in range(depth):
                content = {'data': content}
            value['output'] = {'taskId': 'child', 'runId': 'child-run', 'artifacts': [], 'result': content}
            if depth == 64:
                self.assertEqual(validate_runtime_observation(value, 'original-operation', adapter, revision), value)
            else:
                with self.subTest(depth=depth), self.assertRaisesRegex(ValueError, ERROR):
                    validate_runtime_observation(value, 'original-operation', adapter, revision)
