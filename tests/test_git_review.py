"""Inline anchors come from actual Git hunks and canonical repository paths."""
from pathlib import Path
from contextlib import nullcontext
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import HTTPException
from sqlalchemy import Column, JSON, MetaData, String, Table, create_engine

from agent_factory.applications import GovernedStorage
from research.git_review import DiffComment, ResearchGitReview, ReviewRequest, diff_anchors
from research.session_git import git, snapshot


class GitReviewAnchors(unittest.TestCase):
    def test_native_findings_remain_bound_to_reviewed_patch_after_workspace_changes(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        git(root, 'init')
        git(root, 'config', 'user.name', 'Review fixture')
        git(root, 'config', 'user.email', 'fixture@example.invalid')
        (root / 'main.py').write_text('before\n', encoding='utf-8')
        git(root, 'add', '.')
        git(root, 'commit', '-m', 'fixture')
        baseline = git(root, 'rev-parse', 'HEAD').decode().strip()
        (root / 'main.py').write_text('after\n', encoding='utf-8')
        original = snapshot(root, baseline)
        (root / '__pycache__').mkdir()
        (root / '__pycache__' / 'verification.pyc').write_bytes(b'verification artifact')
        changed = snapshot(root, baseline)
        self.assertNotEqual(original['reviewId'], changed['reviewId'])
        engine = create_engine('sqlite://')
        metadata = MetaData()
        turns = Table('turns', metadata, Column('id', String, primary_key=True),
            Column('session_id', String), Column('owner_id', String), Column('body', JSON))
        metadata.create_all(engine)
        row = {'id': 'session', 'body': {}}
        sessions = SimpleNamespace(store=SimpleNamespace(engine=engine),
            db=SimpleNamespace(command_table=GovernedStorage.command_table,
                old=GovernedStorage.old, record=GovernedStorage.record),
            auth=SimpleNamespace(require_member=Mock()), turns=turns,
            _write=engine.begin, _row=lambda *args: row,
            _save_session=lambda conn, saved, body: saved.update(body=body))
        git_service = SimpleNamespace(read=Mock(return_value=changed))
        review = ResearchGitReview(sessions, git_service)
        with engine.begin() as conn:
            conn.execute(turns.insert().values(id='turn', session_id='session', owner_id='owner', body={
                'origin': {'kind': 'git-review', 'reviewId': original['reviewId'], 'files': original['files']},
                'messages': [{'text': 'Review instructions\nPatch:\n' + original['diff']}] }))
        request = DiffComment(requestId='finding-1', reviewId=original['reviewId'], path='main.py', side='right', line=1, text='Bug')
        saved = review.create('owner', 'session', request, turn_id='turn')
        self.assertEqual(saved['reviewId'], original['reviewId'])
        self.assertEqual(row['body']['gitComments'], [saved])
        self.assertEqual(review.create('owner', 'session', request, turn_id='turn'), saved)
        git_service.read.assert_not_called()
        with self.assertRaises(HTTPException) as invalid:
            review.create('owner', 'session', request.model_copy(update={'requestId': 'bad-line', 'line': 2}), turn_id='turn')
        self.assertEqual(invalid.exception.status_code, 422)
        with self.assertRaises(HTTPException) as stale:
            review.create('owner', 'session', request.model_copy(update={'requestId': 'human-01'}))
        self.assertEqual(stale.exception.status_code, 409)
        engine.dispose()

    def test_review_reports_existing_native_input_limit_as_422(self):
        conn = Mock()
        conn.execute.return_value.mappings.return_value.first.return_value = None
        review = object.__new__(ResearchGitReview)
        review.sessions = SimpleNamespace(db=SimpleNamespace(read=lambda: nullcontext(conn)),
            commands=Table('commands', MetaData(), Column('actor_id', String), Column('request_id', String)),
            _row=Mock())
        review.git = SimpleNamespace(read=lambda *args: {'reviewId': 'revision', 'diff': 'a' * (1 << 20), 'files': []})
        review.listing = lambda *args: {'items': []}
        with self.assertRaises(HTTPException) as large:
            review._review_turn('owner', 'session', ReviewRequest(requestId='review-1', reviewId='revision'))
        self.assertEqual(large.exception.status_code, 422)

    def test_actual_diff_new_deleted_unicode_and_content_line_separators(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            git(root, 'init')
            git(root, 'config', 'user.name', 'Review fixture')
            git(root, 'config', 'user.email', 'fixture@example.invalid')
            original = root / '中文 file.py'
            original.write_text('before\nsecond\n', encoding='utf-8')
            (root / 'deleted.txt').write_text('removed\n', encoding='utf-8')
            git(root, 'add', '.')
            git(root, 'commit', '-m', 'fixture')
            baseline = git(root, 'rev-parse', 'HEAD').decode().strip()
            original.write_text('after\u2028same line\vstill same\nsecond\n', encoding='utf-8')
            (root / 'deleted.txt').unlink()
            (root / 'new.txt').write_text('new\n', encoding='utf-8')
            state = snapshot(root, baseline)
            anchors = diff_anchors(state['diff'], state['files'])
            self.assertEqual(anchors, {
                ('中文 file.py', 'left', 1), ('中文 file.py', 'left', 2),
                ('中文 file.py', 'right', 1), ('中文 file.py', 'right', 2),
                ('deleted.txt', 'left', 1), ('new.txt', 'right', 1)})
            self.assertEqual(git(root, 'diff', '--cached'), b'')


if __name__ == '__main__':
    unittest.main()
