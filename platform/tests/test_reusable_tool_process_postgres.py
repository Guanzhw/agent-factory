"""Full graceful OS replacement over original PG/vault, not crash recovery."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest

from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL/native queue')
class ReusableToolProcessPostgresTests(unittest.TestCase):
    def test_graceful_process_replacement_restores_accounts_receipts_and_unknown(self):
        database = self.enterContext(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        directory = self.enterContext(TemporaryDirectory(prefix='reusable-operation-process-'))
        workspace = Path(directory)
        observations = []
        evidence = os.getenv('FACTORY_REUSABLE_TOOL_EVIDENCE_DIR')
        def preserve():
            if evidence:
                destination = Path(evidence) / workspace.name
                destination.mkdir(parents=True, exist_ok=False)
                # No environment/config/DB URL or vault key is copied.
                for pattern in ('*-report.json', 'process-observations.json', 'business.jsonl', '*.log'):
                    for source in workspace.glob(pattern):
                        if source.suffix == '.log':
                            safe = source.read_text(errors='replace').replace(database.url, '[synthetic-database-url]')
                            safe = re.sub(r'synthetic-operation-token-[A-Za-z-]+', '[synthetic-token]', safe)
                            (destination / source.name).write_text(safe)
                        else:
                            shutil.copy2(source, destination / source.name)
        root = Path(__file__).resolve().parents[2]
        environment = {**os.environ, 'REUSABLE_PROCESS_DATABASE_URL': database.url,
            'PYTHONPATH': os.pathsep.join(str(path) for path in (root / 'platform', root / 'apps/research',
                                                              root / 'deployment', root / 'platform/tests'))}
        environment.pop('FACTORY_TEST_DATABASE_URL', None)
        worker = Path(__file__).with_name('reusable_tool_process_worker.py')
        try:
            for phase in ('first', 'restore'):
                log = workspace / (phase + '.log')
                began = time.monotonic()
                forced = False
                with log.open('wb') as stream:
                    process = subprocess.Popen([sys.executable, str(worker), phase, '--workspace', str(workspace)],
                        cwd=root, env=environment, stdout=stream, stderr=subprocess.STDOUT)
                    try:
                        code = process.wait(timeout=120)
                    except subprocess.TimeoutExpired:
                        forced = True
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                        code = process.returncode
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.wait(timeout=5)
                observations.append({'phase': phase, 'pid': process.pid, 'exitCode': code,
                    'forcedFixtureStop': forced, 'elapsedSeconds': round(time.monotonic() - began, 3)})
                (workspace / 'process-observations.json').write_text(json.dumps(observations, sort_keys=True))
                tail = log.read_text(errors='replace')[-10000:].replace(database.url, '[synthetic-database-url]')
                tail = re.sub(r'synthetic-operation-token-[A-Za-z-]+', '[synthetic-token]', tail)
                self.assertFalse(forced, 'Owned worker exceeded bounded wait: ' + tail)
                self.assertEqual(code, 0, 'Owned worker must exit cleanly: ' + tail)
                report = json.loads((workspace / (phase + '-report.json')).read_text())
                self.assertTrue(report['servicesClosed'])
                self.assertEqual(report['pid'], process.pid)
            self.assertNotEqual(observations[0]['pid'], observations[1]['pid'])
            first = json.loads((workspace / 'first-report.json').read_text())
            restored = json.loads((workspace / 'restore-report.json').read_text())
            self.assertTrue(restored['singletonRestored'])
            self.assertEqual(restored['previousPid'], first['pid'])
            self.assertEqual(restored['unknown'], first['unknown']['task'])
            self.assertEqual(restored['unknownEffects'], first['unknown']['effects'])
            self.assertEqual(restored['calls'], first['calls'] + ['bob', 'bob'])
        finally:
            preserve()


if __name__ == '__main__':
    unittest.main()
