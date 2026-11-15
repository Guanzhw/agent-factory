"""Real Git worktrees, native coding paths, reviewed apply and crash truth."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from research.session_git import ResearchSessionGit, git
from research.session_tools import ResearchSessionTools


class Sessions:
    def __init__(self, root):
        self.rows = {name: {'id': name, 'body': {}} for name in ('one', 'two', 'fork')}
        self.tools = ResearchSessionTools(workspace_root=root)
        self.auth = SimpleNamespace(require_member=lambda owner: None)
        self.db = SimpleNamespace(read=self._write)
        self.lock = threading.RLock()
        self.active = False

    @contextmanager
    def _write(self):
        with self.lock:
            saved = deepcopy(self.rows)
            try:
                yield None
            except BaseException:
                self.rows = saved
                raise

    def _row(self, conn, owner, identifier):
        return self.rows[identifier]

    def _turns(self, conn, identifier):
        return [None] if self.active else []

    def _safe(self, owner, turn):
        return not self.active

    def _save_session(self, conn, row, body):
        self.rows[row['id']] = {**row, 'body': deepcopy(body)}


class SessionGit(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='factory-session-git-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        git(self.source, 'init')
        git(self.source, 'config', 'core.autocrlf', 'false')
        (self.source / 'code.txt').write_text('one\ntwo\nthree\n', encoding='utf-8')
        (self.source / 'user.txt').write_text('user original\n', encoding='utf-8')
        (self.source / '.gitignore').write_text('forced.txt\n', encoding='utf-8')
        git(self.source, 'add', '.')
        git(self.source, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'fixture')
        self.sessions = Sessions(self.root / 'workspaces')
        self.service = ResearchSessionGit(self.sessions)

    def attach(self, name='one'):
        nested = self.source / 'nested'
        nested.mkdir(exist_ok=True)
        result = self.service.attach('owner', name, str(nested))
        self.assertEqual(result['repositoryPath'], str(self.source))
        return Path(result['workspacePath'])

    def review(self, name='one'):
        return self.service.read('owner', name)['reviewId']

    def test_concurrent_worktrees_new_files_stale_apply_and_incremental_gc(self):
        (self.source / 'user.txt').write_text('user staged\n', encoding='utf-8')
        git(self.source, 'add', 'user.txt')
        index_before = git(self.source, 'diff', '--cached', '--binary')
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(self.attach, ('one', 'two')))
        self.assertNotEqual(first, second)
        (first / 'code.txt').write_text('one\nagent\nthree\n', encoding='utf-8')
        (first / '新增.txt').write_text('new\n', encoding='utf-8')
        (first / 'binary.bin').write_bytes(b'\0\xff\x01')
        (first / 'forced.txt').write_text('explicitly staged', encoding='utf-8')
        git(first, 'add', '-f', 'forced.txt')
        self.assertEqual((second / 'code.txt').read_text(), 'one\ntwo\nthree\n')
        self.assertEqual((self.source / 'code.txt').read_text(), 'one\ntwo\nthree\n')
        state = self.service.read('owner', 'one')
        self.assertIn('Binary files', state['diff'])
        self.assertNotIn('GIT binary patch', state['diff'])
        self.assertIn({'status': 'A', 'path': '新增.txt'}, state['files'])
        self.assertIn({'status': 'A', 'path': 'forced.txt'}, state['files'])
        (first / '新增.txt').write_text('updated new\n', encoding='utf-8')
        with self.assertRaises(HTTPException) as stale:
            self.service.apply('owner', 'one', state['reviewId'])
        self.assertEqual(stale.exception.detail['code'], 'RESEARCH_GIT_STALE_REVIEW')
        review = self.review()
        self.assertTrue(self.service.apply('owner', 'one', review)['applied'])
        self.assertTrue(self.service.apply('owner', 'one', review)['repeated'])
        self.assertEqual((self.source / 'code.txt').read_text(), 'one\nagent\nthree\n')
        self.assertEqual((self.source / 'binary.bin').read_bytes(), b'\0\xff\x01')
        self.assertEqual((self.source / 'user.txt').read_text(), 'user staged\n')
        self.assertEqual(git(self.source, 'diff', '--cached', '--binary'), index_before)
        git(self.source, 'gc', '--prune=now')
        self.assertEqual(self.service.read('owner', 'one')['files'], [])
        (first / 'code.txt').write_text('one\nagent second\nthree\n', encoding='utf-8')
        repeated = self.service.apply('owner', 'one', review)
        self.assertTrue(repeated['repeated'])
        self.assertFalse(repeated['applied'])
        self.assertEqual(repeated['appliedReviewId'], review)
        self.assertNotEqual(repeated['reviewId'], review)
        self.assertEqual((self.source / 'code.txt').read_text(), 'one\nagent\nthree\n')
        self.service.apply('owner', 'one', self.review())
        self.assertEqual((self.source / 'code.txt').read_text(), 'one\nagent second\nthree\n')
        self.assertEqual(git(self.source, 'diff', '--cached', '--binary'), index_before)

    def test_conflicting_source_preserves_all_files_and_fork_inherits_dirty_snapshot(self):
        first = self.attach()
        (first / 'code.txt').write_text('one\nagent\nthree\n', encoding='utf-8')
        (first / 'new.txt').write_text('new', encoding='utf-8')
        with self.sessions._write() as conn:
            metadata = self.service.fork_workspace('owner', 'one', 'fork', conn)
            self.sessions.rows['fork']['body']['gitWorkspace'] = metadata
        fork = Path(self.service.read('owner', 'fork')['workspacePath'])
        self.assertEqual((fork / 'new.txt').read_text(), 'new')
        self.assertEqual((fork / 'code.txt').read_bytes(), (first / 'code.txt').read_bytes())
        (fork / 'code.txt').write_text('fork only', encoding='utf-8')
        self.assertEqual((first / 'code.txt').read_text(), 'one\nagent\nthree\n')
        (self.source / 'code.txt').write_text('one\nuser changed\nthree\n', encoding='utf-8')
        before = (self.source / 'code.txt').read_bytes()
        with self.assertRaises(HTTPException):
            self.service.apply('owner', 'one', self.review())
        self.assertEqual((self.source / 'code.txt').read_bytes(), before)
        self.assertFalse((self.source / 'new.txt').exists())
        self.assertEqual(self.service.read('owner', 'one')['applicationState'], 'ready')

    def test_interrupted_persistence_is_unknown_and_never_reapplies(self):
        first = self.attach()
        (first / 'code.txt').write_text('one\nagent\nthree\n', encoding='utf-8')
        review = self.review()
        save = self.sessions._save_session
        calls = 0
        def fail_receipt(conn, row, body):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('simulated persistence loss after native apply')
            save(conn, row, body)
        with patch.object(self.sessions, '_save_session', side_effect=fail_receipt):
            with self.assertRaises(RuntimeError):
                self.service.apply('owner', 'one', review)
        applied = (self.source / 'code.txt').read_bytes()
        self.assertEqual(applied, (first / 'code.txt').read_bytes())
        with self.assertRaises(HTTPException) as unknown:
            self.service.apply('owner', 'one', review)
        self.assertEqual(unknown.exception.detail['code'], 'RESEARCH_GIT_APPLY_UNKNOWN')
        self.assertEqual((self.source / 'code.txt').read_bytes(), applied)
        self.assertEqual(self.service.read('owner', 'one')['applicationState'], 'unknown')

    def test_definite_failure_between_intent_and_apply_clears_pending(self):
        first = self.attach()
        (first / 'code.txt').write_text('one\nagent\nthree\n', encoding='utf-8')
        review = self.review()
        idle = self.service._idle
        checks = 0
        def start_turn_between_transactions(conn, owner, identifier):
            nonlocal checks
            checks += 1
            if checks == 2:
                self.sessions.active = True
            return idle(conn, owner, identifier)
        with patch.object(self.service, '_idle', side_effect=start_turn_between_transactions):
            with self.assertRaises(HTTPException) as active:
                self.service.apply('owner', 'one', review)
        self.assertEqual(active.exception.detail['code'], 'RESEARCH_GIT_SESSION_ACTIVE')
        self.assertEqual(self.service.read('owner', 'one')['applicationState'], 'ready')
        self.assertEqual((self.source / 'code.txt').read_text(), 'one\ntwo\nthree\n')

    def test_interrupted_attach_recovers_owned_worktree_without_overwriting_files(self):
        with patch.object(self.sessions, '_save_session', side_effect=RuntimeError('metadata write failed')):
            with self.assertRaises(RuntimeError):
                self.attach()
        self.assertNotIn('gitWorkspace', self.sessions.rows['one']['body'])
        workspace = self.service._workspace('owner', 'one')
        (workspace / 'new.txt').write_text('preserved after interruption', encoding='utf-8')
        original = (workspace / 'code.txt').read_bytes()
        self.assertEqual(self.attach(), workspace)
        self.assertEqual((workspace / 'new.txt').read_text(), 'preserved after interruption')
        self.assertEqual((workspace / 'code.txt').read_bytes(), original)
        self.assertIn({'status': 'A', 'path': 'new.txt'}, self.service.read('owner', 'one')['files'])
        other = self.service._workspace('owner', 'two')
        (other / 'existing.txt').write_text('user file', encoding='utf-8')
        with self.assertRaises(HTTPException):
            self.attach('two')
        self.assertEqual((other / 'existing.txt').read_text(), 'user file')

    def test_attach_snapshot_failure_keeps_committed_binding(self):
        with patch.object(self.service, '_view', side_effect=RuntimeError('snapshot failed')):
            with self.assertRaises(RuntimeError):
                self.attach()
        self.assertIn('gitWorkspace', self.sessions.rows['one']['body'])
        self.assertEqual(self.attach(), self.service._workspace('owner', 'one'))


if __name__ == '__main__':
    unittest.main()
