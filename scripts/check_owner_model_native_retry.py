"""Explicit offline acceptance with pinned OpenCode; never contacts a provider.

Requires the already installed Linux binary and container image as arguments.
The native session's default retry policy is left intact. All upstream outcomes
are synthetic; the container has no external network or credentials. Tool cases
run the native read tool twice; CC continues the same native session once more.
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

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / part)
    for part in ('platform', 'deployment')]
from agent_factory.owner_runtime_broker import OwnerRuntimeBroker
from agent_factory.personal_remote_provider import SecretLease
from owner_model_native_fixture import environment

PIN = '77b2cfe4b97df6f15c3673b22100b9f79c711f25ecb9bf513bb82526b15d24fa'
CASES = ('disconnect', 'provider_502', 'downstream_response_lost', 'normal_two_turns',
         'cc_tool_rounds', 'responses_tool_rounds', 'cc_compaction', 'responses_compaction')


def tool_reply(protocol, turn, *, read_index=None, text='Synthetic settled reply'):
    """Only fixed synthetic read calls; the native executable owns execution."""
    read_index = turn if read_index is None and turn < 3 else read_index
    arguments = json.dumps({'filePath': '/session/work/synthetic-' + str(read_index) + '.txt'}, indent=1)
    if protocol == 'responses':
        output = [{'type': 'reasoning', 'id': f'rs_synthetic{turn}', 'summary': [],
                   'encrypted_content': f'synthetic-private-reasoning-{turn}'}]
        if read_index is not None:
            output.append({'type': 'function_call', 'id': f'fc_synthetic{turn}',
                'call_id': f'call_synthetic{turn}', 'name': 'read', 'arguments': arguments})
        else:
            output.append({'type': 'message', 'role': 'assistant', 'content': [
                {'type': 'output_text', 'text': text}]})
        return {'status': 'completed', 'output': output}
    message = {'role': 'assistant', 'content': text,
               'reasoning_content': f'synthetic-private-reasoning-{turn}'}
    if read_index is not None:
        message.update(content=None, tool_calls=[{'id': f'call_synthetic{turn}', 'type': 'function',
            'function': {'name': 'read', 'arguments': arguments}}])
    return {'choices': [{'index': 0, 'message': message,
                        'finish_reason': 'tool_calls' if read_index is not None else 'stop'}]}


def compaction_evidence(calls, native_bodies, protocol, output):
    reports = []
    for line in output.splitlines():
        try: value = json.loads(line)
        except ValueError: continue
        if isinstance(value, dict) and value.get('nativeCompaction'): reports.append(value)
    report = reports[-1] if reports else {}
    parts = [part for message in report.get('messages', []) for part in message['parts']]
    reads = [part for part in parts if part.get('tool') == 'read' and part.get('status') == 'completed'
             and part.get('readOutputVerified')]
    manual = [part for part in parts if part['type'] == 'compaction' and part['auto'] is False]
    original_finals = []
    for message in report.get('messages', []):
        if message['summary']: break
        if message['role'] == 'assistant' and message['finish'] == 'stop':
            original_finals.append(''.join(part['text'] for part in message['parts'] if part['type'] == 'text'))
    repeated = original_finals == ['Synthetic settled reply', 'Synthetic settled reply']
    restored = False
    retained_tail = any(part.get('tailStartId') for part in manual)
    if len(calls) == 8:
        body = json.loads(calls[-1].content)
        if protocol == 'chat-completions':
            reasoning = [message.get('reasoning_content') for message in body['messages'] if message['role'] == 'assistant']
        else:
            reasoning = [item.get('encrypted_content') for item in body['input'] if item.get('type') == 'reasoning']
        restored = reasoning == ['synthetic-private-reasoning-5', 'synthetic-private-reasoning-4',
                                'synthetic-private-reasoning-6', 'synthetic-private-reasoning-7']
    return {'protocol': protocol, 'explicitNativeCompaction': len(manual) == 1,
        'summaryComplete': report.get('summaryComplete', False), 'continuedComplete': report.get('continuedComplete', False),
        'nativeCompletedReadEvents': len(reads), 'compactedReasoningRestored': restored,
        'retainedNativeTail': retained_tail, 'sameFinalTextDifferentReasoning': repeated and restored,
        'nativeMessages': report.get('messages', []),
        'nativeRequestShapes': [{'roles': [message['role'] for message in body['messages']],
            'assistantText': [message.get('content') for message in body['messages'] if message['role'] == 'assistant'],
            'toolsPresent': bool(body.get('tools'))} for body in native_bodies],
        'compactionAccepted': len(manual) == 1 and len(reads) == 4 and restored and retained_tail and repeated
            and report.get('summaryAcknowledged', False)
            and report.get('summaryComplete', False) and report.get('continuedComplete', False)}


def tool_evidence(calls, protocol, output):
    bodies = [json.loads(request.content) for request in calls]
    expected = 4 if protocol == 'chat-completions' else 3
    tools_read, reasoning_restored, continued = False, False, False
    if len(bodies) == expected:
        if protocol == 'responses':
            history = bodies[2]['input']
            results = [item.get('output', '') for item in history if item.get('type') == 'function_call_output']
            reasoning_restored = [item.get('encrypted_content') for item in history if item.get('type') == 'reasoning'] == [
                'synthetic-private-reasoning-1', 'synthetic-private-reasoning-2']
        else:
            history = bodies[2]['messages']
            results = [message.get('content', '') for message in history if message.get('role') == 'tool']
            reasoning_restored = [message.get('reasoning_content') for message in history if message.get('role') == 'assistant'] == [
                'synthetic-private-reasoning-1', 'synthetic-private-reasoning-2']
            continued = [message.get('reasoning_content') for message in bodies[3]['messages']
                if message.get('role') == 'assistant'] == [
                'synthetic-private-reasoning-1', 'synthetic-private-reasoning-2', 'synthetic-private-reasoning-3']
        tools_read = (len(results) == 2 and 'SYNTHETIC_READ_ONE' in results[0]
                      and 'SYNTHETIC_READ_TWO' in results[1])
    events = []
    for line in output.splitlines():
        try: value = json.loads(line)
        except ValueError: continue
        if isinstance(value, dict): events.append(value)
    reads = [value.get('part', {}) for value in events if value.get('type') == 'tool_use'
             and value.get('part', {}).get('tool') == 'read']
    native_reads = len(reads) == 2 and all(part.get('state', {}).get('status') == 'completed' for part in reads)
    endpoint = '/responses' if protocol == 'responses' else '/chat/completions'
    return {'protocol': protocol, 'actualNativeReadResults': tools_read, 'nativeCompletedReadEvents': len(reads),
        'privateReasoningRestored': reasoning_restored,
        'continuedUserTurnRestoredFinalReasoning': continued if protocol == 'chat-completions' else None,
        'privateReasoningAbsentFromNativeOutput': 'synthetic-private-reasoning-' not in output,
        'upstreamProtocolPathVerified': bool(calls) and all(request.url.path.endswith(endpoint) for request in calls),
        'toolLoopAccepted': tools_read and native_reads and reasoning_restored
            and (continued if protocol == 'chat-completions' else True)
            and 'synthetic-private-reasoning-' not in output}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--opencode', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--wire-proof', type=Path, help='Save synthetic request bodies for one explicit case; no headers or credentials.')
    args = parser.parse_args()
    if args.wire_proof and not args.case: parser.error('--wire-proof requires --case')
    binary = Path(args.opencode).resolve()
    with binary.open('rb') as file:
        if hashlib.file_digest(file, 'sha256').hexdigest() != PIN:
            raise ValueError('NATIVE_BINARY_PIN_MISMATCH')
    if not args.image.startswith('sha256:') or len(args.image) != 71:
        raise ValueError('NATIVE_IMAGE_PIN_REQUIRED')
    root = Path(__file__).resolve().parents[1]
    bridge = root / 'scripts/owner_model_native_fixture.py'
    results = []
    for outcome in ((args.case,) if args.case else CASES):
        with TemporaryDirectory(prefix='af-native-retry-') as folder:
            private = Path(folder)
            for name in ('sockets', 'home', 'work', 'xdg/config', 'xdg/data', 'xdg/cache', 'xdg/state'):
                (private / name).mkdir(parents=True, mode=0o700, exist_ok=True)
            compact_case = outcome in {'cc_compaction', 'responses_compaction'}
            tool_case = outcome in {'cc_tool_rounds', 'responses_tool_rounds'}
            protocol = 'responses' if outcome in {'responses_tool_rounds', 'responses_compaction'} else 'chat-completions'
            if tool_case or compact_case:
                (private / 'work/synthetic-1.txt').write_text('SYNTHETIC_READ_ONE\n')
                (private / 'work/synthetic-2.txt').write_text('SYNTHETIC_READ_TWO\n')
            calls = []
            def wire(request):
                calls.append(request)
                if outcome == 'disconnect': raise httpx.ReadError('synthetic upstream disconnect')
                if outcome == 'provider_502': return httpx.Response(502, json={'error': 'synthetic upstream rejection'})
                if compact_case:
                    turn = len(calls)
                    return httpx.Response(200, json=tool_reply(protocol, turn,
                        read_index=turn - 5 if turn in {6, 7} else None,
                        text='Synthetic compacted summary' if turn == 5 else 'Synthetic settled reply'))
                if tool_case: return httpx.Response(200, json=tool_reply(protocol, len(calls)))
                return httpx.Response(200, json={'id': 'chatcmpl-synthetic', 'object': 'chat.completion', 'created': 1,
                    'model': 'synthetic-owner-model', 'choices': [{'index': 0,
                        'message': {'role': 'assistant', 'content': 'Synthetic settled reply'}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})
            handle = SimpleNamespace(owner='synthetic-owner', body={'ownerId': 'synthetic-owner',
                'reference': 'synthetic-model', 'revision': 'model-r1', 'credentialRef': 'synthetic-credential',
                'credentialRevision': 'credential-r1', 'provider': 'openai-compatible', 'protocol': protocol,
                'baseURL': 'https://opencode.ai/inference/go/v1' if tool_case or compact_case else 'https://opencode.ai/zen/go/v1',
                'model': 'gpt-6-luna' if protocol == 'responses' else 'deepseek-flash' if tool_case else 'synthetic-owner-model'},
                service=SimpleNamespace(transport_factory=lambda: httpx.MockTransport(wire)),
                check=lambda: None, credential=lambda: SecretLease('api-key', 'synthetic-offline-credential'))
            broker = OwnerRuntimeBroker(private / 'sockets/broker.sock', handle)
            broker.start()
            native_bodies = []
            original_completion = broker.native_completion
            def observe_completion(body, session_id, request_id):
                native_bodies.append(body)
                if compact_case: (private / 'native-requests.json').write_text(json.dumps(native_bodies))
                return original_completion(body, session_id, request_id)
            broker.native_completion = observe_completion
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
            if compact_case:
                fixture_config = json.loads(env['OPENCODE_CONFIG_CONTENT'])
                fixture_config['compaction'] = {'tail_turns': 1, 'preserve_recent_tokens': 2048}
                env['OPENCODE_CONFIG_CONTENT'] = json.dumps(fixture_config)
            # Whitelist a fresh environment. Never inherit a user's API keys.
            launch_env = {'PATH': os.defpath, **env}
            command = ['docker', 'run', '--pull', 'never', '--name', name, '--network', 'none', '--read-only',
                '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--memory', '2g', '--pids-limit', '128',
                '--user', str(os.getuid()) + ':' + str(os.getgid()),
                '--tmpfs', '/tmp:rw,nosuid,nodev,size=134217728', '--workdir', '/session/work',
                '--mount', f'type=bind,src={private},dst=/session',
                '--mount', f'type=bind,src={binary},dst=/trusted/opencode-real,readonly',
                '--mount', f'type=bind,src={bridge},dst=/trusted/bridge.py,readonly']
            for key in env: command += ['--env', key]
            # No retry flags, request rewriting or alternate research controller.
            if compact_case:
                command += ['--mount', f'type=bind,src={Path(__file__).with_name("owner_model_native_compaction.py").resolve()},dst=/trusted/compaction.py,readonly',
                    args.image, '/bin/sh', '-c', '/trusted/opencode-real --version; /usr/local/bin/python3 -I -B /trusted/compaction.py']
            else: command += [args.image, '/bin/sh', '-c',
                '/usr/local/bin/python3 -I -B /trusted/bridge.py --bridge & '
                '/trusted/opencode-real --version; '
                '/trusted/opencode-real run --format json --model opencode-factory/owner-model --agent factory "Synthetic offline retry check"'
                + ('; /trusted/opencode-real run --continue --format json --model opencode-factory/owner-model --agent factory "Synthetic offline retry check"'
                   if outcome in {'normal_two_turns', 'cc_tool_rounds'} else '')]
            try:
                try:
                    run = subprocess.run(command, env=launch_env, capture_output=True, timeout=150, check=False)
                except subprocess.TimeoutExpired as error:
                    if not compact_case: raise
                    run = SimpleNamespace(returncode=-1, stdout=error.stdout or b'', stderr=error.stderr or b'')
                output = (run.stdout + run.stderr).decode(errors='replace')
                if args.wire_proof:
                    args.wire_proof.write_text(json.dumps({'case': outcome, 'native': native_bodies,
                        'upstream': [json.loads(request.content) for request in calls]}, indent=2))
                error_case = outcome in {'disconnect', 'provider_502'}
                expected_calls = (8 if compact_case else 4 if outcome == 'cc_tool_rounds' else 3 if outcome == 'responses_tool_rounds'
                                  else 2 if outcome == 'normal_two_turns' else 1)
                accepted = (len(calls) == expected_calls and '1.18.35' in output
                    and ('OWNER_MODEL_CALL_UNCONFIRMED' in output and 'diag_' in output if error_case
                         else 'nativeCompaction' in output if compact_case else 'Synthetic settled reply' in output)
                    and 'synthetic-offline-credential' not in output)
                sessions = [request.headers.get('x-opencode-session') for request in calls]
                if outcome == 'normal_two_turns':
                    accepted = accepted and len(set(sessions)) == 1 and len({r['nativeRequest'] for r in ingress}) == 2
                evidence = tool_evidence(calls, protocol, output) if tool_case else {}
                if compact_case:
                    evidence = compaction_evidence(calls, native_bodies, protocol, output)
                    evidence['nativeDriverExitCode'] = run.returncode
                    if run.returncode != 0:
                        progress = private / 'compaction-progress.json'
                        evidence['nativeDriverStage'] = json.loads(progress.read_text()) if progress.exists() else None
                        evidence['nativeDriverFailure'] = output[-1600:].replace(broker.capability, '<redacted>')
                    accepted = (accepted and run.returncode == 0 and evidence['compactionAccepted']
                        and len(set(sessions)) == 1 and len({r['nativeRequest'] for r in ingress}) == 4)
                if tool_case:
                    expected_requests = 2 if outcome == 'cc_tool_rounds' else 1
                    accepted = (accepted and run.returncode == 0 and evidence['toolLoopAccepted']
                        and evidence['upstreamProtocolPathVerified'] and len(set(sessions)) == 1
                        and len({r['nativeRequest'] for r in ingress}) == expected_requests)
                results.append({'outcome': outcome, 'providerDispatches': len(calls), 'accepted': accepted,
                    'nativeVersion': '1.18.35', 'network': 'none', 'nativeRetryPolicyUnmodified': True,
                    **evidence,
                    'ingress': ingress,
                    'providerSessionIds': sessions,
                    'providerBodyHashes': [hashlib.sha256(request.content).hexdigest() for request in calls]})
            finally:
                subprocess.run(['docker', 'rm', '-f', name], capture_output=True, check=False)
                broker.close()
    print(json.dumps({'cases': results, 'accepted': all(row['accepted'] for row in results),
        'realModelCalls': 0, 'binarySha256': PIN, 'imageId': args.image, 'harness': 'actual-pinned-opencode-binary',
        'orx': 'not-run'}))
    return 0 if all(row['accepted'] for row in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
