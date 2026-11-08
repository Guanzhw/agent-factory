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
        _, identity = session_context.summary_source(row, [old])
        row['body']['contextCheckpoint'] = {**identity, 'summary': {'summary': 'old-summary-secret'}}
        original = deepcopy((row, old))
        service._prepare_turn_configuration = lambda conn, owner, row, turns: row
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
        payload = service._start(saved_row, continued).inputValues['sessionContext']
        self.assertNotIn('old-', payload)
        self.assertIn('Available independent answer', payload)
        self.assertEqual(saved_row['body']['contextAfterSequence'], 1)
        self.assertEqual((row, old), original)
        service._context_sources('owner', saved_row, [old, continued])
        continued['body'].update(terminal=True, status='completed', result='Clean final answer')
        summary, checkpoint = session_context.summary_source(saved_row, [old, continued])
        self.assertNotIn('old-', str(summary))
        saved_row['body']['contextCheckpoint'] = {**checkpoint, 'summary': {'summary': 'Clean summary'}}
        projected = session_context.project(saved_row, [old, continued])
        self.assertNotIn('old-', projected)
        self.assertIn('Clean summary', projected)
        self.assertIn('old-derived-secret', session_context.project(saved_row, [old, continued], raw=True))

    def test_source_service_failure_is_not_treated_as_revocation(self):
        service = object.__new__(ResearchSessions)
        service.content = SimpleNamespace(read=Mock(side_effect=HTTPException(503, 'temporarily unavailable')))
        row = {'id': 'session', 'owner_id': 'owner', 'body': {'sharedSourceIds': ['source']}}
        with self.assertRaises(HTTPException) as raised:
            service._continuation_context(row, [])
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(row['body']['sharedSourceIds'], ['source'])
