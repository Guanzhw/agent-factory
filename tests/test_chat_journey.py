"""Browser journeys and focused regressions; no external services are required."""
import ast
import asyncio
import datetime
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import json
import os
from pathlib import Path
import secrets
import re
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import AsyncMock, patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, ed25519
from cryptography.x509.oid import NameOID
from playwright.sync_api import sync_playwright, expect
from sqlalchemy import create_engine, make_url, text
import uvicorn

from agent_factory.config import Settings
from agent_factory.byok_model import OwnerChatModel
from agent_factory._personal_cli_process import CLIProcessError, CLIProcessResult
from agno.compression.manager import CompressionManager
from agno.models.message import Message
from fastapi import HTTPException
from agent_factory_server.main import factory_state
from agent_factory_server.research import create_app
from research.session_tools import ResearchSessionTools, _directory, _open_file

DOCUMENT = '状态：初稿\n' + '研究结果：文件内容保持完整。\n' * 2000
PRESENTATION = "### 聊天呈现\n\n| 项目 | 状态 |\n| --- | --- |\n| Markdown | 可读 |\n\n```python\nprint('中文验收')  # " + 'long ' * 40 + '\n```\n\n```\n\n```\n\n' + '\n\n'.join(f'第 {i} 段：保留历史阅读位置，同时提供回到底部。' for i in range(60))


class ModelEndpoint(BaseHTTPRequestHandler):
    """Speak actual Chat Completions SSE, without replacing application/tool code."""
    def log_message(self, *_):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append(request)
        names = {call['id']: call['function']['name'] for message in request['messages']
                 for call in message.get('tool_calls', [])}
        results = [(names.get(m.get('tool_call_id')), m.get('content'))
                   for m in request['messages'] if m['role'] == 'tool']
        system = '\n'.join(m['content'] for m in request['messages'] if m['role'] == 'system')
        user_text = next((m['content'] for m in reversed(request['messages']) if m['role'] == 'user'), '')
        tool, arguments, reply = None, {}, '任务完成，结果可下载。\n\n| 结果 | 状态 |\n| --- | --- |\n| 工具 | 已完成 |'
        if request['model'] == 'compression':
            reply = '压缩摘要：数值42'
        elif user_text == '思考与内容顺序验收':
            if not results:
                tool, arguments = 'research_edit_file', {'path': 'ordered.txt', 'old': '', 'new': '顺序工具结果'}
            reply = '顺序验收最终回答。'
        elif user_text.startswith('共享资料验收:'):
            if not results:
                tool, arguments = 'research_read_shared_evidence', {'content_id': user_text.split(':', 1)[1]}
            reply = 'derived-source-marker: Shared evidence says source-secret-marker.'
        elif '独立文件继续' in user_text:
            if not results:
                tool, arguments = 'research_edit_file', {'path': 'independent-source.txt', 'old': '', 'new': 'independent-source-result'}
            reply = '独立文件已写入。'
        elif '切换模型后继续' in user_text:
            reply = '切换模型后完成。'
        elif user_text == '聊天呈现验收':
            reply = PRESENTATION
        elif user_text in {'ssh 可用了吗?', '再看一下 SSH 状态'}:
            if not results:
                tool = 'ssh_servers'
            reply = '已找到配置的 SSH 服务器；本轮只查询配置，连接状态尚未探测。'
        elif user_text in {'SSH 断线回执验收', 'SSH 空命令验收', 'SSH 启动失败验收', 'SSH 派发异常验收', 'SSH 取消验收', 'SSH 准备失败验收', 'SSH 清理失败验收', 'SSH 参数缺失验收'}:
            if not results:
                tool = 'ssh_servers'
            elif len(results) == 1:
                tool, arguments = 'ssh_run', {'reference': ast.literal_eval(results[0][1])[0]['reference'],
                                             'argv': [] if user_text == 'SSH 空命令验收' else ['pwd']}
                if user_text == 'SSH 参数缺失验收':
                    del arguments['argv']
            reply = 'SSH 结果未确认，需要核对原命令。'
        elif '"goal": "child-only"' in system:
            if not results:
                tool, arguments = 'research_edit_file', {'path': 'child.txt', 'old': '', 'new': '子助手已完成'}
            reply = '子助手已完成'
        elif 'unknown-followup' in json.dumps(request['messages']):
            reply = '后续分析完成，原操作仍待核对。'
        elif 'unknown-journey-case' in system:
            steps = [('uncertain_cli', {'arguments': {}}),
                     ('research_edit_file', {'path': 'independent.txt', 'old': '', 'new': '独立任务完成'}),
                     ('research_read_file', {'path': 'independent.txt'})]
            if len(results) < len(steps):
                tool, arguments = steps[len(results)]
            reply = '独立工作已完成，原操作仍待核对。'
        elif 'skills-stop-case' in system:
            if not results:
                tool, arguments = 'get_skill_script', {'skill_name': 'journey-skill',
                    'script_path': 'nested/runner.py', 'execute': True, 'args': ['stop']}
        elif 'skills-journey-case' in system:
            steps = [('get_skill_instructions', {'skill_name': 'journey-skill'}),
                     ('get_skill_reference', {'skill_name': 'journey-skill', 'reference_path': 'nested/guide.md'}),
                     ('get_skill_script', {'skill_name': 'journey-skill', 'script_path': 'nested/runner.py'}),
                     ('get_skill_script', {'skill_name': 'journey-skill', 'script_path': 'nested/runner.py',
                         'execute': True, 'args': ['fail', 'argument with spaces', '中文']}),
                     ('get_skill_script', {'skill_name': 'journey-skill', 'script_path': 'nested/runner.py',
                         'execute': True, 'args': ['success', 'argument with spaces', '中文'], 'cwd': 'skill-work'})]
            if len(results) < len(steps):
                tool, arguments = steps[len(results)]
            elif len(results) == len(steps):
                tool, arguments = 'get_skill_script', {'skill_name': 'journey-skill',
                    'script_path': 'nested/runner.py', 'execute': True, 'args': ['resource'],
                    'cwd': json.loads(results[0][1])['source_path']}
            reply = '技能脚本完成，失败诊断已处理。'
        elif 'stop-case' in system:
            if not results:
                tool, arguments = 'research_run', {'argv': [sys.executable, '-c',
                    "import os,time; from pathlib import Path; Path('started.txt').write_text(str(os.getpid())); time.sleep(600)"]}
        else:
            steps = [('demo_cli', {'arguments': {'mode': 'fail'}}), ('demo_cli', {'arguments': {'mode': 'ok'}}), ('ssh_servers', {}),
                     ('research_edit_file', {'path': '结果.txt', 'old': '', 'new': DOCUMENT}),
                     ('research_edit_file', {'path': '结果.txt', 'old': '状态：初稿', 'new': '状态：已复核'}),
                     ('research_delegate', {'goal': 'child-only'})]
            if len(results) < len(steps):
                tool, arguments = steps[len(results)]
            elif len(results) == len(steps):
                tool, arguments = 'research_wait_child', {'childTaskId': ast.literal_eval(results[-1][1])['childTaskId']}
        delta = {'role': 'assistant', 'content': '正在执行任务。' if tool else reply}
        if tool:
            delta['tool_calls'] = [{'index': 0, 'id': 'call_' + uuid4().hex, 'type': 'function',
                                   'function': {'name': tool, 'arguments': json.dumps(arguments, ensure_ascii=False)}}]
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        changes = [(delta, None), ({}, 'tool_calls' if tool else 'stop')]
        if user_text == '思考与内容顺序验收':
            changes = [({'role': 'assistant', 'reasoning_content': '先核对' if tool else '收到工具'}, None),
                       ({'reasoning_content': '工具参数。' if tool else '结果后继续。'}, None),
                       ({**delta, 'content': '即将写入顺序文件。' if tool else reply}, None),
                       ({}, 'tool_calls' if tool else 'stop')]
            if not tool:
                changes[2:3] = [({'content': '顺序验收'}, None),
                                ({'reasoning_content': '再核对最终输出。'}, None),
                                ({'content': '最终回答。'}, None)]
        for change, finish in changes:
            chunk = {'id': 'completion', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'regression',
                     'choices': [{'index': 0, 'delta': change, 'finish_reason': finish}]}
            self.wfile.write(('data: ' + json.dumps(chunk, ensure_ascii=False) + '\n\n').encode())
            self.wfile.flush()
            if user_text == '思考与内容顺序验收' and change.get('reasoning_content') == '再核对最终输出。':
                self.server.reasoning_pause.wait()
        self.wfile.write(b'data: [DONE]\n\n')


