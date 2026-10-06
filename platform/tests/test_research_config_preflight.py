"""Pure diagnostics: no target, filesystem, database or provider activity."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from agent_factory.research_config_preflight import config_preflight, KEYS, FIELDS


def example():
    return {'schema': 1, 'ackLocalDevelopment': True, 'ackTraining': True,
        'databaseUrlFile': '/private/database', 'workspace': '/private/new', 'requestId': 'fixture-request',
        'inputRoot': '/private/input', 'tokenizerBasename': 'tokenizer.json',
        'shards': [{'id': 'train', 'basename': 'train.parquet'}, {'id': 'valid', 'basename': 'valid.parquet'}],
        'validationIds': ['valid'], 'upstreamRoot': '/private/upstream', 'projectRoot': '/private/project',
        'venvRoot': '/private/venv', 'interpreterTarget': '/private/python', 'interpreterSha256': 'a'*64,
        'approvedInterpreterRoots': ['/private'], 'deviceUuid': 'GPU-12345678', 'receiverNamespaceSha256': 'b'*64,
        'nvidiaSmi': {'executable': '/private/nvidia-smi', 'sha256': 'c'*64},
        'limits': {'cpu_seconds': 900, 'address_space_mb': 16384, 'file_size_bytes': 1073741824,
                   'wall_seconds': 900, 'disk_bytes': 3221225472, 'output_bytes': 16777216}, 'microbatch': 1}


def inspect(value):
    result = config_preflight(json.dumps(value).encode())
    return result, {row['field']: row for row in result['checks']}


class ConfigPreflightTests(unittest.TestCase):
    def test_complete_matches_authoritative_field_set_and_has_no_io(self):
        script = Path(__file__).resolve().parents[2] / 'scripts' / 'run_research_baseline.py'
        parsed = ast.parse(script.read_text())
        fields = next(ast.literal_eval(node.value) for node in parsed.body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == '_KEYS' for target in node.targets))
        self.assertEqual(KEYS, fields)
        with patch('builtins.open', side_effect=AssertionError('unexpected IO')):
            result, rows = inspect(example())
        self.assertEqual(set(rows), set(FIELDS))
        self.assertTrue(all(row['status'] == 'PASS' for row in rows.values()))
        self.assertTrue(KEYS <= result['validFields'])
        self.assertEqual(result['config'], example())

    def test_many_independent_failures_accumulate_even_without_training_ack(self):
        value = example()
        value.update(ackTraining=False, workspace='relative-secret-path', microbatch=3, interpreterSha256='wrong')
        value['limits']['cpu_seconds'] = True
        value['nvidiaSmi']['sha256'] = 'bad'
        result, rows = inspect(value)
        for field in ('ackTraining', 'workspace', 'microbatch', 'interpreterSha256', 'limits.cpu_seconds', 'nvidiaSmi.sha256'):
            self.assertEqual(rows[field]['status'], 'BLOCKED', field)
            self.assertNotIn(field, result['validFields'])
        self.assertTrue({'inputRoot', 'tokenizerBasename', 'interpreterTarget'} <= result['validFields'])
        self.assertNotIn('limits', result['validFields'])
        self.assertNotIn('nvidiaSmi', result['validFields'])
        self.assertNotIn('relative-secret-path', json.dumps(result['checks']))

    def test_missing_extra_and_nested_shape_do_not_hide_other_fields(self):
        value = example(); del value['inputRoot']
        value['private-secret-field'] = 'never echo'
        value['limits'] = []
        value['shards'] = [{'id': 'train'}, 1]
        value['nvidiaSmi'] = None
        result, rows = inspect(value)
        self.assertEqual(rows['inputRoot']['code'], 'FIELD_MISSING')
        self.assertEqual(rows['config.fields']['status'], 'BLOCKED')
        self.assertEqual(rows['limits.diskReservation']['status'], 'NOT_CHECKED')
        self.assertEqual(rows['shards.ids']['status'], 'NOT_CHECKED')
        self.assertEqual(rows['validationIds.membership']['status'], 'NOT_CHECKED')
        self.assertEqual(rows['nvidiaSmi.executable']['status'], 'NOT_CHECKED')
        self.assertEqual(rows['microbatch']['status'], 'PASS')
        self.assertNotIn('private-secret-field', json.dumps(result['checks']))

    def test_json_rejects_duplicates_constants_overflow_and_wrong_root(self):
        for raw in (b'{"schema":1,"schema":1}', b'{"x":{"a":1,"a":2}}', b'{"x":NaN}',
                    b'{"x":Infinity}', b'{"x":1e999}', b'[]', b'null', b'\xff', b'{'):
            with self.subTest(raw=raw):
                result = config_preflight(raw)
                self.assertIsNone(result['config'])
                self.assertEqual(next(r for r in result['checks'] if r['field'] == 'json')['status'], 'BLOCKED')
                self.assertEqual(next(r for r in result['checks'] if r['field'] == 'inputRoot')['status'], 'NOT_CHECKED')
        for raw in ('{}', b'', b' '* (2*1024**2 + 1)):
            self.assertIsNone(config_preflight(raw)['config'])

    def test_limits_independent_ranges_and_relations(self):
        value = example()
        value['limits'].update(cpu_seconds=86401, address_space_mb=31, wall_seconds=300,
                               file_size_bytes=1024, output_bytes=2048, disk_bytes=2048)
        _, rows = inspect(value)
        for field in ('cpu_seconds', 'address_space_mb', 'wall_seconds'):
            self.assertEqual(rows['limits.' + field]['status'], 'BLOCKED')
        self.assertEqual(rows['limits.outputBound']['code'], 'OUTPUT_EXCEEDS_FILE_LIMIT')
        self.assertEqual(rows['limits.diskReservation']['code'], 'DISK_RESERVATION_TOO_SMALL')
        value['limits']['file_size_bytes'] = None
        _, rows = inspect(value)
        self.assertEqual(rows['limits.diskReservation']['status'], 'NOT_CHECKED')

    def test_shard_names_ids_and_validation_are_bounded_and_distinct(self):
        value = example()
        value['shards'][1] = deepcopy(value['shards'][0])
        _, rows = inspect(value)
        self.assertEqual(rows['shards.ids']['status'], 'BLOCKED')
        self.assertEqual(rows['shards.basenames']['status'], 'BLOCKED')
        self.assertEqual(rows['validationIds.membership']['status'], 'NOT_CHECKED')
        value = example(); value['validationIds'] = ['absent']
        result, rows = inspect(value)
        self.assertEqual(rows['validationIds.membership']['status'], 'BLOCKED')
        self.assertNotIn('validationIds', result['validFields'])
        value = example(); value['tokenizerBasename'] = 'train.parquet'
        _, rows = inspect(value)
        self.assertEqual(rows['tokenizerBasename.distinct']['status'], 'BLOCKED')

    def test_path_and_bool_confusion_never_mark_safe_fields(self):
        for invalid in ('/a/../b', '/a/./b', '/a//b', 1, None, True):
            value = example(); value['inputRoot'] = invalid
            result, _ = inspect(value)
            self.assertNotIn('inputRoot', result['validFields'])
        for field in ('schema', 'microbatch'):
            value = example(); value[field] = True
            result, _ = inspect(value)
            self.assertNotIn(field, result['validFields'])
