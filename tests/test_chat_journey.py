"""Two browser journeys through PostgreSQL/Agno; only the model endpoint is scripted."""
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
from unittest.mock import patch
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
from research.session_tools import ResearchSessionTools

DOCUMENT = '研究结果：文件内容保持完整。\n' * 2000


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
        tool, arguments, reply = None, {}, '任务完成，结果可下载。'
        if request['model'] == 'compression':
            reply = '压缩摘要：数值42'
        elif '"goal": "child-only"' in system:
            if not results:
                tool, arguments = 'research_edit_file', {'path': 'child.txt', 'old': '', 'new': '子助手已完成'}
            reply = '子助手已完成'
        elif 'stop-case' in system:
            if not results:
                tool, arguments = 'research_run', {'argv': [sys.executable, '-c',
                    "import os,time; from pathlib import Path; Path('started.txt').write_text(str(os.getpid())); time.sleep(600)"]}
        else:
            steps = [('demo_cli', {'mode': 'fail'}), ('demo_cli', {'mode': 'ok'}), ('ssh_servers', {}),
                     ('research_edit_file', {'path': '结果.txt', 'old': '', 'new': DOCUMENT}),
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
        cls.app = create_app(settings, session_tools=ResearchSessionTools(workspace_root=root / 'research'))
        cls.state = factory_state(cls.app)
        cls.server = uvicorn.Server(uvicorn.Config(cls.app, ssl_certfile=str(root / 'cert.pem'),
            ssl_keyfile=str(root / 'key.pem'), log_level='warning', access_log=False))
        thread = threading.Thread(target=lambda: cls.server.run(sockets=[listener]), daemon=True)
        thread.start()
        def shutdown():
            cls.server.should_exit = True
            thread.join(20)
            if thread.is_alive():
                raise RuntimeError('Application did not stop')
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
        self.assertIn({'exitCode': 7, 'stdout': 'diagnostic\n', 'stderr': 'problem\n'}, outputs)
        self.assertIn({'ok': True}, outputs)
        self.assertEqual(len(turn['children']), 1)
        self.assertEqual(turn['children'][0]['status'], 'completed')
        self.assertIn('子助手已完成', turn['children'][0]['result'])
        # The next real HTTP model request must contain the tool's discovered server.
        self.assertTrue(any(server['reference'] in json.dumps(r['messages']) for r in self.model.requests))
        self.assertTrue(any(e['type'] == 'model_content_delta' for e in turn['events']))
        requests_before_refresh = len(self.model.requests)
        self.page.reload()
        expect(self.page.get_by_text('任务完成，结果可下载。', exact=False).first).to_be_visible()
        with self.page.expect_download() as download:
            self.page.get_by_role('link', name='结果.txt', exact=True).click()
        self.assertEqual(download.value.suggested_filename, '结果.txt')
        self.assertEqual(Path(download.value.path()).read_bytes(), DOCUMENT.encode())
        expect(self.page.get_by_role('link', name='child.txt', exact=True)).to_be_visible()
        self.assertEqual(len(self.session()['turns']), 1)  # Refresh must not start another run.
        self.assertEqual(len(self.model.requests), requests_before_refresh)
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.page.locator('.rs-files').scroll_into_view_if_needed()
        self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth'))
        expect(self.page.get_by_role('link', name='结果.txt', exact=True)).to_be_visible()

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

    def test_stop_running_command(self):
        self.send('stop-case')
        snapshot = self.wait_for(lambda s: any(e['type'] == 'research_tool_started'
            for e in s['turns'][-1]['events']))
        files = self.origin + '/api/factory/research/sessions/' + snapshot['id'] + '/files'
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            response = self.context.request.get(files + '/download?path=started.txt')
            if response.ok:
                break
            self.page.wait_for_timeout(100)
        self.assertTrue(response.ok, 'Command did not start')
        pid = int(response.text())
        os.kill(pid, 0)  # Prove the command is still alive before exercising Stop.
        self.page.get_by_role('button', name='请求停止', exact=True).click()
        snapshot = self.wait_for(lambda s: s['state'] == 'stopped')
        self.assertIn(snapshot['turns'][-1]['status'], ['cancelled', 'canceled'])
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.page.reload()
        self.assertEqual(len(self.session()['turns']), 1)


if __name__ == '__main__':
    unittest.main()
