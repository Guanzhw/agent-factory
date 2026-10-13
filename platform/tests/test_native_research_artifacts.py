"""Pinned native file contract and link-safe selected platform reader; keyless."""
import hashlib
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from urllib.parse import parse_qs, urlsplit

from agent_factory.personal_orx_transport import PersonalOrxHandle, PersonalOrxHTTPS, PersonalOrxProvider, worktree_file_path
from agent_factory.personal_remote_provider import RemoteConnectionError
from agent_factory.platform_openresearch import PlatformOrxProvider
from test_personal_agent_sessions import Secrets
from test_personal_orx_transport import NativeOrxWire


class ArtifactWire(NativeOrxWire):
    def __init__(self, root):
        super().__init__()
        self.root, self.rewrite, self.file_calls = Path(root), None, []

    def request(self, destination, address, method, path, lease, payload=None):
        parsed = urlsplit(path)
        if parsed.path.endswith('/worktree'):
            self.calls.append((method, path, payload, lease is not None))
            value = {'exists': True, 'files': [{'path': str(f.relative_to(self.root)), 'status': 'untracked'}
                for f in sorted(self.root.rglob('*')) if f.is_file()]}
            return 200, value
        if parsed.path.endswith('/file'):
            assert self.allows(method, path, payload)
            values = parse_qs(parsed.query)
            self.file_calls.append(values)
            raw = (self.root / values['path'][0]).read_bytes()
            value = {'path': values['path'][0], 'root': 'worktree', 'content': raw.decode(),
                'notFound': False, 'binary': False, 'truncated': False, 'version': hashlib.sha256(raw).hexdigest()}
            if self.rewrite: self.rewrite(value)
            return 200, value
        return super().request(destination, address, method, path, lease, payload)


class ArtifactFixtureProvider(PersonalOrxProvider):
    # Trusted fixture installation; no real endpoint, model or credential.
    provider_id = 'platform-openresearch-session-v1'

    def worktree_file_bytes(self, owner, configuration, session_id, path):
        if not self.authorized(owner, configuration): raise RemoteConnectionError('fixture-revoked')
        return (self.transport(configuration).root / path).read_bytes()


class NativeArtifactWireTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); (self.root/'report.txt').write_text('Actual fixture bytes\n')
        self.wire = ArtifactWire(self.root)
        self.provider = ArtifactFixtureProvider(Secrets(), transport=self.wire)
        self.config = {'origin': 'https://runtime.example.com', 'credentialRef': 'synthetic-reference',
            'credentialRevision': 'r1', 'projectId': 'native-project', 'authMode': 'basic-proxy'}
        self.handle = PersonalOrxHandle(self.provider, 'alice', self.config, lambda _: None)

    def test_native_inventory_and_exact_file_bytes_are_not_inferred_from_chat(self):
        (self.root/'reports').mkdir(); (self.root/'reports/比较.tsv').write_text('item\tvalue\nA\t7\n')
        (self.root/'.env').write_text('Private fixture control')
        (self.root/'opencode.json').write_text('Runtime fixture control')
        self.assertEqual(self.handle.worktree_files('chat_original'), ['report.txt', 'reports/比较.tsv'])
        self.assertEqual(self.handle.worktree_file('chat_original', 'reports/比较.tsv'), b'item\tvalue\nA\t7\n')
        self.assertEqual(self.wire.file_calls[-1]['sessionId'], ['chat_original'])
        self.assertEqual(self.wire.prompts, 0)

    def test_whitelist_rejects_traversal_absolute_hidden_duplicate_extra_and_blank_queries(self):
        for path in ['../secret', '/secret', 'a/../secret', 'a//b', './b', 'a\\b', '.env', 'a/.git/key', 'opencode.json', 'a%2fb']:
            self.assertFalse(worktree_file_path(path), path)
        prefix = '/api/projects/native-project/file?'
        for query in ['path=../x&sessionId=chat_original', 'path=x&sessionId=chat_original&ref=main',
                'path=x&path=y&sessionId=chat_original', 'path=x&sessionId=',
                'path=x&sessionId=chat_original&unused=', 'path=%252e%252e%252fx&sessionId=chat_original']:
            self.assertFalse(PersonalOrxHTTPS.allows('GET', prefix+query, None), query)
        self.assertFalse(PersonalOrxHTTPS.allows('POST', prefix+'path=x&sessionId=chat_original', {}))
        self.assertFalse(PersonalOrxHTTPS.allows('GET', '/api/file?path=/etc/passwd', None))

    def test_file_hash_truncation_binary_clone_fallback_and_secret_echo_fail_closed(self):
        for changes in [{'version':'0'*64}, {'truncated':True}, {'binary':True}, {'root':'clone'}, {'notFound':True},
                {'content':'synthetic-test-password'}]:
            self.wire.rewrite = lambda value, changes=changes: value.update(changes)
            with self.assertRaises(RemoteConnectionError): self.handle.worktree_file('chat_original', 'report.txt')
        self.assertEqual(self.wire.prompts, 0)

    def test_other_project_session_and_unreviewed_remote_reader_are_rejected(self):
        self.wire.rows['chat_original']['projectId'] = 'foreign-project'
        with self.assertRaises(RemoteConnectionError): self.handle.worktree_files('chat_original')
        self.assertEqual(self.wire.file_calls, [])
        self.wire.rows['chat_original']['projectId'] = 'native-project'
        plain = PersonalOrxProvider(Secrets(), transport=self.wire)
        handle = PersonalOrxHandle(plain, 'alice', self.config, lambda _: None)
        with self.assertRaises(RemoteConnectionError): handle.worktree_file('chat_original', 'report.txt')
        self.assertEqual(self.wire.file_calls, [])


class NativePlatformFileReaderTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.project, self.session, self.env = 'project-fixture', 'chat_original', 'env-'+'a'*32
        self.work = root/'orx/worktrees'/self.project/self.session; self.work.mkdir(parents=True)
        self.file = self.work/'report.txt'; self.file.write_bytes(b'Native actual bytes\n')
        body = {'ownerId':'alice','projectId':self.project}
        self.package = SimpleNamespace(live={self.env:{'root':root,'body':body}},
            connection_revision=lambda _: 'r1',check=lambda _: True)
        self.provider = PlatformOrxProvider(self.package)
        self.config = {'origin':'https://'+self.env+'.platform.invalid','credentialRef':self.env,
            'credentialRevision':'r1','projectId':self.project,'authMode':'bearer'}

    def unsupported_host(self):
        if sys.platform == 'linux': return False
        with self.assertRaises(RemoteConnectionError):
            self.provider.worktree_file_bytes('alice',self.config,self.session,'report.txt')
        return True

    def test_reads_exact_scoped_regular_file_and_rejects_foreign_owner_revision_project(self):
        if self.unsupported_host(): return
        self.assertEqual(self.provider.worktree_file_bytes('alice',self.config,self.session,'report.txt'),self.file.read_bytes())
        for owner, config in [('bob',self.config), ('alice',{**self.config,'credentialRevision':'r2'}),
                ('alice',{**self.config,'projectId':'other-project'})]:
            with self.assertRaises(ValueError): self.provider.worktree_file_bytes(owner,config,self.session,'report.txt')

    def test_final_and_parent_symlinks_hardlinks_and_special_files_are_never_followed(self):
        if self.unsupported_host(): return
        (self.work/'alias.txt').symlink_to(self.file)
        (self.work/'linked').symlink_to(self.work,target_is_directory=True)
        os.link(self.file,self.work/'hard.txt')
        os.mkfifo(self.work/'pipe.txt')
        for path in ['alias.txt','linked/report.txt','hard.txt','report.txt','pipe.txt']:
            with self.assertRaises(RemoteConnectionError): self.provider.worktree_file_bytes('alice',self.config,self.session,path)

    def test_missing_oversized_private_and_traversal_are_rejected_without_reading(self):
        if self.unsupported_host(): return
        (self.work/'large.txt').write_bytes(b'x'*512001)
        for path in ['missing.txt','large.txt','.env','../report.txt']:
            with self.assertRaises(ValueError): self.provider.worktree_file_bytes('alice',self.config,self.session,path)

    def test_credential_revocation_after_read_does_not_return_bytes(self):
        if self.unsupported_host(): return
        count = [0]
        def check(_):
            count[0] += 1
            return count[0] < 2
        self.package.check = check
        with self.assertRaises(RemoteConnectionError): self.provider.worktree_file_bytes('alice',self.config,self.session,'report.txt')
