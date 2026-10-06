"""Synthetic bytes only: no filesystem, database, process or ML execution."""
import base64
import json
import unittest
from unittest.mock import patch

from agent_factory.research_preparation_preflight import tokenizer_preflight


def value():
    return {'schema': 1, 'pat_str': '.',
            'mergeable_ranks': [[base64.b64encode(bytes([i])).decode(), i] for i in range(256)],
            'special_tokens': {'<|reserved_0|>': 256}}


def raw(data):
    return json.dumps(data, separators=(',', ':')).encode()


def checks(result):
    return {item['field']: item['status'] for item in result['checks']}


class PreparationPreflightTests(unittest.TestCase):
    def test_valid_export_uses_authority_and_returns_no_values(self):
        data = value(); data['pat_str'] = 'synthetic-private-pattern'
        result = tokenizer_preflight(raw(data))
        self.assertEqual(result['status'], 'PASS')
        self.assertTrue(all(item == 'PASS' for item in checks(result).values()))
        self.assertFalse(result['executionVerified'])
        self.assertNotIn('synthetic-private-pattern', json.dumps(result))
        self.assertLess(len(json.dumps(result)), 4096)

    def test_all_independent_fields_reported_in_one_result(self):
        data = value()
        data.update(schema=True, pat_str='', extra='private-unknown-key-value')
        data['mergeable_ranks'][0][1] = True
        data['mergeable_ranks'][1][0] = data['mergeable_ranks'][0][0]
        data['special_tokens'] = {'private-special': True, '': 999}
        result = tokenizer_preflight(raw(data)); rows = checks(result)
        for field in ('object_keys', 'schema', 'pattern', 'rank_ids', 'token_uniqueness',
                      'byte_coverage', 'special_names', 'special_ids', 'reserved_token', 'decoder_authority'):
            self.assertEqual(rows[field], 'BLOCKED', field)
        self.assertEqual(rows['payload_authority'], 'NOT_CHECKED')
        self.assertNotIn('private-', json.dumps(result))

    def test_invalid_bytes_utf8_json_and_duplicates_have_explicit_dependencies(self):
        for candidate, failed in ((None, 'input_bytes'), (b'', 'input_bytes'),
                (b'x' * (1024**2 + 1), 'input_bytes'), (b'\xff', 'utf8'),
                (b'{', 'json'), (b'{"schema":1,"schema":1}', 'json'), (b'NaN', 'json')):
            with self.subTest(field=failed):
                result = tokenizer_preflight(candidate)
                self.assertEqual(checks(result)[failed], 'BLOCKED')
                self.assertEqual(checks(result)['payload_authority'], 'NOT_CHECKED')
                self.assertEqual(result['status'], 'BLOCKED')

    def test_malformed_types_do_not_crash_or_hide_independent_special_checks(self):
        for ranks in (None, {}, [None], [['!', []]]):
            data = value(); data['mergeable_ranks'] = ranks
            data['special_tokens'] = {'': []}
            result = tokenizer_preflight(raw(data)); rows = checks(result)
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertEqual(rows['special_names'], 'BLOCKED')
            self.assertEqual(rows['reserved_token'], 'BLOCKED')
            self.assertEqual(rows['decoder_authority'], 'BLOCKED')
        self.assertEqual(checks(tokenizer_preflight(b'[]'))['object_keys'], 'BLOCKED')

    def test_noncanonical_base64_empty_and_oversized_token(self):
        for token, field in (('AB==', 'token_encoding'), ('', 'token_lengths'),
                (base64.b64encode(b'a' * 65537).decode(), 'token_lengths')):
            data = value(); data['mergeable_ranks'][0][0] = token
            self.assertEqual(checks(tokenizer_preflight(raw(data)))[field], 'BLOCKED')

    def test_preparation_vocab_cap_is_stricter_than_decoder(self):
        data = value()
        for i in range(256, 8192):
            data['mergeable_ranks'].append([base64.b64encode(i.to_bytes(4, 'little')).decode(), i])
        data['special_tokens'] = {'<|reserved_0|>': 8192}
        result = checks(tokenizer_preflight(raw(data)))
        self.assertEqual(result['decoder_authority'], 'PASS')
        self.assertEqual(result['vocabulary_size'], 'BLOCKED')
        self.assertEqual(result['payload_authority'], 'BLOCKED')

    def test_serialized_config_bound_is_independent_of_json_validity(self):
        result = checks(tokenizer_preflight(b'\n' * 1024**2))
        self.assertEqual(result['input_bytes'], 'PASS')
        self.assertEqual(result['serialized_config_bound'], 'BLOCKED')
        self.assertEqual(result['json'], 'BLOCKED')

    def test_authority_rejection_can_never_be_overridden_by_diagnostics(self):
        for target, field in (('decode_tokenizer_json', 'decoder_authority'),
                              ('tokenizer_payload', 'payload_authority')):
            with patch('agent_factory.research_preparation_preflight.' + target,
                       side_effect=ValueError('synthetic-secret')) as authority:
                result = tokenizer_preflight(raw(value()))
            authority.assert_called_once()
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertEqual(checks(result)[field], 'BLOCKED')
            self.assertNotIn('synthetic-secret', json.dumps(result))
