"""Explicit publication only, with synthetic governance mocks and no database."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import bootstrap_autoresearch as module
from agent_factory.autoresearch import ResearchPreset
from agent_factory.applications import ApplicationDefinition
from agent_factory.material_governance import MaterialDefinition


def preset():
    return ResearchPreset('synthetic-project', 'Synthetic project', 'Synthetic goal', 'alice',
        'Fixed approved instructions', {'synthetic': True},
        {'maxExperiments': 1, 'experimentSeconds': 30, 'totalSeconds': 300},
        blockers=('Actual baseline and subordinate executor unavailable',))


def state():
    events = []
    def service(kind):
        obj = Mock()
        def draft(author, definition, key):
            (MaterialDefinition if kind == 'material' else ApplicationDefinition).model_validate(definition)
            events.append((kind, 'draft', author, key))
            return {**definition, 'version': 1, 'sha256': 'a'*64}
        def request(author, identifier, version, key):
            events.append((kind, 'review', author, key)); return {'id': key}
        def decision(reviewer, identifier, approved, key):
            events.append((kind, 'decision', reviewer, key)); assert approved is True
        obj.create_draft.side_effect = draft
        obj.request_publication.side_effect = request
        obj.decide_publication.side_effect = decision
        return obj
    return {'auth': Mock(), 'material_governance': service('material'), 'applications': service('app')}, events


class BootstrapAutoResearchTests(unittest.TestCase):
    def test_settings_register_only_explicit_native_profile_and_preserve_blockers(self):
        original = preset()
        config = module.settings(db_url='postgresql+psycopg://synthetic.invalid/not-connected',
            workspace=Path('/synthetic/not-created'), preset=original, jwt_key='synthetic-not-a-real-credential')
        self.assertEqual(config.max_workers, 1)
        self.assertEqual(config.temporary_policy, 'admin-review')
        self.assertEqual(config.material_review_mode, 'separate-admin')
        self.assertNotEqual(config.policy_revision, config.material_policy_revision)
        self.assertEqual(config.runtime_tool_contract, 'autoresearch-session-v1')
        self.assertIs(config.autoresearch_presets[original.id], original)
        self.assertEqual(len(config.runtime_adapters), 8); self.assertEqual(len(config.usage_pricing), 1)
        self.assertIsNone(config.usage_pricing[0].local_model_type)
        self.assertTrue(original.unavailable()); self.assertEqual(original.application_ref, {})

    def test_explicit_publication_has_eleven_separate_reviews_and_preserves_original(self):
        original = preset(); services, events = state()
        result = module.publish_application(services, original, author='author', reviewer='reviewer')
        self.assertEqual(len(events), 33)
        self.assertEqual([e[1] for e in events], ['draft', 'review', 'decision'] * 11)
        self.assertTrue(all(e[2] == ('reviewer' if e[1] == 'decision' else 'author') for e in events))
        self.assertEqual(result.application_ref, {'id': 'autoresearch-goal-session-v1', 'version': 1, 'sha256': 'a'*64})
        self.assertEqual(result.blockers, original.blockers); self.assertEqual(original.application_ref, {})
        self.assertIs(result.runtime_factory, original.runtime_factory)
        services['auth'].require.assert_any_call('author', 'components:write')
        services['auth'].require.assert_any_call('reviewer', 'agent_os:admin')
        first_keys = [e[3] for e in events]
        events.clear(); module.publish_application(services, original, author='author', reviewer='reviewer')
        self.assertEqual(first_keys, [e[3] for e in events])

    def test_self_review_denied_and_current_permission_failure_never_publishes(self):
        services, events = state()
        with self.assertRaises(ValueError): module.publish_application(services, preset(), author='same', reviewer='same')
        self.assertEqual(events, [])
        denial = PermissionError('synthetic revoked'); services['auth'].require.side_effect = denial
        with self.assertRaises(PermissionError) as caught:
            module.publish_application(services, preset(), author='author', reviewer='reviewer')
        self.assertIs(caught.exception, denial); self.assertEqual(events, [])

    def test_failed_material_review_stops_before_application_and_budget_is_bounded(self):
        services, events = state()
        services['material_governance'].decide_publication.side_effect = PermissionError('synthetic denied')
        with self.assertRaises(PermissionError): module.publish_application(services, preset(), author='author', reviewer='reviewer')
        services['applications'].create_draft.assert_not_called()
        with self.assertRaises(ValueError): module.application_budget(replace(preset(), limits={'experimentSeconds': True}))
