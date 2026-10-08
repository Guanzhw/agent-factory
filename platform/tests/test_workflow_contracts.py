"""Pure commitments/observation safety; no adapters executed or external effects."""
from copy import deepcopy
import unittest

from agent_factory.workflow_contracts import (ERROR, WorkflowContext, validate_failure_json,
    validate_resume, validate_runtime_observation, validate_workflow_definition, workflow_fingerprint)


def definition():
    return {'schema': 1, 'id': 'workflow', 'revision': '1', 'maxParallel': 2, 'stages': [
        {'id': name, 'adapterId': 'trusted-science', 'revision': '1', 'dependencies': dependencies,
         'inputs': {'sampleCount': 3, 'threshold': 0.5}, 'failureRoutes': {}, 'humanGate': gate}
        for name, dependencies, gate in (('fetch', [], False), ('measure', ['fetch'], True),
                                         ('review', ['measure'], False))]}


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
    def test_generic_dag_is_detached_canonical_and_has_no_hardcoded_stage_names(self):
        value = definition(); original = deepcopy(value)
        result = validate_workflow_definition(value)
        result['stages'][0]['inputs']['sampleCount'] = 4
        self.assertEqual(value, original)
        reordered = {key:value[key] for key in reversed(value)}
        self.assertEqual(workflow_fingerprint(value), workflow_fingerprint(reordered))
        self.assertNotEqual(workflow_fingerprint(value), workflow_fingerprint(result))
        context = WorkflowContext('workflow','run','user@example','fetch',workflow_fingerprint(value))
        self.assertEqual(context.stage_id, 'fetch')

    def test_graph_limits_cycles_unknown_nodes_and_failure_route_cycles_rejected(self):
        cases = []
        def case(change):
            value = definition(); change(value); cases.append(value)
        case(lambda d: d.update(maxParallel=True))
        case(lambda d: d.update(maxParallel=17))
        case(lambda d: d['stages'].extend([deepcopy(d['stages'][0])]*14))
        case(lambda d: d['stages'][0].update(dependencies=['review']))
        case(lambda d: d['stages'][0].update(dependencies=['missing']))
        case(lambda d: d['stages'][1].update(dependencies=['fetch','fetch']))
        case(lambda d: d['stages'][2].update(failureRoutes={'FAILED':'fetch'}))
        case(lambda d: d['stages'][0].update(failureRoutes={'FAILED':'missing'}))
        case(lambda d: d['stages'][0].update(humanGate='true'))
        for index, value in enumerate(cases):
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, ERROR):
                validate_workflow_definition(value)
        value = definition(); value['stages'][0]['failureRoutes'] = {'INPUT_INVALID':'review'}
        self.assertEqual(validate_workflow_definition(value), value)

    def test_inert_input_cannot_carry_endpoints_credentials_code_hooks_or_unbounded_data(self):
        for inputs in ({'endpoint':'https://example.invalid'}, {'nested':{'api_key':'synthetic'}},
                       {'factory':'arbitrary.callable'}, {'note':'https://example.invalid'},
                       {'data':'x'*4097}, {'data':'bad\x7f'}, {'data':'bad\ud800'}, {'value':float('nan')}, {'value':object()},
                       {'values':list(range(65))}):
            value = definition(); value['stages'][0]['inputs'] = inputs
            with self.subTest(keys=list(inputs)), self.assertRaisesRegex(ValueError, ERROR):
                validate_workflow_definition(value)

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

    def test_resume_requires_all_ancestors_and_never_replays_existing_selected_stage(self):
        value = definition()
        self.assertEqual(validate_resume(value,'fetch',{}), value['stages'][0])
        prior = {'fetch':observation(), 'measure':observation()}
        self.assertEqual(validate_resume(value,'review',prior), value['stages'][2])
        for incomplete in ({}, {'measure':observation()}, {'fetch':observation('UNKNOWN'), 'measure':observation()}):
            with self.assertRaisesRegex(ValueError, ERROR): validate_resume(value,'review',incomplete)
        for state in ('UNKNOWN','FAILED','COMPLETED','CANCELLED','WAITING','RUNNING'):
            with self.subTest(state=state), self.assertRaisesRegex(ValueError, ERROR):
                validate_resume(value,'review',{**prior,'review':observation(state)})
        # Validation preserves the gate; it does not approve it.
        self.assertTrue(validate_resume(value,'measure',{'fetch':observation()})['humanGate'])

    def test_unknown_fields_and_non_json_schema_do_not_create_authority(self):
        for value in ({**definition(), 'endpoint':'elsewhere'}, {**definition(), 'schema':True}):
            with self.assertRaisesRegex(ValueError, ERROR): validate_workflow_definition(value)
        value = observation(); value['authorityGranted'] = True
        with self.assertRaisesRegex(ValueError, ERROR): validate(value)
