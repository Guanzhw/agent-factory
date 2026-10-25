"""Hard controller death with actual PG/native jobs and original helper custody.

The existing command worker owns the HTTP process lifecycle. SSH transport is
the local subprocess substitute; no external server, model or GPU is contacted.
"""
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import sys
import unittest

from agno.db.postgres import PostgresDb
from sqlalchemy import create_engine, text

from agent_factory.process_enforcement import BoundedProcessAdapter, birth, same_birth
import test_control_commands_process as command_fixture
import test_ssh_native_postgres as native_fixture


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL') and sys.platform == 'linux',
                     'Requires isolated PostgreSQL and Linux process custody')
class SSHNativeProcessTests(unittest.TestCase):
    until = native_fixture.SSHNativePostgresTests.until

    def setUp(self):
        for name in ('ssh-agent', 'ssh-add'):
            if not shutil.which(name):
                self.skipTest(name + ' is unavailable')
        self.cleanup_registered = False
        self.orphan_agents = []
        self.server = command_fixture.CommandProcessTests('runTest')
        setattr(self.server, 'worker_module', 'controlled_ssh_command_worker')
        self.server.start = self.start
        self.server.setUp()
        self.engine = create_engine(self.server.database.url)
        self.addCleanup(self.engine.dispose)
        self.native = PostgresDb(db_url=self.server.database.url, id='factory-native-postgres')
        self.addCleanup(self.native.db_engine.dispose)

    def start(self):
        if not self.cleanup_registered:
            # The reused fixture has allocated its DB, directory and client
            # before start(); register cleanup even if child startup fails.
            self.addCleanup(self.cleanup)
            self.cleanup_registered = True
        command_fixture.CommandProcessTests.start(self.server)

    def cleanup(self):
        (self.server.root / 'release').touch()
        try:
            for path in (self.server.root / 'remote').glob('*/custody.sqlite'):
                adapter = BoundedProcessAdapter(path)
                adapter.cancel(owner_id='alice')
                stopped = adapter.wait(owner_id='alice', timeout=7)
                self.assertTrue(stopped['stoppedProof'], stopped)
        finally:
            try:
                self.cleanup_orphan_agents()
            finally:
                self.server.tearDown()

    def cleanup_orphan_agents(self):
        # This is test-owned recovery after bare-PID kill, not a product claim
        # that key expiry terminates an orphan ssh-agent.
        roots = {}
        for agent in self.orphan_agents:
            root, folder, sock = agent['paths']
            for metadata in (root, folder, sock):
                path = Path(metadata['path'])
                if not path.exists():
                    continue
                info = path.lstat()
                self.assertEqual((info.st_dev, info.st_ino, info.st_uid, info.st_mode),
                    tuple(metadata[key] for key in ('dev', 'ino', 'uid', 'mode')))
                self.assertEqual(info.st_uid, os.getuid())
                self.assertFalse(stat.S_ISLNK(info.st_mode))
            expected = agent['birth']
            actual = birth(expected['pid'])
            if actual is not None and actual['state'] != 'Z':
                with os.fdopen(os.pidfd_open(expected['pid']), 'rb') as descriptor:
                    self.assertTrue(same_birth(birth(expected['pid']), expected))
                    command = Path(f"/proc/{expected['pid']}/cmdline").read_bytes().split(b'\0')
                    self.assertEqual(Path(os.fsdecode(command[0])).name, 'ssh-agent')
                    self.assertIn(b'-D', command)
                    self.assertEqual(os.fsdecode(command[command.index(b'-a') + 1]), sock['path'])
                    signal.pidfd_send_signal(descriptor.fileno(), signal.SIGTERM)
                    self.until(lambda: (value := birth(expected['pid'])) is None or value['state'] == 'Z',
                               'owned orphan ssh-agent exits')
            socket_path = Path(sock['path'])
            if socket_path.exists():
                socket_path.unlink()
            folder_path = Path(folder['path'])
            if folder_path.exists():
                folder_path.rmdir()  # Fail rather than delete unexpected contents.
            roots[root['path']] = root
        for path, metadata in roots.items():
            root_path = Path(path)
            if root_path.exists():
                info = root_path.lstat()
                self.assertEqual((info.st_dev, info.st_ino), (metadata['dev'], metadata['ino']))
                root_path.rmdir()

    def rows(self, sql, **parameters):
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(text(sql), parameters).mappings()]

    def test_hard_kill_paused_controller_preserves_original_helper_and_run(self):
        connection = json.loads((self.server.root / 'ssh-setup.json').read_text())['connectionRef']
        started = self.server.api('POST', '/application-interface/v1/starts',
            {'application': 'ssh-native', 'mode': 'train', 'goal': 'Survive actual controller process death',
             'requestId': 'hard-controller-restart', 'connectionRefs': {'compute': connection}})
        task_id = started['job']['id']
        task = self.rows('SELECT * FROM af_tasks WHERE id=:task', task=task_id)[0]
        run_id = task['run_id']
        self.until(lambda: (self.server.root / 'starts').exists(), 'original helper starts')
        self.until(lambda: (self.native.get_job(run_id) or {})['status'] == 'paused', 'actual native PAUSED')
        operations = self.rows('SELECT id,body FROM af_external_operations WHERE task_id=:task', task=task_id)
        leases = self.rows('SELECT id,body FROM af_leases WHERE body->>\'localTaskId\'=:task', task=task_id)
        self.assertEqual(len(operations), 1)
        self.assertEqual(len(leases), 1)
        operation, lease = operations[0], leases[0]
        retained = operation['body']['inputs']
        self.assertEqual(retained['inputs'], {'width': 1, 'label': 'first'})
        journal = self.server.root / 'remote' / lease['id'] / 'custody.sqlite'
        adapter = BoundedProcessAdapter(journal)
        observed = adapter.inspect(owner_id='alice')
        self.assertEqual(observed['state'], 'RUNNING')
        child = observed['child']
        self.assertTrue(same_birth(birth(child['pid']), child))
        process = self.server.process
        assert process is not None
        controller_pid = process.pid
        self.orphan_agents = [json.loads(path.read_text())
            for path in self.server.root.glob(f'ssh-agent-{controller_pid}-*.json')]
        self.assertTrue(self.orphan_agents, 'record exact test-owned agents before controller death')
        process.kill()
        self.assertEqual(process.wait(timeout=10), -signal.SIGKILL)
        self.assertTrue(same_birth(birth(child['pid']), child), 'helper must survive actual controller death')
        after_kill = adapter.inspect(owner_id='alice')
        self.assertEqual(after_kill['id'], observed['id'])
        self.assertEqual(after_kill['child'], child)
        self.assertEqual(after_kill['state'], 'RUNNING')
        surviving_child = birth(child['pid'])
        assert surviving_child is not None
        self.assertNotEqual(surviving_child['state'], 'Z')
        self.assertFalse(after_kill['stoppedProof'])
        self.start()
        assert self.server.process is not None
        self.assertNotEqual(self.server.process.pid, controller_pid)
        (self.server.root / 'release').touch()
        self.until(lambda: self.rows('SELECT terminal FROM af_tasks WHERE id=:task', task=task_id)[0]['terminal'],
                   'original native task completes after hard restart')
        self.assertEqual((self.native.get_job(run_id) or {})['status'], 'completed')
        restored_task = self.rows('SELECT * FROM af_tasks WHERE id=:task', task=task_id)[0]
        for key in ('id', 'run_id', 'plan_id', 'request_id'):
            self.assertEqual(restored_task[key], task[key])
        restored_op = self.rows('SELECT id,body FROM af_external_operations WHERE task_id=:task', task=task_id)
        self.assertEqual([row['id'] for row in restored_op], [operation['id']])
        self.assertEqual(restored_op[0]['body']['inputs'], retained)
        self.assertEqual(self.rows('SELECT id FROM af_leases WHERE body->>\'localTaskId\'=:task', task=task_id),
                         [{'id': lease['id']}])
        commands = self.rows('SELECT command_id FROM af_control_commands WHERE task_ref=:task', task=task_id)
        self.assertEqual(len(commands), 1)
        command_id = commands[0]['command_id']
        for _ in range(2):
            receipt = self.server.api('GET', f'/jobs/{task_id}/commands/{command_id}')
            self.assertTrue(receipt['decisionRecorded'])
            self.assertFalse(receipt['canDispatch'])
        self.assertEqual(self.server.count({'commandId': command_id}), 1)
        self.assertEqual([json.loads(line) for line in (self.server.root / 'starts').read_text().splitlines()],
                         [{'width': 1, 'label': 'first'}])
        result = self.native.get_run(run_id)
        assert result is not None and not isinstance(result, dict)
        assert isinstance(result.content, str)
        self.assertEqual(json.loads(result.content)['received'], {'width': 1, 'label': 'first'})
