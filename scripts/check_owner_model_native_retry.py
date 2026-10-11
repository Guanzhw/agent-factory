"""Explicit offline acceptance with pinned OpenCode; never contacts a provider.

Requires the already installed Linux binary and container image as arguments.
The native session's default retry policy is left intact. All upstream outcomes
are synthetic; the container has no external network or credentials.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform'))
from agent_factory.owner_runtime_broker import OwnerRuntimeBroker
from agent_factory.personal_remote_provider import SecretLease
from agent_factory.runtime_packages.openresearch_v1.entry import environment

PIN = '77b2cfe4b97df6f15c3673b22100b9f79c711f25ecb9bf513bb82526b15d24fa'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--opencode', required=True)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    binary = Path(args.opencode).resolve()
    with binary.open('rb') as file:
        if hashlib.file_digest(file, 'sha256').hexdigest() != PIN:
            raise ValueError('NATIVE_BINARY_PIN_MISMATCH')
    if not args.image.startswith('sha256:') or len(args.image) != 71:
        raise ValueError('NATIVE_IMAGE_PIN_REQUIRED')
    root = Path(__file__).resolve().parents[1]
    package = root / 'platform/agent_factory/runtime_packages/openresearch_v1'
    results = []
    for outcome in ('disconnect', 'provider_502'):
        with TemporaryDirectory(prefix='af-native-retry-') as folder:
            private = Path(folder)
            for name in ('sockets', 'home', 'work', 'xdg/config', 'xdg/data', 'xdg/cache', 'xdg/state'):
                (private / name).mkdir(parents=True, mode=0o700, exist_ok=True)
            calls = []
            def wire(request):
                calls.append(request)
                if outcome == 'disconnect': raise httpx.ReadError('synthetic upstream disconnect')
                return httpx.Response(502, json={'error': 'synthetic upstream rejection'})
            handle = SimpleNamespace(body={'baseURL': 'https://opencode.ai/zen/go/v1', 'model': 'synthetic-owner-model'},
                service=SimpleNamespace(transport_factory=lambda: httpx.MockTransport(wire)),
                check=lambda: None, credential=lambda: SecretLease('api-key', 'synthetic-offline-credential'))
            broker = OwnerRuntimeBroker(private / 'sockets/broker.sock', handle)
            broker.start()
            name = 'af-native-retry-' + uuid4().hex
            env = environment(broker.capability, 4096)
            # Whitelist a fresh environment. Never inherit a user's API keys.
            launch_env = {'PATH': os.defpath, **env}
            command = ['docker', 'run', '--pull', 'never', '--name', name, '--network', 'none', '--read-only',
                '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--memory', '2g', '--pids-limit', '128',
                '--user', str(os.getuid()) + ':' + str(os.getgid()),
                '--tmpfs', '/tmp:rw,nosuid,nodev,size=134217728', '--workdir', '/session/work',
                '--mount', f'type=bind,src={private},dst=/session',
                '--mount', f'type=bind,src={binary},dst=/trusted/opencode-real,readonly',
                '--mount', f'type=bind,src={package / "bridge.py"},dst=/trusted/bridge.py,readonly']
            for key in env: command += ['--env', key]
            # No retry flags, request rewriting or alternate research controller.
            command += [args.image, '/bin/sh', '-c',
                '/usr/local/bin/python3 -I -B /trusted/bridge.py --bridge & '
                '/trusted/opencode-real --version; '
                '/trusted/opencode-real run --format json --model factory/owner-model --agent factory "Synthetic offline retry check"']
            try:
                run = subprocess.run(command, env=launch_env, capture_output=True, timeout=150, check=False)
                output = (run.stdout + run.stderr).decode(errors='replace')
                accepted = (len(calls) == 1 and '1.18.35' in output and 'OWNER_MODEL_CALL_UNCONFIRMED' in output
                    and 'diag_' in output and 'synthetic-offline-credential' not in output)
                results.append({'outcome': outcome, 'providerDispatches': len(calls), 'accepted': accepted,
                    'nativeVersion': '1.18.35', 'network': 'none', 'nativeRetryPolicyUnmodified': True})
            finally:
                subprocess.run(['docker', 'rm', '-f', name], capture_output=True, check=False)
                broker.close()
    print(json.dumps({'cases': results, 'accepted': all(row['accepted'] for row in results),
        'realModelCalls': 0, 'binarySha256': PIN}))
    return 0 if all(row['accepted'] for row in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
