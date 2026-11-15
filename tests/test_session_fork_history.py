"""Forked history reaches native model formatting without redispatching old tools."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from uuid import uuid4

from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession
from fastapi import HTTPException
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, create_engine, select

from research import session_context
from research.session_routes import ForkSession
from research.sessions import ResearchSessions


class ForkHistory(unittest.TestCase):
    def test_forks_before_and_after_source_reset_keep_selected_clean_dialogue(self):
        service = object.__new__(ResearchSessions)
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        metadata = MetaData()
        service.sessions = Table('sessions', metadata, Column('id', String, primary_key=True),
            Column('owner_id', String), Column('assistant_id', String), Column('body', JSON))
        service.turns = Table('turns', metadata, Column('id', String, primary_key=True),
            Column('owner_id', String), Column('session_id', String), Column('sequence', Integer),
            Column('application_request_id', String), Column('body', JSON))
        metadata.create_all(engine)
        service.auth = SimpleNamespace(require_member=Mock())
        service.assistants = SimpleNamespace(create=Mock(return_value={'id': 'new-assistant'}))
        service.db = SimpleNamespace(old=Mock(return_value=None))
        service.commands = Mock()
        service._write = engine.begin
        service._command = Mock()
        service._history_native = Mock(return_value=None)
        service.git = None
        point_id = str(uuid4())
        original = {'title': 'Original', 'goal': 'Original goal', 'boundaries': '', 'configuration': {},
            'contextAfterSequence': 2, 'contextNotice': 'Later unavailable source reset'}
        turn = {'status': 'completed', 'terminal': True, 'result': 'clean answer',
            'messages': [{'id': 'question', 'kind': 'instruction', 'text': 'clean question'}],
            'sharedSourceIds': []}
        with engine.begin() as conn:
            conn.execute(service.sessions.insert().values(id='parent', owner_id='owner',
                assistant_id='parent-assistant', body=original))
            conn.execute(service.turns.insert().values(id=point_id, session_id='parent', owner_id='owner',
                sequence=1, application_request_id='original', body=turn))
        child_id = service.fork('owner', 'parent', ForkSession(requestId='fork-request', turnId=point_id))
        with engine.connect() as conn:
            child = service._row(conn, 'owner', child_id)
            inherited = service._turns(conn, child_id)
            self.assertNotIn('contextAfterSequence', child['body'])
            self.assertNotIn('contextNotice', child['body'])
            self.assertEqual(len(session_context.active_turns(child, inherited)), 1)
            self.assertIn('clean question', str(session_context.history_run(inherited[0], None).messages))
            self.assertEqual(service._row(conn, 'owner', 'parent')['body'], original)
            self.assertEqual(conn.execute(select(service.turns.c.body).where(
                service.turns.c.id == point_id)).scalar_one(), turn)

        # A later clean turn must not inherit dependencies from history already cut away.
        clean_id = str(uuid4())
        source_reset = {**original, 'contextAfterSequence': 1, 'sharedSourceIds': []}
        with engine.begin() as conn:
            conn.execute(service.sessions.update().where(service.sessions.c.id == 'parent').values(body=source_reset))
            conn.execute(service.turns.update().where(service.turns.c.id == point_id).values(
                body={**turn, 'sharedSourceIds': ['withdrawn-source']}))
            conn.execute(service.turns.insert().values(id=clean_id, session_id='parent', owner_id='owner',
                sequence=2, application_request_id='clean-turn', body={**turn, 'result': 'independent answer'}))
        service.content = SimpleNamespace(read=Mock(side_effect=HTTPException(404, 'withdrawn')))
        later_id = service.fork('owner', 'parent', ForkSession(requestId='later-fork', turnId=clean_id))
        with engine.connect() as conn:
            later = service._row(conn, 'owner', later_id)
            later_turns = service._turns(conn, later_id)
            self.assertEqual(later['body']['sharedSourceIds'], [])
            continuing = service._continuation_context(later, later_turns)
            self.assertEqual(continuing['body']['contextAfterSequence'], 1)
            active = session_context.active_turns(continuing, later_turns)
            self.assertEqual(len(active), 1)
            self.assertIn('independent answer', str(session_context.history_run(active[0], None).messages))
            service.content.read.assert_not_called()

    def test_snapshot_preserves_dialogue_and_tool_results_without_original_runtime(self):
        original = RunOutput(run_id='original-run', status=RunStatus.completed, messages=[
            Message(role='system', content='private original runtime instructions'),
            Message(role='user', content='prior unrelated context', from_history=True),
            Message(role='user', content='inherited research question'),
            Message(role='assistant', tool_calls=[{'id': 'original-call', 'type': 'function',
                'function': {'name': 'read_file', 'arguments': '{"path":"evidence.txt"}'}}]),
            Message(role='tool', tool_call_id='original-call', content='observed evidence'),
            Message(role='assistant', content='inherited answer')])
        turn = {'id': 'original-turn', 'body': {'status': 'completed', 'messages': []}}
        snapshot = session_context.history_run(turn, original)
        inherited = {'id': 'child-turn', 'body': {'status': 'completed',
            'messages': [],
            'inheritedMessages': [item.model_dump(mode='json', exclude_none=True)
                for item in snapshot.messages or []]}}
        unchanged = deepcopy(inherited)
        child = AgentSession(session_id='independent-child')
        session_context.history_view(child, [session_context.history_run(inherited, None)], None)
        # Exercise the actual Agno wire formatter, including the archived tool call/result pair.
        payload = OpenAIChat(id='fixture')._format_all_messages(child.get_messages())
        self.assertEqual([item['role'] for item in payload], ['user', 'assistant', 'tool', 'assistant'])
        self.assertEqual(payload[0]['content'], 'inherited research question')
        self.assertEqual(payload[2]['content'], 'observed evidence')
        self.assertEqual(payload[2]['tool_call_id'], payload[1]['tool_calls'][0]['id'])
        self.assertEqual(payload[-1]['content'], 'inherited answer')
        self.assertEqual(inherited, unchanged)
        self.assertEqual(len(original.messages or []), 6)
        self.assertEqual(child.runs, None)

        inherited['body']['messages'].append({'id': 'new-correction', 'kind': 'correction',
            'text': 'child correction before first continuation'})
        corrected = session_context.history_run(inherited, None)
        self.assertEqual((corrected.messages or [])[-1].content, 'child correction before first continuation')
