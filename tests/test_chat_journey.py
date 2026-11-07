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
        elif user_text in {'ssh 可用了吗?', '再看一下 SSH 状态'}:
            if not results:
                tool = 'ssh_servers'
            reply = '已找到配置的 SSH 服务器；本轮只查询配置，连接状态尚未探测。'
        elif user_text == 'SSH 断线回执验收':
            if not results:
                tool = 'ssh_servers'
            elif len(results) == 1:
                tool, arguments = 'ssh_run', {'reference': ast.literal_eval(results[0][1])[0]['reference'],
                                             'argv': ['pwd']}
            reply = 'SSH 结果未确认，需要核对原命令。'
        elif '"goal": "child-only"' in system:
            if not results:
                tool, arguments = 'research_edit_file', {'path': 'child.txt', 'old': '', 'new': '子助手已完成'}
            reply = '子助手已完成'
        elif 'unknown-followup' in json.dumps(request['messages']):
            reply = '后续分析完成，原操作仍待核对。'
        elif 'unknown-journey-case' in system:
            steps = [('uncertain_cli', {}),
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
            steps = [('demo_cli', {'mode': 'fail'}), ('demo_cli', {'mode': 'ok'}), ('ssh_servers', {}),
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
        for change, finish in [(delta, None), ({}, 'tool_calls' if tool else 'stop')]:
            chunk = {'id': 'completion', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'regression',
                     'choices': [{'index': 0, 'delta': change, 'finish_reason': finish}]}
            self.wfile.write(('data: ' + json.dumps(chunk, ensure_ascii=False) + '\n\n').encode())
            self.wfile.flush()
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
        expect(self.page.get_by_role('combobox', name=re.compile('使用模型'))).to_have_value(re.compile('.+'))

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

    def test_chat_tools_files_and_child(self):
        self.post('/personal-tools/resources', {'transport': 'cli', 'toolName': 'demo_cli',
            'description': 'Diagnostic CLI', 'executable': sys.executable,
            'arguments': ['-c', 'import json,sys; v=json.load(sys.stdin); print("diagnostic" if v["mode"]=="fail" else json.dumps({"ok":True})); print("problem",file=sys.stderr); sys.exit(7 if v["mode"]=="fail" else 0)'],
            'inputSchema': {'type': 'object', 'properties': {'mode': {'type': 'string'}}, 'required': ['mode']}})
        server = self.configure_ssh()
        self.page.get_by_role('textbox', name=re.compile('^研究目标')).fill('保留这份草稿')
        self.page.get_by_role('button', name='配置我的模型', exact=True).click()
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
        self.assertTrue(any(e['type'] == 'model_content_delta' for e in turn['events']))
        requests_before_refresh = len(self.model.requests)
        self.page.reload()
        expect(self.page.get_by_text('任务完成，结果可下载。', exact=False).first).to_be_visible()
        with self.page.expect_download() as download:
            self.page.get_by_role('link', name='结果.txt', exact=True).click()
        self.assertEqual(download.value.suggested_filename, '结果.txt')
        expected_bytes = DOCUMENT.replace('状态：初稿', '状态：已复核').replace('\n', os.linesep).encode()
        self.assertEqual(Path(download.value.path()).read_bytes(), expected_bytes)
        workspace = self.state['store'].research_sessions.workspace(self.owner, snapshot['id'])
        self.assertEqual((workspace / '结果.txt').read_bytes(), expected_bytes)
        self.assertEqual((workspace / 'child.txt').read_text(encoding='utf-8'), '子助手已完成')
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
        expect(self.page.get_by_role('link', name='child.txt', exact=True)).to_be_visible()
        self.assertEqual(len(self.session()['turns']), 1)  # Refresh must not start another run.
        self.assertEqual(len(self.model.requests), requests_before_refresh)
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.page.locator('.rs-files').scroll_into_view_if_needed()
        self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth'))
        expect(self.page.get_by_role('link', name='结果.txt', exact=True)).to_be_visible()

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
        expect(self.page.get_by_text('已找到配置的 SSH 服务器', exact=False).first).to_be_visible()
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

    def test_activity_wait_disconnect_and_reconciliation_display(self):
        # UI-only snapshots isolate transport loss and missing/late events.
        self.send('ssh 可用了吗?')
        snapshot = self.wait_for(lambda s: s['turns'][-1]['status'] == 'completed')
        turn = snapshot['turns'][-1]
        old = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=30)).isoformat()
        def event(identifier, kind, data):
            return {'id': identifier, 'jobId': turn['taskId'], 'type': kind, 'message': 'UI fixture',
                    'createdAt': old, 'data': {'callId': 'display-call', 'toolName': 'ssh_run', **data}}
        turn.update(status='running', result=None, events=[event(1, 'tool_started',
            {'arguments': {'argv': ['pwd'], 'reference': 'synthetic-server'}})])
        snapshot.update(state='running', allowedActions=['correct', 'stop'])
        def stream(route):
            route.fulfill(content_type='text/event-stream', body='event: session\ndata: ' +
                          json.dumps(snapshot, ensure_ascii=False) + '\n\n')
        self.page.route('**/research/sessions/*/events', stream)
        self.page.reload()
        expect(self.page.get_by_text(re.compile('秒未收到新执行事件'))).to_be_visible()
        self.page.screenshot(path=str(Path(self.folder.name) / 'ui-fixture-waiting.png'))
        expect(self.page.get_by_text(re.compile('实时连接已断开'))).to_be_visible()
        expect(self.page.get_by_text('已开始 · 等待结果', exact=True)).to_be_visible()
        snapshot.update(state='idle', allowedActions=['start', 'stop'])
        turn.update(status='completed', result='UI fixture answer\n\n| 结果 | 状态 |\n| --- | --- |\n| SSH | 已确认 |', events=[*turn['events'],
            event(2, 'tool_finished', {'outcome': 'unknown', 'code': 'SSH_TOOL_OUTCOME_UNKNOWN'})])
        expect(self.page.get_by_text(re.compile('原工具操作结果未知'))).to_be_visible()
        self.page.screenshot(path=str(Path(self.folder.name) / 'ui-fixture-unknown.png'))
        turn['events'].append(event(3, 'tool_finished', {'outcome': 'completed', 'reconciled': True,
                                                     'output': {'stdout': '/tmp', 'exitCode': 0}}))
        expect(self.page.get_by_text(re.compile('原工具操作结果未知'))).not_to_be_visible()
        process = self.page.locator('.rs-process')
        process.locator('summary').first.click()
        expect(process.locator('.rs-tool-call')).to_have_count(1)
        expect(process.get_by_text('已完成', exact=True)).to_be_visible()
        expect(self.page.get_by_role('cell', name='SSH', exact=True)).to_be_visible()
        self.page.screenshot(path=str(Path(self.folder.name) / 'ui-fixture-reconciled.png'))
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth'))
        self.page.screenshot(path=str(Path(self.folder.name) / 'ui-fixture-mobile.png'))

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
        self.page.reload()
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
            snapshot = self.wait_for(lambda s: s['turns'][-1]['status'] in {'completed', 'failed', 'unknown', 'cancelled'})
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
