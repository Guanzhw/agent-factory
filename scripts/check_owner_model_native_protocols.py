"""Offline CC/Responses acceptance using OpenCode's actual pinned SDK tool loop.

Provide --sdk-root with @ai-sdk/openai-compatible 2.0.41, ai 6.0.168 and zod 4.1.8
installed, and apply OpenCode v1.18.35's published compatible SDK patch. The
package versions and patched entry SHA-256 are checked before execution. This
script never downloads dependencies, launches OpenCode, or calls a real model.
Node's custom fetch reaches only the broker Unix socket; upstream is MockTransport.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform'))
from agent_factory.owner_runtime_broker import OwnerRuntimeBroker
from agent_factory.personal_remote_provider import SecretLease


def check(sdk_root, protocol, scenario):
    with TemporaryDirectory(prefix='af-native-protocol-') as folder:
        private = Path(folder)
        calls = []
        def wire(request):
            body = json.loads(request.content); calls.append(body)
            turn = len(calls)
            # Non-canonical whitespace and a float force the real SDK to parse
            # then stringify arguments. Copying the broker response cannot pass.
            arguments = '{ "round" : ' + str(turn) + '.0, "query" : "synthetic-' + str(turn) + '" }'
            if protocol == 'responses':
                output = [{'type': 'reasoning', 'id': f'rs_synthetic{turn}', 'summary': [],
                    'encrypted_content': f'synthetic-encrypted-reasoning-{turn}'}]
                if turn < 3:
                    output.append({'type': 'function_call', 'id': f'fc_synthetic{turn}',
                        'call_id': f'call_synthetic{turn}', 'name': 'synthetic_lookup', 'arguments': arguments})
                else:
                    output.append({'type': 'message', 'role': 'assistant', 'content': [
                        {'type': 'output_text', 'text': 'Synthetic native tool loop completed'}]})
                payload = {'status': 'completed', 'output': output}
            else:
                message = {'role': 'assistant', 'content': 'Synthetic native tool loop completed'}
                if turn < 3:
                    message['reasoning_content'] = f'synthetic-private-reasoning-{turn}'
                    if turn == 1 and scenario == 'final_then_tools':
                        message['content'] = 'Synthetic first answer'
                    else:
                        message.update(content=None, tool_calls=[{'id': f'call_synthetic{turn}', 'type': 'function',
                            'function': {'name': 'synthetic_lookup', 'arguments': arguments}}])
                payload = {'choices': [{'message': message, 'finish_reason': 'tool_calls' if message.get('tool_calls') else 'stop'}]}
            return httpx.Response(200, json=payload)
        handle = SimpleNamespace(owner='synthetic-owner', body={'ownerId': 'synthetic-owner',
            'reference': 'synthetic-model', 'revision': 'model-r1', 'credentialRef': 'synthetic-credential',
            'credentialRevision': 'credential-r1', 'provider': 'openai-compatible', 'protocol': protocol,
            'baseURL': 'https://opencode.ai/inference/go/v1',
            'model': 'gpt-6-luna' if protocol == 'responses' else 'deepseek-flash'},
            service=SimpleNamespace(transport_factory=lambda: httpx.MockTransport(wire)),
            check=lambda: None, credential=lambda: SecretLease('api-key', 'synthetic-offline-credential'))
        broker = OwnerRuntimeBroker(private / 'broker.sock', handle)
        broker.start()
        try:
            node = shutil.which('node')
            if node is None: raise ValueError('NODE_REQUIRED')
            run = subprocess.run([node, str(Path(__file__).with_name('owner_model_native_sdk.cjs'))],
                input=json.dumps({'sdkRoot': str(sdk_root), 'socket': str(broker.path),
                    'capability': broker.capability, 'scenario': scenario}),
                text=True, capture_output=True, timeout=40,
                env={'PATH': os.defpath, 'HOME': str(private), 'XDG_CONFIG_HOME': str(private)})
            if not run.stdout.strip():
                raise ValueError('NATIVE_SDK_SETUP_FAILED')
            result = json.loads(run.stdout)
            restored = False
            if len(calls) == 3:
                if protocol == 'responses':
                    restored = [item['encrypted_content'] for item in calls[2]['input'] if item.get('type') == 'reasoning'] == [
                        'synthetic-encrypted-reasoning-1', 'synthetic-encrypted-reasoning-2']
                else:
                    restored = [message.get('reasoning_content') for message in calls[2]['messages']
                        if message['role'] == 'assistant'] == ['synthetic-private-reasoning-1', 'synthetic-private-reasoning-2']
            normalized = result.get('normalized', [[]])
            tool_message = (normalized[-1][-1] if scenario == 'final_then_tools' else normalized[0][0]) if normalized and normalized[0] else {}
            expected_round = 2 if scenario == 'final_then_tools' else 1
            actual_sdk_normalization = bool(tool_message.get('content') == '' and tool_message.get('arguments') ==
                json.dumps({'round': expected_round, 'query': f'synthetic-{expected_round}'}, separators=(',', ':')))
            return {**result, 'protocol': protocol, 'scenario': scenario, 'providerDispatches': len(calls),
                'privateReasoningRestored': restored, 'actualSdkNormalization': actual_sdk_normalization,
                'accepted': run.returncode == 0 and result['accepted'] and restored and actual_sdk_normalization}
        finally:
            broker.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk-root', required=True, type=Path)
    parser.add_argument('--protocol', choices=('chat-completions', 'responses'))
    args = parser.parse_args()
    cases = [check(args.sdk_root.resolve(), protocol, 'tool_rounds') for protocol in
        ([args.protocol] if args.protocol else ['chat-completions', 'responses'])]
    if args.protocol in {None, 'chat-completions'}:
        cases.append(check(args.sdk_root.resolve(), 'chat-completions', 'final_then_tools'))
    print(json.dumps({'cases': cases, 'accepted': all(case['accepted'] for case in cases), 'realModelCalls': 0,
        'harness': 'actual-pinned-sdk-streamText', 'opencodeBinary': 'not-run', 'orx': 'not-run'}))
    return 0 if all(case['accepted'] for case in cases) else 1


if __name__ == '__main__':
    raise SystemExit(main())
