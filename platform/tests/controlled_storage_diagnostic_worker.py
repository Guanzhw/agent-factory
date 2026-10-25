"""One storage-test child diagnostic; never imported by product startup."""
import asyncio
import faulthandler
from functools import wraps
import json
import threading
import time

from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import NullPool

import controlled_command_worker as original


def install(app):
    state = app.app.state.factory
    store = state['store']
    directory = store.settings.workspace
    output = (directory / 'storage-cancel-diagnostic.jsonl').open('a', buffering=1)
    stacks = (directory / 'storage-cancel-stacks.txt').open('a', buffering=1)
    active = threading.Event()
    write_lock = threading.Lock()
    count = 0

    def record(phase, **fields):
        nonlocal count
        with write_lock:
            if count < 3000:
                output.write(json.dumps({'at': time.monotonic(), 'thread': threading.get_ident(),
                                         'phase': phase, **fields}) + '\n')
                count += 1

    def trace(service, name):
        method = getattr(service, name)
        @wraps(method)
        async def wrapped(*args, **kwargs):
            measured = active.is_set()
            if measured:
                record(name + ':begin')
            try:
                return await method(*args, **kwargs)
            finally:
                if measured:
                    record(name + ':end')
        setattr(service, name, wrapped)

    api = state['factory_api']
    for service, names in ((api, ('detail',)), (api.commands, ('submit', 'dispatch', 'recover')),
                           (store.delegation, ('cascade_cancel', 'inspect_group')),
                           (state['bridge'], ('cancel_run', 'detail'))):
        for name in names:
            trace(service, name)

    instrumented = set()
    def instrument(engine, label):
        if id(engine) not in instrumented:
            instrumented.add(id(engine))
            event.listen(engine, 'checkout', lambda *_: record('pool:checkout', pool=label) if active.is_set() else None)
            event.listen(engine, 'checkin', lambda *_: record('pool:checkin', pool=label) if active.is_set() else None)
            connect = engine.connect
            def measured_connect(*args, **kwargs):
                measured = active.is_set()
                if measured:
                    record('connect:begin', pool=label)
                try:
                    return connect(*args, **kwargs)
                finally:
                    if measured:
                        record('connect:end', pool=label)
            engine.connect = measured_connect
        return engine
    instrument(store.engine, 'metadata')
    instrument(store.native_db.db_engine, 'native')
    original_root_engine = store.root_lock_engine
    store.root_lock_engine = lambda: instrument(original_root_engine(), 'root-lock')

    async def heartbeat():
        while active.is_set():
            record('heartbeat')
            await asyncio.sleep(.5)

    def task_stacks():
        record('async-stacks:executed')
        for task in asyncio.all_tasks():
            stacks.write('\nTASK ' + getattr(task.get_coro(), '__qualname__', type(task.get_coro()).__name__) + '\n')
            for frame in task.get_stack(limit=12):
                stacks.write(json.dumps({'file': frame.f_code.co_filename,
                    'line': frame.f_lineno, 'function': frame.f_code.co_name}) + '\n')
        stacks.flush()

    def sample(loop, done, task_id):
        # Independent connection: sampling cannot occupy a product pool slot.
        engine = create_engine(store.engine.url, poolclass=NullPool,
            connect_args={'connect_timeout': 1, 'options': '-c statement_timeout=1000 -c lock_timeout=1000'})
        started = time.monotonic()
        try:
            for second in (5, 12):
                if done.wait(max(0, started + second - time.monotonic())):
                    return
                record('sample', second=second)
                faulthandler.dump_traceback(file=stacks, all_threads=True)
                record('async-stacks:requested')
                loop.call_soon_threadsafe(task_stacks)
                try:
                    with engine.connect() as conn:
                        activity = conn.execute(text("SELECT pid,state,wait_event_type,wait_event,"
                            "pg_blocking_pids(pid) AS blockers FROM pg_stat_activity "
                            "WHERE datname=current_database() AND pid<>pg_backend_pid()"))
                        record('pg-activity', rows=[dict(row) for row in activity.mappings()])
                        task = conn.execute(text('SELECT id,run_id,admission,cancel_requested,terminal '
                            'FROM af_tasks WHERE id=:task'), {'task': task_id})
                        record('original-task', rows=[dict(row) for row in task.mappings()])
                        commands = conn.execute(text('SELECT command_id,state,action FROM af_control_commands '
                            'WHERE task_ref=:task'), {'task': task_id})
                        record('original-commands', rows=[dict(row) for row in commands.mappings()])
                except Exception as error:
                    record('pg-sample-error', errorType=type(error).__name__)
        finally:
            engine.dispose()

    inner = state['http_app']
    async def boundary(scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] != 'http' or scope.get('method') != 'POST' or not (
                path.startswith('/api/factory/jobs/') and path.endswith('/cancel')):
            return await inner(scope, receive, send)
        task_id = path.split('/')[-2]
        active.set()
        record('cancel-http:begin', taskId=task_id)
        done = threading.Event()
        beat = asyncio.create_task(heartbeat())
        sampler = threading.Thread(target=sample, args=(asyncio.get_running_loop(), done, task_id), daemon=True)
        sampler.start()
        try:
            return await inner(scope, receive, send)
        finally:
            record('cancel-http:end', taskId=task_id)
            active.clear()
            done.set()
            await beat
            await asyncio.to_thread(sampler.join, 3)
    state['http_app'] = boundary
    return app


if __name__ == '__main__':
    create = original.create_app
    original.create_app = lambda *args, **kwargs: install(create(*args, **kwargs))
    original.main()