class ChatJourney(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Always create a new database. Never initialize or clear the supplied database.
        admin_url = make_url(os.environ['FACTORY_TEST_DATABASE_URL'])
        cls.admin = create_engine(admin_url, isolation_level='AUTOCOMMIT')
        cls.database = 'factory_regression_' + uuid4().hex
        with cls.admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE {cls.database}'))
        def drop_database():
            with cls.admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE {cls.database} WITH (FORCE)'))
            cls.admin.dispose()
        cls.addClassCleanup(drop_database)
        cls.folder = tempfile.TemporaryDirectory(prefix='factory-regression-')
        cls.addClassCleanup(cls.folder.cleanup)
        root = Path(cls.folder.name)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
        now = datetime.datetime.now(datetime.UTC)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
                .not_valid_after(now + datetime.timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), False)
                .sign(key, hashes.SHA256()))
        (root / 'cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (root / 'key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        cls.model = ThreadingHTTPServer(('127.0.0.1', 0), ModelEndpoint)
        cls.model.requests = []
        threading.Thread(target=cls.model.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.model.server_close)
        cls.addClassCleanup(cls.model.shutdown)
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        cls.addClassCleanup(listener.close)
        cls.origin = f'https://127.0.0.1:{listener.getsockname()[1]}'
        settings = Settings(db_url=admin_url.set(database=cls.database).render_as_string(hide_password=False),
                            jwt_key=secrets.token_urlsafe(40), workspace=root, local_login_origin=cls.origin)
        (root / 'research').mkdir()
        skill = root / 'external-skills' / 'journey-skill'
        (skill / 'references' / 'nested').mkdir(parents=True)
        (skill / 'scripts' / 'nested').mkdir(parents=True)
        (skill / 'SKILL.md').write_text('---\nname: journey-skill\ndescription: Exercise external skill resources.\n'
            'custom-client-field: accepted\n---\nRead references/nested/guide.md and run scripts/nested/runner.py.\n')
        (skill / 'references' / 'nested' / 'guide.md').write_text('Nested reference marker: 42.\n')
        (skill / 'asset.txt').write_text('External skill asset: 73.\n')
        (skill / 'scripts' / 'nested' / 'runner.py').write_text(
            '#!/usr/bin/env -S python3 -O\nimport json, os, sys, time\nfrom pathlib import Path\n'
            'mode = sys.argv[1]\n'
            'if mode == "resource":\n'
            '    print(json.dumps({"asset": Path("asset.txt").read_text(), "cwd": str(Path.cwd())}))\n    sys.exit(0)\n'
            'if mode == "stop":\n'
            '    Path("skills-started.txt").write_text(str(os.getpid()))\n    time.sleep(600)\n'
            'if mode == "fail":\n'
            '    Path("skill-work").mkdir()\n    print("skill diagnostic", file=sys.stderr)\n'
            '    print(json.dumps({"args": sys.argv[2:], "cwd": str(Path.cwd())}))\n    sys.exit(7)\n'
            'time.sleep(31)\n'
            'result = json.dumps({"args": sys.argv[2:], "cwd": str(Path.cwd()), "finished": True, "optimize": sys.flags.optimize})\n'
            'Path("skill-result.json").write_text(result)\nprint(result)\n')
        with patch.dict(os.environ, FACTORY_SKILL_PATHS=str(skill.parent)):
            cls.app = create_app(settings, session_tools=ResearchSessionTools(workspace_root=root / 'research'))
        cls.state = factory_state(cls.app)
        cls.server = uvicorn.Server(uvicorn.Config(cls.app, ssl_certfile=str(root / 'cert.pem'),
            ssl_keyfile=str(root / 'key.pem'), log_level='warning', access_log=False,
            timeout_graceful_shutdown=35))
        thread = threading.Thread(target=lambda: cls.server.run(sockets=[listener]), daemon=True)
        thread.start()
        def shutdown():
            cls.server.should_exit = True
            # Match the production transport budget, then allow application cleanup.
            thread.join(75)
            if thread.is_alive():
                raise RuntimeError('Application did not stop')
            if (not cls.server.lifespan.shutdown_event.is_set() or cls.server.lifespan.error_occurred
                    or cls.server.lifespan.shutdown_failed):
                raise RuntimeError('Application lifespan shutdown failed')
        cls.addClassCleanup(shutdown)
        deadline = time.monotonic() + 30
        while not cls.server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError('Application did not start')
            time.sleep(0.05)
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch()
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.owner = 'user-' + uuid4().hex
        password = secrets.token_urlsafe(20)
        self.state['browser_auth'].local_passwords.create(self.owner, password)
        self.context = self.browser.new_context(ignore_https_errors=True, accept_downloads=True,
                                                viewport={'width': 1280, 'height': 900})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.goto(self.origin)
        self.page.get_by_label('用户名', exact=True).fill(self.owner)
        self.page.get_by_label('密码', exact=True).fill(password)
        self.page.get_by_role('button', name='登录', exact=True).click()
        expect(self.page.get_by_role('heading', name='今天想一起完成什么？')).to_be_visible()
        self.csrf = self.context.request.get(self.origin + '/api/factory/auth/session').json()['csrfToken']
        self.page.get_by_role('button', name='配置我的模型', exact=True).click()
        self.page.get_by_label('模型提供方', exact=True).select_option('openai-compatible')
        self.page.get_by_label('模型名称', exact=True).fill('regression')
        self.page.get_by_label('API 端点', exact=True).fill(f'http://127.0.0.1:{self.model.server_port}/v1')
        self.page.get_by_label('模型凭据来源', exact=True).select_option('none')
        self.page.get_by_role('button', name='保存并设为默认', exact=True).click()
        expect(self.page.get_by_text('默认模型', exact=True)).to_be_visible()
        self.page.get_by_role('button', name=re.compile('^返回')).click()
        expect(self.page.get_by_role('button', name='选择模型', exact=True)).to_contain_text('regression')

    def post(self, path, body):
        response = self.context.request.post(self.origin + '/api/factory' + path,
            data={'requestId': str(uuid4()), **body}, headers={'Origin': self.origin, 'X-Factory-CSRF': self.csrf})
        self.assertTrue(response.ok, f'{response.status}: {response.text()}')
        return response.json()

    def session(self):
        from urllib.parse import parse_qs, urlsplit
        identifier = parse_qs(urlsplit(self.page.url).query)['researchSession'][0]
        return self.context.request.get(self.origin + '/api/factory/research/sessions/' + identifier).json()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            snapshot = self.session()
            if snapshot['turns'] and predicate(snapshot):
                return snapshot
            self.page.wait_for_timeout(100)
        self.fail('Timed out: ' + json.dumps(snapshot, ensure_ascii=False)[-3000:])

    def send(self, goal):
        self.page.get_by_role('textbox', name=re.compile('^研究目标')).fill(goal)
        with self.page.expect_response(lambda response: response.request.method == 'POST'
                                       and response.url.endswith('/turns')) as submitted:
            self.page.get_by_role('button', name='发送消息', exact=True).click()
        self.assertTrue(submitted.value.ok, submitted.value.text())
        self.page.wait_for_url('**/*researchSession=*')
        identifier = self.session()['id']
        self.addCleanup(lambda: self.post('/research/sessions/' + identifier + '/stop', {}))

    def test_revoked_source_keeps_history_but_new_turn_has_clean_model_context(self):
        from agent_factory.application_content import ContentPublication, ContentSource
        from research import session_context
        content = self.state['application_content']
        publisher = 'publisher-' + uuid4().hex
        self.state['browser_auth'].local_passwords.create(publisher, secrets.token_urlsafe(20))
        source = content.publish(publisher, ContentPublication(
            source=ContentSource(application='research', record='source-fixture', revision='1'),
            content={'observation': 'source-secret-marker'}, visibility='team'), str(uuid4()))
        self.send('共享资料验收:' + source['id'])
        completed = self.wait_for(lambda value: value['turns'][-1]['status'] == 'completed')
        self.assertIn('derived-source-marker', completed['turns'][0]['result'])
        service = self.state['research_sessions']
        # Persist representative old correction/summary records; the provider path is real.
        with service._write() as conn:
            row = service._row(conn, self.owner, completed['id'])
            turns = service._turns(conn, row['id'])
            turn = turns[0]
            body = {**turn['body'], 'messages': [*turn['body']['messages'],
                service._message('correction', 'source-correction-marker')]}
            service._save_turn(conn, turn, body)
            turns = [{**turn, 'body': body}]
            _, identity = session_context.summary_source(row, turns)
            service._save_session(conn, row, {**row['body'], 'contextCheckpoint': {
                **identity, 'summary': {'summary': 'source-summary-marker', 'topics': []}}})
        content.set_visibility(publisher, source['id'], 'personal', str(uuid4()))
        snapshot = self.session()
        self.assertIn('start', snapshot['allowedActions'])
        self.assertNotEqual(snapshot['state'], 'blocked')
        self.page.reload()
        expect(self.page.get_by_text(re.compile('旧共享来源或助手回答已不可用'))).to_be_visible()
        requests_before = len(self.model.requests)
        path = '/research/sessions/' + snapshot['id'] + '/turns'
        request = {'requestId': str(uuid4()), 'text': '独立文件继续'}
        self.post(path, request)
        continued = self.wait_for(lambda value: len(value['turns']) == 2 and value['turns'][-1]['status'] == 'completed')
        sent = json.dumps(self.model.requests[requests_before:], ensure_ascii=False)
        for marker in ('source-secret-marker', 'derived-source-marker', 'source-correction-marker', 'source-summary-marker'):
            self.assertNotIn(marker, sent)
        self.assertIn('独立文件继续', sent)
        self.assertEqual((service.workspace(self.owner, snapshot['id']) / 'independent-source.txt').read_text(),
                         'independent-source-result')
        self.assertIn('derived-source-marker', continued['turns'][0]['result'])
        self.post(path, request)
        self.page.reload()
        self.assertEqual(len(self.session()['turns']), 2)
        with service.db.read() as conn:
            row = service._row(conn, self.owner, snapshot['id'])
            turns = service._turns(conn, row['id'])
            summary, _ = session_context.summary_source(row, turns)
        self.assertNotIn('source-', json.dumps(summary))
        with self.assertRaises(HTTPException):
            content.read(self.owner, source['id'])

    def test_source_revoked_during_run_fails_only_that_run_then_allows_new_turn(self):
        from agent_factory.application_content import ContentPublication, ContentSource
        service, content = self.state['research_sessions'], self.state['application_content']
        publisher = 'publisher-' + uuid4().hex
        self.state['browser_auth'].local_passwords.create(publisher, secrets.token_urlsafe(20))
        source = content.publish(publisher, ContentPublication(
            source=ContentSource(application='research', record='active-source', revision='1'),
            content={'observation': 'source-secret-marker'}, visibility='team'), str(uuid4()))
        record_source = service.record_source
        def revoke_after_read(context, identifier):
            record_source(context, identifier)
            content.set_visibility(publisher, identifier, 'personal', str(uuid4()))
        before = len(self.model.requests)
        with patch.object(service, 'record_source', side_effect=revoke_after_read):
            self.send('共享资料验收:' + source['id'])
            failed = self.wait_for(lambda value: value['turns'][-1]['status'] == 'failed'
                                   and value['turns'][-1]['completedAt'] is not None)
        self.assertIn('start', failed['allowedActions'])
        self.assertIn('共享来源已不可读', failed['turns'][-1]['failure'])
        self.assertEqual(len(self.model.requests) - before, 1)
        self.post('/research/sessions/' + failed['id'] + '/turns', {'text': '切换模型后继续'})
        finished = self.wait_for(lambda value: len(value['turns']) == 2 and value['turns'][-1]['status'] == 'completed')
        self.assertIn('切换模型后完成', finished['turns'][-1]['result'])
        self.assertNotIn('source-secret-marker', json.dumps(self.model.requests[before:], ensure_ascii=False))

    def test_native_tool_compression_checks_source_before_provider_request(self):
        from agent_factory.application_content import ContentPublication, ContentSource
        content = self.state['application_content']
        publisher = 'publisher-' + uuid4().hex
        self.state['browser_auth'].local_passwords.create(publisher, secrets.token_urlsafe(20))
        source = content.publish(publisher, ContentPublication(
            source=ContentSource(application='research', record='compressed-source', revision='1'),
            content={'observation': 'source-secret-marker'}, visibility='team'), str(uuid4()))
        model = self.post('/personal-models', {'provider': 'openai-compatible', 'model': 'source-compression',
            'baseURL': f'http://127.0.0.1:{self.model.server_port}/v1', 'autoCompactTokenLimit': 1})
        self.post('/personal-models/' + model['reference'] + '/default', {})
        self.page.reload()
        self.page.get_by_role('button', name='选择模型', exact=True).click()
        self.page.get_by_role('option', name='source-compression', exact=True).click()
        native_compress, attempts = CompressionManager.acompress, []
        async def revoke_before_compression(manager, messages, **kwargs):
            if any(message.role == 'tool' and 'source-secret-marker' in str(message.content) for message in messages):
                attempts.append(True)
                await asyncio.to_thread(content.set_visibility, publisher, source['id'], 'personal', str(uuid4()))
            return await native_compress(manager, messages, **kwargs)
        before = len(self.model.requests)
        with patch.object(CompressionManager, 'acompress', new=revoke_before_compression):
            self.send('共享资料验收:' + source['id'])
            self.assertEqual(self.session()['model']['connectionRef'], model['connectionRef'])
            self.assertEqual(self.session()['model']['autoCompactTokenLimit'], 1)
            failed = self.wait_for(lambda value: value['turns'][-1]['status'] == 'failed'
                                   and value['turns'][-1]['completedAt'] is not None)
        self.assertEqual(attempts, [True])
        self.assertEqual(len(self.model.requests) - before, 1)
        self.assertNotIn('source-secret-marker', json.dumps(self.model.requests[before:], ensure_ascii=False))
        self.assertIn('start', failed['allowedActions'])
        self.assertIn('共享来源已不可读', failed['turns'][-1]['failure'])

    def test_initial_stream_refresh_disconnect_and_missing_session(self):
        requests = []
        self.page.on('request', lambda request: requests.append((request.method, request.url)))
        self.send('切换模型后继续')
        snapshot = self.wait_for(lambda value: value['turns'][-1]['status'] == 'completed')
        identifier, address = snapshot['id'], self.page.url
        endpoint = self.origin + '/api/factory/research/sessions/' + identifier
        expect(self.page.locator('.rs-turn')).to_contain_text('切换模型后完成。')
        self.page.reload()
        expect(self.page.locator('.rs-turn')).to_contain_text('切换模型后完成。')
        self.assertNotIn(('GET', endpoint), requests)
        self.page.get_by_role('button', name='刷新会话', exact=True).click()
        expect(self.page.get_by_role('textbox', name='下一轮指令', exact=True)).to_be_visible()
        failed = []
        def disconnect(route):
            if len(failed) < 2:
                failed.append(True)
                if len(failed) == 1:
                    route.fulfill(status=503, json={'detail': 'temporary fixture outage'})
                else:
                    route.abort()
            else:
                route.continue_()
        self.page.route(endpoint + '/events', disconnect)
        self.page.reload()
        expect(self.page.locator('.rs-connection')).to_contain_text('正在重连')
        expect(self.page.locator('.rs-turn')).to_contain_text('切换模型后完成。')
        self.page.unroute(endpoint + '/events', disconnect)
        self.page.goto(address.replace(identifier, str(uuid4())))
        expect(self.page.locator('main').get_by_role('alert')).to_have_text('会话不存在或已不可访问。')
        expect(self.page.get_by_role('textbox', name='下一轮指令', exact=True)).to_have_count(0)
        self.page.goto(address)
        expect(self.page.locator('.rs-turn')).to_contain_text('切换模型后完成。')
        self.page.route(endpoint + '/events', lambda route: route.fulfill(status=401, json={'detail': 'expired'}))
        self.page.reload()
        expect(self.page.get_by_label('用户名', exact=True)).to_be_visible()
        expect(self.page.locator('.rs-turn')).to_have_count(0)

    def test_delayed_initial_stream_cannot_replace_a_new_turn_or_session(self):
        self.send('切换模型后继续')
        snapshot = self.wait_for(lambda value: value['turns'][-1]['status'] == 'completed')
        endpoint = self.origin + '/api/factory/research/sessions/' + snapshot['id'] + '/events'
        held = []
        def delay(route):
            if not held:
                held.append(route)
            else:
                route.continue_()
        def await_request():
            deadline = time.monotonic() + 5
            while not held and time.monotonic() < deadline:
                self.page.wait_for_timeout(20)
            self.assertEqual(len(held), 1)
        def release():
            await_request()
            held[0].fulfill(content_type='text/event-stream', body='event: session\ndata: ' +
                json.dumps(snapshot, ensure_ascii=False) + '\n\n')
        self.page.route(endpoint, delay)
        self.page.reload()
        expect(self.page.get_by_text('正在读取会话详情…', exact=True)).to_be_visible()
        expect(self.page.get_by_role('textbox', name='下一轮指令', exact=True)).to_have_count(0)
        release()
        expect(self.page.get_by_role('textbox', name='下一轮指令', exact=True)).to_be_visible()
        held.clear()
        self.page.get_by_role('button', name='刷新会话', exact=True).click()
        await_request()
        self.page.get_by_role('textbox', name='下一轮指令', exact=True).fill('切换模型后继续')
        self.page.get_by_role('button', name='发送', exact=True).click()
        self.wait_for(lambda value: len(value['turns']) == 2 and value['turns'][-1]['status'] == 'completed')
        release()
        expect(self.page.locator('.rs-turn')).to_have_count(2)
        held.clear()
        self.page.get_by_role('button', name='刷新会话', exact=True).click()
        await_request()
        self.page.get_by_role('button', name='新建会话', exact=True).click()
        release()
        expect(self.page.get_by_role('heading', name='今天想一起完成什么？')).to_be_visible()
        expect(self.page.locator('.rs-turn')).to_have_count(0)

    def test_chat_tools_files_and_child(self):
        self.post('/personal-tools/resources', {'transport': 'cli', 'toolName': 'demo_cli',
            'description': 'Diagnostic CLI', 'executable': sys.executable,
            'arguments': ['-c', 'import json,sys; v=json.load(sys.stdin); print("diagnostic" if v["mode"]=="fail" else json.dumps({"ok":True})); print("problem",file=sys.stderr); sys.exit(7 if v["mode"]=="fail" else 0)'],
            'inputSchema': {'type': 'object', 'properties': {'mode': {'type': 'string'}}, 'required': ['mode']}})
        server = self.configure_ssh()
        self.page.get_by_role('textbox', name=re.compile('^研究目标')).fill('保留这份草稿')
        self.page.get_by_role('button', name='选择模型', exact=True).click()
        self.page.get_by_role('button', name='管理模型', exact=True).click()
        self.page.get_by_role('button', name=re.compile('^返回')).click()
        expect(self.page.get_by_role('textbox', name=re.compile('^研究目标'))).to_have_value('保留这份草稿')
        self.send('完成工具任务并使用子助手')
        snapshot = self.wait_for(lambda s: s['turns'][-1]['status'] in {'completed', 'failed', 'unknown', 'cancelled'})
        self.assertEqual(snapshot['turns'][-1]['status'], 'completed', snapshot)
        turn = snapshot['turns'][-1]
        outputs = [e['data']['output'] for e in turn['events'] if e['type'] == 'tool_finished']
        self.assertIn({'exitCode': 7, 'stdout': 'diagnostic' + os.linesep, 'stderr': 'problem' + os.linesep}, outputs)
        self.assertIn({'ok': True}, outputs)
        self.assertEqual(len(turn['children']), 1)
        self.assertEqual(turn['children'][0]['status'], 'completed')
        self.assertIn('子助手已完成', turn['children'][0]['result'])
        edits = [e for e in turn['events'] if e['type'] == 'research_tool_finished'
                 and e['data'].get('toolName') == 'research_edit_file']
        self.assertTrue(edits, turn['events'])
        self.assertTrue(all(e['data']['outcome'] == 'completed' for e in edits), edits)
        # The next real HTTP model request must contain the tool's discovered server.
        self.assertTrue(any(server['reference'] in json.dumps(r['messages']) for r in self.model.requests))
        command = next(tool['function'] for request in reversed(self.model.requests)
            for tool in request.get('tools', []) if tool['function']['name'] == 'research_run')
        self.assertIn(sys.platform, command['description'])
        self.assertIn(sys.executable, command['description'])
        self.assertTrue(any(e['type'] == 'model_content_delta' for e in turn['events']))
        requests_before_refresh = len(self.model.requests)
        self.page.reload()
        expect(self.page.locator('.rs-turn > .rs-reply').get_by_text('任务完成，结果可下载。', exact=False)).to_be_visible()
        expect(self.page.locator('.rs-child-preview')).to_have_count(1)
        expect(self.page.locator('.rs-active-children')).to_have_count(0)
        self.page.locator('.rs-child-result > summary').click()
        expect(self.page.locator('.rs-child-result').get_by_text('子助手已完成', exact=False)).to_be_visible()
        self.page.locator('.rs-child-result > summary').click()
        expect(self.page.locator('#rs-file-panel')).to_be_hidden()
        self.page.get_by_role('button', name='会话文件', exact=True).click()
        with self.page.expect_download() as download:
            self.page.get_by_role('link', name='结果.txt', exact=True).click()
        self.assertEqual(download.value.suggested_filename, '结果.txt')
        expected_bytes = DOCUMENT.replace('状态：初稿', '状态：已复核').replace('\n', os.linesep).encode()
        self.assertEqual(Path(download.value.path()).read_bytes(), expected_bytes)
        workspace = self.state['store'].research_sessions.workspace(self.owner, snapshot['id'])
        self.assertEqual((workspace / '结果.txt').read_bytes(), expected_bytes)
        self.assertEqual((workspace / 'child.txt').read_text(encoding='utf-8'), '子助手已完成')
        preview_url = re.compile('/files/download\\?path=' + re.escape(quote('结果.txt')) + '$')
        pending_preview = []
        self.page.route(preview_url, lambda route: pending_preview.append(route))
        with self.page.expect_request(preview_url):
            self.page.locator('.rs-files li').filter(has=self.page.get_by_role('link', name='结果.txt', exact=True)).get_by_role('button', name='预览', exact=True).click()
        self.page.locator('.rs-files li').filter(has=self.page.get_by_role('link', name='child.txt', exact=True)).get_by_role('button', name='预览', exact=True).click()
        expect(self.page.locator('.rs-file-preview')).to_have_text('子助手已完成')
        pending_preview[0].fulfill(content_type='application/octet-stream', body='过期预览不得覆盖当前文件')
        expect(self.page.locator('.rs-file-preview')).to_have_text('子助手已完成')
        self.page.unroute(preview_url)
        self.page.get_by_role('button', name='关闭预览', exact=True).click()
        sibling = Path(str(workspace) + '-neighbor')
        sibling.mkdir()
        (sibling / 'outside.txt').write_text('outside this session')
        if sys.platform == 'win32':
            import _winapi
            _winapi.CreateJunction(str(sibling), str(workspace / 'escape'))
        else:
            (workspace / 'escape').symlink_to(sibling, target_is_directory=True)
        download_url = self.origin + '/api/factory/research/sessions/' + snapshot['id'] + '/files/download'
        for path in ('../' + sibling.name + '/outside.txt', str(sibling / 'outside.txt'), 'escape/outside.txt'):
            with self.subTest(download=path):
                self.assertEqual(self.context.request.get(download_url, params={'path': path}).status, 404)
        normalized = self.context.request.get(download_url, params={'path': 'unused/../结果.txt'})
        self.assertEqual(normalized.body(), expected_bytes)
        blocked = workspace / '不可读实验目录'
        blocked.mkdir()
        (blocked / 'hidden.txt').write_text('not listable')
        if sys.platform == 'win32':
            import ntsecuritycon
            import win32api
            import win32security
            original_acl = win32security.GetNamedSecurityInfo(str(blocked), win32security.SE_FILE_OBJECT,
                win32security.DACL_SECURITY_INFORMATION).GetSecurityDescriptorDacl()
            user_sid = win32security.LookupAccountName(None, win32api.GetUserName())[0]
            denied_acl = win32security.ACL()
            denied_acl.AddAccessDeniedAce(win32security.ACL_REVISION, ntsecuritycon.FILE_LIST_DIRECTORY, user_sid)
            denied_acl.AddAccessAllowedAce(win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, user_sid)
        try:
            if sys.platform == 'win32':
                win32security.SetNamedSecurityInfo(str(blocked), win32security.SE_FILE_OBJECT,
                    win32security.DACL_SECURITY_INFORMATION, None, None, denied_acl, None)
            else:
                blocked.chmod(0)
            with self.assertRaises(PermissionError):
                with os.scandir(blocked) as entries:
                    list(entries)
            response = self.context.request.get(download_url.removesuffix('/download'))
            self.assertEqual(response.status, 200)
            self.assertIn('结果.txt', [file['path'] for file in response.json()['files']])
            self.assertEqual([issue['path'] for issue in response.json()['errors']], [blocked.name])
            reason = response.json()['errors'][0]['message']
            self.assertTrue(reason)
            self.page.get_by_role('button', name='刷新文件列表', exact=True).click()
            expect(self.page.locator('.rs-files [role="alert"]')).to_contain_text(blocked.name)
            expect(self.page.locator('.rs-files [role="alert"]')).to_contain_text(reason)
            expect(self.page.locator('.rs-files').get_by_text('还没有生成文件。', exact=True)).to_have_count(0)
            with self.page.expect_download() as partial_download:
                self.page.get_by_role('link', name='结果.txt', exact=True).click()
            self.assertEqual(Path(partial_download.value.path()).read_bytes(), expected_bytes)
            self.page.screenshot(path=str(Path(self.folder.name) / 'partial-files.png'), full_page=True)
            next_session = self.post('/research/sessions', {'title': '文件列表切换验收', 'goal': '尚未执行',
                'boundaries': '', 'modelConnectionRef': snapshot['model']['connectionRef']})
            self.page.get_by_role('button', name='刷新会话', exact=True).click()
            pending = []
            next_files = '**/research/sessions/' + next_session['id'] + '/files'
            self.page.route(next_files, lambda route: pending.append(route))
            with self.page.expect_request(next_files):
                self.page.get_by_role('button', name=re.compile('^文件列表切换验收')).click()
            expect(self.page.get_by_role('heading', name='文件列表切换验收', exact=True)).to_be_visible()
            expect(self.page.locator('#rs-file-panel')).to_be_hidden()
            self.page.get_by_role('button', name='会话文件', exact=True).click()
            file_panel = self.page.locator('.rs-files')
            expect(file_panel.get_by_role('status')).to_have_text('正在读取文件…')
            expect(file_panel.get_by_role('link')).to_have_count(0)
            expect(file_panel.get_by_role('alert')).to_have_count(0)
            expect(file_panel.get_by_text('还没有生成文件。', exact=True)).to_have_count(0)
            self.assertEqual(len(pending), 1)
            pending[0].fulfill(status=503, json={'detail': '文件列表读取失败验收'})
            expect(file_panel.get_by_role('alert')).to_have_text('文件列表读取失败验收')
            self.page.get_by_role('button', name='关闭会话文件', exact=True).click()
            expect(self.page.locator('.rs-detail-body > .rs-panel-warning')).to_contain_text('部分会话文件无法读取')
            expect(self.page.locator('#rs-file-panel')).to_be_hidden()
            self.page.get_by_role('button', name='查看文件问题', exact=True).click()
            expect(file_panel.get_by_role('link')).to_have_count(0)
            expect(file_panel.get_by_text(blocked.name, exact=False)).to_have_count(0)
            expect(file_panel.get_by_text('还没有生成文件。', exact=True)).to_have_count(0)
            self.page.unroute(next_files)
            self.page.get_by_role('button', name='刷新文件列表', exact=True).click()
            expect(file_panel.get_by_role('alert')).to_have_count(0)
            expect(file_panel.get_by_text('还没有生成文件。', exact=True)).to_have_count(1)
            self.page.get_by_role('button', name=re.compile('^' + re.escape(snapshot['title']))).click()
            self.page.get_by_role('button', name='会话文件', exact=True).click()
            expect(self.page.locator('.rs-files [role="alert"]')).to_contain_text(blocked.name)
        finally:
            if sys.platform == 'win32':
                win32security.SetNamedSecurityInfo(str(blocked), win32security.SE_FILE_OBJECT,
                    win32security.DACL_SECURITY_INFORMATION, None, None, original_acl, None)
            else:
                blocked.chmod(0o700)
        self.page.get_by_role('button', name='刷新文件列表', exact=True).click()
        expect(self.page.locator('.rs-files [role="alert"]')).to_have_count(0)
        expect(self.page.get_by_role('link', name=blocked.name + '/hidden.txt', exact=True)).to_be_visible()
        expect(self.page.get_by_role('link', name='child.txt', exact=True)).to_be_visible()
        self.assertEqual(len(self.session()['turns']), 1)  # Refresh must not start another run.
        self.assertEqual(len(self.model.requests), requests_before_refresh)
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.page.locator('.rs-files').scroll_into_view_if_needed()
        self.page.screenshot(path=str(Path(self.folder.name) / 'files-mobile.png'), full_page=True)
        overflow = self.page.evaluate('''() => ({width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
            offenders: [...document.querySelectorAll('body *')].flatMap(el => {
                const r = el.getBoundingClientRect();
                return r.width && r.height && (r.right > innerWidth + 1 || r.left < -1)
                    ? [{tag: el.tagName, class: el.getAttribute('class'), left: r.left, right: r.right, width: r.width}]
                    : [];
            }).slice(0, 30)})''')
        self.assertLessEqual(overflow['scrollWidth'], overflow['width'], json.dumps(overflow, ensure_ascii=False))
        expect(self.page.get_by_role('link', name='结果.txt', exact=True)).to_be_visible()

    def test_reasoning_content_order_and_inline_model_selection(self):
        # The local protocol fixture declares its effort support; no real provider is contacted.
        capabilities = patch('research.session_setup.reasoning_efforts',
            side_effect=lambda configuration: ['low', 'high', 'max']
            if configuration['model'] == 'deepseek-v4.1-flash' else [])
        capabilities.start()
        self.addCleanup(capabilities.stop)
        model = self.post('/personal-models', {'provider': 'openai-compatible',
            'baseURL': f'http://127.0.0.1:{self.model.server_port}/v1', 'model': 'deepseek-v4.1-flash',
            'protocol': 'chat-completions'})
        self.page.reload()
        self.page.get_by_role('button', name='选择模型', exact=True).click()
        self.page.get_by_role('option', name='deepseek-v4.1-flash', exact=True).click()
        self.page.get_by_role('button', name='选择模型', exact=True).click()
        self.page.get_by_role('combobox', name='推理强度', exact=True).select_option('high')
        self.page.keyboard.press('Escape')
        self.model.reasoning_pause = threading.Event()
        self.addCleanup(self.model.reasoning_pause.set)
        self.send('思考与内容顺序验收')
        expect(self.page.locator('.rs-thinking').get_by_text('再核对最终输出。', exact=True)).to_be_visible()
        expect(self.page.locator('.rs-streaming-reply').get_by_text('顺序验收', exact=True)).to_be_visible()
        self.model.reasoning_pause.set()
        snapshot = self.wait_for(lambda s: s['turns'][-1]['status'] == 'completed')
        turn = snapshot['turns'][-1]
        self.assertEqual(turn['result'], '顺序验收最终回答。')
        self.assertEqual(snapshot['model']['connectionRef'], model['connectionRef'])
        ordered = [event for event in turn['events'] if event['type'] in
            {'model_reasoning_delta', 'model_content_delta', 'research_tool_started', 'research_tool_finished'}]
        self.assertEqual([event['type'] for event in ordered], ['model_reasoning_delta', 'model_content_delta',
            'research_tool_started', 'research_tool_finished', 'model_reasoning_delta', 'model_content_delta',
            'model_reasoning_delta', 'model_content_delta'])
        self.assertEqual([event['data']['text'] for event in ordered if 'text' in event['data']],
            ['先核对工具参数。', '即将写入顺序文件。', '收到工具结果后继续。', '顺序验收', '再核对最终输出。', '最终回答。'])
        calls = [event for event in ordered if 'callId' in event['data']]
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]['data']['callId'], calls[1]['data']['callId'])
        native_requests = [request for request in self.model.requests if any(message['role'] == 'user'
            and message['content'] == '思考与内容顺序验收' for message in request['messages'])]
        self.assertTrue(native_requests)
        self.assertTrue(all(request['model'] == 'deepseek-v4.1-flash'
                            and request.get('reasoning_effort') == 'high' for request in native_requests))
        self.page.reload()
        process = self.page.locator('.rs-process')
        expect(process).not_to_have_attribute('open', '')
        process.locator(':scope > summary').click()
        steps = process.locator('.rs-process-steps')
        expect(steps).to_have_attribute('open', '')
        call = steps.locator('.rs-tool-call')
        expect(call).to_have_count(1)
        expect(self.page.locator('.rs-tool-results')).to_have_count(0)
        steps.locator(':scope > summary').click()
        expect(call.locator(':scope > summary')).to_be_hidden()
        steps.locator(':scope > summary').click()
        expect(call).not_to_have_attribute('open', '')
        call.locator(':scope > summary').click()
        expect(call.get_by_text('已完成', exact=True)).to_be_visible()
        expect(steps.locator('.rs-thinking')).to_have_count(3)
        expect(steps.locator('.rs-thinking').first).not_to_have_attribute('open', '')
        steps.locator('.rs-thinking').first.locator(':scope > summary').click()
        expect(steps.get_by_text('先核对工具参数。', exact=True)).to_be_visible()
        text = steps.locator(':scope > ol').text_content()
        self.assertLess(text.index('先核对工具参数。'), text.index('即将写入顺序文件。'))
        self.assertLess(text.index('即将写入顺序文件。'), text.index('修改文件'))
        self.assertLess(text.index('修改文件'), text.index('收到工具结果后继续。'))
        self.assertNotIn('model_binding_selected', text)
        self.assertNotIn('native_accepted', text)
        self.assertNotIn('顺序验收', text)
        self.assertNotIn('最终回答。', text)
        self.page.screenshot(path=str(Path(self.folder.name) / 'thinking-content-order.png'))
        expect(self.page.locator('.rs-turn > .rs-reply').get_by_text('顺序验收最终回答。', exact=True)).to_be_visible()
        self.page.get_by_role('button', name='选择模型', exact=True).click()
        self.page.get_by_role('option', name='regression', exact=True).click()
        expect(self.page.get_by_role('combobox', name='推理强度', exact=True)).to_have_count(0)
        self.page.get_by_role('textbox', name='下一轮指令', exact=True).fill('切换模型后继续')
        self.page.get_by_role('button', name='发送', exact=True).click()
        self.wait_for(lambda s: len(s['turns']) == 2 and s['turns'][-1]['status'] == 'completed')
        latest = next(request for request in reversed(self.model.requests) if any(message['role'] == 'user'
            and message['content'] == '切换模型后继续' for message in request['messages']))
        self.assertEqual(latest['model'], 'regression')
        self.assertNotIn('reasoning_effort', latest)
        requests_before_refresh = len(self.model.requests)
        self.page.reload()
        expect(self.page.locator('.rs-turn')).to_have_count(2)
        self.assertEqual(len(self.model.requests), requests_before_refresh)

    def test_ssh_question_and_followup_keep_current_user_message(self):
        server = self.configure_ssh()
        self.send('ssh 可用了吗?')
        for question in ('ssh 可用了吗?', '再看一下 SSH 状态'):
            if question != 'ssh 可用了吗?':
                self.post('/research/sessions/' + self.session()['id'] + '/turns', {'text': question})
            snapshot = self.wait_for(lambda s: s['turns'][-1]['status'] in {'completed', 'failed', 'unknown', 'cancelled'})
            turn = snapshot['turns'][-1]
            self.assertEqual(turn['status'], 'completed', snapshot)
            self.assertIn('已找到配置的 SSH 服务器', turn['result'])
            events = [e for e in turn['events'] if e['data'].get('toolName') == 'ssh_servers']
            self.assertEqual([e['type'] for e in events], ['tool_started', 'tool_finished'])
            self.assertEqual(events[0]['data']['callId'], events[1]['data']['callId'])
            self.assertEqual(events[0]['data']['arguments'], {})
            self.assertEqual(events[1]['data']['outcome'], 'completed')
            self.assertEqual(events[1]['data']['output'][0]['reference'], server['reference'])
            self.assertTrue(any(any(m['role'] == 'user' and m['content'] == question for m in r['messages'])
                for r in self.model.requests))
        store = self.state['store']
        for _ in range(1001):
            store.event(turn['taskId'], 'model_content_delta', 'window fixture', {'responseId': 'window', 'text': 'x'})
        self.assertEqual(len([e for e in self.session()['turns'][-1]['events']
                              if e['data'].get('toolName') == 'ssh_servers']), 2)
        before_refresh = len(self.model.requests)
        self.page.reload()
        expect(self.page.locator('.rs-turn > .rs-reply').get_by_text('已找到配置的 SSH 服务器', exact=False).last).to_be_visible()
        process = self.page.locator('.rs-process').last
        process.locator('summary').first.click()
        call = process.locator('.rs-tool-call').first
        call.locator('summary').first.click()
        call.get_by_text('调用参数', exact=True).click()
        expect(call.locator('pre').first).to_have_text('{}')
        call.get_by_text('完整工具结果', exact=True).click()
        expect(call.get_by_text(server['reference'], exact=False).first).to_be_visible()
        self.assertEqual(len(self.session()['turns']), 2)
        self.assertEqual(len(self.model.requests), before_refresh)

        disconnected = {'exitCode': 255, 'stdout': '', 'stderr': 'connection lost', 'stopped': False}
        with patch.object(self.state['store'].personal_ssh, 'run', new=AsyncMock(return_value=disconnected)):
            self.post('/research/sessions/' + self.session()['id'] + '/turns', {'text': 'SSH 断线回执验收'})
            snapshot = self.wait_for(lambda s: len(s['turns']) == 3 and s['turns'][-1]['status'] == 'completed')
        receipt = next(e['data'] for e in snapshot['turns'][-1]['events']
                       if e['type'] == 'tool_finished' and e['data'].get('toolName') == 'ssh_run')
        self.assertEqual(receipt['outcome'], 'unknown')
        self.assertEqual(receipt['output'], disconnected)
        self.assertEqual(receipt['code'], 'SSH_TOOL_OUTCOME_UNKNOWN')
        expect(self.page.get_by_text('原工具操作结果未知，需核对原任务，不要重发同一操作。', exact=True)).to_be_visible()

    def test_ssh_rejection_and_uncertain_dispatch(self):
        from contextlib import contextmanager
        from tempfile import TemporaryDirectory
        self.configure_ssh()
        @contextmanager
        def directory(**kwargs):
            if message == 'SSH 准备失败验收':
                raise PermissionError('synthetic private path must not appear in receipt')
            with TemporaryDirectory(**kwargs) as folder:
                yield folder
            if message == 'SSH 清理失败验收':
                raise OSError('synthetic private path must not appear in receipt')
        cases = [('SSH 空命令验收', None, 'failed', 'SSH_COMMAND_INVALID'),
                 ('SSH 参数缺失验收', None, 'failed', 'SSH_COMMAND_INVALID'),
                 ('SSH 准备失败验收', None, 'failed', 'SSH_PREPARATION_FAILED'),
                 ('SSH 启动失败验收', CLIProcessError('SPAWN_FAILED', dispatched=False, stopped=True), 'failed', 'SSH_SPAWN_FAILED'),
                 ('SSH 派发异常验收', CLIProcessError('CONNECTION_LOST', dispatched=True, stopped=True), 'unknown', 'SSH_CONNECTION_LOST'),
                 ('SSH 取消验收', CLIProcessError('CANCELLED', dispatched=False, stopped=True, cancelled=True), 'unknown', 'SSH_CANCELLED'),
                 ('SSH 清理失败验收', None, 'unknown', 'SSH_EXECUTION_OUTCOME_UNKNOWN')]
        for index, (message, error, outcome, code) in enumerate(cases):
            with self.subTest(message=message), patch('agent_factory.personal_ssh.TemporaryDirectory', directory), patch(
                    'agent_factory.personal_ssh.run_cli_process', new=AsyncMock(side_effect=error,
                        return_value=CLIProcessResult(returncode=0, stdout=b'/tmp\n', stderr=b''))) as process:
                if index == 0:
                    self.send(message)
                else:
                    self.post('/research/sessions/' + self.session()['id'] + '/turns', {'text': message})
                snapshot = self.wait_for(lambda s: len(s['turns']) == index + 1 and s['turns'][-1]['status'] == 'completed')
                receipt = next(event['data'] for event in snapshot['turns'][-1]['events']
                               if event['type'] == 'tool_finished' and event['data'].get('toolName') == 'ssh_run')
                self.assertEqual(receipt['outcome'], outcome)
                self.assertEqual(receipt['code'], code)
                if message in {'SSH 空命令验收', 'SSH 参数缺失验收', 'SSH 准备失败验收'}:
                    process.assert_not_called()
                else:
                    process.assert_awaited_once()
                expect(self.page.locator('.rs-turn')).to_have_count(index + 1)
                expect(self.page.locator('.rs-turn').last.locator('.rs-process > summary')).to_contain_text('已完成')
                call = self.page.locator('.rs-turn').last.locator('.rs-tool-call').last
                self.page.locator('.rs-turn').last.locator('.rs-process > summary').click()
                expect(call.get_by_text('失败' if outcome == 'failed' else '结果未确认', exact=True)).to_be_visible()

    def test_activity_wait_disconnect_and_reconciliation_display(self):
        # UI-only snapshots isolate transport loss and missing/late events.
        self.send('ssh 可用了吗?')
        snapshot = self.wait_for(lambda s: s['turns'][-1]['status'] == 'completed')
        turn = snapshot['turns'][-1]
        old = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=30)).isoformat()
        def event(identifier, kind, data):
            return {'id': identifier, 'jobId': turn['taskId'], 'type': kind, 'message': 'UI fixture',
                    'createdAt': old, 'data': {'callId': 'display-call', 'toolName': 'ssh_run', **data}}
        turn.update(status='running', result=None,
            toolResults=[{'effectKey': turn['runId'] + ':personal-tool:display-call', 'status': 'UNKNOWN', 'result': None}],
            events=[event(1, 'tool_started',
            {'arguments': {'argv': ['pwd'], 'reference': 'synthetic-server'}})])
        snapshot.update(state='running', allowedActions=['correct', 'stop'])
        def stream(route):
            route.fulfill(content_type='text/event-stream', body='event: session\ndata: ' +
                          json.dumps(snapshot, ensure_ascii=False) + '\n\n')
        self.page.route('**/research/sessions/*/events', stream)
        self.page.route('**/research/sessions/' + snapshot['id'], lambda route: route.fulfill(json=snapshot))
        self.page.evaluate('''value => sessionStorage.setItem(
            `factory:research-sessions:${encodeURIComponent(value.owner)}:requests`,
            JSON.stringify([{requestId: value.request, action: 'turn', sessionId: value.session}]))''',
            {'owner': self.owner, 'request': str(uuid4()), 'session': snapshot['id']})
        self.page.reload()
        expect(self.page.locator('.rs-recovery')).to_be_visible()
        expect(self.page.get_by_role('button', name='请求停止', exact=True)).to_be_enabled()
        expect(self.page.get_by_text(re.compile('秒未收到更新'))).to_be_visible()
        self.page.screenshot(path=str(Path(self.folder.name) / 'ui-fixture-waiting.png'))
        expect(self.page.locator('.rs-content').get_by_text(re.compile('实时连接已断开'))).to_be_visible()
        expect(self.page.get_by_text('已开始 · 等待结果', exact=True)).to_be_visible()
        expect(self.page.locator('.rs-tool-call')).to_have_count(1)
        expect(self.page.locator('.rs-tool-results')).to_have_count(0)
        unknown_warning = self.page.locator('.rs-activity').get_by_text(re.compile('原工具操作结果未知'))
        expect(unknown_warning).to_have_count(0)
        turn['toolResults'].append({'effectKey': turn['runId'] + ':personal-tool:other-call',
            'status': 'UNKNOWN', 'result': None})
        expect(self.page.locator('.rs-tool-results details')).to_have_count(1)
        expect(self.page.locator('.rs-tool-results')).to_contain_text('other-call')
        expect(unknown_warning).to_be_visible()
        turn['toolResults'].pop()
        expect(self.page.locator('.rs-tool-results')).to_have_count(0)
        expect(unknown_warning).to_have_count(0)
        turn['events'].append(event(2, 'tool_finished', {'outcome': 'unknown'}))
        expect(self.page.get_by_text('结果未确认', exact=True)).to_be_visible()
        expect(unknown_warning).to_be_visible()
        turn['events'].pop()
        expect(self.page.get_by_text('已开始 · 等待结果', exact=True)).to_be_visible()
        expect(unknown_warning).to_have_count(0)
        self.page.locator('.rs-tool-call > summary').click()
        expect(self.page.locator('.rs-tool-call')).to_have_attribute('open', '')
        snapshot.update(state='idle', allowedActions=['start', 'stop'])
        turn['status'] = 'completed'
        expect(self.page.locator('.rs-tool-results .rs-tool-warning')).to_be_visible()
        expect(unknown_warning).to_be_visible()
        turn.update(status='completed', result='UI fixture answer\n\n| 结果 | 状态 |\n| --- | --- |\n| SSH | 已确认 |', events=[*turn['events'],
            event(2, 'tool_finished', {'outcome': 'unknown', 'code': 'SSH_TOOL_OUTCOME_UNKNOWN'})])
        expect(self.page.get_by_text(re.compile('原工具操作结果未知'))).to_be_visible()
        self.page.screenshot(path=str(Path(self.folder.name) / 'ui-fixture-unknown.png'))
        # Reconciliation can update the effect receipt without appending a finish event.
        recovered = {'outcome': 'completed', 'output': {'stdout': '恢复后的原操作结果', 'exitCode': 0}}
        turn['toolResults'] = [{'effectKey': 'legacy:display-call', 'status': 'DONE', 'result': recovered}]
        receipt = self.page.locator('.rs-tool-results')
        expect(receipt.get_by_text('回执已确认', exact=False)).to_be_visible()
        receipt.locator('details > summary').first.click()
        expect(receipt.get_by_text('恢复后的原操作结果', exact=False)).to_be_visible()
        turn['events'].append(event(3, 'tool_finished', recovered))
        expect(receipt).to_have_count(0)
        turn['toolResults'][0]['status'] = 'UNKNOWN'
        expect(receipt.locator('.rs-tool-warning')).to_be_visible()
        turn['toolResults'][0]['status'] = 'DONE'
        turn['toolResults'][0]['result'] = {'outcome': 'completed',
            'output': {'stdout': '修订后的成功结果', 'exitCode': 0}}
        expect(receipt.get_by_text('回执已确认', exact=False)).to_be_visible()
        receipt.locator('details > summary').first.click()
        expect(receipt.get_by_text('修订后的成功结果', exact=False)).to_be_visible()
        turn['toolResults'] = []
        turn['events'].append(event(4, 'tool_finished', {'outcome': 'completed', 'reconciled': True,
                                                     'output': {'stdout': '/tmp', 'exitCode': 0}}))
        expect(self.page.get_by_text(re.compile('原工具操作结果未知'))).not_to_be_visible()
        process = self.page.locator('.rs-process')
        process.locator('summary').first.click()
        expect(process.locator('.rs-tool-call')).to_have_count(1)
        expect(process.locator('.rs-tool-call')).to_have_attribute('open', '')
        expect(process.locator('.rs-tool-call').get_by_text('已完成', exact=True)).to_be_visible()
        expect(self.page.get_by_role('cell', name='SSH', exact=True)).to_be_visible()
        self.page.screenshot(path=str(Path(self.folder.name) / 'ui-fixture-reconciled.png'))
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth'))
        self.page.screenshot(path=str(Path(self.folder.name) / 'ui-fixture-mobile.png'))

        # Stopping plain text keeps a visible status without inventing process steps.
        snapshot.update(state='running', allowedActions=['correct', 'stop'])
        turn.update(status='running', result=None, failure=None, children=[], toolResults=[],
            events=[event(4, 'native_accepted', {}),
                    event(5, 'model_content_delta', {'responseId': 'plain-first', 'text': '前段回复。'}),
                    event(6, 'model_content_delta', {'responseId': 'plain-response', 'text': '保留部分回复。'})])
        activity = self.page.locator('.rs-activity')
        expect(activity.get_by_text('正在生成回答…', exact=True)).to_be_visible()
        expect(activity.get_by_text('前段回复。保留部分回复。', exact=True)).to_be_visible()
        expect(self.page.locator('.rs-turn .rs-execution')).to_have_count(0)
        expect(activity.locator('.rs-process')).to_have_count(0)
        snapshot.update(state='stopped', allowedActions=['start'])
        for status in ('cancelled', 'canceled'):
            turn['status'] = status
            expect(activity.get_by_text('本轮已停止', exact=True)).to_be_visible()
            expect(activity.get_by_text('前段回复。保留部分回复。', exact=True)).to_be_visible()
            self.page.reload()
            expect(activity.get_by_text('本轮已停止', exact=True)).to_be_visible()
            expect(activity.get_by_text('前段回复。保留部分回复。', exact=True)).to_be_visible()
            expect(activity.locator('.rs-process')).to_have_count(0)
        turn['events'] = []
        self.page.reload()
        expect(activity.get_by_text('本轮已停止', exact=True)).to_be_visible()
        expect(activity.locator('.rs-streaming-reply')).to_have_count(0)
        expect(activity.locator('.rs-process')).to_have_count(0)
        for status in ('failed', 'unknown'):
            turn['status'] = status
            self.page.reload()
            expect(activity.get_by_role('alert')).to_contain_text('本轮结果未知' if status == 'unknown' else '本轮未完成')
            expect(activity.locator('.rs-process')).to_have_count(0)
        turn['failure'] = '提供方连接中断'
        self.page.reload()
        expect(activity.get_by_role('alert')).to_contain_text('本轮结果未知')
        expect(self.page.locator('.rs-turn > .rw-error')).to_contain_text('提供方连接中断')
        turn['toolResults'] = [{'effectKey': 'legacy:call', 'status': 'UNKNOWN', 'result': None}]
        self.page.reload()
        expect(self.page.locator('.rs-tool-results .rs-tool-warning')).to_be_visible()
        expect(activity.get_by_text(re.compile('原工具操作结果未知'))).to_be_visible()
        turn['children'] = [{'childTaskId': 'display-child', 'runId': None, 'goal': '核对独立子任务',
            'status': 'unknown', 'result': None}]
        self.page.reload()
        expect(self.page.locator('.rs-child-preview')).to_have_count(1)
        expect(self.page.locator('.rs-active-children')).to_have_count(0)
        expect(activity.get_by_text('子助手有未完成或未确认的结果，请查看子助手记录。', exact=True)).to_be_visible()

    def test_short_chat_header_and_native_detail_panels(self):
        self.configure_ssh()
        self.send('ssh 可用了吗?')
        snapshot = self.wait_for(lambda s: s['turns'][-1]['status'] == 'completed')
        files_url = '**/research/sessions/' + snapshot['id'] + '/files'
        with self.page.expect_response(files_url) as files:
            self.page.reload()
        self.assertTrue(files.value.ok)
        expect(self.page.locator('.rs-turn > .rs-reply').get_by_text('已找到配置的 SSH 服务器', exact=False).last).to_be_visible()
        pane = self.page.locator('.rs-content')
        header = self.page.locator('.rs-detail > .rs-detail-heading')
        self.assertAlmostEqual(header.bounding_box()['height'], 76, delta=1)
        self.assertEqual(header.evaluate('el => el.nextElementSibling.className'), 'rs-content')
        self.assertLessEqual(header.bounding_box()['y'] + header.bounding_box()['height'], pane.bounding_box()['y'] + 1)
        expect(self.page.get_by_role('button', name='停止会话', exact=True)).not_to_be_visible()
        expect(self.page.get_by_role('button', name='请求停止', exact=True)).to_have_count(0)
        summary = self.page.locator('.rs-process > summary')
        summary.click()
        expect(self.page.locator('.rs-process-steps > summary')).to_be_visible()
        self.assertLessEqual(pane.evaluate('el => el.scrollHeight - el.clientHeight'), 1)
        expect(self.page.get_by_role('button', name='回到底部', exact=True)).to_have_count(0)
        summary.click()
        expect(self.page.locator('.rs-turn .rs-execution')).to_have_count(0)
        for name, panel_id in [('会话文件', 'rs-file-panel'), ('同事问答', 'rs-question-panel'),
                               ('会话信息', 'rs-info-panel')]:
            panel = self.page.locator('#' + panel_id)
            expect(panel).to_be_hidden()
            self.page.get_by_role('button', name=name, exact=True).click()
            self.assertTrue(panel.evaluate('el => el.matches(":popover-open")'))
            if name == '会话文件':
                expect(panel.get_by_role('button', name='刷新文件列表', exact=True)).to_be_visible()
                expect(panel.get_by_text('还没有生成文件。', exact=True)).to_be_visible()
            elif name == '同事问答':
                expect(panel.get_by_role('button', name='刷新已发问题', exact=True)).to_be_visible()
            else:
                expect(panel.get_by_text(snapshot['goal'], exact=True)).to_be_visible()
                expect(panel.get_by_text(re.compile('当前上下文 .* 字符'))).to_be_visible()
                expect(panel.get_by_text('可继续', exact=True)).to_be_visible()
                expect(panel.get_by_role('heading', name='诊断记录', exact=True)).to_be_visible()
                panel.locator('.rs-execution > summary').click()
                expect(panel.locator('.rs-events > summary')).to_be_visible()
                panel.locator('.rs-events > summary').click()
                expect(panel.get_by_text('以下是执行端保存的诊断记录。', exact=True)).to_be_visible()
                expect(panel.get_by_role('button', name='停止会话', exact=True)).to_be_visible()
            self.page.get_by_role('button', name='关闭' + name, exact=True).click()
            expect(panel).to_be_hidden()
        composer = self.page.get_by_role('textbox', name='下一轮指令', exact=True)
        composer.fill('模型设置往返保留草稿')
        self.page.locator('.rs-composer-model').click()
        self.page.get_by_role('button', name='管理模型', exact=True).click()
        expect(self.page.get_by_role('heading', name='我的模型/API', exact=True)).to_be_visible()
        self.page.get_by_role('button', name=re.compile('^返回')).click()
        expect(composer).to_have_value('模型设置往返保留草稿')
        composer.fill('')
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.assertAlmostEqual(header.bounding_box()['y'], 0, delta=1)
        self.assertAlmostEqual(header.bounding_box()['height'], 76, delta=1)
        self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth'))
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollHeight'), 844)
        navigation = self.page.locator('.rs-navigation')
        navigation.locator(':scope > summary').click()
        expect(navigation).to_have_attribute('open', '')
        navigation.locator(':scope > summary').click()
        expect(navigation).not_to_have_attribute('open', '')
        for name in ('会话文件', '同事问答', '会话信息'):
            self.page.get_by_role('button', name=name, exact=True).click()
            expect(self.page.get_by_role('complementary', name=name, exact=True)).to_be_visible()
            self.page.get_by_role('button', name='关闭' + name, exact=True).click()
        self.page.get_by_role('button', name='更多会话操作', exact=True).click()
        expect(self.page.locator('#rs-compose-menu')).to_be_visible()
        self.page.keyboard.press('Escape')
        expect(self.page.locator('#rs-compose-menu')).to_be_hidden()

        snapshot['turns'][-1]['continuation'] = {'questionIds': ['synthetic-question']}
        self.page.route('**/research/sessions/' + snapshot['id'], lambda route: route.fulfill(json=snapshot))
        self.page.route('**/research/sessions/*/events', lambda route: route.fulfill(content_type='text/event-stream',
            body='event: session\ndata: ' + json.dumps(snapshot, ensure_ascii=False) + '\n\n'))
        self.page.route('**/assistant-questions/synthetic-question',
                        lambda route: route.fulfill(status=404, json={'detail': '原问题不存在验收'}))
        self.page.reload()
        original_question = self.page.get_by_role('button', name='自动继续的原问题 synthetic-question', exact=True)
        for close in ('button', 'Escape'):
            original_question.click()
            expect(self.page.locator('#rs-question-panel')).to_be_visible()
            if close == 'button':
                self.page.get_by_role('button', name='关闭同事问答', exact=True).click()
            else:
                self.page.keyboard.press(close)
            expect(self.page.locator('#rs-question-panel')).to_be_hidden()
        original_question.click()
        expect(self.page.locator('#rs-question-panel')).to_be_visible()
        self.page.get_by_role('button', name='返回本会话问答', exact=True).click()
        self.page.get_by_role('button', name='关闭同事问答', exact=True).click()

        # A lost acknowledgement blocks new turns, but must not block an allowed Stop.
        self.page.unroute('**/research/sessions/' + snapshot['id'])
        self.page.unroute('**/research/sessions/*/events')
        self.page.evaluate('''value => sessionStorage.setItem(
            `factory:research-sessions:${encodeURIComponent(value.owner)}:requests`,
            JSON.stringify([{requestId: value.request, action: 'turn', sessionId: value.session}]))''',
            {'owner': self.owner, 'request': str(uuid4()), 'session': snapshot['id']})
        self.page.reload()
        expect(self.page.locator('.rs-recovery')).to_be_visible()
        expect(self.page.get_by_role('textbox', name='下一轮指令', exact=True)).to_be_disabled()
        self.page.get_by_role('button', name='会话信息', exact=True).click()
        stop = self.page.get_by_role('button', name='停止会话', exact=True)
        expect(stop).to_be_enabled()
        requests_before_stop = len(self.model.requests)
        with self.page.expect_response(lambda response: response.request.method == 'POST'
                                       and response.url.endswith('/stop')) as stopped:
            stop.click()
        self.assertTrue(stopped.value.ok, stopped.value.text())
        self.assertEqual(stopped.value.json()['state'], 'stopped')
        self.assertEqual(self.session()['state'], 'stopped')
        self.assertEqual(len(self.model.requests), requests_before_stop)

    def test_chat_copy_composer_and_scroll_following(self):
        self.context.grant_permissions(['clipboard-read', 'clipboard-write'])
        self.send('聊天呈现验收')
        snapshot = self.wait_for(lambda s: s['turns'][-1]['status'] == 'completed')
        self.assertEqual(snapshot['turns'][-1]['result'], PRESENTATION)
        expect(self.page.locator('.rs-process')).to_have_count(0)
        expect(self.page.locator('.rs-turn .rs-execution')).to_have_count(0)
        self.page.get_by_role('button', name='会话信息', exact=True).click()
        info = self.page.locator('#rs-info-panel')
        expect(info.get_by_role('heading', name='诊断记录', exact=True)).to_be_visible()
        info.locator('.rs-execution > summary').click()
        info.locator('.rs-events > summary').click()
        expect(info.get_by_text('以下是执行端保存的诊断记录。', exact=True)).to_be_visible()
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.assertLessEqual(info.evaluate('el => el.scrollWidth'), info.evaluate('el => el.clientWidth'))
        self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth'))
        self.page.set_viewport_size({'width': 1280, 'height': 900})
        self.page.get_by_role('button', name='关闭会话信息', exact=True).click()
        expect(self.page.locator('.rs-code-block')).to_have_count(2)
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollHeight'), 900)
        pane = self.page.locator('.rs-content')
        code = self.page.locator('.rs-code-block').first
        self.page.get_by_role('button', name='复制代码', exact=True).first.click()
        self.assertEqual(self.page.evaluate('navigator.clipboard.readText()'), "print('中文验收')  # " + 'long ' * 40)
        expect(code.get_by_role('checkbox', name='自动换行')).to_be_checked()
        self.assertEqual(code.locator('code').evaluate('el => getComputedStyle(el).whiteSpace'), 'pre-wrap')
        code.get_by_role('checkbox', name='自动换行').uncheck()
        self.assertEqual(code.locator('code').evaluate('el => getComputedStyle(el).whiteSpace'), 'pre')
        self.page.get_by_role('button', name='复制助手回复', exact=True).click()
        self.assertEqual(self.page.evaluate('navigator.clipboard.readText()').replace('\r\n', '\n'), PRESENTATION)
        self.page.get_by_role('button', name='复制用户消息', exact=True).click()
        self.assertEqual(self.page.evaluate('navigator.clipboard.readText()'), '聊天呈现验收')
        expect(self.page.get_by_role('button', name='回到底部', exact=True)).to_be_visible()
        self.page.get_by_role('button', name='回到底部', exact=True).click()
        self.page.wait_for_function("() => { const p = document.querySelector('.rs-content'); return p.scrollHeight - p.scrollTop - p.clientHeight < 5; }")
        composer = self.page.get_by_role('textbox', name='下一轮指令', exact=True)
        expect(self.page.get_by_role('button', name='发送', exact=True)).to_be_disabled()
        expect(self.page.locator('.rs-composer-model')).to_contain_text('regression')
        composer.fill('\n'.join(['draft line'] * 8))
        self.assertGreater(composer.evaluate('el => el.clientHeight'), 80)
        composer.fill('')
        self.assertLessEqual(composer.evaluate('el => el.clientHeight'), 44)
        composer.fill('resize ' * 20)
        desktop_height = composer.evaluate('el => el.clientHeight')
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.assertGreater(composer.evaluate('el => el.clientHeight'), desktop_height)
        self.page.set_viewport_size({'width': 1280, 'height': 900})
        composer.fill('')
        expect(self.page.get_by_role('button', name='发送', exact=True)).to_be_disabled()
        before = len(self.model.requests)
        composer.press('Enter')
        self.assertEqual(len(self.model.requests), before)

        turn = snapshot['turns'][-1]
        turn.update(status='running', completedAt=None, result=None, events=[{'id': 100, 'jobId': turn['taskId'],
            'type': 'model_content_delta', 'message': 'UI fixture', 'createdAt': turn['createdAt'],
            'data': {'responseId': 'presentation', 'text': PRESENTATION}}])
        snapshot.update(state='running', allowedActions=['correct', 'stop'])
        self.page.route('**/research/sessions/*/events', lambda route: route.fulfill(content_type='text/event-stream',
            body='event: session\ndata: ' + json.dumps(snapshot, ensure_ascii=False) + '\n\n'))
        self.page.route('**/research/sessions/' + snapshot['id'], lambda route: route.fulfill(json=snapshot))
        self.page.reload()
        expect(self.page.get_by_role('textbox', name='补充或纠正当前研究', exact=True)).to_be_visible()
        self.page.wait_for_function("() => { const p = document.querySelector('.rs-content'); return p.scrollHeight - p.scrollTop - p.clientHeight < 5; }")
        expect(self.page.locator('.rs-process')).to_have_count(0)
        self.page.locator('.rs-code-block').first.get_by_role('checkbox', name='自动换行').uncheck()
        pane.evaluate('el => { el.scrollTop = Math.max(0, el.scrollTop - 240); }')
        expect(self.page.get_by_role('button', name='回到底部', exact=True)).to_be_visible()
        reading_position = pane.evaluate('el => el.scrollTop')
        turn['events'][0]['id'] += 1
        turn['events'][0]['data']['text'] += '\n\n展开记录时的新内容'
        expect(self.page.get_by_text('展开记录时的新内容', exact=True)).to_be_attached()
        self.assertLess(abs(pane.evaluate('el => el.scrollTop') - reading_position), 2)
        self.page.get_by_role('button', name='回到底部', exact=True).click()
        self.page.wait_for_function("() => { const p = document.querySelector('.rs-content'); return p.scrollHeight - p.scrollTop - p.clientHeight < 5; }")
        expect(self.page.get_by_role('button', name='回到底部', exact=True)).to_have_count(0)
        header_before = self.page.locator('.rs-detail-heading').bounding_box()
        pane.evaluate('el => { el.scrollTop = 0; }')
        expect(self.page.get_by_role('button', name='回到底部', exact=True)).to_be_visible()
        header_after = self.page.locator('.rs-detail-heading').bounding_box()
        self.assertEqual(header_after, header_before)
        self.assertGreater(pane.evaluate('el => el.scrollHeight - el.clientHeight'), 180)
        turn['events'][0]['id'] += 1
        turn['events'][0]['data']['text'] += '\n\n历史阅读期间的新内容'
        expect(self.page.get_by_text('历史阅读期间的新内容', exact=True)).to_be_attached()
        self.assertLess(pane.evaluate('el => el.scrollTop'), 5)
        self.page.get_by_role('button', name='回到底部', exact=True).click()
        expect(self.page.get_by_role('button', name='回到底部', exact=True)).to_have_count(0)
        turn['events'][0]['id'] += 1  # Event count stays fixed, as in the retained fragment window.
        turn['events'][0]['data']['text'] += '\n\n恢复跟随后新内容'
        expect(self.page.get_by_text('恢复跟随后新内容', exact=True)).to_be_attached()
        self.page.wait_for_function("() => { const p = document.querySelector('.rs-content'); return p.scrollHeight - p.scrollTop - p.clientHeight < 5; }")
        self.page.set_viewport_size({'width': 390, 'height': 844})
        expect(self.page.get_by_role('button', name='请求停止', exact=True)).to_be_visible()
        self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth'))
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollHeight'), 844)
        self.page.screenshot(path=str(Path(self.folder.name) / 'chat-detail-mobile.png'))

    @staticmethod
    def run_async(coroutine):
        # Playwright owns this thread's event loop.
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coroutine).result()

    def configure_ssh(self):
        key = ed25519.Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()).decode()
        credential = self.post('/personal-credentials', {'providerId': 'owner-ssh-server-v1',
            'destination': 'ssh://agent@127.0.0.1:2222', 'username': 'agent', 'password': key})
        return self.post('/personal-ssh', {'name': '研究服务器', 'address': '127.0.0.1', 'port': 2222,
            'username': 'agent', 'allowedRoot': '/tmp', 'credentialRef': credential['credentialRef'],
            'credentialRevision': credential['credentialRevision']})

    def test_ssh_revocation_and_temporary_key(self):
        server = self.configure_ssh()
        ssh = self.state['store'].personal_ssh
        key_paths = []
        async def observe_key(**kwargs):
            key = Path(kwargs['argv'][kwargs['argv'].index('-i') + 1])
            key_paths.append(key)
            if sys.platform == 'win32':
                import win32api
                import win32con
                import win32security
                token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
                try:
                    user = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
                    acl = win32security.GetNamedSecurityInfo(str(key), win32security.SE_FILE_OBJECT,
                        win32security.DACL_SECURITY_INFORMATION).GetSecurityDescriptorDacl()
                    self.assertEqual(acl.GetAceCount(), 1)
                    self.assertEqual(acl.GetAce(0)[2], user)
                finally:
                    win32api.CloseHandle(token)
            else:
                self.assertEqual(key.stat().st_mode & 0o777, 0o600)
                self.assertEqual(key.parent.stat().st_mode & 0o777, 0o700)
            serialization.load_ssh_private_key(key.read_bytes(), password=None)
            if len(key_paths) == 2:
                raise CLIProcessError('CONNECTION_LOST', dispatched=True, stopped=True)
            return CLIProcessResult(returncode=0, stdout=b'/tmp\n', stderr=b'', stopped=True, dispatched=True)
        with patch('agent_factory.personal_ssh.run_cli_process', side_effect=observe_key) as process:
            self.assertEqual(ssh.available(self.owner)[0]['reference'], server['reference'])
            self.run_async(ssh.run(self.owner, server['reference'], ['pwd']))
            from agent_factory.personal_tool_contract import ToolInvocationError
            with self.assertRaises(ToolInvocationError):
                self.run_async(ssh.run(self.owner, server['reference'], ['pwd']))
            self.assertTrue(all(not key.parent.exists() for key in key_paths))
            revoked = self.post('/personal-ssh/' + server['reference'] + '/revoke', {})
            self.assertFalse(revoked['enabled'])
            self.assertFalse(revoked['executionEnabled'])
            self.assertEqual(ssh.functions(self.owner)[0].entrypoint(), [])
            with self.assertRaises(HTTPException) as error:
                self.run_async(ssh.run(self.owner, server['reference'], ['pwd']))
            self.assertEqual(error.exception.detail, 'SSH_SERVER_REVOKED')
            self.assertEqual(process.call_count, 2)  # Revocation prevents a new process.

    def test_native_compression_reaches_model_payload(self):
        configuration = {'provider': 'openai-compatible', 'model': 'compression',
                         'baseURL': f'http://127.0.0.1:{self.model.server_port}/v1'}
        message = Message(role='tool', tool_call_id='call_original', content='原始长输出42 ' * 1000)
        manager = CompressionManager(model=OwnerChatModel(configuration, lambda: None))
        self.run_async(manager.acompress([message]))
        self.assertEqual(message.compressed_content, '压缩摘要：数值42')
        for protocol in ('chat-completions', 'responses'):
            model = OwnerChatModel({**configuration, 'protocol': protocol}, lambda: None)
            for enabled, expected in ((True, message.compressed_content), (False, message.content)):
                with self.subTest(protocol=protocol, compressed=enabled):
                    body = model._body([message], compress_tool_results=enabled)
                    sent = body['messages'][0]['content'] if protocol == 'chat-completions' else body['input'][0]['output']
                    self.assertEqual(sent, expected)
        self.assertTrue(message.content.startswith('原始长输出42'))  # Compression retains original history.

    def test_workspace_open_requires_a_leaf_name(self):
        with _directory(Path(self.folder.name)) as parent:
            for path in ('../outside', '/etc/passwd', '.', '..'):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    _open_file(parent, path)
        if sys.platform == 'win32':
            root = Path(self.folder.name) / 'directory-lock'
            root.mkdir()
            ResearchSessionTools._edit(root, {'path': '中文.txt', 'old': '', 'new': 'before'})
            ResearchSessionTools._edit(root, {'path': '中文.txt', 'old': 'before', 'new': 'after'})
            self.assertEqual((root / '中文.txt').read_text(encoding='utf-8'), 'after')
            with _directory(root), self.assertRaises(OSError) as blocked:
                root.rename(root.with_name('directory-moved'))
            self.assertEqual(blocked.exception.winerror, 32)

    def test_external_skill_resources_and_long_script(self):
        first_request = len(self.model.requests)
        started = time.monotonic()
        self.send('skills-journey-case')
        snapshot = self.wait_for(lambda s: s['turns'][-1]['status'] in {'completed', 'failed', 'unknown', 'cancelled'})
        self.assertEqual(snapshot['turns'][-1]['status'], 'completed', snapshot)
        self.assertGreaterEqual(time.monotonic() - started, 31)
        requests = self.model.requests[first_request:]
        advertised = {tool['function']['name'] for tool in requests[0]['tools']}
        self.assertTrue({'get_skill_instructions', 'get_skill_reference', 'get_skill_script'} <= advertised)
        final = requests[-1]['messages']
        results = [message['content'] for message in final if message['role'] == 'tool']
        self.assertEqual(len(results), 6)
        self.assertIn('references/nested/guide.md', results[0])
        self.assertIn('Nested reference marker: 42.', results[1])
        self.assertIn('time.sleep(31)', results[2])
        failed, succeeded = (ast.literal_eval(value) for value in results[3:5])
        self.assertEqual(failed['exitCode'], 7)
        self.assertEqual(failed['stderr'], 'skill diagnostic' + os.linesep)
        workspace = self.state['store'].research_sessions.workspace(self.owner, snapshot['id'])
        self.assertEqual(json.loads(failed['stdout']), {'args': ['argument with spaces', '中文'], 'cwd': str(workspace)})
        self.assertEqual(succeeded['exitCode'], 0)
        expected = {'args': ['argument with spaces', '中文'], 'cwd': str(workspace / 'skill-work'), 'finished': True, 'optimize': 1}
        self.assertEqual(json.loads(succeeded['stdout']), expected)
        resource = ast.literal_eval(results[5])
        self.assertEqual(resource['exitCode'], 0)
        self.assertEqual(json.loads(resource['stdout']), {'asset': 'External skill asset: 73.\n',
            'cwd': json.loads(results[0])['source_path']})
        calls = [call for message in final for call in message.get('tool_calls', [])]
        self.assertEqual(len(calls), 6)
        events = snapshot['turns'][-1]['events']
        for call, result in zip(calls[:3], results[:3]):
            with self.subTest(skill_read=call['function']['name']):
                started_events = [event['data'] for event in events if event['type'] == 'tool_started'
                                  and event['data'].get('callId') == call['id']]
                finished_events = [event['data'] for event in events if event['type'] == 'tool_finished'
                                   and event['data'].get('callId') == call['id']]
                expected_call = {'toolName': call['function']['name'], 'callId': call['id'],
                                 'arguments': json.loads(call['function']['arguments'])}
                self.assertEqual(started_events, [expected_call])
                self.assertEqual(finished_events, [{**expected_call, 'outcome': 'completed', 'output': result}])
        executed = [event['data'] for event in events if event['type'] == 'research_tool_finished'
                    and event['data'].get('toolName') == 'research_run']
        self.assertEqual([event['callId'] for event in executed], [call['id'] for call in calls[3:]])
        self.assertEqual(len([event for event in events if event['type'] in {'tool_started', 'tool_finished'}]), 6)
        from agno.exceptions import RunCancelledException
        from agno.run import RunContext
        from agno.tools.function import FunctionCall
        function = next(tool for tool in self.state['executor'].skills.get_tools() if tool.name == 'get_skill_script')
        function.process_entrypoint()
        function._run_context = RunContext(user_id=self.owner, session_id=snapshot['turns'][-1]['taskId'],
                                          run_id=snapshot['turns'][-1]['runId'])
        boundary_calls = []
        for arguments, outcome in (({'skill_name': 'journey-skill', 'script_path': 'nested/runner.py',
                                     'execute': 'false'}, 'completed'),
                                   ({'skill_name': 'journey-skill', 'script_path': 'missing.py',
                                     'execute': True}, 'failed'), ({}, 'failed'),
                                   ({'skill_name': 'journey-skill', 'script_path': 'nested/runner.py',
                                     'execute': True, 'args': 123}, 'failed'),
                                   ({'skill_name': 'journey-skill', 'script_path': 'nested/runner.py',
                                     'execute': True, 'cwd': None}, 'failed')):
            call = FunctionCall(function=function, call_id='boundary-' + uuid4().hex, arguments=arguments)
            self.run_async(call.aexecute())
            boundary_calls.append((call, outcome))
        self.assertEqual(boundary_calls[0][0].result, results[2])
        self.assertIn('error', json.loads(boundary_calls[1][0].result))
        self.assertTrue(boundary_calls[2][0].error)
        # Exercise Agno's cancellation finally-hook; this is an injected cancellation.
        with patch.object(function, 'entrypoint', AsyncMock(side_effect=RunCancelledException('fixture cancellation'))):
            call = FunctionCall(function=function, call_id='boundary-' + uuid4().hex,
                                arguments={'skill_name': 'journey-skill'})
            with self.assertRaises(RunCancelledException):
                self.run_async(call.aexecute())
            boundary_calls.append((call, 'unknown'))
        boundary_events = self.state['store'].events(snapshot['turns'][-1]['taskId'])
        for call, outcome in boundary_calls:
            observed = [event for event in boundary_events if event['data'].get('callId') == call.call_id]
            self.assertEqual([event['type'] for event in observed], ['tool_started', 'tool_finished'])
            self.assertTrue(all(event['data']['arguments'] == call.arguments for event in observed))
            self.assertEqual(observed[-1]['data']['outcome'], outcome)
            if call.result is not None:
                self.assertEqual(observed[-1]['data']['output'], call.result)
            else:
                self.assertNotIn('output', observed[-1]['data'])
            if call.error:
                self.assertEqual(observed[-1]['data']['message'], call.error)
        # Render the actual native boundary events; the completed turn's snapshot is already frozen.
        snapshot['turns'][-1]['events'] = boundary_events
        self.page.route('**/research/sessions/' + snapshot['id'], lambda route: route.fulfill(json=snapshot))
        self.page.route('**/research/sessions/*/events', lambda route: route.fulfill(content_type='text/event-stream',
            body='event: session\ndata: ' + json.dumps(snapshot) + '\n\n'))
        self.page.reload()
        self.page.locator('.rs-process > summary').click()
        for call, _ in boundary_calls[3:5]:
            assert call.error is not None
            row = self.page.locator('.rs-tool-call').filter(has=self.page.get_by_text(call.error, exact=True))
            expect(row).to_have_count(1)
            row.locator(':scope > summary').click()
            expect(row.get_by_text('失败', exact=True)).to_be_visible()
            expect(row.get_by_text(call.error, exact=True)).to_be_visible()
        self.page.get_by_role('button', name='会话文件', exact=True).click()
        with self.page.expect_download() as download:
            self.page.get_by_role('link', name='skill-work/skill-result.json', exact=True).click()
        self.assertEqual(json.loads(Path(download.value.path()).read_bytes()), expected)

    def test_unknown_tool_result_does_not_block_independent_work(self):
        from agent_factory.personal_tool_contract import ToolInvocationError
        self.post('/personal-tools/resources', {'transport': 'cli', 'toolName': 'uncertain_cli',
            'description': 'An operation whose response is lost', 'executable': sys.executable,
            'arguments': ['-c', 'print("not dispatched in this fixture")'],
            'inputSchema': {'type': 'object', 'properties': {}}})
        with patch('agent_factory.personal_cli.MemberCliAdapter.invoke',
                   side_effect=ToolInvocationError('SIMULATED_LOST_RESPONSE', outcome='unknown', stopped=False)) as adapter:
            self.send('unknown-journey-case')
            snapshot = self.wait_for(lambda s: s['turns'][-1]['completedAt'] is not None)
            self.assertEqual(snapshot['turns'][-1]['status'], 'completed', snapshot)
            self.assertIn('start', snapshot['allowedActions'])
            original_task = snapshot['turns'][-1]['taskId']
            unknown = [effect for effect in self.state['store'].effects(original_task) if effect['status'] == 'UNKNOWN']
            self.assertEqual(len(unknown), 1)
            self.assertIsNone(unknown[0]['result'])
            workspace = self.state['store'].research_sessions.workspace(self.owner, snapshot['id'])
            self.assertEqual((workspace / 'independent.txt').read_text(encoding='utf-8'), '独立任务完成')
            results = [m['content'] for m in self.model.requests[-1]['messages'] if m['role'] == 'tool']
            self.assertIn('SIMULATED_LOST_RESPONSE', results[0])
            self.assertIn('独立任务完成', results[-1])
            expect(self.page.get_by_label('下一轮指令', exact=True)).to_be_enabled()
            self.page.get_by_label('下一轮指令', exact=True).fill('unknown-followup')
            with self.page.expect_response(lambda response: response.request.method == 'POST'
                                           and response.url.endswith('/turns')) as submitted:
                self.page.get_by_role('button', name='发送', exact=True).click()
            self.assertTrue(submitted.value.ok, submitted.value.text())
            snapshot = self.wait_for(lambda s: len(s['turns']) == 2 and s['turns'][-1]['status'] == 'completed')
            self.assertIn('后续分析完成', snapshot['turns'][-1]['result'])
            self.assertEqual(adapter.call_count, 1)
            self.assertEqual([e for e in self.state['store'].effects(original_task) if e['status'] == 'UNKNOWN'], unknown)

    def test_stop_skill_script(self):
        self.stop_running('skills-stop-case', 'skills-started.txt')

    def test_stop_running_command(self):
        self.stop_running('stop-case', 'started.txt')

    def stop_running(self, goal, marker):
        self.send(goal)
        snapshot = self.wait_for(lambda s: any(e['type'] == 'research_tool_started'
            for e in s['turns'][-1]['events']))
        files = self.origin + '/api/factory/research/sessions/' + snapshot['id'] + '/files'
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            response = self.context.request.get(files + '/download', params={'path': marker})
            if response.ok:
                break
            self.page.wait_for_timeout(100)
        self.assertTrue(response.ok, 'Command did not start')
        pid = int(response.text())
        if sys.platform == 'win32':
            import win32api
            import win32con
            import win32event
            handle = win32api.OpenProcess(win32con.SYNCHRONIZE, False, pid)
            self.addCleanup(handle.Close)
            self.assertEqual(win32event.WaitForSingleObject(handle, 0), win32event.WAIT_TIMEOUT)
        else:
            os.kill(pid, 0)
        self.page.get_by_role('button', name='请求停止', exact=True).click()
        snapshot = self.wait_for(lambda s: s['state'] == 'stopped')
        self.assertIn(snapshot['turns'][-1]['status'], ['cancelled', 'canceled'])
        if sys.platform == 'win32':
            self.assertEqual(win32event.WaitForSingleObject(handle, 0), win32event.WAIT_OBJECT_0)
        else:
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        self.page.reload()
        self.assertEqual(len(self.session()['turns']), 1)


if __name__ == '__main__':
    unittest.main()
