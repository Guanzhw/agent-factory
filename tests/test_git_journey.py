"""Git workspaces, review and forks through PostgreSQL, native tools and Chromium."""
import json
from pathlib import Path
import subprocess
from uuid import uuid4

from playwright.sync_api import expect

from test_native_history import NativeHistory
from test_native_model import chunk, reply


class GitJourney(NativeHistory):
    def setUp(self):
        super().setUp()
        self.repo = Path(self.folder.name) / ('repository-' + uuid4().hex)
        self.repo.mkdir()
        self.git('init')
        self.git('config', 'user.name', 'Synthetic QA')
        self.git('config', 'user.email', 'qa@example.invalid')
        self.git('config', 'core.autocrlf', 'false')
        (self.repo / '中文 文件.py').write_text('value = 1\n', encoding='utf-8')
        self.git('add', '.')
        self.git('commit', '-m', 'Synthetic baseline')
        self.provider.answer = self.answer

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def post(self, path, body):
        if not path.endswith(('/git', '/git/apply')):
            return super().post(path, body)
        response = self.context.request.post(self.origin + '/api/factory' + path, data=body,
            headers={'Origin': self.origin, 'X-Factory-CSRF': self.csrf})
        self.assertTrue(response.ok, response.text())
        return response.json()

    def get(self, path):
        response = self.context.request.get(self.origin + '/api/factory' + path)
        self.assertTrue(response.ok, response.text())
        return response.json()

    def answer(self, body):
        messages = body['messages']
        index = max(i for i, message in enumerate(messages) if message['role'] == 'user')
        user = messages[index]['content']
        results = [message for message in messages[index:] if message['role'] == 'tool']
        if user == 'git-native-change-marker':
            steps = [('read_file', {'file_path': '中文 文件.py'}),
                     ('edit_file', {'file_path': '中文 文件.py', 'old_text': 'value = 1', 'new_text': 'value = 2'}),
                     ('write_file', {'file_path': 'notes.txt', 'contents': 'native-new-file-marker\n'}),
                     ('run_shell', {'command': 'git diff --stat'})]
            if len(results) < len(steps):
                name, arguments = steps[len(results)]
                return 200, [chunk({'role': 'assistant', 'tool_calls': [{'index': 0,
                    'id': 'git_' + uuid4().hex, 'type': 'function',
                    'function': {'name': name, 'arguments': json.dumps(arguments)}}]}),
                    chunk({}, 'tool_calls')]
            return 200, reply('git-original-answer-marker')
        return 200, reply('git-review-answer-marker')

    def test_worktree_native_diff_review_apply_and_fork(self):
        original_path = self.path
        first = self.post(self.path + '/git', {'repositoryPath': str(self.repo)})
        other = self.post('/research/sessions', {'title': 'Independent worktree',
            'goal': 'Keep parallel edits independent', 'modelConnectionRef': self.reference})
        other_path = '/research/sessions/' + other['id']
        second = self.post(other_path + '/git', {'repositoryPath': str(self.repo)})
        self.assertNotEqual(first['workspacePath'], second['workspacePath'])
        self.assertEqual(first['baseCommit'], second['baseCommit'])
        first_root, second_root = Path(first['workspacePath']), Path(second['workspacePath'])
        self.assertEqual((first_root / '中文 文件.py').read_text(), 'value = 1\n')
        self.assertEqual((second_root / '中文 文件.py').read_text(), 'value = 1\n')
        completed = self.turn('git-native-change-marker', 1)
        self.assertEqual(completed['turns'][-1]['status'], 'completed')
        tools = [event['data'].get('toolName') for event in completed['turns'][-1]['events']
                 if event['type'] == 'tool_finished']
        self.assertEqual(tools, ['read_file', 'edit_file', 'write_file', 'run_shell'])
        self.assertEqual((first_root / '中文 文件.py').read_text(), 'value = 2\n')
        self.assertEqual((first_root / 'notes.txt').read_text(), 'native-new-file-marker\n')
        self.assertEqual((second_root / '中文 文件.py').read_text(), 'value = 1\n')
        self.assertFalse((second_root / 'notes.txt').exists())
        self.assertEqual((self.repo / '中文 文件.py').read_text(), 'value = 1\n')
        state = self.get(self.path + '/git')
        self.assertEqual({file['path'] for file in state['files']}, {'中文 文件.py', 'notes.txt'})
        self.assertIn('+value = 2', state['diff'])
        self.assertIn('+native-new-file-marker', state['diff'])
        invalid = self.context.request.post(self.origin + '/api/factory' + self.path + '/git/comments',
            data={'requestId': str(uuid4()), 'reviewId': state['reviewId'], 'path': '中文 文件.py',
                  'side': 'right', 'line': 1000, 'text': 'invalid-anchor'},
            headers={'Origin': self.origin, 'X-Factory-CSRF': self.csrf})
        self.assertEqual(invalid.status, 422, invalid.text())
        (first_root / 'notes.txt').write_text('changed after review\n', encoding='utf-8')
        stale = self.context.request.post(self.origin + '/api/factory' + self.path + '/git/apply',
            data={'reviewId': state['reviewId']}, headers={'Origin': self.origin, 'X-Factory-CSRF': self.csrf})
        self.assertEqual(stale.status, 409, stale.text())
        self.assertEqual((self.repo / '中文 文件.py').read_text(), 'value = 1\n')
        (first_root / 'notes.txt').write_text('native-new-file-marker\n', encoding='utf-8')
        self.page.reload()
        # UI review assertions below use the same real worktree and native run.
        self.check_review_and_apply(state)
        reviewed = self.session()
        self.assertEqual(len(reviewed['turns']), 2)
        self.assertEqual(reviewed['turns'][-1]['status'], 'completed')
        original_turns = reviewed['turns']
        fork = self.post(self.path + '/fork', {'turnId': original_turns[0]['id'], 'title': 'Fork at baseline review'})
        self.assertNotEqual(fork['id'], reviewed['id'])
        fork_git = self.get('/research/sessions/' + fork['id'] + '/git')
        self.assertNotEqual(fork_git['workspacePath'], str(first_root))
        self.assertEqual((Path(fork_git['workspacePath']) / '中文 文件.py').read_text(), 'value = 2\n')
        self.path = '/research/sessions/' + fork['id']
        self.page.goto(self.origin + '/?researchSession=' + fork['id'])
        self.addCleanup(lambda: self.post('/research/sessions/' + fork['id'] + '/stop', {}))
        before = len(self.provider.requests)
        self.post(self.path + '/turns', {'text': 'fork-independent-marker'})
        forked = self.wait_for(lambda row: row['turns'][-1]['completedAt'] is not None)
        self.assertEqual(forked['turns'][-1]['status'], 'completed')
        wire = json.dumps(self.provider.requests[before][0], ensure_ascii=False)
        self.assertIn('git-native-change-marker', wire)
        self.assertIn('git-original-answer-marker', wire)
        self.assertNotIn('git-review-answer-marker', wire)
        self.assertIn('fork-independent-marker', wire)
        self.assertEqual(self.get(original_path)['turns'], original_turns)

    def check_review_and_apply(self, state):
        self.page.get_by_role('button', name='Git 变更', exact=True).click()
        diff = self.page.get_by_label('代码差异', exact=True)
        expect(diff).to_contain_text('+value = 2')
        expect(diff).to_contain_text('native-new-file-marker')
        self.page.get_by_role('button', name='评论 中文 文件.py:1 right', exact=True).click()
        comment = 'line-review-marker: check value on the changed first line'
        self.page.get_by_label('行审查意见', exact=True).fill(comment)
        with self.page.expect_response(lambda response: response.request.method == 'POST'
                                       and response.url.endswith('/git/comments')) as comment_response:
            self.page.get_by_role('button', name='保存行评论', exact=True).click()
        self.assertTrue(comment_response.value.ok, comment_response.value.text())
        expect(self.page.locator('.rs-git-comment').get_by_text(comment, exact=True)).to_be_visible()
        self.page.reload()
        self.page.get_by_role('button', name='Git 变更', exact=True).click()
        expect(self.page.locator('.rs-git-comment').get_by_text(comment, exact=True)).to_be_visible()
        saved = self.get(self.path + '/git/comments')['items']
        self.assertEqual(len(saved), 1)
        self.assertEqual((saved[0]['path'], saved[0]['side'], saved[0]['line']), ('中文 文件.py', 'right', 1))
        before = len(self.provider.requests)
        with self.page.expect_response(lambda response: response.request.method == 'POST'
                                       and response.url.endswith('/git/review')) as submission:
            self.page.get_by_role('button', name='模型审查', exact=True).click()
        self.assertTrue(submission.value.ok, submission.value.text())
        review_request = submission.value.request.post_data_json
        reviewed = self.wait_for(lambda row: len(row['turns']) == 2 and row['turns'][-1]['completedAt'] is not None)
        self.assertEqual(reviewed['turns'][-1]['status'], 'completed')
        wire = json.dumps(self.provider.requests[before][0], ensure_ascii=False)
        self.assertIn(comment, wire)
        self.assertIn('+value = 2', wire)
        self.assertIn('中文 文件.py', wire)
        self.post(self.path + '/git/comments', {'reviewId': state['reviewId'], 'path': '中文 文件.py',
            'side': 'right', 'line': 1, 'text': 'later-comment-marker'})
        repeated = self.post(self.path + '/git/review', review_request)
        self.assertEqual(len(repeated['turns']), 2)
        # A conflicting original edit must survive a rejected application.
        (self.repo / '中文 文件.py').write_text('value = 99\n', encoding='utf-8')
        rejected = self.context.request.post(self.origin + '/api/factory' + self.path + '/git/apply',
            data={'reviewId': state['reviewId']}, headers={'Origin': self.origin, 'X-Factory-CSRF': self.csrf})
        self.assertEqual(rejected.status, 409, rejected.text())
        self.assertEqual((self.repo / '中文 文件.py').read_text(), 'value = 99\n')
        self.assertFalse((self.repo / 'notes.txt').exists())
        (self.repo / '中文 文件.py').write_text('value = 1\n', encoding='utf-8')
        self.page.get_by_role('button', name='应用到原仓库', exact=True).click()
        expect(self.page.get_by_text('变更已应用到原仓库。', exact=True)).to_be_visible()
        self.assertEqual((self.repo / '中文 文件.py').read_text(), 'value = 2\n')
        self.assertEqual((self.repo / 'notes.txt').read_text(), 'native-new-file-marker\n')
        self.assertEqual((Path(self.get(self.path + '/git')['workspacePath']) / '中文 文件.py').read_text(), 'value = 2\n')


def load_tests(loader, tests, pattern):
    return loader.loadTestsFromName('test_worktree_native_diff_review_apply_and_fork', GitJourney)
