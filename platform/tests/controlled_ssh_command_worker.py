"""SSH configuration for the existing owned command-process test worker.

The exposed listener is the internal native fixture boundary, not public OIDC.
Only SSH transport is substituted with the existing actual local helper process.
"""
from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent_factory.credential_vault import EncryptedCredentialVault
from agent_factory.execution_bindings import AdapterRegistration, EnvironmentLimits
from agent_factory.main import create_app
from agent_factory.ssh_credentials import PROVIDER_ID, SSHCredentialPolicy
from fixture_auth import initialize_members
import controlled_command_worker as original
import test_ssh_native_postgres as native


def main():
    fixture = native.SSHNativePostgresTests('runTest')
    fixture.processes = []

    def build(settings):
        fixture.folder = Path(settings.workspace).parent
        fixture.remote = fixture.folder / 'remote'
        fixture.remote.mkdir(mode=0o700, exist_ok=True)
        fixture.started, fixture.release = fixture.folder / 'starts', fixture.folder / 'release'
        fixture.model_inputs, fixture.model_results = {'width': 1, 'label': 'first'}, []
        fixture.profile = native.training_profile(fixture.remote, fixture.started, fixture.release)
        settings = replace(settings, ssh_training_profiles={'native-fixture': fixture.profile},
            runtime_adapters=[AdapterRegistration('model', 'ssh-native-model', '1',
                lambda _: native.SSHSequenceModel(fixture.model_inputs, fixture.model_results)),
                AdapterRegistration('environment', 'ssh-native-environment', '1', lambda _: EnvironmentLimits())],
            credential_vault_factory=lambda engine: EncryptedCredentialVault(engine, b'n' * 32,
                {PROVIDER_ID: SSHCredentialPolicy()}))
        fixture.app = create_app(settings)
        fixture.state = fixture.app.app.state.factory
        fixture.store, fixture.auth = fixture.state['store'], fixture.state['auth']
        initialize_members(fixture.auth)
        marker = fixture.folder / 'ssh-setup.json'
        # Bootstrap only the first controller. A restart must use original
        # resource revisions and publication pins, not regenerate credentials.
        if not marker.exists():
            fixture.client = TestClient(fixture.app, base_url='https://testserver')
            try:
                fixture.configure()
                fixture.publish()
            finally:
                fixture.client.close()
            marker.write_text(json.dumps({'connectionRef': fixture.connection}))
        return fixture.app

    original.create_app = build
    with patch('agent_factory.ssh_process_provider.pinned_ssh', side_effect=fixture.local_helper):
        try:
            original.main()
        finally:
            for process in fixture.processes:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)


if __name__ == '__main__':
    main()
