"""Container-only driver for explicit compaction by the pinned native server.

Uses only the native localhost session API. It never builds model messages,
edits session storage, or changes the runtime configuration.
"""
import json
from pathlib import Path
import subprocess
import time
import urllib.request


def main():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(method, path, body=None, *, timeout=80):
        Path('/session/compaction-progress.json').write_text(json.dumps({'method': method, 'path': path}))
        payload = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request('http://127.0.0.1:4791' + path, data=payload,
            method=method, headers={'Content-Type': 'application/json', 'x-opencode-directory': '/session/work'})
        with opener.open(req, timeout=timeout) as response:
            return json.load(response)

    def projection(messages):
        return [{'id': row['info']['id'], 'role': row['info']['role'],
            'summary': row['info'].get('summary') is True, 'finish': row['info'].get('finish'),
            'error': (row['info'].get('error') or {}).get('name'),
            'parts': [{'type': part['type'], **({'auto': part.get('auto'),
                'tailStartId': part.get('tail_start_id')} if part['type'] == 'compaction' else {}),
                **({'text': part['text']} if part['type'] == 'text' else {}),
                **({'tool': part['tool'], 'status': part['state']['status'],
                    'callId': part['callID'], 'readOutputVerified':
                        'SYNTHETIC_READ_' in part['state'].get('output', '')} if part['type'] == 'tool' else {})}
                for part in row['parts']]} for row in messages]

    with Path('/session/native-server.log').open('w') as log:
        bridge = subprocess.Popen(['/usr/local/bin/python3', '-I', '-B', '/trusted/bridge.py', '--bridge'],
            stdout=log, stderr=log)
        server = subprocess.Popen(['/trusted/opencode-real', 'serve', '--hostname', '127.0.0.1', '--port', '4791', '--print-logs'],
            stdout=log, stderr=log)
        try:
            for _ in range(300):
                try:
                    request('GET', '/session', timeout=1)
                    break
                except (OSError, ValueError):
                    if server.poll() is not None: raise RuntimeError('NATIVE_SERVER_EXITED')
                    time.sleep(.1)
            else: raise RuntimeError('NATIVE_SERVER_NOT_READY')
            session = request('POST', '/session', {'title': 'Synthetic explicit compaction'})
            path = '/session/' + session['id']
            prompt = {'model': {'providerID': 'opencode-factory', 'modelID': 'owner-model'},
                'agent': 'factory', 'parts': [{'type': 'text', 'text': 'Synthetic pre-compaction read checks'}]}
            initial = request('POST', path + '/message', prompt)
            prompt['parts'][0]['text'] = 'Synthetic retained user turn with repeated final text'
            repeated = request('POST', path + '/message', prompt)
            summary_ack = request('POST', path + '/summarize', {
                'providerID': 'opencode-factory', 'modelID': 'owner-model', 'auto': False})
            compacted = request('GET', path + '/message')
            summary = [row for row in compacted if row['info'].get('summary') is True]
            summary_ok = bool(summary) and all(not row['info'].get('error') and row['info'].get('finish') for row in summary)
            continued = None
            if summary_ok:
                prompt['parts'][0]['text'] = 'Synthetic post-compaction read checks'
                continued = request('POST', path + '/message', prompt)
            final = request('GET', path + '/message')
            print(json.dumps({'nativeCompaction': True, 'summaryAcknowledged': summary_ack is True,
                'initialComplete': not initial['info'].get('error'), 'summaryComplete': summary_ok,
                'repeatedComplete': not repeated['info'].get('error'),
                'continuedComplete': continued is not None and not continued['info'].get('error'),
                'session': session['id'], 'messages': projection(final)}))
        finally:
            for process in (server, bridge):
                process.terminate()
            for process in (server, bridge):
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)


if __name__ == '__main__':
    main()
