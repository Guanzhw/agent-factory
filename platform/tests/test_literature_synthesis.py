"""Bounded source snapshots and fixture-only structural citation checks."""
import copy
from types import SimpleNamespace
from typing import Any, cast
import unittest

from agent_factory.execution_bindings import KnowledgeContext
from agent_factory.literature_evidence import source_projection
from agent_factory.literature_synthesis import (
    FIXTURE_PROVIDER, SCIENTIFIC_CAPABILITY, build_source_context,
    knowledge_registration, require_scientific_provider, validate_synthesis_report,
)
from agent_factory.orx_literature_tools import evidence_record


def projection(text='Synthetic fixture discusses bounded observations.', kind='controlled_literature_fixture') -> dict[str, Any]:
    row = evidence_record('123', text, status='abstract_only', field='abstract')
    return dict(schema=1, status='ready', evidenceKind=kind,
                mode='bibliography-excerpts-no-provider', sourceCount=1,
                sources=[source_projection({**row, 'evidenceKind': kind})],
                retrievalErrors=[], reportArtifactId=None, bundleArtifactId=None)


def report() -> dict[str, Any]:
    return dict(schema=1, claims=[dict(text='A fixture observation requires review.',
        sourceIds=['123'], quotes=[dict(sourceId='123', text='Synthetic fixture')])],
        limitations=['Only a synthetic abstract excerpt is available; no scientific validation.'])


def validate(value, context=None, **overrides):
    kwargs = dict(provider_id=FIXTURE_PROVIDER, capabilities=(SCIENTIFIC_CAPABILITY,), execution_mode='controlled-fixture')
    kwargs.update(overrides)
    return validate_synthesis_report(value, context or build_source_context('Question?', projection()), **kwargs)


