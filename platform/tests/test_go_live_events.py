import os
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent_factory.go_live_events import GoDiagnosticJournal


@unittest.skipUnless(os.name == "posix", "POSIX private diagnostic files required")
class GoLiveEventsTests(unittest.TestCase):
    def test_reopen_sequence_private_and_sanitized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.sqlite'
            journal = GoDiagnosticJournal.create(path, 'campaign')
            journal.record('d727898b-7233-4417-87fc-1c99b5f4843a', 'PREPARED')
            journal.record('d727898b-7233-4417-87fc-1c99b5f4843a', 'FAILED', error=ValueError('private-content'),
                           response_headers={'authorization': 'private-content'})
            before = path.read_bytes(), path.stat().st_mtime_ns
            reopened = GoDiagnosticJournal(path)
            result = reopened.inspect()
            self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
            self.assertEqual([e['sequence'] for e in result['events']], [1, 2])
            self.assertNotIn('private-content', json.dumps(result))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            reopened.record('runner', 'RUNNER_STARTED')
            self.assertEqual(reopened.inspect()['events'][-1]['sequence'], 3)
            with sqlite3.connect(path) as conn:
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute('DELETE FROM events')

    def test_no_create_overwrite_symlink_or_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.sqlite'
            with self.assertRaises(FileNotFoundError):
                GoDiagnosticJournal(path)
            self.assertFalse(path.exists())
            path.write_bytes(b'legacy')
            path.chmod(0o600)
            before = path.read_bytes(), path.stat().st_mtime_ns
            with self.assertRaises(FileExistsError):
                GoDiagnosticJournal.create(path, 'campaign')
            with self.assertRaises(sqlite3.DatabaseError):
                GoDiagnosticJournal(path)
            self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
            link = Path(directory) / 'link'
            link.symlink_to(path)
            with self.assertRaises(OSError):
                GoDiagnosticJournal(link)
            self.assertEqual(path.read_bytes(), b'legacy')

    def test_committed_events_survive_immediate_process_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.sqlite'
            script = '''import os, sys
from agent_factory.go_live_events import GoDiagnosticJournal
journal = GoDiagnosticJournal.create(sys.argv[1], 'crash')
journal.record('d727898b-7233-4417-87fc-1c99b5f4843a', 'PREPARED')
journal.record('d727898b-7233-4417-87fc-1c99b5f4843a', 'DISPATCH_STARTED')
os._exit(0)
'''
            result = subprocess.run([sys.executable, '-c', script, str(path)], check=False)
            self.assertEqual(result.returncode, 0)
            events = GoDiagnosticJournal(path).inspect()['events']
            self.assertEqual([e['phase'] for e in events], ['PREPARED', 'DISPATCH_STARTED'])
            self.assertEqual([e['sequence'] for e in events], [1, 2])

    def test_invalid_phase_and_ticket_do_not_append(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = GoDiagnosticJournal.create(Path(directory) / 'events.sqlite', 'campaign')
            for ticket, phase in [('d727898b-7233-4417-87fc-1c99b5f4843a', 'private-value'),
                                  ('unsafe value', 'FAILED'), ('server-request-id', 'FAILED'),
                                  ('d727898b-7233-1417-87fc-1c99b5f4843a', 'FAILED')]:
                with self.assertRaises(ValueError):
                    journal.record(ticket, phase)
            self.assertEqual(journal.inspect()['events'], [])

    def test_missing_platform_protection_fails_closed_before_create(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.sqlite'
            with patch('agent_factory.go_live_events.os.O_NOFOLLOW', 0):
                with self.assertRaisesRegex(ValueError, 'POSIX'):
                    GoDiagnosticJournal.create(path, 'campaign')
            self.assertFalse(path.exists())
