"""Execute the shipped read-only SQL against disposable synthetic PostgreSQL."""
import json
import os
from pathlib import Path
import unittest

from sqlalchemy import create_engine, text

from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.environ.get('FACTORY_TEST_DATABASE_URL'), 'PostgreSQL fixture not configured')
class OriginalQueueAuditPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL'])
        cls.database.__enter__()
        cls.engine = create_engine(cls.database.url)
        with cls.engine.begin() as c:
            for ddl in (
                'CREATE SCHEMA ai',
                'CREATE TABLE public.af_tasks(id text PRIMARY KEY,owner_id text,request_id text,plan_id text,run_id text,terminal boolean)',
                'CREATE TABLE public.af_plans(id text PRIMARY KEY,owner_id text,body jsonb,hash text)',
                'CREATE TABLE public.af_delegation_links(root_id text,parent_id text,child_id text)',
                'CREATE TABLE ai.agno_jobs(id text PRIMARY KEY,session_id text,user_id text,component_type text,component_id text,job_type text,status text,payload jsonb)',
                'CREATE TABLE ai.agno_runs(run_id text PRIMARY KEY,session_id text,user_id text,agent_id text,run_type text,status text,parent_run_id text,run_data jsonb)',
                'CREATE TABLE ai.agno_sessions(session_id text PRIMARY KEY,user_id text,agent_id text,session_type text,session_data jsonb)',
            ):
                c.execute(text(ddl))
        raw = (Path(__file__).resolve().parents[2] / 'scripts/research_original_queue_audit.sql').read_text()
        # Execute the shipped query, not a second implementation; psql variables
        # become driver parameters. Transaction controls remain explicit below.
        cls.query = raw[raw.index('WITH\npin AS'):raw.rindex('ROLLBACK;')].strip().removesuffix(';')
        for key in ('task_id', 'owner_id', 'request_id'):
            cls.query = cls.query.replace(f":'original_{key}'", f'%(original_{key})s')

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        cls.database.__exit__(None, None, None)

    def setUp(self):
        self.envelope = {'plan_ref': 'plan', 'user_id': 'owner', 'task_id': 'task', 'request_id': 'request'}
        plan = {'id': 'plan', 'ownerId': 'owner', 'application': 'research-process-fixture-v1',
                'applicationRef': {'id': 'research-process-fixture-v1'}, 'mode': 'controlled-fixture',
                'tools': ['research_process_run'], 'capabilities': ['compute:local']}
        with self.engine.begin() as c:
            c.execute(text('TRUNCATE public.af_tasks,public.af_plans,public.af_delegation_links,ai.agno_jobs,ai.agno_runs,ai.agno_sessions'))
            c.execute(text("INSERT INTO public.af_tasks VALUES('task','owner','request','plan','ticket',true)"))
            c.execute(text("INSERT INTO public.af_plans VALUES('plan','owner',CAST(:body AS jsonb),'separately-audited')"), {'body': json.dumps(plan)})
        self.add_job('ticket')

    def mutate(self, sql, **params):
        with self.engine.begin() as c:
            c.execute(text(sql), params)

    def add_job(self, identifier, status='cancelled', session='task', payload=None):
        self.mutate("INSERT INTO ai.agno_jobs VALUES(:id,:session,'owner','agent','factory-executor','run',:status,CAST(:payload AS jsonb))",
                    id=identifier, session=session, status=status,
                    payload=json.dumps(payload if payload is not None else {'kwargs': {'session_state': {'factory_envelope': self.envelope}}}))

    def audit(self):
        with self.engine.connect() as c:
            c.exec_driver_sql('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
            c.exec_driver_sql("SET LOCAL statement_timeout='30s'")
            c.exec_driver_sql("SET LOCAL lock_timeout='2s'")
            c.exec_driver_sql('SET LOCAL search_path=pg_catalog')
            result = c.exec_driver_sql(self.query, {'original_task_id': 'task', 'original_owner_id': 'owner',
                                                   'original_request_id': 'request'}).scalar_one()
            c.rollback()
            return result

    def test_cancelled_before_run_or_session_creation(self):
        result = self.audit()
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['descendants'], 'NO_DESCENDANTS_OF_ORIGINAL_ROOT')
        self.assertFalse(result['resourceReleaseVerified'])
        self.assertFalse(result['newAttemptAuthorizedByThisQuery'])

    def test_extra_same_session_queued_ticket_without_run_rejected(self):
        self.add_job('retry', status='queued')
        self.assertEqual(self.audit()['status'], 'UNKNOWN')

    def test_extra_same_session_terminal_ticket_included(self):
        self.add_job('retry')
        self.assertEqual(self.audit()['relatedTicketCount'], 2)
        self.assertEqual(self.audit()['status'], 'PASS')

    def test_null_child_intent_rejected(self):
        self.mutate("INSERT INTO public.af_delegation_links VALUES('task','task',NULL)")
        self.assertEqual(self.audit()['status'], 'UNKNOWN')

    def test_foreign_session_native_child_rejected(self):
        self.mutate("INSERT INTO ai.agno_runs VALUES('child','foreign','other','foreign','agent','COMPLETED','ticket','{}')")
        self.assertEqual(self.audit()['status'], 'UNKNOWN')

    def test_queued_child_without_run_rejected(self):
        self.add_job('child', session='foreign', payload={'kwargs': {'parent_run_id': 'ticket'}})
        self.assertEqual(self.audit()['status'], 'UNKNOWN')

    def test_dangling_native_parent_rejected(self):
        self.mutate("INSERT INTO ai.agno_runs VALUES('ticket','task','owner','factory-executor','agent','CANCELLED','absent','{}')")
        self.assertEqual(self.audit()['status'], 'UNKNOWN')

    def test_cross_owner_ticket_rejected(self):
        self.mutate("UPDATE ai.agno_jobs SET user_id='other'")
        self.assertEqual(self.audit()['status'], 'UNKNOWN')

    def test_missing_original_ticket_rejected(self):
        self.mutate('DELETE FROM ai.agno_jobs')
        self.assertEqual(self.audit()['status'], 'UNKNOWN')

    def test_unfamiliar_payload_rejected(self):
        self.mutate("UPDATE ai.agno_jobs SET payload='{}'")
        self.assertEqual(self.audit()['status'], 'UNKNOWN')

    def test_remote_handoff_profile_rejected(self):
        self.mutate("UPDATE public.af_plans SET body=body || '{\"remoteHandoff\":{\"id\":\"remote\"}}'")
        self.assertEqual(self.audit()['status'], 'UNKNOWN')

    def test_envelope_alias_in_foreign_session_not_filtered_out(self):
        self.add_job('alias', session='foreign')
        self.assertEqual(self.audit()['status'], 'UNKNOWN')
