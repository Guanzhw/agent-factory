"""Failure-only observations for native integration waits, never recovery/stop proof.

The caller retains its original timeout/assertion. Output counts and strings are
bounded and observations are non-atomic. No fresh database reads are performed;
optional task/ticket observations must come from the caller's original poll.
No payloads, exception messages, SQL parameters, locals or task reprs are emitted.
"""
from itertools import islice
from pathlib import Path
import sys

MAX_TASKS = 24
MAX_THREADS = 32
MAX_FRAMES = 16
MAX_TEXT = 160
TASK_FIELDS = ('id', 'run_id', 'plan_id', 'owner_id', 'admission', 'terminal', 'cancel_requested')
TICKET_FIELDS = ('id', 'session_id', 'status', 'attempt', 'max_attempts', 'locked_by',
                 'locked_at', 'created_at', 'updated_at', 'completed_at')


def _scalar(value):
    if type(value) is str:
        return value[:MAX_TEXT]
    if value is None or type(value) in (bool, int):
        return value
    return None


def _error(error):
    return {'diagnosticErrorType': type(error).__name__[:MAX_TEXT]}


def _frame(frame):
    return {'file': Path(frame.f_code.co_filename).name[:MAX_TEXT],
            'function': frame.f_code.co_name[:MAX_TEXT], 'line': frame.f_lineno}


def _task(task):
    if task is None:
        return None
    try:
        cursor, seen, frames = task.get_coro(), set(), []
        while cursor is not None and len(seen) < MAX_FRAMES and id(cursor) not in seen:
            seen.add(id(cursor))
            frame = getattr(cursor, 'cr_frame', None) or getattr(cursor, 'gi_frame', None)
            if frame is not None:
                frames.append(_frame(frame))
            cursor = getattr(cursor, 'cr_await', None) or getattr(cursor, 'gi_yieldfrom', None)
        return {'done': bool(task.done()), 'cancelled': bool(task.cancelled()),
                'awaitChain': frames, 'awaitChainTruncated': cursor is not None}
    except Exception as error:
        return _error(error)


def snapshot(state, app, *, observed_task=None, observed_ticket=None):
    """Return a JSON-safe diagnostic; do not mutate runtime or replace failures.

    ``app`` is the FastAPI object (e.g. TestClient.app), ``state`` its factory
    mapping (never read here). No scheduling, joining, cancellation, SQL or remote
    calls are performed. Optional observations are from the last original poll.
    Concurrent collection changes are reported as diagnostic errors, not retried.
    """
    result = {'nonAtomic': True, 'stopProof': False,
              'limits': {'tasks': MAX_TASKS, 'threads': MAX_THREADS, 'frames': MAX_FRAMES},
              'freshDatabaseReads': False}
    try:
        worker = getattr(app.state, 'queue_worker', None)
        if worker is None:
            result['worker'] = {'present': False}
        else:
            flights = list(islice(worker._in_flight.items(), MAX_TASKS + 1))
            result['worker'] = {
                'present': True, 'workerId': _scalar(worker.worker_id),
                'pollTask': _task(worker._task),
                'inFlight': [{'runId': _scalar(run_id), 'task': _task(task)}
                             for run_id, task in flights[:MAX_TASKS]],
                'inFlightTruncated': len(flights) > MAX_TASKS,
            }
    except Exception as error:
        result['worker'] = _error(error)
    try:
        current = sys._current_frames()
        selected = list(islice(current.items(), MAX_THREADS))
        result['threadsTruncated'] = len(current) > MAX_THREADS
        result['threads'] = []
        for identifier, cursor in selected:
            frames = []
            while cursor is not None and len(frames) < MAX_FRAMES:
                frames.append(_frame(cursor))
                cursor = cursor.f_back
            result['threads'].append({'threadId': identifier, 'frames': frames,
                                      'framesTruncated': cursor is not None})
    except Exception as error:
        result['threadsError'] = _error(error)
    for name, row, fields in (('observedTask', observed_task, TASK_FIELDS),
                              ('observedTicket', observed_ticket, TICKET_FIELDS)):
        try:
            result[name] = None if row is None else {key: _scalar(row.get(key)) for key in fields}
        except Exception as error:
            result[name] = _error(error)
    return result
