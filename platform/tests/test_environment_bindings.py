"""Credential continuation never rewrites native identity or dispatches work."""
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from agent_factory.application_environments import PrepareEnvironment, RebindEnvironment
from agent_factory_research.runtime_packages.openresearch_v1 import ssh_install
import test_application_environments as fixtures


class EnvironmentBindingTests(fixtures.ApplicationEnvironmentTests):
    def row(self, owner, identifier):
        with self.service.db.read() as conn: return self.service._row(conn, owner, identifier)

    def test_different_actual_ssh_install_bytes_require_new_directory_and_preserve_original_package(self):
        root = Path(self.folder.name)
        root.chmod(0o700)
        version = ['old-synthetic-package']
        original_prepare = self.package.prepare
        def install_bytes(directory):
            files = {name: (version[0] + ':' + name).encode() for name in sorted(ssh_install.FILES)}
            manifest = {'allowedRoot': str(root), 'directory': directory, 'image': 'sha256:'+'a'*64,
                'nonce': 'a'*24, 'files': {name: {'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()} for name,raw in files.items()}}
            raw = json.dumps(manifest).encode()+b'\n'+b''.join(files.values())
            inventory = SimpleNamespace(returncode=0, stdout=(manifest['image']+'\n').encode())
            # Execute the unchanged installer against real private files. Only
            # Docker inventory is synthetic; no image or runtime is launched.
            with patch.object(ssh_install.sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(raw))), \
                    patch.object(ssh_install.subprocess, 'run', return_value=inventory):
                ssh_install.install()
        def prepare(body, handle):
            install_bytes(body['remoteDirectory']); original_prepare(body,handle)
        ssh = SimpleNamespace(**self.package.__dict__)
        ssh.prepare = prepare
        ssh.selection = lambda owner, ref, directory: {'location':'ssh','serverRef':ref,
            'remoteDirectory':directory,'serverRevision':'one','serverPin':'one','serverScopePin':'owned-host'}
        self.service.packages['openresearch:ssh'] = ssh
        directory = str(root/'old-data')
        previous_umask = os.umask(0o077); self.addCleanup(os.umask, previous_umask)
        old = self.service.prepare('alice','openresearch','ssh-install-original',location='ssh',server_ref='owned',directory=directory)['environment']
        package = Path(directory)/'factory_package'
        original_bytes = {p.name:p.read_bytes() for p in package.iterdir()}
        retained = Path(directory)/'retained-research.txt'; retained.write_text('SYNTHETIC ORIGINAL DATA')
        version[0] = 'different-synthetic-package'; ssh.version = 'fixture-package-2'
        preview = self.service.bindings.preview('alice',old['id'])
        self.assertEqual(preview['reason'],'ENVIRONMENT_SSH_PACKAGE_UPDATE_UNSUPPORTED')
        self.assertEqual(preview['nextAction'],'choose-new-location'); self.assertFalse(preview['canRebind'])
        with self.assertRaises(HTTPException) as refused:
            self.service.prepare('alice','openresearch','ssh-upgrade-denied',location='ssh',server_ref='owned',directory=directory,new_environment=True)
        self.assertEqual(refused.exception.detail,'ENVIRONMENT_SSH_PACKAGE_UPDATE_UNSUPPORTED')
        self.assertEqual(len(self.prepares),1)
        with self.assertRaises(ValueError): install_bytes(directory)
        self.assertEqual({name:(package/name).read_bytes() for name in original_bytes},original_bytes)
        new = self.service.prepare('alice','openresearch','ssh-install-new-directory',location='ssh',server_ref='owned',directory=str(root/'new-data'),new_environment=True)['environment']
        self.assertNotEqual(new['id'],old['id']); self.assertNotEqual(new['projectId'],old['projectId'])
        self.assertNotEqual((Path(new['remoteDirectory'])/'factory_package'/'entry.py').read_bytes(),original_bytes['entry.py'])
        self.assertEqual(retained.read_text(),'SYNTHETIC ORIGINAL DATA'); self.assertEqual(self.research,[])

    def test_explicit_stopped_model_binding_preserves_original_body_and_never_prepares_or_prompts(self):
        first = self.service.prepare('alice', 'openresearch', 'original-prepare')
        identifier = first['environment']['id']; original = deepcopy(self.row('alice', identifier))
        self.model_revision = 'rotated-model'
        live = self.service.bindings.preview('alice', identifier)
        self.assertFalse(live['canRebind']); self.assertEqual(live['nextAction'], 'stop-environment')
        with self.assertRaises(HTTPException): self.service.bindings.rebind('alice', identifier, 'deny-live-bind', live['previewHash'])
        self.service.stop('alice', identifier, 'original-stop')
        preview = self.service.bindings.preview('alice', identifier)
        self.assertTrue(preview['canRebind']); self.assertTrue(preview['sessionRebindRequired'])
        result = self.service.bindings.rebind('alice', identifier, 'confirm-model-bind', preview['previewHash'])
        self.assertFalse(result['runtimePrepared']); self.assertFalse(result['researchSubmitted'])
        self.assertEqual(len(self.prepares), 1)
        row = self.row('alice', identifier)
        self.assertEqual(row['body'], original['body']); self.assertEqual(row['body_hash'], original['body_hash'])
        self.assertEqual(row['credential_binding']['modelRevision'], 'rotated-model')
        handle = self.service.model_handle('alice', row['body'])
        self.assertTrue(handle.environment_credential_revision.startswith('env-binding-')); handle.check()
        restored = self.service.prepare('alice', 'openresearch', 'explicit-original-restore')
        self.assertEqual(restored['environment']['projectId'], first['environment']['projectId'])
        self.assertEqual(restored['environment']['modelRevision'], 'rotated-model')
        self.assertEqual(restored['environment']['originalModelRevision'], 'fixture-model-revision')
        self.assertEqual(len(self.allocations), 1); self.assertEqual(self.research, [])
        self.revoked = True
        with self.assertRaises(HTTPException): handle.check()

    def test_rebind_receipt_stale_preview_owner_and_changed_intent_are_fenced(self):
        env = self.service.prepare('alice', 'openresearch', 'scope-prepare')['environment']
        self.service.stop('alice', env['id'], 'scope-stop'); self.model_revision = 'model-2'
        preview = self.service.bindings.preview('alice', env['id'])
        self.model_revision = 'model-3'
        with self.assertRaises(HTTPException): self.service.bindings.rebind('alice', env['id'], 'stale-confirm', preview['previewHash'])
        preview = self.service.bindings.preview('alice', env['id'])
        first = self.service.bindings.rebind('alice', env['id'], 'original-confirm', preview['previewHash'])
        again = self.service.bindings.rebind('alice', env['id'], 'original-confirm', preview['previewHash'])
        self.assertEqual(first, again); self.assertEqual(len(self.service.bindings.history('alice', env['id'])), 1)
        with self.assertRaises(HTTPException): self.service.bindings.rebind('alice', env['id'], 'original-confirm', 'a' * 64)
        with self.assertRaises(HTTPException) as foreign: self.service.bindings.request('bob', 'original-confirm')
        self.assertEqual(foreign.exception.status_code, 404)
        self.assertEqual(len(self.prepares), 1); self.assertEqual(self.research, [])

    def test_cached_handle_loses_authority_after_another_explicit_binding(self):
        env = self.service.prepare('alice', 'openresearch', 'cached-prepare')['environment']
        self.service.stop('alice', env['id'], 'cached-stop'); self.model_revision = 'model-2'
        preview = self.service.bindings.preview('alice', env['id'])
        self.service.bindings.rebind('alice', env['id'], 'cached-bind-2', preview['previewHash'])
        original = self.row('alice', env['id']); handle = self.service.model_handle('alice', original['body']); handle.check()
        self.model_revision = 'model-3'; preview = self.service.bindings.preview('alice', env['id'])
        self.service.bindings.rebind('alice', env['id'], 'cached-bind-3', preview['previewHash'])
        with self.assertRaises(HTTPException) as changed: handle.check()
        self.assertEqual(changed.exception.detail, 'ENVIRONMENT_BINDING_CHANGED')
        self.assertEqual(self.row('alice', env['id'])['body'], original['body'])

    def test_ssh_key_rotation_requires_same_stable_host_user_root_and_rejects_legacy_guess(self):
        revision, scope = ['server-1'], ['same-host-user-root']
        def selection(owner, reference, directory):
            return {'location': 'ssh', 'serverRef': reference, 'serverRevision': revision[0],
                'serverPin': revision[0], 'identityPin': 'key-' + revision[0], 'remoteDirectory': directory,
                'serverScopePin': scope[0]}
        ssh = SimpleNamespace(**self.package.__dict__); ssh.selection = selection
        self.service.packages['openresearch:ssh'] = ssh
        env = self.service.prepare('alice', 'openresearch', 'ssh-scope-first', location='ssh',
            server_ref='owned-server', directory='/private/alice/research')['environment']
        original = self.row('alice', env['id'])
        self.service.stop('alice', env['id'], 'ssh-scope-stop'); revision[0] = 'server-2'
        preview = self.service.bindings.preview('alice', env['id']); self.assertTrue(preview['canRebind'])
        self.service.bindings.rebind('alice', env['id'], 'ssh-scope-confirm', preview['previewHash'])
        self.assertEqual(self.row('alice', env['id'])['body'], original['body'])
        scope[0] = 'different-host'; bad = self.service.bindings.preview('alice', env['id'])
        self.assertEqual(bad['classification'], 'needs-new-run'); self.assertFalse(bad['canRebind'])
        self.assertEqual(bad['reason'], 'ENVIRONMENT_SERVER_SCOPE_CHANGED')
        with self.assertRaises(HTTPException): self.service.bindings.rebind('alice', env['id'], 'ssh-scope-denied', preview['previewHash'])
        # A legacy body without stable host-scope evidence cannot infer that a
        # different server/key pin still refers to the same authorized host.
        def legacy(owner, reference, directory):
            return {key: value for key, value in selection(owner, reference, directory).items() if key != 'serverScopePin'}
        ssh.selection = legacy; scope[0] = 'same-host-user-root'
        old = self.service.prepare('alice', 'openresearch', 'legacy-scope-first', location='ssh',
            server_ref='owned-server', directory='/private/alice/legacy')['environment']
        self.service.stop('alice', old['id'], 'legacy-scope-stop'); revision[0] = 'server-3'; ssh.selection = selection
        refused = self.service.bindings.preview('alice', old['id'])
        self.assertEqual(refused['reason'], 'ENVIRONMENT_SERVER_SCOPE_CHANGED'); self.assertFalse(refused['canRebind'])

    def test_unknown_and_package_update_offer_reconciliation_or_explicit_new_environment_without_replay(self):
        self.failed = True
        old = self.service.prepare('alice', 'openresearch', 'unknown-original')['environment']
        preview = self.service.bindings.preview('alice', old['id'])
        self.assertEqual(preview['classification'], 'results-only'); self.assertEqual(preview['nextAction'], 'read-original-request')
        self.assertFalse(preview['originalWorkReplay']); self.assertEqual(len(self.prepares), 1)
        self.package.version = 'fixture-package-2'; self.failed = False
        changed = self.service.bindings.preview('alice', old['id'])
        self.assertEqual(changed['classification'], 'needs-new-run'); self.assertEqual(changed['nextAction'], 'new-environment')
        new = self.service.prepare('alice', 'openresearch', 'explicit-new-generation', new_environment=True)['environment']
        self.assertNotEqual(new['id'], old['id']); self.assertNotEqual(new['projectId'], old['projectId'])
        self.assertEqual(self.service.inspect('alice', old['id'])['projectId'], old['projectId'])
        repeated = self.service.prepare('alice', 'openresearch', 'explicit-new-generation', new_environment=True)['environment']
        self.assertEqual(repeated['id'], new['id']); self.assertEqual(len(self.prepares), 2); self.assertEqual(self.research, [])

    def test_new_environment_and_binding_consent_use_strict_booleans(self):
        for flag in ('true', 1, None):
            with self.subTest(flag=flag), self.assertRaises(ValidationError): PrepareEnvironment(requestId='strict-new-environment', newEnvironment=flag)
            with self.subTest(flag=flag), self.assertRaises(ValidationError): RebindEnvironment(requestId='strict-new-binding', previewHash='a' * 64, approved=flag)


for _name in dir(fixtures.ApplicationEnvironmentTests):
    if _name.startswith('test_'): setattr(EnvironmentBindingTests, _name, None)

if __name__ == '__main__': unittest.main()
