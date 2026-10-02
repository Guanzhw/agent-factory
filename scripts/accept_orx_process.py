"""Real loopback Factory/native-queue SIGKILL and exact-run Linux recovery.

Uses only a newly generated demo store, pinned public ORX and the sealed toy.
No model provider, production identity, remote resource or database is created.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from uuid import uuid4

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url', required=True)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--source-archive', required=True, type=Path)
    parser.add_argument('--git-binary', required=True, type=Path)
    parser.add_argument('--port', type=int, default=3105)
    args = parser.parse_args()
    root = args.workspace.resolve(); root.mkdir(parents=True, exist_ok=False)
    fixture_path = root / 'private-fixture.json'
    workspace = root / 'service'
    command = [sys.executable, str(Path(__file__).with_name('start_orx_local.py')), '--isolated-demo',
               '--database-url', args.database_url, '--workspace', str(workspace), '--binary', str(args.binary),
               '--source-archive', str(args.source_archive), '--git-binary', str(args.git_binary),
               '--port', str(args.port), '--fixture-file', str(fixture_path)]
    process = None
    fixture = None
    log = (root / 'service.log').open('w')
    client = httpx.Client(base_url=f'http://127.0.0.1:{args.port}', timeout=20)
    def wait_for(function, timeout=100):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = function()
            if value:
                return value
            time.sleep(.2)
        raise AssertionError('Owned acceptance condition timed out')
    def start(resume=False):
        nonlocal process, fixture
        if fixture_path.exists(): fixture_path.unlink()
        process = subprocess.Popen([*command, *(['--resume'] if resume else [])], stdout=log, stderr=log)
        # The application does not need a special health endpoint: root is served locally.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if process.poll() is not None: raise AssertionError('Owned service failed to start; inspect service.log')
            try:
                if fixture_path.exists() and client.get('/').is_success: break
            except httpx.TransportError: pass
            time.sleep(.2)
        else: raise AssertionError('Owned service startup timed out')
        fixture = json.loads(fixture_path.read_text())
    def api(method, path, body=None, reviewer=False):
        response = client.request(method, '/api/factory' + path, json=body,
            headers=fixture['reviewerHeaders' if reviewer else 'ownerHeaders'])
        assert response.is_success, (method, path, response.status_code)
        return response.json()
    def post(path, body, reviewer=False):
        return api('POST', path, {'requestId': str(uuid4()), **body}, reviewer)
    try:
        start()
        app = next(a for a in api('GET', '/applications') if a['id'] == fixture['applicationId'])
        proposal = post('/compositions/proposals', {'goal': 'Owned real native queue crash recovery', 'mode': 'cancellable',
            'applicationRef': {k: app[k] for k in ('id', 'version', 'sha256')}, 'connectionRefs': fixture['connectionRefs']})
        plan = post('/compositions/proposals/' + proposal['id'] + '/accept', {})
        review = post('/plan-reviews', {'planId': plan['id']})
        post('/plan-reviews/' + review['id'] + '/decision', {'approved': True}, True)
        job = post('/instances', {'planId': plan['id']}); task_id = job['id']
        def detail(): return api('GET', '/jobs/' + task_id)
        paused = wait_for(lambda: (d if (d := detail())['job']['status'] == 'waiting_approval' else None))
        approval = paused['job']['approvalDetail']
        approval_command = {'commandId': str(uuid4()), 'action': 'approve', 'requirementId': approval['id'], 'version': approval['version'], 'approved': True}
        # The actual HTTP request commits, then the owned caller discards the
        # response before retaining any receipt. Recovery below only uses GET.
        response = client.post('/api/factory/jobs/' + task_id + '/commands', json=approval_command, headers=fixture['ownerHeaders'])
        assert response.status_code == 202
        del response
        running = wait_for(lambda: (d if (d := detail()).get('orxExperiment', {}).get('status') == 'running' else None))
        original = running['orxExperiment']
        assert original['orxRunId'] and original['nativeRunId'] and not original['stopEvidence']['allStopped']
        assert process is not None
        process.kill(); process.wait(timeout=10)  # SIGKILL: no Python/Factory cleanup runs.
        cid = original['stopEvidence']['containerId']
        live = json.loads(subprocess.check_output(['docker', 'inspect', cid], text=True))[0]
        assert live['State']['Running']
        survivors = subprocess.check_output(['docker', 'top', cid, '-eo', 'pid'], text=True).splitlines()[1:]
        assert len(survivors) > 1, 'Detached evaluator/supervisor must survive actual Factory SIGKILL'
        start(resume=True)
        restored = detail()['orxExperiment']
        assert restored['orxRunId'] == original['orxRunId'] and restored['nativeRunId'] == original['nativeRunId']
        approval_receipt = api('GET', '/jobs/' + task_id + '/commands/' + approval_command['commandId'])
        assert approval_receipt['decisionRecorded'] and approval_receipt['approved'] is True
        cancel_command = {'commandId': str(uuid4()), 'action': 'cancel'}
        response = client.post('/api/factory/jobs/' + task_id + '/commands', json=cancel_command, headers=fixture['ownerHeaders'])
        assert response.status_code == 202
        del response
        process.kill(); process.wait(timeout=10)
        start(resume=True)
        cancel_receipt = wait_for(lambda: (r if (r := api('GET', '/jobs/' + task_id + '/commands/' + cancel_command['commandId']))['stopConfirmed'] else None))
        stopped = wait_for(lambda: (d if (d := detail()).get('orxExperiment', {}).get('stopEvidence', {}).get('allStopped') is True else None))
        current = stopped['orxExperiment']
        assert current['orxRunId'] == original['orxRunId'] and current['nativeRunId'] == original['nativeRunId']
        assert len([e for e in stopped['events'] if e['type'] == 'native_accepted']) == 1
        databases = list(workspace.glob('orx-tasks/*/' + task_id + '/orx-store/orx.db'))
        assert len(databases) == 1
        with sqlite3.connect(databases[0]) as db:
            runs = db.execute('select id from runs').fetchall()
        assert runs == [(original['orxRunId'],)]
        evidence = {'kind': 'actual_linux_factory_native_queue_sigkill', 'taskId': task_id,
                    'before': original, 'after': current, 'factoryStatus': stopped['job']['status'],
                    'nativeAdmissions': 1, 'nativeORXRuns': 1, 'approvalCommand': approval_receipt, 'cancelCommand': cancel_receipt,
                    'discardedControlResponses': 2, 'recoveryControlPOSTs': 0, 'detachedSurvivorsAfterSIGKILL': len(survivors) - 1,
                    'paidProviderCalls': 0}
        (root / 'process-evidence.json').write_text(json.dumps(evidence, indent=2))
        print(json.dumps({'ok': True, 'evidence': str(root / 'process-evidence.json')}))
    finally:
        if process is not None and process.poll() is None:
            (workspace / 'stop-local-orx.txt').touch()
            try: process.wait(timeout=45)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=10)
        client.close(); log.close()


if __name__ == '__main__':
    main()
