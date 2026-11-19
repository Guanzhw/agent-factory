"""Exercise file retries and lazy previews through the browser and public upload endpoint."""
import subprocess
import sys
import unittest
from tempfile import TemporaryDirectory
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect

from test_chat_journey import ChatJourney


class SessionFileJourney(ChatJourney):
    def test_retry_after_lost_response_and_intentional_second_upload(self):
        self.send('Reply with OK.')
        session = self.wait_for(lambda row: row['turns'][-1]['status'] == 'completed')
        path = self.state['research_sessions'].workspace(self.owner, session['id'])
        file = Path(self.folder.name) / 'input.txt'
        file.write_text('first upload', encoding='utf8')
        control = self.page.get_by_label('上传会话文件')
        self.page.evaluate("""() => {
            const original = window.fetch;
            window.fetch = async (...args) => {
                const response = await original(...args);
                if (response.url.includes('/files?requestId=') && response.status === 201) {
                    window.fetch = original;
                    throw new TypeError('response lost');
                }
                return response;
            };
        }""")
        control.set_input_files(file)
        expect(self.page.locator('.rs-composer').get_by_role('alert')).to_be_visible()
        self.page.reload()
        control.set_input_files(file)
        expect(self.page.get_by_label('下一轮指令')).to_have_value('附件：input.txt（12 字节）')
        self.assertEqual(sorted(p.name for p in path.iterdir()), ['input.txt'])
        control.set_input_files(file)
        expect(self.page.get_by_label('下一轮指令')).to_have_value(
            '附件：input.txt（12 字节）\n附件：input (2).txt（12 字节）')
        self.assertEqual((path / 'input (2).txt').read_bytes(), file.read_bytes())

    def test_hidden_panel_and_growth_since_listing(self):
        listing = []
        self.page.on('request', lambda r: listing.append(r.url) if '/files?directory=' in r.url else None)
        self.send('Reply with OK.')
        session = self.wait_for(lambda row: row['turns'][-1]['status'] == 'completed')
        workspace = self.state['research_sessions'].workspace(self.owner, session['id'])
        log = workspace / 'growing.log'
        log.touch()
        self.assertEqual(listing, [])
        self.page.get_by_role('button', name='会话文件', exact=True).click()
        item = self.page.locator('.rs-files li').filter(has_text='growing.log')
        item.get_by_role('button', name='预览', exact=True).click()
        expect(item.locator('pre')).to_have_text('')
        item.get_by_role('button', name='关闭预览').click()
        log.write_bytes(b'x' * 65537)
        item.get_by_role('button', name='预览', exact=True).click()
        expect(item.get_by_role('button', name='继续读取')).to_be_visible()
        self.assertEqual(len(item.locator('pre').inner_text()), 65536)

    def test_upload_receipt_after_move_replacement_and_request_conflict(self):
        self.send('Reply with OK.')
        session = self.wait_for(lambda row: row['turns'][-1]['status'] == 'completed')
        workspace = self.state['research_sessions'].workspace(self.owner, session['id'])
        key = uuid4()
        url = self.origin + f"/api/factory/research/sessions/{session['id']}/files?requestId={key}"
        def upload(name, body):
            return self.context.request.post(url, headers={'Origin': self.origin, 'X-Factory-CSRF': self.csrf},
                multipart={'file': {'name': name, 'mimeType': 'text/plain', 'buffer': body}})
        paths = self.page.evaluate("""async ([url, csrf]) => {
            async function send() {
                const data = new FormData();
                data.append('file', new Blob(['first']), 'a.txt');
                const response = await fetch(url, { method: 'POST', headers: {'X-Factory-CSRF': csrf}, body: data });
                return (await response.json()).path;
            }
            return Promise.all([send(), send()]);
        }""", [url, self.csrf])
        self.assertEqual(paths, ['a.txt', 'a.txt'])
        self.assertEqual(upload('b.txt', b'first').status, 409)
        self.assertEqual(upload('a.txt', b'other').status, 409)
        (workspace / 'a.txt').rename(workspace / 'moved')
        self.assertEqual(upload('a.txt', b'first').status, 409)
        (workspace / 'a.txt').write_bytes(b'replacement')
        self.assertEqual(upload('a.txt', b'first').status, 409)
        self.assertEqual((workspace / 'a.txt').read_bytes(), b'replacement')
        self.assertEqual(sorted(p.name for p in workspace.iterdir()), ['a.txt', 'moved'])


class InterruptedFilePublication(unittest.TestCase):
    def test_retry_before_and_after_publication(self):
        from fastapi import HTTPException
        from research.session_files import publish_upload, staged_upload

        child = """
import os, sys
from io import BytesIO
from pathlib import Path
from research import session_files
workspace = Path(sys.argv[1])
publish = session_files._publish_file
def interrupt(*args):
    if sys.argv[2] == 'after': publish(*args)
    os._exit(7)
session_files._publish_file = interrupt
with session_files.staged_upload(workspace, 'a.txt', BytesIO(b'data')) as (staged, checksum):
    assert not list(workspace.iterdir())
    session_files.publish_upload(workspace, 'a.txt', staged, workspace.parent / 'receipt', checksum)
"""
        for when in ('before', 'after'):
            with self.subTest(when=when), TemporaryDirectory() as root:
                workspace = Path(root) / 'workspace'
                workspace.mkdir()
                self.assertEqual(subprocess.run([sys.executable, '-c', child, str(workspace), when]).returncode, 7)
                with staged_upload(workspace, 'a.txt', BytesIO(b'change')) as (staged, checksum):
                    with self.assertRaises(HTTPException) as conflict:
                        publish_upload(workspace, 'a.txt', staged, Path(root) / 'receipt', checksum)
                    self.assertEqual(conflict.exception.status_code, 409)
                with staged_upload(workspace, 'a.txt', BytesIO(b'data')) as (staged, checksum):
                    name = publish_upload(workspace, 'a.txt', staged, Path(root) / 'receipt', checksum)
                self.assertEqual(name, 'a.txt')
                self.assertEqual(list(workspace.iterdir()), [workspace / name])
                self.assertEqual((workspace / name).read_bytes(), b'data')
                self.assertEqual(sorted(p.name for p in Path(root).iterdir()), ['receipt', 'workspace'])


def load_tests(loader, tests, pattern):
    suite = loader.loadTestsFromTestCase(InterruptedFilePublication)
    suite.addTests(SessionFileJourney(name) for name in SessionFileJourney.__dict__ if name.startswith('test_'))
    return suite
