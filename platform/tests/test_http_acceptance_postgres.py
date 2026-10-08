"""Real loopback TCP/FastAPI/Agno/PostgreSQL acceptance, with a synthetic model.

Maps applicable PR #8 invariants to actual Factory routes. No reference runtime,
fixture credentials, external host, model spending or fake executor is used.
Only the proxy's post-commit connection fault is synthetic.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
import unittest
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, text
from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable PostgreSQL')
class LiveHTTPPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        cls.addClassCleanup(cls.database.__exit__, None, None, None)
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.engine = create_engine(cls.database.url)
        cls.addClassCleanup(cls.engine.dispose)
        cls.root = Path(__file__).resolve().parents[2]
        with socket.socket() as available:
            available.bind(('127.0.0.1', 0))
            cls.port = available.getsockname()[1]
        cls.base = f'http://127.0.0.1:{cls.port}'
        # Windows normalizes environment iteration to uppercase; preserve SystemRoot explicitly.
        cls.env = {name: os.environ[name] for name in ('SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'PATH', 'LANG', 'LC_ALL')
                   if name in os.environ}
        cls.env.update(PYTHONPATH=os.pathsep.join([str(cls.root / 'platform'), sysconfig.get_path('purelib')]), PYTHONIOENCODING='utf-8',
                       FACTORY_DATABASE_URL=cls.database.url, FACTORY_MODE='demo',
                       FACTORY_JWT_KEY=secrets.token_urlsafe(48), FACTORY_PORT=str(cls.port),
                       FACTORY_WORKSPACE=cls.directory.name, AGNO_TELEMETRY='false')
        cls.process = None
        cls.addClassCleanup(cls._stop)
        cls._start()

    @classmethod
    def _start(cls):
        cls.log = open(Path(cls.directory.name) / 'owned-api.log', 'ab')
        # Windows venv launchers redirect to another PID. Own the real worker
        # and wait for its exit before releasing the log handle/workspace.
        interpreter = sys._base_executable if os.name == 'nt' else sys.executable
        cls.process = subprocess.Popen([interpreter, '-m', 'agent_factory'], cwd=cls.root,
            env=cls.env, stdout=cls.log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0,
            start_new_session=os.name != 'nt')
        deadline = time.monotonic() + 25
        with httpx.Client(timeout=1, trust_env=False) as probe:
            while time.monotonic() < deadline:
                if cls.process.poll() is not None:
                    cls.log.flush()
                    evidence = (Path(cls.directory.name) / 'owned-api.log').read_text(encoding='utf-8', errors='replace')[-5000:]
                    raise RuntimeError('Owned native HTTP acceptance startup failed: ' + evidence)
                try:
                    response = probe.get(cls.base + '/api/factory/status')
                    if response.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
        raise TimeoutError('Owned native HTTP acceptance process did not become ready')

    @classmethod
    def _stop(cls):
        process = cls.process
        if process is not None and process.poll() is None:
            # Popen supplies this owned actual worker PID; never discover/kill a port owner.
            if os.name == 'nt':
                subprocess.run([str(Path(os.environ['SystemRoot']) / 'System32/taskkill.exe'),
                                '/PID', str(process.pid), '/T', '/F'], capture_output=True, check=True)
            else:
                os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
        cls.process = None
        if hasattr(cls, 'log'):
            cls.log.close()

    def setUp(self):
        self.client = httpx.Client(base_url=self.base, timeout=15, trust_env=False)
        self.addCleanup(self.client.close)
        self.client.post('/api/factory/demo/login', json={'persona':'alice'}).raise_for_status()

    def tearDown(self):
        # All jobs belong to this generated database and synthetic test identity.
        for job in self.client.get('/api/factory/jobs').json():
            if job['status'] not in {'completed', 'canceled', 'failed'}:
                self.client.post(f"/api/factory/jobs/{job['id']}/cancel").raise_for_status()
                self.wait_status(job['id'], 'canceled')

    def rows(self, statement, **params):
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(text(statement), params).mappings()]

    def plan(self, topic='scope', application='research'):
        response = self.client.post('/api/factory/plans', json={
            'topic':topic, 'mode':'literature', 'application':application, 'requestId':str(uuid4())})
        response.raise_for_status()
        return response.json()

    def admit(self, plan, key):
        response = self.client.post('/api/factory/instances', json={'planId':plan['id'], 'requestId':key})
        response.raise_for_status()
        return response.json()

    def wait_status(self, task_id, expected):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            response = self.client.get('/api/factory/jobs/' + task_id)
            response.raise_for_status()
            detail = response.json()
            if detail['job']['status'] == expected:
                return detail
            time.sleep(.1)
        self.fail('Native TCP run did not reach ' + expected)

    def test_01_committed_ack_loss_recovers_original_intent_without_mutation(self):
        actual_base = self.base
        committed = []
        class DropAfterCommit(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(handler):
                body = handler.rfile.read(int(handler.headers['Content-Length']))
                with httpx.Client(trust_env=False, timeout=15) as forward:
                    response = forward.post(actual_base + handler.path, content=body,
                        headers={'Content-Type':'application/json', 'Cookie':handler.headers.get('Cookie', '')})
                    response.raise_for_status()
                    committed.append(response.json()['id'])
                handler.close_connection = True  # Commit happened; send no ACK.

        plan, key = self.plan(), str(uuid4())
        proxy = ThreadingHTTPServer(('127.0.0.1', 0), DropAfterCommit)
        worker = threading.Thread(target=proxy.serve_forever, daemon=True)
        worker.start()
        try:
            with self.assertRaises(httpx.RemoteProtocolError):
                self.client.post(f'http://127.0.0.1:{proxy.server_port}/api/factory/instances',
                                 json={'planId':plan['id'], 'requestId':key})
        finally:
            proxy.shutdown(); proxy.server_close(); worker.join(timeout=2)
        self.assertEqual(len(committed), 1)
        self.wait_status(committed[0], 'waiting_input')
        before = self.rows('SELECT * FROM af_tasks WHERE owner_id=:owner AND request_id=:key', owner='alice', key=key)
        event_count = self.rows('SELECT COUNT(*) AS n FROM af_events')[0]['n']
        receipt = self.client.get('/api/factory/requests/' + key).json()
        self.assertEqual(receipt['taskId'], committed[0])
        self.assertEqual(receipt['runId'], before[0]['run_id'])
        self.assertEqual(receipt['admission'], 'accepted')
        self.assertEqual(before, self.rows('SELECT * FROM af_tasks WHERE owner_id=:owner AND request_id=:key', owner='alice', key=key))
        self.assertEqual(event_count, self.rows('SELECT COUNT(*) AS n FROM af_events')[0]['n'])
        self.assertEqual(len(before), 1)
        self.assertEqual(self.rows("SELECT COUNT(*) AS n FROM af_events WHERE task_id=:id AND type='native_accepted'", id=committed[0])[0]['n'], 1)

    def test_02_original_receipt_survives_actual_api_process_restart(self):
        key = str(uuid4())
        job = self.admit(self.plan(), key)
        self.wait_status(job['id'], 'waiting_input')
        before = self.client.get('/api/factory/requests/' + key).json()
        self._stop(); self._start()
        response = self.client.get('/api/factory/requests/' + key)
        response.raise_for_status()
        self.assertEqual(response.json(), before)
        self.assertEqual(self.wait_status(job['id'], 'waiting_input')['job']['id'], job['id'])

    def test_03_concurrent_original_keys_and_changed_payload_conflict(self):
        plan, key = self.plan(), str(uuid4())
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = list(pool.map(lambda _: self.admit(plan, key), range(3)))
        self.assertEqual(len({job['id'] for job in jobs}), 1)
        self.wait_status(jobs[0]['id'], 'waiting_input')
        other_plan = self.plan('different bounded literature goal')
        conflict = self.client.post('/api/factory/instances', json={'planId':other_plan['id'], 'requestId':key})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(len(self.rows('SELECT id FROM af_tasks WHERE owner_id=:owner AND request_id=:key', owner='alice', key=key)), 1)
        self.assertEqual(self.client.get('/api/factory/requests/' + key).json()['planId'], plan['id'])

    def test_04_receipts_are_scoped_and_do_not_open_native_execution(self):
        key = str(uuid4())
        job = self.admit(self.plan(), key)
        self.wait_status(job['id'], 'waiting_input')
        with httpx.Client(base_url=self.base, trust_env=False) as stranger:
            self.assertEqual(stranger.get('/api/factory/requests/' + key).status_code, 401)
            stranger.post('/api/factory/demo/login', json={'persona':'bob'}).raise_for_status()
            self.assertEqual(stranger.get('/api/factory/requests/' + key).status_code, 404)
        self.assertEqual(self.client.get('/api/factory/requests/' + str(uuid4())).status_code, 404)
        self.assertEqual(self.client.post('/agents/factory-executor/runs', data={'message':'bypass'}).status_code, 403)

    def test_05_actual_native_artifact_download_and_owner_hash(self):
        job = self.admit(self.plan('Actual UTF-8 checksum evidence: 中文', 'checksum'), str(uuid4()))
        detail = self.wait_status(job['id'], 'completed')
        self.assertEqual(len(detail['artifacts']), 1)
        artifact = detail['artifacts'][0]
        path = f"/api/factory/jobs/{job['id']}/artifacts/{artifact['id']}"
        response = self.client.get(path)
        response.raise_for_status()
        self.assertEqual(hashlib.sha256(response.content).hexdigest(), artifact['sha256'])
        self.assertEqual(len(response.content), artifact['size'])
        with httpx.Client(base_url=self.base, trust_env=False) as stranger:
            stranger.post('/api/factory/demo/login', json={'persona':'bob'}).raise_for_status()
            self.assertEqual(stranger.get(path).status_code, 404)
