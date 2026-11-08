"""Unavailable adopted replies do not prevent independent automatic continuations."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import HTTPException
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table

from research import session_context
from research.session_collaboration import ResearchCollaboration
from research.sessions import ResearchSessions


class SourceContext(unittest.TestCase):
    def test_automatic_continuation_and_later_summary_drop_unavailable_history(self):
        service = object.__new__(ResearchSessions)
        service.content = SimpleNamespace(read=Mock())
        def validate(owner, session, reply):
            if reply['questionId'] == 'old':
                raise HTTPException(404, 'unavailable')
        service.conversations = SimpleNamespace(validate_reply=validate)
        row = {'id': 'session', 'owner_id': 'owner', 'body': {
            'goal': 'Independent research', 'boundaries': '', 'sharedSourceIds': [],
            'configuration': {'connectionRefs': {'model': 'model'}, 'model': {}},
        }}
        old = {'id': 'old-turn', 'sequence': 1, 'body': {'status': 'completed', 'terminal': True,
            'result': 'old-derived-secret', 'messages': [{'id': 'correction', 'kind': 'correction',
                'text': 'old-correction-secret'}], 'assistantReplies': [
                    {'questionId': 'old', 'reply': {'text': 'old-reply-secret'}}]}}
        row['body']['contextCheckpoint'] = {'throughSequence': 1, 'summary': {'summary': 'old-summary-secret'}}
        original = deepcopy((row, old))
        service._prepare_turn_configuration = lambda conn, owner, row, turns, request=None: row
        service._save_session = Mock()
        service._command = Mock()
        service.turns = Table('turns', MetaData(), Column('id', String), Column('session_id', String),
            Column('owner_id', String), Column('application_request_id', String),
            Column('sequence', Integer), Column('body', JSON))
        collaboration = object.__new__(ResearchCollaboration)
        collaboration.sessions, collaboration._save = service, Mock()
        ready = [({'question_id': 'new', 'body': {'eventId': 'event'}},
                  {'questionId': 'new', 'reply': {'text': 'Available independent answer'}})]
        continued = collaboration._reserve(Mock(), row, [old], ready, 'event')
        saved_row = service._save_session.call_args.args[1]
        self.assertNotIn('sessionContext', service._start(saved_row, continued).inputValues or {})
        additions = session_context.additions(continued)
        self.assertNotIn('old-', str(additions))
        self.assertIn('Available independent answer', str(additions))
        self.assertEqual(saved_row['body']['contextAfterSequence'], 1)
        self.assertEqual((row, old), original)
        service._context_sources('owner', saved_row, [old, continued])
        continued['body'].update(terminal=True, status='completed', result='Clean final answer')
        active = session_context.active_turns(saved_row, [old, continued])
        self.assertEqual([item['id'] for item in active], [continued['id']])
        run = session_context.history_run(continued, None)
        self.assertNotIn('old-', str(run.messages))
        self.assertIn('Clean final answer', str(run.messages))
        self.assertEqual(old['body']['result'], 'old-derived-secret')

    def test_source_service_failure_is_not_treated_as_revocation(self):
        service = object.__new__(ResearchSessions)
        service.content = SimpleNamespace(read=Mock(side_effect=HTTPException(503, 'temporarily unavailable')))
        row = {'id': 'session', 'owner_id': 'owner', 'body': {'sharedSourceIds': ['source']}}
        with self.assertRaises(HTTPException) as raised:
            service._continuation_context(row, [])
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(row['body']['sharedSourceIds'], ['source'])
