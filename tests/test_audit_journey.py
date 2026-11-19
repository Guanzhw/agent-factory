"""Member onboarding, attachments, recovery and cross-page search through real browser routes."""
from base64 import b64decode
from pathlib import Path
from uuid import uuid4
import unittest
from unittest.mock import patch

from playwright.sync_api import expect

from agent_factory.auth import ACCOUNT_ADMIN_ROLE
from test_chat_journey import ChatJourney


class AuditJourney(ChatJourney):
    def test_attachment_from_first_message_and_reply(self):
        self.page.get_by_label('附加文件').set_input_files({
            'name': 'input.csv', 'mimeType': 'text/csv', 'buffer': b'fruit,score\nplum,42\n'})
        self.send('审计附件验收')
        value = self.wait_for(lambda row: row['turns'][-1]['status'] == 'completed')
        image = self.page.get_by_role('img', name='产物')
        expect(image).to_be_visible()
        self.page.wait_for_function("document.querySelector('img[alt=产物]')?.naturalWidth === 1")
        with self.page.expect_download() as download:
            self.page.get_by_role('link', name='原始材料').click()
        self.assertEqual(Path(download.value.path()).read_bytes(), b'fruit,score\nplum,42\n')
        response = self.context.request.post(self.origin + '/api/factory/research/sessions/' + value['id'] + '/files',
            headers={'Origin': self.origin, 'X-Factory-CSRF': self.csrf}, multipart={
                'file': {'name': 'input.csv', 'mimeType': 'text/plain', 'buffer': b'duplicate'}})
        self.assertEqual(response.status, 201)
        self.assertEqual(response.json()['path'], 'input (2).csv')
        self.page.get_by_role('button', name='会话文件', exact=True).click()
        self.page.get_by_role('button', name='刷新文件列表').click()
        panel = self.page.locator('.rs-files')
        png = b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aS1sAAAAASUVORK5CYII=')
        for name, expected in [('input.csv', b'fruit,score\nplum,42\n'), ('input (2).csv', b'duplicate'), ('out.png', png)]:
            with self.page.expect_download() as file:
                panel.get_by_role('link', name=name, exact=True).click()
            self.assertEqual(Path(file.value.path()).read_bytes(), expected)
        fork = self.post('/research/sessions/' + value['id'] + '/fork', {'turnId': value['turns'][0]['id']})
        self.assertFalse(fork['fork']['copiedWorktree'])
        files = self.context.request.get(self.origin + '/api/factory/research/sessions/' + fork['id'] + '/files')
        self.assertEqual(files.json()['files'], [])

    def test_large_preview_reads_each_range_once_and_detects_file_replacement(self):
        self.send('独立文件继续')
        session = self.wait_for(lambda row: row['turns'][-1]['status'] == 'completed')
        workspace = self.state['research_sessions'].workspace(self.owner, session['id'])
        log = workspace / 'large.log'
        contents = 'x' * 65535 + '界' + 'y' * 65533 + '末尾'
        log.write_text(contents, encoding='utf-8')
        self.page.get_by_role('button', name='会话文件', exact=True).click()
        self.page.get_by_role('button', name='刷新文件列表').click()
        row = self.page.locator('.rs-files li').filter(has=self.page.get_by_role('link', name='large.log'))
        ranges = []
        self.page.on('request', lambda r: ranges.append(r.headers.get('range')) if 'download?path=large.log' in r.url else None)
        row.get_by_role('button', name='预览', exact=True).click()
        row.get_by_role('button', name='继续读取').click()
        row.get_by_role('button', name='继续读取').click()
        expect(row.locator('pre')).to_have_text(contents)
        self.assertEqual(ranges, ['bytes=0-65535', 'bytes=65536-131071', 'bytes=131072-196607'])
        row.get_by_role('button', name='关闭预览').click()
        row.get_by_role('button', name='预览', exact=True).click()
        expect(row.get_by_role('button', name='继续读取')).to_be_visible()
        log.write_text('new' * 30000, encoding='utf-8')
        row.get_by_role('button', name='继续读取').click()
        expect(row.get_by_role('alert')).to_contain_text('文件已变化')

    def test_unsent_and_explicit_refusal_keep_editable_text(self):
        path = '**/research/sessions/*/turns'
        self.page.route(path, lambda route: route.abort())
        self.page.get_by_role('textbox', name='研究目标').fill('保留这段首轮草稿')
        self.page.get_by_role('button', name='发送消息', exact=True).click()
        self.page.get_by_role('button', name='重新获取', exact=True).click()
        expect(self.page.get_by_role('alert')).to_contain_text('尚未找到原请求')
        self.page.reload()
        self.page.get_by_role('button', name='停止等待，继续编辑').click()
        editor = self.page.get_by_role('textbox', name='下一轮指令')
        expect(editor).to_have_value('保留这段首轮草稿')
        self.page.unroute(path)
        self.page.route(path, lambda route: route.fulfill(status=409, json={
            'code': 'RESEARCH_MODEL_UNAVAILABLE', 'message': '所选模型连接当前不可用。'}))
        editor.fill('换模型后再发送')
        self.page.get_by_role('button', name='发送', exact=True).click()
        expect(self.page.get_by_role('alert')).to_contain_text('模型连接当前不可用')
        expect(editor).to_be_editable()
        expect(editor).to_have_value('换模型后再发送')
        self.assertEqual(self.session()['turns'], [])

    def test_lost_turn_reply_recovers_once(self):
        self.page.evaluate("""() => {
            const save = Storage.prototype.setItem;
            Storage.prototype.setItem = function(key, value) {
                if (key.startsWith('factory:research-sessions:')) throw new Error('Storage disabled');
                return save.call(this, key, value);
            };
        }""")
        def lose_reply(route):
            self.assertTrue(route.fetch().ok)
            route.abort()
        self.page.route('**/research/sessions/*/turns', lose_reply)
        self.page.get_by_role('textbox', name='研究目标').fill('独立文件继续')
        self.page.get_by_role('button', name='发送消息', exact=True).click()
        self.page.get_by_role('button', name='重新获取', exact=True).click()
        editor = self.page.get_by_role('textbox', name='下一轮指令')
        value = self.wait_for(lambda row: row['turns'][-1]['status'] == 'completed')
        expect(editor).to_be_editable()
        expect(editor).to_have_value('')
        self.assertEqual(len(value['turns']), 1)
        writes = [e for e in value['turns'][0]['events'] if e['type'] == 'tool_finished'
                  and e['data'].get('toolName') == 'write_file']
        self.assertEqual(len(writes), 1)

    def test_member_password_and_model_diagnostics(self):
        self.state['auth'].account_roles.assign(self.owner, ACCOUNT_ADMIN_ROLE)
        self.page.goto(self.origin + '/?tab=accounts')
        member = 'member-' + uuid4().hex
        self.page.get_by_label('账号标识', exact=True).fill(member)
        self.page.get_by_label('初始本地密码').fill('synthetic-first')
        self.page.get_by_role('button', name='新增账号').click()
        expect(self.page.get_by_role('heading', name=member)).to_be_visible()
        editor = self.page.locator('article').filter(has=self.page.get_by_role('heading', name=member))
        def login(password):
            return client.post(self.origin + '/api/factory/auth/local-login',
                headers={'Origin': self.origin}, data={'username': member, 'password': password})
        client = self.playwright.request.new_context(ignore_https_errors=True)
        self.addCleanup(client.dispose)
        self.assertTrue(login('synthetic-first').ok)
        editor.get_by_label('新本地密码').fill('synthetic-second')
        with self.page.expect_response(lambda r: r.request.method == 'PUT') as reset:
            editor.get_by_role('button', name='重置本地密码').click()
        self.assertTrue(reset.value.ok)
        self.assertEqual(login('synthetic-first').status, 401)
        self.assertTrue(login('synthetic-second').ok)
        self.page.get_by_label('登录方式').select_option('directory')
        self.page.get_by_label('账号标识', exact=True).fill(member + '-external')
        self.page.get_by_role('button', name='新增账号').click()
        expect(self.page.get_by_role('heading', name=member + '-external')).to_be_visible()
        denied = self.context.request.put(self.origin + '/api/factory/accounts/' + member + '-external/password',
            headers={'Origin': self.origin, 'X-Factory-CSRF': self.csrf}, data={'password': 'synthetic'})
        self.assertEqual(denied.status, 409)
        self.page.goto(self.origin + '/?tab=models')
        self.page.get_by_role('button', name='验证连接', exact=False).click()
        expect(self.page.get_by_text('此版本最近一次连接验证成功', exact=False)).to_be_visible()
        self.page.goto(self.origin)
        button = self.page.get_by_role('button', name='选择模型', exact=True)
        button.focus()
        button.press('Enter')
        expect(self.page.get_by_role('option', name='regression')).to_be_focused()
        self.page.keyboard.press('Escape')
        expect(button).to_be_focused()

    def test_shared_model_listing_tracks_credential_rotation_and_withdrawal(self):
        models = self.state['store'].personal_models
        colleague = 'colleague-' + uuid4().hex
        self.state['auth'].directory.upsert(colleague, name=colleague)
        credential = models.vault.create(owner=colleague, provider_id='byok-chat-v1',
            destination='https://example.com', username='api-key', password='synthetic')
        values = dict(provider='openai-compatible', baseURL='https://example.com/v1', model='shared',
                      credentialRef=credential['credentialRef'], credentialRevision=credential['credentialRevision'])
        ref = models.configure(colleague, values, str(uuid4()))['reference']

        def visible():
            records = self.context.request.get(self.origin + '/api/factory/personal-models').json()
            return {record['reference']: record for record in records}

        self.assertNotIn(ref, visible())
        models.share(colleague, ref, 'team', str(uuid4()))
        self.post('/personal-models/' + ref + '/default', {})
        shared = visible()[ref]
        self.assertTrue(shared['isDefault'] and shared['available'])
        self.assertNotIn('credentialRef', shared)
        models.vault.rotate(owner=colleague, reference=credential['credentialRef'],
            revision=credential['credentialRevision'], username='api-key', password='rotated-synthetic')
        self.assertFalse(visible()[ref]['available'])
        models.share(colleague, ref, 'personal', str(uuid4()))
        self.assertNotIn(ref, visible())

    def test_list_and_detail_agree_when_submission_is_unconfirmed(self):
        with patch.object(self.state['research_sessions'].runs, 'submit', side_effect=ConnectionError):
            self.send('等待原提交确认')
        detail = self.session()
        items = self.context.request.get(self.origin + '/api/factory/research/sessions').json()['items']
        listed = next(item for item in items if item['id'] == detail['id'])
        self.assertEqual(detail['state'], 'blocked')
        self.assertEqual(listed['state'], detail['state'])

    def test_search_and_recent_activity_across_pages(self):
        api = self.origin + '/api/factory/research/sessions'
        model = self.context.request.get(api + '/options').json()['models'][0]['connectionRef']
        ids = [self.post('/research/sessions', {'title': f'历史记录 {i:02d}', 'goal': 'history',
               'modelConnectionRef': model})['id'] for i in range(40)]
        page = self.context.request.get(api).json()
        self.assertEqual([s['id'] for s in page['items']], list(reversed(ids[20:])))
        second = self.context.request.get(api, params={'after': page['nextCursor']}).json()
        self.assertEqual([s['id'] for s in second['items']], list(reversed(ids[:20])))
        self.post('/research/sessions/' + ids[0] + '/stop', {})
        self.assertEqual(self.context.request.get(api).json()['items'][0]['id'], ids[0])
        self.page.get_by_label('搜索会话').fill('记录 02')
        expect(self.page.get_by_role('button', name='历史记录 02', exact=False)).to_be_visible()


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(AuditJourney(name) for name in AuditJourney.__dict__ if name.startswith('test_'))