class LiteratureSynthesisTests(unittest.TestCase):
    def test_modes_remain_distinct_and_semantic_review_required(self):
        for kind in ('controlled_literature_fixture', 'public_literature_excerpt'):
            context = build_source_context('Question?', projection(kind=kind))
            result = validate(report(), context)
            self.assertEqual(result['sourceEvidenceKind'], kind)
            self.assertEqual(result['generatedBy'], 'controlled-fixture')
            self.assertTrue(result['citationStructureVerified'])
            self.assertFalse(result['scientificConclusionVerified'])
            self.assertEqual(result['semanticReview'], 'required')
            self.assertIn('untrusted data', context.content)

    def test_gate_excludes_go_real_provider_and_missing_capability(self):
        for changes in ({'provider_id': 'opencode-go'}, {'provider_id': 'production-science'},
                        {'execution_mode': 'live'}, {'capabilities': ()},
                        {'capabilities': SCIENTIFIC_CAPABILITY}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate(report(), **changes)
        require_scientific_provider(provider_id=FIXTURE_PROVIDER, execution_mode='controlled-fixture', capabilities=[SCIENTIFIC_CAPABILITY])

    def test_snapshot_binds_question_source_and_isolation_owner(self):
        original = projection()
        context = build_source_context('Question?', original)
        registration = knowledge_registration('Question?', original, owner_id='alice')
        config = {'snapshotSha256': context.provenance['snapshotSha256']}
        self.assertTrue(registration.demo_only)
        self.assertIsNotNone(registration.validator)
        assert registration.validator is not None
        registration.validator(config)
        binding: Any = SimpleNamespace(spec={'config': config}, run_context=SimpleNamespace(user_id='alice'), plan={'ownerId': 'alice'})
        original['sources'][0]['title'] = 'Changed'
        first = registration.factory(binding)
        first.provenance['snapshot']['evidence']['sources'][0]['title'] = 'Mutated'
        self.assertEqual(registration.factory(binding), context)
        self.assertNotEqual(build_source_context('Other?', projection()).provenance['snapshotSha256'], config['snapshotSha256'])
        self.assertNotEqual(build_source_context('Question?', original).provenance['snapshotSha256'], config['snapshotSha256'])
        for bad in ({}, {'snapshotSha256': '0'*64}, {**config, 'extra': True}):
            with self.assertRaises(ValueError): registration.validator(bad)
        for user, plan_owner in [('bob', 'alice'), ('alice', 'bob')]:
            binding.run_context.user_id = user
            binding.plan['ownerId'] = plan_owner
            with self.assertRaises(ValueError): registration.factory(binding)

    def test_invalid_projections_fail_closed(self):
        mutations = [lambda p: p.update(schema=True), lambda p: p.update(status='pending'),
            lambda p: p.update(sourceCount=True), lambda p: p.update(sources=[], sourceCount=0),
            lambda p: p.update(evidenceKind='live'), lambda p: p.update(retrievalErrors=['SECRET']),
            lambda p: p.update(reportArtifactId='../../secret'),
            lambda p: p['sources'][0].update(url='https://evil.example/'),
            lambda p: p['sources'][0].update(sha256=None),
            lambda p: p['sources'][0].update(fullTextAvailable=True),
            lambda p: p['sources'][0].update(hashScope='pdf'),
            lambda p: p['sources'][0]['locator'].update(start=True),
            lambda p: p['sources'][0]['locator'].update(endExclusive=999),
            lambda p: p['sources'][0].update(title='\ud800'),
            lambda p: p.update(sources=p['sources']*2, sourceCount=2)]
        for mutate in mutations:
            value = projection()
            mutate(value)
            with self.subTest(value=value), self.assertRaises(ValueError): build_source_context('Question?', value)
        for question in ('', 'x'*1001, '\ud800'):
            with self.assertRaises(ValueError): build_source_context(question, projection())
        with self.assertRaises(ValueError): build_source_context('Question?', projection(''))

    def test_report_invalid_structure_and_citations(self):
        mutations = [lambda r: r.update(schema=True), lambda r: r.update(extra='live'),
            lambda r: r.update(claims=[]), lambda r: r.update(limitations=[]),
            lambda r: r['claims'][0].update(sourceIds=[]),
            lambda r: r['claims'][0].update(sourceIds=['unknown']),
            lambda r: r['claims'][0].update(sourceIds=['123','123']),
            lambda r: r['claims'][0]['quotes'][0].update(sourceId='unknown'),
            lambda r: r['claims'][0]['quotes'][0].update(text='invented quotation'),
            lambda r: r['claims'][0].update(text='x'*601),
            lambda r: r.update(limitations=['x'*401])]
        for mutate in mutations:
            value = report()
            mutate(value)
            with self.subTest(value=value), self.assertRaises(ValueError): validate(value)

    def test_quotation_budget_is_aggregate_across_claims_words_and_characters(self):
        for text in (' '.join('word'+str(n) for n in range(11)), '文'*81):
            context = build_source_context('Question?', projection(text))
            claim = dict(text='Requires review.', sourceIds=['123'], quotes=[dict(sourceId='123', text=text)])
            value: dict[str, Any] = dict(schema=1, claims=[claim], limitations=['Abstract only.'])
            validate(value, context)
            value['claims'].append(copy.deepcopy(claim))
            with self.assertRaises(ValueError): validate(value, context)

    def test_context_tampering_rejected(self):
        for field in ('content', 'snapshotSha256', 'sourceEvidenceKind'):
            context = build_source_context('Question?', projection())
            if field == 'content':
                context = KnowledgeContext('tampered', context.provenance)
            else:
                cast(dict[str, Any], context.provenance)[field] = 'tampered'
            with self.assertRaises(ValueError): validate(report(), context)

    def test_metadata_only_source_cannot_support_claim(self):
        value = projection()
        row = evidence_record('456', '', status='metadata_only', field='abstract')
        value['sources'].append(source_projection({**row, 'evidenceKind': value['evidenceKind']}))
        value['sourceCount'] = 2
        output = report()
        output['claims'][0].update(sourceIds=['456'], quotes=[])
        with self.assertRaises(ValueError): validate(output, build_source_context('Question?', value))


if __name__ == '__main__':
    unittest.main()
