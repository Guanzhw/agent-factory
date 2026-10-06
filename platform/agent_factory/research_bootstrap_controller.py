"""Trusted local operator orchestration over existing Factory APIs and native runs.

No provider construction, credentials, training implementation or scientific proof.
HTTP and portal callbacks belong to the already-authorized in-process operator.
Persist progress outside this helper before starting a different invocation; failures
never resubmit a native task or research process. An UNKNOWN lease stays held.
"""
from copy import deepcopy
import asyncio
import re
import time


class ResearchBootstrapError(RuntimeError):
    def __init__(self, progress):
        super().__init__('RESEARCH_BOOTSTRAP_STOPPED')
        self.progress = deepcopy(progress)


def _require(value):
    if not value:
        raise ValueError('RESEARCH_BOOTSTRAP_INVALID')


def cleanup_original(state, owner, task_id, *, runtime, call_async, timeout_seconds: float = 5,
                     clock=time.monotonic, sleep=time.sleep):
    """Stop-only reconciliation while the original lifespan is still open.

    The timeout bounds asynchronous observation/polling, not the synchronous SQL
    calls, which retain their configured database timeouts. No absolute whole-
    cleanup wall-time guarantee is implied.
    """
    result = {'cancelRequested': False, 'cleanupConfirmed': False, 'leaseId': None}
    deadline = clock() + timeout_seconds
    try:
        task = state['store'].task(task_id, owner)
        _require(task['id'] == task_id and task['owner_id'] == owner)
        state['store'].request_cancel(task_id)
        result['cancelRequested'] = True
        original = runtime._original(task_id)
        if original is None:
            return result  # Unknown dispatch acknowledgement: never invent a lease.
        _require(original['task_id'] == task_id and original['owner_id'] == owner
                 and original['native_run_id'] == task['run_id'])
        result['leaseId'] = original['lease_id']
        while clock() < deadline:
            async def stop_only():
                async with asyncio.timeout(max(.001, deadline - clock())):
                    return await runtime.observe_lease(original['lease_id'])
            lease = call_async(stop_only)
            _require(lease['id'] == original['lease_id'] and lease['ownerId'] == owner
                     and lease['localTaskId'] == task_id and lease['nativeRunId'] == task['run_id'])
            if (lease['state'] == 'RECLAIMED' and lease.get('capacityHeld') is False
                    and (lease.get('stopEvidence') or {}).get('allStopped') is True
                    and ('gpuEvidence' not in lease or lease['gpuEvidence'].get('state') == 'RELEASED')):
                result['cleanupConfirmed'] = True
                return result
            sleep(min(.1, max(0, deadline - clock())))
    except BaseException:
        pass  # Retain UNKNOWN and original capacity; never infer positive stop.
    return result


