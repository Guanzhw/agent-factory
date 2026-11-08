"""Recover actual native queue acceptance without submitting another run."""
from uuid import uuid4
from unittest.mock import AsyncMock, patch
import unittest
import time

from fastapi import HTTPException
from sqlalchemy import Table, MetaData, select, func
from agno.os.job_queue import QueueWorker
import test_chat_journey as journey
from research.session_routes import SessionCommand


class AdmissionRecovery(unittest.TestCase):
    setUpClass = classmethod(journey.ChatJourney.setUpClass.__func__)
    setUp = journey.ChatJourney.setUp
    post = journey.ChatJourney.post

    def test_original_queue_recovery_stop_and_preparation_failure(self):
        store, bridge = self.state['store'], self.state['bridge']
        service = store.research_sessions
        options = service.options(self.owner)
        model = options['models'][0]['connectionRef']
        submit = bridge.submit
        created = []

        def new_session():
            result = self.post('/research/sessions', {'title': 'Admission recovery', 'goal': 'pending',
                'modelConnectionRef': model})
            created.append(result['id'])
            return '/research/sessions/' + result['id']

        def read(path):
            response = self.context.request.get(self.origin + '/api/factory' + path)
            self.assertTrue(response.ok, response.text())
            return response.json()

        async def lost_ack(plan, owner, request):
            await submit(plan, owner, request)
            # A 409 is not proof of rejection: the original ticket already exists.
            raise HTTPException(409, 'Original acknowledgement unavailable')

        async def stop_before_enqueue(plan, owner, request):
            session_id = plan['inputValues']['sessionId']
            await service.stop(owner, session_id, SessionCommand(requestId=str(uuid4())))
            await submit(plan, owner, request)
            raise HTTPException(503, 'Lost acknowledgement')

        # Keep real PostgreSQL enqueue/prepare/cancel; pause only native claiming.
        with patch.object(QueueWorker, '_claim_burst', AsyncMock()):
            path = new_session()
            request = {'requestId': str(uuid4()), 'text': 'pending'}
            async def pause_recovery(task):
                return task
            with patch.object(store.lifecycle_observer, 'recover_admission', pause_recovery), patch.object(bridge, 'submit', lost_ack):
                first = self.post(path + '/turns', request)
            task_id = first['turns'][-1]['taskId']
            self.assertIsNotNone(task_id, (first, store.sql('SELECT id,run_id,admission FROM af_tasks')))
            for _ in range(50):
                task = store.task(task_id, self.owner)
                if task['run_id']:
                    break
                time.sleep(.1)
            self.assertIsNotNone(task['run_id'])
            self.assertEqual(store.native_db.get_job(task['run_id'])['status'], 'queued')
            duplicate = self.post(path + '/turns', request)
            self.assertEqual(duplicate['turns'][-1]['taskId'], task_id)
            with store.native_db.db_engine.connect() as conn:
                jobs = Table(store.native_db.job_table_name, MetaData(), schema=store.native_db.db_schema, autoload_with=conn)
                count = conn.execute(select(func.count()).select_from(jobs).where(jobs.c.session_id == task_id)).scalar()
            self.assertEqual(count, 1)
            store.event(task_id, 'research_tool_started', 'read observation fixture', {'callId': 'read-fixture'})
            store.effect_reserve(task['run_id'], 'read-fixture', {'fixture': 'observation'})
            observed = read(path)['turns'][-1]
            self.assertTrue(any(event['data'].get('callId') == 'read-fixture' for event in observed['events']))
            self.assertEqual(observed['toolResults'][0]['status'], 'UNKNOWN')
            with patch.object(service.runs.factory, 'delegation', None):
                ungrouped = read(path)['turns'][-1]
            self.assertEqual(ungrouped['toolResults'], observed['toolResults'])
            self.assertEqual(ungrouped['status'], observed['status'])
            store.effect_complete(task['run_id'], 'read-fixture', {'output': 'latest observation'})
            updated = read(path)['turns'][-1]
            self.assertEqual(updated['toolResults'][0]['status'], 'DONE')
            self.assertEqual(updated['toolResults'][0]['result']['output'], 'latest observation')
            full_path = new_session()
            worker = self.state['http_app'].state.queue_worker
            with patch.object(worker.config, 'max_queue_depth', 1):
                full = self.post(full_path + '/turns', {'text': 'queue full'})
            self.assertEqual(full['turns'][-1]['status'], 'failed', full)
            self.assertIn('start', full['allowedActions'])
            self.post(path + '/stop', {})
            resumed = self.post(full_path + '/turns', {'text': 'continue after queue full'})
            self.assertIsNotNone(resumed['turns'][-1]['runId'])
            self.post(full_path + '/stop', {})

            path = new_session()
            with patch.object(bridge, 'submit', stop_before_enqueue), patch.object(service, '_cancel_original', AsyncMock()):
                stopped = self.post(path + '/turns', {'text': 'pending'})
            task_id = stopped['turns'][-1]['taskId']
            for _ in range(50):
                current = read(path)
                if current['turns'][-1]['completedAt']:
                    break
                self.page.wait_for_timeout(100)
            self.assertEqual(store.native_db.get_job(store.task(task_id)['run_id'])['status'], 'cancelled')
            self.assertIn('start', current['allowedActions'])

            path = new_session()
            with patch('agno.os.job_queue.aprepare_queued_run', AsyncMock(side_effect=RuntimeError('prepare fixture'))):
                prepared = self.post(path + '/turns', {'text': 'pending'})
            task_id = prepared['turns'][-1]['taskId']
            for _ in range(50):
                current = read(path)
                if current['turns'][-1]['completedAt']:
                    break
                self.page.wait_for_timeout(100)
            self.assertEqual(store.native_db.get_job(store.task(task_id)['run_id'])['status'], 'cancelled')
            self.assertIn('start', current['allowedActions'], current)
        for identifier in created:
            self.post('/research/sessions/' + identifier + '/stop', {})
