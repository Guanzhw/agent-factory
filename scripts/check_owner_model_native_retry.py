"""Explicit offline acceptance with pinned OpenCode; never contacts a provider.

Requires the already installed Linux binary and container image as arguments.
The native session's default retry policy is left intact. All upstream outcomes
are synthetic; the container has no external network or credentials.
"""
import argparse
import hashlib
import json
import os
import socket
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
    parser.add_argument('--case', choices=('disconnect', 'provider_502', 'downstream_response_lost', 'normal_two_turns'))
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
    for outcome in ((args.case,) if args.case else ('disconnect', 'provider_502', 'downstream_response_lost', 'normal_two_turns')):
        with TemporaryDirectory(prefix='af-native-retry-') as folder:
            private = Path(folder)
            for name in ('sockets', 'home', 'work', 'xdg/config', 'xdg/data', 'xdg/cache', 'xdg/state'):
                (private / name).mkdir(parents=True, mode=0o700, exist_ok=True)
            calls = []
            def wire(request):
                calls.append(request)
                if outcome == 'disconnect': raise httpx.ReadError('synthetic upstream disconnect')
                if outcome == 'provider_502': return httpx.Response(502, json={'error': 'synthetic upstream rejection'})
                return httpx.Response(200, json={'id': 'chatcmpl-synthetic', 'object': 'chat.completion', 'created': 1,
                    'model': 'synthetic-owner-model', 'choices': [{'index': 0,
                        'message': {'role': 'assistant', 'content': 'Synthetic settled reply'}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})
            handle = SimpleNamespace(body={'baseURL': 'https://opencode.ai/zen/go/v1', 'model': 'synthetic-owner-model'},
                service=SimpleNamespace(transport_factory=lambda: httpx.MockTransport(wire)),
                check=lambda: None, credential=lambda: SecretLease('api-key', 'synthetic-offline-credential'))
            broker = OwnerRuntimeBroker(private / 'sockets/broker.sock', handle)
            broker.start()
            ingress, dropped = [], []
            handler = broker.server.RequestHandlerClass
            original = handler.send_response
            def observe_reply(self, code, message=None):
                ingress.append({'status': code, 'session': self.headers.get('x-opencode-session-id'),
                    'nativeRequest': self.headers.get('x-opencode-request')})
                if outcome == 'downstream_response_lost' and code == 200 and not dropped:
                    dropped.append(True)
                    self.connection.shutdown(socket.SHUT_RDWR)
                    raise BrokenPipeError('synthetic lost downstream response after provider settled')
                return original(self, code, message)
            handler.send_response = observe_reply
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
                '/trusted/opencode-real run --format json --model opencode-factory/owner-model --agent factory "Synthetic offline retry check"'
                + ('; /trusted/opencode-real run --continue --format json --model opencode-factory/owner-model --agent factory "Synthetic offline retry check"'
                   if outcome == 'normal_two_turns' else '')]
            try:
                run = subprocess.run(command, env=launch_env, capture_output=True, timeout=150, check=False)
                output = (run.stdout + run.stderr).decode(errors='replace')
                error_case = outcome in {'disconnect', 'provider_502'}
                accepted = (len(calls) == (2 if outcome == 'normal_two_turns' else 1) and '1.18.35' in output
                    and ('OWNER_MODEL_CALL_UNCONFIRMED' in output and 'diag_' in output if error_case
                         else 'Synthetic settled reply' in output)
                    and 'synthetic-offline-credential' not in output)
                sessions = [request.headers.get('x-opencode-session') for request in calls]
                if outcome == 'normal_two_turns':
                    accepted = accepted and len(set(sessions)) == 1 and len({r['nativeRequest'] for r in ingress}) == 2
                results.append({'outcome': outcome, 'providerDispatches': len(calls), 'accepted': accepted,
                    'nativeVersion': '1.18.35', 'network': 'none', 'nativeRetryPolicyUnmodified': True,
                    'ingress': ingress,
                    'providerSessionIds': sessions,
                    'providerBodyHashes': [hashlib.sha256(request.content).hexdigest() for request in calls]})
            finally:
                subprocess.run(['docker', 'rm', '-f', name], capture_output=True, check=False)
                broker.close()
    print(json.dumps({'cases': results, 'accepted': all(row['accepted'] for row in results),
        'realModelCalls': 0, 'binarySha256': PIN}))
    return 0 if all(row['accepted'] for row in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