class ResearchBootstrapController:
    def __init__(self, state, request, call_async, *, clock=time.monotonic, sleep=time.sleep):
        self.state, self.request, self.call_async = state, request, call_async
        self.clock, self.sleep = clock, sleep

    def run(self, *, owner, reviewer, application_ref, goal, request_id, after_reclaimed,
            timeout_seconds=900, on_progress=lambda value: None):
        """Run once; `after_reclaimed(owner, task, lease)` imports original evidence.

        request(method, '/api/factory/...', body, owner=...) returns decoded JSON
        and must raise on non-2xx. It must itself enforce a bounded I/O timeout.
        call_async is e.g. TestClient.portal.call. Callback data are detached.
        Request IDs are correlation keys, never invented task/run/lease IDs.
        """
        _require(type(request_id) is str and re.fullmatch(r'[A-Za-z0-9_.:-]{8,60}', request_id)
                 and type(owner) is str and owner and type(reviewer) is str and reviewer != owner
                 and type(goal) is str and 1 <= len(goal) <= 4000
                 and type(timeout_seconds) in (int, float) and 0 < timeout_seconds <= 86400
                 and callable(after_reclaimed) and callable(on_progress))
        _require(type(application_ref) is dict and set(application_ref) == {'id', 'version', 'sha256'})
        progress = {'requestId': request_id, 'phase': 'STARTED', 'taskId': None, 'planId': None,
                    'nativeRunId': None, 'leaseId': None, 'providerJobId': None,
                    'cancelRequested': False, 'cleanupConfirmed': False,
                    'orchestrationKind': 'deterministic-development-control',
                    'scientificConclusionVerified': False}
        deadline = self.clock() + timeout_seconds
        instance_attempted = False

        def remaining():
            value = deadline - self.clock()
            if value <= 0:
                raise TimeoutError('RESEARCH_BOOTSTRAP_DEADLINE')
            return value

        def mark(phase):
            progress['phase'] = phase
            on_progress(deepcopy(progress))

        def http(method, path, body=None, *, actor=owner):
            remaining()
            return self.request(method, '/api/factory' + path, body, owner=actor)

        def post(path, body=None, *, key, actor=owner):
            return http('POST', path, {**(body or {}), 'requestId': request_id + ':' + key}, actor=actor)

        def invoke(method, *args):
            budget = remaining()
            async def bounded():
                async with asyncio.timeout(budget):
                    return await method(*args)
            return self.call_async(bounded)

        def task_current():
            task = self.state['store'].task(progress['taskId'], owner)
            _require(task['id'] == progress['taskId'] and task['owner_id'] == owner
                     and task['plan_id'] == progress['planId'])
            if progress['nativeRunId'] is None:
                _require(type(task.get('run_id')) is str and bool(task['run_id']))
                progress['nativeRunId'] = task['run_id']
            _require(task['run_id'] == progress['nativeRunId'])
            return task

        def detail():
            value = http('GET', '/jobs/' + progress['taskId'])
            job = value['job']
            _require(job['id'] == progress['taskId'] and job['ownerId'] == owner
                     and job['planId'] == progress['planId'])
            task_current()
            return value

        def pause_poll():
            self.sleep(min(.1, remaining()))

        def lease_current(lease):
            _require(lease['id'] == progress['leaseId'] and lease['ownerId'] == owner
                     and lease['localTaskId'] == progress['taskId'] and lease['planId'] == progress['planId']
                     and lease['nativeRunId'] == progress['nativeRunId'])
            job = lease.get('providerJobId')
            if progress['providerJobId'] is None and job is not None:
                _require(type(job) is str and bool(job))
                progress['providerJobId'] = job
            _require(job == progress['providerJobId'])

        try:
            mark('STARTED')
            proposal = post('/compositions/proposals', {'goal': goal, 'mode': 'controlled-fixture',
                'applicationRef': deepcopy(application_ref)}, key='proposal')
            plan = post('/compositions/proposals/' + proposal['id'] + '/accept', key='accept')
            progress['planId'] = plan['id']
            review = post('/plan-reviews', {'planId': plan['id']}, key='review')
            post('/plan-reviews/' + review['id'] + '/decision', {'approved': True}, key='decision', actor=reviewer)
            mark('PLAN_APPROVED')
            instance_attempted = True
            task = post('/instances', {'planId': plan['id']}, key='instance')
            progress['taskId'] = task['id']
            mark('TASK_ACCEPTED')
            runtime = self.state['store'].research_runtime
            while True:
                value = detail()
                if value['job']['status'] == 'waiting_approval':
                    original = task_current()
                    bound_plan = self.state['store'].plan(progress['planId'], owner)
                    _, manifest, variant = runtime._config(original, bound_plan)
                    pinned = runtime._paused(original, manifest, variant)
                    requirement = {'id': pinned['id'], 'version': pinned['version']}
                    break
                _require(value['job']['status'] not in {'completed', 'failed', 'canceled', 'unknown'})
                pause_poll()
            mark('NATIVE_PAUSED')
            runtime = self.state['store'].research_runtime
            lease = invoke(runtime.submit, owner, progress['taskId'])  # Exactly one allocation attempt.
            progress['leaseId'] = lease['id']
            lease_current(lease)
            mark('PROCESS_SUBMITTED')
            while lease['state'] != 'RECLAIMED':
                pause_poll()
                lease = invoke(runtime.inspect_task, owner, progress['taskId'])
                lease_current(lease)
            _require(progress['providerJobId'] is not None and lease.get('executionStatus') == 'COMPLETED' and type(lease.get('exitCode')) is int
                     and lease['exitCode'] == 0 and lease.get('capacityHeld') is False
                     and (lease.get('stopEvidence') or {}).get('allStopped') is True
                     and (lease.get('gpuEvidence') or {}).get('state') == 'RELEASED')
            progress['cleanupConfirmed'] = True
            mark('PROCESS_RECLAIMED')
            task = task_current()
            _require(not task['cancel_requested'] and not task['terminal'])
            current = detail()['job']['approvalDetail']
            _require(all(current.get(key) == val for key, val in requirement.items()))
            remaining()
            imported = after_reclaimed(owner, deepcopy(task), deepcopy(lease))
            remaining()
            mark('EVIDENCE_IMPORTED')
            http('POST', '/jobs/' + progress['taskId'] + '/approve', {'requirementId': requirement['id'], 'version': requirement['version'], 'approved': True})
            while True:
                value = detail()
                if value['job']['status'] == 'completed':
                    break
                _require(value['job']['status'] not in {'failed', 'canceled', 'unknown'})
                pause_poll()
            mark('COMPLETED')
            return {'progress': deepcopy(progress), 'lease': deepcopy(lease), 'imported': imported}
        except BaseException:
            # A lost instance response is resolved only by the existing read-only
            # request receipt. Never re-POST /instances or runtime.submit.
            if progress['taskId'] is None and instance_attempted:
                try:
                    receipt = self.request('GET', '/api/factory/requests/' + request_id + ':instance', None, owner=owner)
                    _require(receipt['planId'] == progress['planId'] and receipt['requestId'] == request_id + ':instance')
                    progress['taskId'] = receipt['taskId']
                except Exception:
                    pass
            validated_original = False
            if progress['taskId'] is not None:
                try:
                    original = self.state['store'].task(progress['taskId'], owner)
                    _require(original['id'] == progress['taskId'] and original['owner_id'] == owner
                             and original['plan_id'] == progress['planId']
                             and (progress['nativeRunId'] is None or original['run_id'] == progress['nativeRunId']))
                    validated_original = True
                    # A reserved task may not yet have acknowledged a native run.
                    # Trusted original-owner cleanup survives revoked run permission;
                    # the normal lifecycle observer reconciles the retained lease.
                except Exception:
                    pass
                if validated_original:
                    try:
                        self.request('POST', '/api/factory/jobs/' + progress['taskId'] + '/cancel', {}, owner=owner)
                    except Exception:
                        pass
            if validated_original:
                cleanup = cleanup_original(self.state, owner, progress['taskId'],
                    runtime=self.state['store'].research_runtime, call_async=self.call_async,
                    clock=self.clock, sleep=self.sleep)
                progress['cancelRequested'] = progress['cancelRequested'] or cleanup['cancelRequested']
                progress['cleanupConfirmed'] = cleanup['cleanupConfirmed']
                if progress['leaseId'] is None:
                    progress['leaseId'] = cleanup['leaseId']
            progress['phase'] = 'STOPPED'
            try:
                on_progress(deepcopy(progress))
            except Exception:
                pass
            raise ResearchBootstrapError(progress) from None
