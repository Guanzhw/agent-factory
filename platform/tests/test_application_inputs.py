"""Bounded input validation and portable governed-plan integrity, no model or queue."""
import copy
import unittest

from fastapi import HTTPException

from agent_factory.input_schema import bounded_json, validate_input_schema, validate_input_values
from agent_factory.store import digest
from test_applications_composition import ApplicationCompositionFixture, app_definition, pin


def schema():
    return {'type': 'object', 'additionalProperties': False, 'required': ['subject'], 'properties': {
        'subject': {'type': 'string', 'maxLength': 24, 'minLength': 1},
        'count': {'type': 'integer', 'minimum': 1, 'maximum': 3},
        'tags': {'type': 'array', 'maxItems': 2, 'items': {'type': 'string', 'maxLength': 8}},
        'enabled': {'type': 'boolean'}, 'empty': {'type': 'null'},
        'choice': {'type': 'string', 'maxLength': 8, 'enum': ['alpha', 'beta']}}}


class InputSchemaTests(unittest.TestCase):
    def test_supported_values_are_copied(self):
        value = {'subject': '公开合成资料', 'count': 2, 'tags': ['one'], 'enabled': True, 'empty': None, 'choice': 'alpha'}
        result = validate_input_values(schema(), value)
        value['tags'].append('two')
        self.assertEqual(result['tags'], ['one'])

    def test_invalid_values_fail_closed(self):
        for value in ({}, {'subject': ''}, {'subject': 'x', 'extra': 1}, {'subject': 'x', 'count': True},
                      {'subject': 'x', 'count': 4}, {'subject': 'x', 'tags': ['1', '2', '3']},
                      {'subject': 'x', 'choice': 'other'}, {'subject': 'x', 'empty': False},
                      {'subject': 'x', 'count': float('nan')}, {'subject': 'x', 'count': float('inf')}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'APPLICATION_INPUT_INVALID'):
                validate_input_values(schema(), value)

    def test_unsupported_schema_features_are_rejected(self):
        invalid = []
        for key, value in (('$ref', 'https://example.invalid/schema'), ('default', {}), ('code', 'pass')):
            invalid.append({**schema(), key: value})
        invalid += [{**schema(), 'additionalProperties': True}, {**schema(), 'required': ['missing']}]
        for child in ({'type': 'string'}, {'type': 'array', 'items': {'type': 'boolean'}},
                      {'type': 'string', 'maxLength': 10, 'pattern': '.*'},
                      {'type': 'number', 'maximum': float('inf')}, {'type': 'boolean', 'enum': [True, True]}):
            invalid.append({'type': 'object', 'properties': {'field': child}, 'additionalProperties': False})
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_input_schema(value)

    def test_depth_cycles_size_and_non_json_rejected(self):
        cycle = {}; cycle['cycle'] = cycle
        nested = {'type': 'boolean'}
        for _ in range(8):
            nested = {'type': 'object', 'properties': {'next': nested}, 'additionalProperties': False}
        with self.assertRaises(ValueError): validate_input_schema(nested)
        for value in (cycle, {'x': object()}, {'x': '中' * 16000}, {'x': 10 ** 1000}):
            with self.assertRaises(ValueError): bounded_json(value)


class GovernedInputTests(ApplicationCompositionFixture):
    def governed(self, identifier='synthetic-inputs'):
        definition = app_definition(self.store, identifier)
        definition['modes']['literature']['inputSchema'] = schema()
        return self.publish(definition)

    def proposal(self, app, values, key='input-proposal'):
        return self.composition.propose('alice', 'Check public synthetic input', application_ref=pin(app),
                                        input_values=values, request_id=key)

    def test_inputs_schema_and_values_are_pinned_and_copied(self):
        app = self.governed()
        values = {'subject': 'public', 'tags': ['one']}
        proposal = self.proposal(app, values)
        values['tags'].append('two')
        candidate = proposal['candidate']
        self.assertEqual(candidate['inputValues']['tags'], ['one'])
        self.assertEqual(candidate['bindingManifest']['inputSchemaSha256'], digest(schema()))
        self.assertEqual(candidate['bindingManifest']['inputValuesSha256'], digest(candidate['inputValues']))
        plan = self.composition.accept('alice', proposal['id'], 'accept-input')
        self.applications.require_plan_current(plan)
        self.assertEqual(self.store.plan(plan['id'], 'alice'), plan)
        self.assertEqual(plan['fingerprint'], digest({k: v for k, v in plan.items() if k not in {'id', 'createdAt', 'fingerprint'}}))

    def test_no_input_apps_omit_fields_and_reject_supplied_values(self):
        app = self.publish()
        first = self.composition.propose('alice', 'Synthetic text', application_ref=pin(app), request_id='old')
        repeated = self.composition.propose('alice', 'Synthetic text', application_ref=pin(app), input_values=None, request_id='old')
        self.assertEqual(first, repeated)
        self.assertNotIn('inputSchema', app['modes']['literature'])
        self.assertNotIn('inputValues', first['candidate'])
        self.assertNotIn('inputSchemaSha256', first['candidate']['bindingManifest'])
        with self.assertRaises(HTTPException) as error: self.proposal(app, {}, 'unexpected')
        self.assertEqual(error.exception.status_code, 422)

    def test_changed_inputs_conflict_and_revise_creates_new_pins(self):
        app = self.governed()
        original = self.proposal(app, {'subject': 'one'})
        with self.assertRaises(HTTPException) as error: self.proposal(app, {'subject': 'two'})
        self.assertEqual(error.exception.status_code, 409)
        revised = self.composition.revise('alice', original['id'], 'Revised synthetic input', application_ref=pin(app),
            input_values={'subject': 'two'}, request_id='revised-input')
        self.assertEqual(revised['candidate']['inputValues'], {'subject': 'two'})
        self.assertEqual(self.composition.inspect('alice', original['id'])['candidate']['inputValues'], {'subject': 'one'})

    def test_schema_and_value_tampering_and_cross_application_fail(self):
        app = self.governed()
        original = self.composition.accept('alice', self.proposal(app, {'subject': 'one'})['id'], 'accept-input')
        for field, value in (('inputValues', {'subject': 'two'}), ('inputSchema', {**schema(), 'required': []})):
            changed = copy.deepcopy(original); changed[field] = value
            with self.assertRaises(HTTPException): self.applications.require_plan_current(changed)
        other = self.publish(app_definition(self.store, 'another-application'))
        changed = copy.deepcopy(original); changed['applicationRef'] = pin(other)
        with self.assertRaises(HTTPException): self.applications.require_plan_current(changed)
        changed = copy.deepcopy(original); changed['inputValues']['subject'] = 'changed'
        with self.store.connection(write=True) as conn:
            conn.execute(self.store.plan_table.update().where(self.store.plan_table.c.id == original['id']).values(body=changed))
        with self.assertRaises(HTTPException): self.store.plan(original['id'], 'alice')

    def test_required_inputs_and_stale_application_pin_rejected(self):
        app = self.governed()
        with self.assertRaises(HTTPException): self.proposal(app, None)
        stale = pin(app); stale['sha256'] = '0' * 64
        with self.assertRaises(HTTPException):
            self.composition.propose('alice', 'Synthetic', application_ref=stale, input_values={'subject': 'one'}, request_id='stale')
