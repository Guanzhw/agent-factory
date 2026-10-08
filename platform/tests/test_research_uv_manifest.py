# pyright: reportMissingImports=false
"""Pure installed uv lock identity tests; no installation or upstream execution."""
from copy import deepcopy
from dataclasses import fields
import hashlib
import json
import unittest

from agent_factory.process_enforcement import ResearchProcessSpec, UvResearchProcessSpec
from agent_factory.research_manifest import manifest_fingerprint, same_comparison_identity, validate_manifest
from agent_factory.research_profile import SOURCE_SHA256
from test_research_manifest import example_manifest


def uv_manifest():
    value = example_manifest()
    value['schema'] = 2
    value['environment']['upstreamLockfileSha256'] = SOURCE_SHA256['uv.lock']
    value['environment']['lockfileSha256'] = hashlib.sha256(b'version = 1\n# synthetic installed uv lock\n').hexdigest()
    return value


class ResearchUvManifestTests(unittest.TestCase):
    def invalid(self, value):
        with self.assertRaisesRegex(ValueError, '^RESEARCH_MANIFEST_INVALID$'):
            validate_manifest(value)

    def test_schema_one_preserves_exact_upstream_lock_and_fingerprint(self):
        original = example_manifest()
        expected = hashlib.sha256(json.dumps(original, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
        self.assertEqual(manifest_fingerprint(original), expected)
        changed = deepcopy(original)
        changed['environment']['lockfileSha256'] = uv_manifest()['environment']['lockfileSha256']
        self.invalid(changed)
        changed = deepcopy(original)
        changed['environment']['upstreamLockfileSha256'] = SOURCE_SHA256['uv.lock']
        self.invalid(changed)

    def test_schema_two_explicitly_separates_installed_lock_and_upstream(self):
        value = uv_manifest(); before = deepcopy(value)
        checked = validate_manifest(value)
        self.assertEqual(checked, before)
        self.assertNotEqual(checked['environment']['lockfileSha256'], checked['environment']['upstreamLockfileSha256'])
        self.assertEqual(checked['environment']['upstreamLockfileSha256'], SOURCE_SHA256['uv.lock'])
        checked['environment']['installedInventory']['sha256'] = '0' * 64
        self.assertEqual(value, before)
        self.assertNotEqual(checked, value)

    def test_missing_wrong_upstream_unknown_fields_and_bool_schema_rejected(self):
        examples = []
        value = uv_manifest(); del value['environment']['upstreamLockfileSha256']; examples.append(value)
        for invalid in ('0' * 64, '', None, True, 1, SOURCE_SHA256['uv.lock'].upper()):
            value = uv_manifest(); value['environment']['upstreamLockfileSha256'] = invalid; examples.append(value)
        for schema in (True, False, 0, 3, 2.0, '2'):
            value = uv_manifest(); value['schema'] = schema; examples.append(value)
        value = uv_manifest(); value['unknown'] = True; examples.append(value)
        value = uv_manifest(); value['environment']['lockfilePath'] = '/untrusted'; examples.append(value)
        for index, value in enumerate(examples):
            with self.subTest(index=index): self.invalid(value)

    def test_installed_lock_changes_identity_without_mutating_either_manifest(self):
        first = uv_manifest(); second = deepcopy(first)
        second['environment']['lockfileSha256'] = hashlib.sha256(b'different synthetic installed lock').hexdigest()
        before_first, before_second = deepcopy(first), deepcopy(second)
        self.assertNotEqual(manifest_fingerprint(first), manifest_fingerprint(second))
        self.assertFalse(same_comparison_identity(first, second))
        self.assertEqual(first, before_first); self.assertEqual(second, before_second)
        self.assertEqual(first['environment']['upstreamLockfileSha256'], second['environment']['upstreamLockfileSha256'])
        legacy = example_manifest(); modern_same_lock = deepcopy(legacy)
        modern_same_lock['schema'] = 2
        modern_same_lock['environment']['upstreamLockfileSha256'] = SOURCE_SHA256['uv.lock']
        self.assertNotEqual(manifest_fingerprint(legacy), manifest_fingerprint(modern_same_lock))

    def test_uv_spec_adds_contract_only_in_explicit_subclass(self):
        legacy = {field.name for field in fields(ResearchProcessSpec)}
        modern = {field.name for field in fields(UvResearchProcessSpec)}
        self.assertNotIn('interpreter_contract', legacy)
        self.assertEqual(modern - legacy, {'interpreter_contract'})
