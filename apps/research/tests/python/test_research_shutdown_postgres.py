"""Real production exit, PostgreSQL custody and original-process restart checks.

No live model/ORX compatibility is claimed. The original 35s close deadline is
not patched. A forced fixture kill never counts as a successful server exit.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import httpx
from sqlalchemy import create_engine, text

from pg_fixture import IsolatedPostgres


# Owned by the test parent, so server os._exit cannot strand this process. It
# executes one immutable file command and acknowledges only that command's stop.
CHILD = r'''
import json, pathlib, sys, time
root = pathlib.Path(sys.argv[1])
deadline = time.monotonic() + 180
identity = None
while time.monotonic() < deadline:
    command = root / 'child-command.json'
    if identity is None and command.exists():
        try:
            identity = json.loads(command.read_text())
        except json.JSONDecodeError:
            time.sleep(.02)
            continue
        temporary = root / 'child-started.tmp'
        temporary.write_text(json.dumps(identity))
        temporary.replace(root / 'child-started.json')
    stop = root / 'child-stop.json'
    if identity is not None and stop.exists():
        try:
            requested = json.loads(stop.read_text())
        except json.JSONDecodeError:
            time.sleep(.02)
            continue
        if requested != identity:
            raise SystemExit(2)
        temporary = root / 'child-stopped.tmp'
        temporary.write_text(json.dumps(identity))
        temporary.replace(root / 'child-stopped.json')
        raise SystemExit(0)
    time.sleep(.02)
raise SystemExit(3)
'''


@unittest.skipUnless(sys.platform == 'linux' and os.getenv('FACTORY_TEST_DATABASE_URL'),
                     'Requires Linux and authorized disposable loopback PostgreSQL')
class ResearchShutdownPostgresTests(unittest.TestCase):
    def setUp(self):
        database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        self.directory = tempfile.TemporaryDirectory(prefix='research-shutdown-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.database_url = database.url
        self.evidence_directory = os.getenv('FACTORY_SHUTDOWN_EVIDENCE_DIR')
        # unittest cleanups are LIFO: preserve after process/log cleanup, before
        # deleting the temporary directory. Never archive configuration or env.
        self.addCleanup(self.preserve_evidence)
        self.engine = create_engine(database.url)
        self.addCleanup(self.engine.dispose)
        self.server = None
        self.child = None
        self.generation = 0
        self.shutdown_results = {}
        self.logs = []
        self.addCleanup(self.cleanup_owned_processes)
        self.child = subprocess.Popen([sys.executable, '-I', '-c', CHILD, str(self.root)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def cleanup_owned_processes(self):
        for process in (self.server, self.child):
            if process is not None and process.poll() is None:
                if process is self.server:
                    self.shutdown_results[self.generation]['fixtureTerminateSent'] = True
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if process is self.server:
                        self.shutdown_results[self.generation]['forcedFixtureKill'] = True
                    process.kill()
                    process.wait(timeout=5)
            if process is self.server and process is not None:
                self.record_server_exit()
        if hasattr(self, 'client'):
            self.client.close()
        for log in self.logs:
            log.close()

    def safe_log(self, value):
        value = value.replace(self.database_url, '[REDACTED_DATABASE_URL]')
        return re.sub(r"postgres(?:ql)?(?:\+[A-Za-z0-9_]+)?://[^\s'\"<>]+",
                      '[REDACTED_DATABASE_URL]', value)

    def log_tail(self):
        generation = getattr(self, 'generation', 0)
        path = self.root / f'server-{generation}.log'
        if not path.exists():
            return 'Worker log not yet available.'
        return self.safe_log(path.read_text(encoding='utf-8', errors='replace'))[-6000:]

    def fail(self, msg=None):
        # Preserve the actual worker failure in CI even without an artifact dir.
        tail = self.log_tail() if hasattr(self, 'root') else 'Worker not initialized.'
        message = str(msg or 'Shutdown assertion failed')
        if hasattr(self, 'database_url'):
            message = self.safe_log(message)
        super().fail(f'{message}\nWorker log tail:\n{tail}')

    def preserve_evidence(self):
        if not self.evidence_directory:
            return
        base = Path(self.evidence_directory)
        base.mkdir(parents=True, exist_ok=True)
        destination = Path(tempfile.mkdtemp(prefix=self._testMethodName + '-', dir=base))
        for pattern in ('server-*.log', 'events-*.jsonl', 'child-*.json', 'dispatches.jsonl'):
            for source in self.root.glob(pattern):
                value = source.read_text(encoding='utf-8', errors='replace')
                (destination / source.name).write_text(self.safe_log(value), encoding='utf-8')
        (destination / 'observations.json').write_text(json.dumps({
            'test': self.id(), 'generation': getattr(self, 'generation', 0),
            'serverReturnCode': self.server.poll() if getattr(self, 'server', None) is not None else None,
            'childReturnCode': self.child.poll() if getattr(self, 'child', None) is not None else None,
            'shutdowns': list(getattr(self, 'shutdown_results', {}).values()),
        }, indent=2), encoding='utf-8')
        print(f'Shutdown fixture evidence: {destination}', flush=True)

    def events(self, generation=None):
        path = self.root / f'events-{generation or self.generation}.jsonl'
        if not path.exists():
            return []
        lines = path.read_text().splitlines()
        # A live writer's final partial line is not yet evidence.
        result = []
        for line in lines:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                break
        return result

    def wait_for(self, predicate, *, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            if self.server is not None and self.server.poll() is not None:
                self.fail('Production worker exited before the expected observation')
            time.sleep(.05)
        self.fail('Controlled shutdown fixture observation timed out')

    def start(self, scenario):
        self.generation += 1
        self.shutdown_results[self.generation] = {
            'generation': self.generation, 'actualCode': None, 'elapsedSeconds': None,
            'signalElapsedSeconds': None, 'fixtureTerminateSent': False, 'forcedFixtureKill': False,
        }
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        configuration = self.root / f'config-{self.generation}.json'
        configuration.write_text(json.dumps({'database': self.database_url, 'workspace': str(self.root),
            'port': port, 'scenario': scenario, 'generation': self.generation}))
        configuration.chmod(0o600)
        project = Path(__file__).resolve().parents[4]
        # Do not inherit model/provider credentials or unrelated host settings.
        environment = {name: os.environ[name] for name in ('PATH', 'LANG', 'LC_ALL', 'TMPDIR')
                       if name in os.environ}
        environment.update(FACTORY_SHUTDOWN_FIXTURE=str(configuration), AGNO_TELEMETRY='false',
            PYTHONPATH=os.pathsep.join(str(project / part) for part in
                ('platform', 'apps/research', 'deployment', 'platform/tests', 'apps/research/tests/python')))
        log = (self.root / f'server-{self.generation}.log').open('ab')
        self.logs.append(log)
        self.server = subprocess.Popen([sys.executable, '-m', 'research_shutdown_worker'],
            cwd=project, env=environment, stdout=log, stderr=log)
        if hasattr(self, 'client'):
            self.client.close()
        self.client = httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=5, trust_env=False)

        def ready():
            try:
                return self.client.get('/api/health').is_success
            except httpx.HTTPError:
                return False

        self.wait_for(ready)
        response = self.client.post('/api/factory/demo/login', json={'persona': 'alice'})
        self.assertEqual(response.status_code, 200)

    def submit(self, request='shutdown-original-request', expected=202):
        response = self.client.post('/api/factory/autoresearch/runs', json={
            'presetId': 'shutdown-original-process', 'requestId': request})
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def snapshot(self, task_id):
        with self.engine.connect() as connection:
            task = dict(connection.execute(text('SELECT id,owner_id,plan_id,run_id,terminal,cancel_requested '
                'FROM af_tasks WHERE id=:task'), {'task': task_id}).mappings().one())
            body = connection.execute(text('SELECT body FROM af_autoresearch_runs WHERE task_id=:task'),
                                      {'task': task_id}).scalar_one()
            effects = [dict(row) for row in connection.execute(text(
                'SELECT effect_key,task_id,run_id,fingerprint,status,result FROM af_effects '
                'WHERE task_id=:task ORDER BY effect_key'), {'task': task_id}).mappings()]
        return {'task': task, 'control': body.get('sessionControl'), 'status': body['status'], 'effects': effects}

    def record_server_exit(self):
        result = self.shutdown_results[self.generation]
        if result['actualCode'] is not None:
            return  # Keep the original observation, including earlier generations.
        result['actualCode'] = self.server.poll()
        observed = time.monotonic()
        starts = [event['time'] for event in self.events() if event['event'] == 'shutdown-entered']
        if starts:
            result['elapsedSeconds'] = observed - starts[0]
        if 'signalSentAt' in result:
            result['signalElapsedSeconds'] = observed - result['signalSentAt']

    def shutdown(self, expected):
        self.shutdown_results[self.generation]['signalSentAt'] = time.monotonic()
        self.server.send_signal(signal.SIGTERM)
        try:
            code = self.server.wait(timeout=70)
        except subprocess.TimeoutExpired:
            self.fail('Production shutdown exceeded 70 seconds; bounded cleanup is not acceptance')
        finally:
            self.record_server_exit()
        # Uvicorn 0.54 restores and re-raises SIGTERM after a clean lifespan.
        # Its normal signal exit must not be confused with fatal os._exit(1).
        self.assertEqual(code, -signal.SIGTERM if expected == 0 else expected)
        records = self.events()
        starts = [event for event in records if event['event'] == 'shutdown-entered']
        self.assertEqual(len(starts), 1)
        for event in records:
            if event['event'] in {'dependency-close', 'graph-release'}:
                self.assertEqual(event['pending'], 0, event)
        if expected == 0:
            self.assertTrue(any(event['event'] == 'graph-release' for event in records))
            log = (self.root / f'server-{self.generation}.log').read_text()
            self.assertIn('Application shutdown complete.', log)
            self.assertNotIn('Application shutdown failed', log)
        else:
            self.assertFalse(any(event['event'] == 'production-main-returned' for event in records))
        return records, starts[0]['time']

    def assert_one_dispatch(self):
        dispatches = (self.root / 'dispatches.jsonl').read_text().splitlines()
        self.assertEqual(len(dispatches), 1)
        return json.loads(dispatches[0])

    def test_active_execution_stops_original_process_and_exits_cleanly(self):
        self.start('active')
        run = self.submit()
        self.wait_for(lambda: any(row['event'] == 'runtime-started' for row in self.events()))
        records, _ = self.shutdown(0)
        self.assertTrue(any(row['event'] == 'cleanup-confirmed' for row in records))
        self.assertEqual(self.child.wait(timeout=5), 0)
        identity = self.assert_one_dispatch()
        self.assertEqual(identity['taskId'], run['id'])
        self.assertEqual(json.loads((self.root / 'child-stopped.json').read_text()), identity)

    def test_completed_execution_preserves_receipt_and_exits_cleanly(self):
        self.start('completed')
        run = self.submit()
        self.wait_for(lambda: self.snapshot(run['id'])['status'] == 'completed')
        before = self.snapshot(run['id'])
        self.assertEqual([effect['status'] for effect in before['effects']], ['DONE'])
        self.shutdown(0)
        self.assertEqual(self.snapshot(run['id'])['effects'], before['effects'])
        self.assertEqual(self.child.wait(timeout=5), 0)
        self.assert_one_dispatch()

    def test_cleanup_over_original_deadline_exits_nonzero_and_restart_never_redispatches(self):
        self.start('slow')
        run = self.submit()
        self.wait_for(lambda: any(row['event'] == 'cleanup-entered' for row in self.events()))
        before = self.snapshot(run['id'])
        self.assertIsNotNone(before['control'])
        self.assertEqual([effect['status'] for effect in before['effects']], ['UNKNOWN'])
        records, started = self.shutdown(1)
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 34.5, 'Must exercise the unchanged 35-second deadline')
        self.assertLess(elapsed, 55, 'Fatal shutdown must be bounded before the fixture kill limit')
        reads = [row for row in records if row['event'] == 'cleanup-dependency-read']
        self.assertTrue(any(row['time'] - started >= 34 for row in reads))
        self.assertTrue(all(row['sameGraph'] for row in reads))
        self.assertFalse(any(row['event'] in {'dependency-close', 'graph-release', 'cleanup-confirmed'}
                             for row in records))
        self.assertFalse((self.root / 'child-stopped.json').exists())
        self.assertIsNone(self.child.poll(), 'Server exit is not original-process stop proof')
        original = self.snapshot(run['id'])
        self.assertFalse(original['task']['terminal'])
        self.assertEqual(original['control'], before['control'])
        self.assertEqual(original['effects'], before['effects'])

        self.start('slow')
        recovered = self.client.get('/api/factory/autoresearch/requests/shutdown-original-request')
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json()['id'], run['id'])
        self.assertEqual(self.submit()['id'], run['id'])
        self.submit('shutdown-new-request-after-restart', expected=429)
        after = self.snapshot(run['id'])
        for key in ('id', 'owner_id', 'plan_id', 'run_id'):
            self.assertEqual(after['task'][key], before['task'][key])
        self.assertFalse(after['task']['terminal'])
        self.assertEqual(after['control'], before['control'])
        self.assertEqual(after['effects'], before['effects'])
        self.assert_one_dispatch()
        self.assertFalse(any(row['event'] == 'runtime-started' for row in self.events()))
        self.shutdown(0)
        self.assert_one_dispatch()


if __name__ == '__main__':
    unittest.main()
