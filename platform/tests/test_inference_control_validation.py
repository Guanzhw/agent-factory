"""Recovery refusal is a typed conflict, never a server error or a dispatch."""
import unittest
from unittest.mock import Mock, patch

from agno.exceptions import RunCancelledException
from fastapi import HTTPException

from agent_factory.inference_wait import CONTROL_NAME, validate_requirement


class InferenceControlValidationTests(unittest.TestCase):
    def test_changed_work_returns_conflict_without_exposing_exception_text(self):
        task = {'id': 'synthetic-task'}
        wait = {'state': 'WAITING', 'controlId': 'synthetic-control'}
        tool = {'tool_name': CONTROL_NAME, 'tool_call_id': wait['controlId'],
                'tool_args': {}, 'external_execution_required': True}
        for error in (PermissionError('private diagnostic'), RunCancelledException('private diagnostic')):
            with self.subTest(error=type(error).__name__), patch('agent_factory.inference_wait.read', return_value=wait), \
                    patch('agent_factory.inference_wait.observe', side_effect=error):
                with self.assertRaises(HTTPException) as caught:
                    validate_requirement(Mock(), task, tool)
                self.assertEqual(caught.exception.status_code, 409)
                self.assertIn('INFERENCE_WAIT_UNAVAILABLE', caught.exception.detail)
                self.assertNotIn('private diagnostic', caught.exception.detail)

    def test_existing_typed_denial_is_preserved(self):
        task = {'id': 'synthetic-task'}
        wait = {'state': 'WAITING', 'controlId': 'synthetic-control'}
        tool = {'tool_name': CONTROL_NAME, 'tool_call_id': wait['controlId'],
                'tool_args': {}, 'external_execution_required': True}
        denial = HTTPException(429, 'USAGE_BUDGET_EXCEEDED')
        with patch('agent_factory.inference_wait.read', return_value=wait), \
                patch('agent_factory.inference_wait.observe', side_effect=denial):
            with self.assertRaises(HTTPException) as caught:
                validate_requirement(Mock(), task, tool)
        self.assertIs(caught.exception, denial)
