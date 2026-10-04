# pyright: reportMissingImports=false
"""Deterministic fixture observation of the pre-initialized SQLite path window."""
from pathlib import Path
import sqlite3
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from agent_factory.process_enforcement import BoundedProcessAdapter
from controlled_remote_process_worker import custody_observations


class CustodyObservationTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "Custody requires POSIX private file permissions")
    def test_visible_empty_sqlite_path_is_not_initialized_custody(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / 'lease'; task.mkdir(mode=0o700)
            path = task / 'custody.sqlite'; path.touch(mode=0o600)
            # This is the actual gap after O_EXCL and before CREATE/INSERT commit.
            with self.assertRaises(sqlite3.OperationalError):
                BoundedProcessAdapter(path).inspect(owner_id='alice')
            row = {'id': 'lease', 'owner_id': 'alice', 'body': {'state': 'UNKNOWN'}}
            store = SimpleNamespace(sql=Mock(return_value=[row]))
            with patch('controlled_remote_process_worker.BoundedProcessAdapter') as adapter:
                observed = custody_observations(store, root)
                adapter.assert_not_called()
            self.assertEqual(observed, [{'leaseId': 'lease', 'state': 'UNKNOWN', 'stoppedProof': False,
                'capacityHeld': True, 'observation': 'custody-not-pinned'}])

    def test_pinned_read_is_not_skipped_and_preserves_real_failures_safely(self):
        row = {'id': 'lease', 'owner_id': 'alice', 'body': {
            'processPin': {'id': 'original'}, 'journalIdentity': [1, 2]}}
        store = SimpleNamespace(sql=Mock(return_value=[row]))
        with patch('controlled_remote_process_worker.BoundedProcessAdapter') as adapter:
            adapter.return_value.inspect.side_effect = ValueError('private path/token must not escape')
            with self.assertRaises(HTTPException) as error:
                custody_observations(store, Path('/synthetic/private'))
            self.assertEqual(error.exception.status_code, 500)
            self.assertEqual(error.exception.detail, {'fixturePhase': 'pinned-custody-inspect', 'errorType': 'ValueError'})
            adapter.return_value.inspect.assert_called_once_with(owner_id='alice')
            adapter.return_value.inspect.side_effect = None
            adapter.return_value.inspect.return_value = {'id': 'original', 'state': 'RUNNING',
                'stoppedProof': False, 'capacityHeld': True, 'secret': 'not projected'}
            result = custody_observations(store, Path('/synthetic/private'))
            self.assertEqual(result[0]['id'], 'original')
            self.assertEqual(result[0]['state'], 'RUNNING')
            self.assertNotIn('secret', result[0])
