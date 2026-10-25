"""QA publication uses actual portable core governance without executing a model."""
from research.qa_workflow import ResearchQAWorkflow
from research.setup import PrepareQASetup, PublishSetup
import unittest
import test_research_setup as fixtures


class ResearchQASetupTests(unittest.TestCase):
    setUp = fixtures.ResearchSetupTests.setUp
    database = fixtures.ResearchSetupTests.database
    no_dispatch = fixtures.ResearchSetupTests.no_dispatch

    def test_publish_exact_qa_without_experiment_or_compute(self):
        qa = ResearchQAWorkflow()
        self.setup.qa_workflow = qa
        for registration in (*qa.tool_registrations, qa.environment_registration):
            self.bindings.register(registration.kind, registration.adapter_id, registration.revision,
                self.no_dispatch, tool_name=registration.tool_name, permissions=registration.permissions)
        self.pin.update(id='research-qa')
        model = self.models.configure('alice', {'provider': 'openai-compatible',
            'baseURL': 'http://localhost:8899/v1', 'model': 'synthetic'}, 'qa-model-config')
        draft = self.setup.prepare_qa('alice', PrepareQASetup(requestId='qa-prepare-original', name='QA',
            modelConnectionRef=model['connectionRef'], budget={'toolCalls': 4}))
        result = self.setup.publish('alice', draft['id'], PublishSetup(requestId='qa-publish-original'))
        app = self.apps.require_current(result['applicationRef'])
        self.assertEqual(set(app['modes']), {'qa'})
        mode = app['modes']['qa']
        self.assertEqual(mode['nativeComponent'], self.pin)
        self.assertEqual(set(mode['toolOrder']), {'research_qa_context', 'research_qa_record'})
        self.assertEqual(result['mode'], 'qa')
        self.assertEqual(self.setup.publish('alice', draft['id'], PublishSetup(requestId='qa-publish-original')), result)
        self.assertNotIn(model['connectionRef'], str(app))
