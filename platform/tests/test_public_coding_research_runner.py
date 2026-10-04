# pyright: reportMissingImports=false
"""Offline public-coding runner contracts; live-labelled inputs are local fixtures."""
import argparse
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_go_project_workflow as workflow_helpers
from test_public_code_knowledge import snapshot

_PATH = Path(__file__).resolve().parents[2] / 'scripts' / 'run_public_coding_research.py'
spec = importlib.util.spec_from_file_location('public_coding_runner_tests', _PATH)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'run_go_project_workflow': workflow_helpers.runner}):
    spec.loader.exec_module(runner)


def serializable(mode='live-public-fetch'):
    value = snapshot(mode)
    for source in value['sources']:
        source['content'] = source['content'].decode()
    return value


class PublicCodingResearchRunnerTests(unittest.TestCase):
    def test_operator_snapshot_loads_exact_pins_but_rejects_fixture_or_changed_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'snapshot.json'
            value = serializable()
            path.write_text(json.dumps(value))
            self.assertEqual(runner.load_snapshot(path), snapshot('live-public-fetch'))
            invalid = [serializable('controlled-fixture'), serializable(), serializable(), serializable()]
            invalid[1]['sources'][0]['content'] += 'tampered'
            invalid[2]['sources'][0]['rawUrl'] = 'https://example.invalid/private'
            invalid[3]['sources'][0]['lineEnd'] = 999
            for item in invalid:
                path.write_text(json.dumps(item))
                with self.assertRaises((ValueError, RuntimeError)):
                    runner.load_snapshot(path)
            path.write_bytes(b'x' * 65537)
            with self.assertRaises(RuntimeError): runner.load_snapshot(path)
            path.write_text('{broken')
            with self.assertRaises(ValueError): runner.load_snapshot(path)

    def test_workflow_forwards_validated_snapshot_and_existing_marker_blocks_replay(self):
        campaign = Mock()
        campaign.inspect.return_value = workflow_helpers.GoProjectWorkflowTests().proof()
        with tempfile.TemporaryDirectory() as root, \
                patch('agent_factory.go_project_campaign.GoProjectCampaign', return_value=campaign), \
                patch.object(workflow_helpers.runner, 'execute_product', return_value={'status': 'completed'}) as product, \
                patch.object(workflow_helpers.runner, 'credential', side_effect=AssertionError) as credential:
            args = argparse.Namespace(model='deepseek-flash', campaign='existing', evidence_directory=root, database_url='unused')
            value = snapshot()
            self.assertEqual(workflow_helpers.runner.run(args, research_snapshot=value)['status'], 'completed')
            product.assert_called_once_with(campaign, args, research_snapshot=value)
            self.assertEqual(workflow_helpers.runner.run(args, research_snapshot=value)['status'], 'inspection-only')
            self.assertEqual(product.call_count, 1)
            credential.assert_not_called()

    def test_invalid_snapshot_prevents_admission_and_main_redacts_exception(self):
        with tempfile.TemporaryDirectory() as root, \
                patch('agent_factory.go_project_campaign.GoProjectCampaign') as campaign:
            args = argparse.Namespace(model='deepseek-flash', campaign='existing', evidence_directory=root, database_url='unused')
            invalid = snapshot(); invalid['sources'][0]['content'] = b'private-payload'
            with self.assertRaises(ValueError): workflow_helpers.runner.run(args, research_snapshot=invalid)
            campaign.assert_not_called()
            self.assertEqual(list(Path(root).iterdir()), [])
        output = io.StringIO()
        argv = ['runner', '--campaign', 'unused', '--evidence-directory', 'unused', '--database-url', 'unused',
                '--snapshot', 'unused', '--model', 'deepseek-flash']
        with patch.object(sys, 'argv', argv), patch.object(runner.logging, 'disable'), \
                patch.object(runner, 'load_snapshot', side_effect=ValueError('private-payload')), \
                patch.object(runner, 'run') as run, redirect_stdout(output):
            runner.main()
        run.assert_not_called()
        self.assertNotIn('private-payload', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['status'], 'stopped')
