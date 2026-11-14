"""Conversation updates from native execution and committed application changes."""
import asyncio
from contextlib import asynccontextmanager
import json

from agno.os.event_streams import get_event_stream
import anyio
import psycopg
from psycopg import sql


CHANNEL = 'factory_research_updates'
TABLES = ('af_events', 'af_tasks', 'af_effects', 'research_sessions', 'research_session_turns',
    'research_collaboration_intents', 'research_question_origins', 'af_assistant_messages',
    'af_application_content', 'af_resource_sharing')


def install_notifications(store):
    # PostgreSQL delivers NOTIFY after commit; no second history or event store.
    with store.engine.begin() as conn:
        conn.exec_driver_sql('''CREATE OR REPLACE FUNCTION af_research_changed() RETURNS trigger
            LANGUAGE plpgsql AS $$ DECLARE row jsonb; BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF to_jsonb(OLD) = to_jsonb(NEW) THEN RETURN NEW; END IF;
                IF TG_TABLE_NAME = 'af_tasks' AND
                    (to_jsonb(OLD) #- '{body,observedAt}') = (to_jsonb(NEW) #- '{body,observedAt}')
                    THEN RETURN NEW; END IF;
                IF TG_ARGV[0] = 'job' AND to_jsonb(OLD)->>'status' = to_jsonb(NEW)->>'status'
                    THEN RETURN NEW; END IF;
            END IF;
            row := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
            PERFORM pg_notify('factory_research_updates', jsonb_build_object(
                'table', TG_TABLE_NAME, 'id', row->>'id', 'task', row->>'task_id',
                'owner', COALESCE(row->>'owner_id', row->>'user_id', row->>'sender_id'),
                'recipient', row->>'recipient_id', 'session', row->>'session_id',
                'type', row->>'type')::text);
            RETURN NULL; END $$''')
        native = store.native_db
        tables = [('public', name) for name in TABLES]
        if native is not None:
            tables.append((native.db_schema, native.job_table_name))
        for schema, table in tables:
            name = sql.Identifier(schema, table).as_string()
            # Native queue tables are initialized by the application lifespan.
            conn.exec_driver_sql(f'DROP TRIGGER IF EXISTS af_research_changed ON {name}')
            kind = 'job' if native is not None and table == native.job_table_name else 'application'
            conn.exec_driver_sql(f'CREATE TRIGGER af_research_changed AFTER INSERT OR UPDATE OR DELETE ON {name} '
                f"FOR EACH ROW EXECUTE FUNCTION af_research_changed('{kind}')")


@asynccontextmanager
async def changes(store):
    url = store.engine.url.set(drivername='postgresql').render_as_string(hide_password=False)
    # Windows needs Proactor for Agent subprocesses; psycopg async requires Selector.
    connecting = asyncio.create_task(asyncio.to_thread(psycopg.Connection.connect, url, autocommit=True))
    pending = connecting
    try:
        connection = await asyncio.shield(connecting)
        pending = asyncio.create_task(asyncio.to_thread(connection.execute, 'LISTEN ' + CHANNEL))
        await asyncio.shield(pending)

        async def notifications():
            nonlocal pending
            while True:
                # Bound only the blocking wait, not the subscription or Agent run.
                pending = asyncio.create_task(asyncio.to_thread(
                    lambda: list(connection.notifies(timeout=1, stop_after=1))))
                for notification in await asyncio.shield(pending):
                    yield notification

        yield notifications()
    finally:
        with anyio.CancelScope(shield=True):
            connection = await connecting
            try:
                await pending
            finally:
                await asyncio.to_thread(connection.close)


def frame(kind, value):
    return 'event: ' + kind + '\ndata: ' + json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n\n'


async def session_updates(request, auth, service, owner, identifier, notifications, initial):
    pending = asyncio.Queue()
    snapshot = initial
    watchers = {}
    cursors = {}

    async def database():
        async for notification in notifications:
            await pending.put(json.loads(notification.payload))

    async def native(run_id):
        try:
            async for index, raw in get_event_stream().tail(run_id, last_event_index=cursors.get(run_id)):
                cursors[run_id] = index
                for line in raw.splitlines():
                    if line.startswith('data:'):
                        event = json.loads(line[5:])
                        await pending.put({'native': run_id, 'type': event.get('event')})
        except Exception:
            # Database notifications remain authoritative if the in-memory tail expires.
            return

    def watch():
        for turn in snapshot['turns']:
            run_id = turn.get('runId')
            if run_id and turn['status'] not in {'completed', 'failed', 'canceled'}:
                task = watchers.get(run_id)
                if task is None or task.done():
                    watchers[run_id] = asyncio.create_task(native(run_id))

    listener = asyncio.create_task(database())
    try:
        yield frame('session', snapshot)
        watch()
        while not await request.is_disconnected():
            if auth.user(request)['id'] != owner:
                return
            try:
                notice = await asyncio.wait_for(pending.get(), timeout=15)
            except TimeoutError:
                yield ': connected\n\n'
                if listener.done():
                    listener.result()
                    return
                continue
            notices = [notice]
            while not pending.empty():
                notices.append(pending.get_nowait())
            turns = {turn['taskId']: turn for turn in snapshot['turns'] if turn.get('taskId')}
            runs = {turn['runId']: turn for turn in snapshot['turns'] if turn.get('runId')}
            changed, refresh = set(), False
            for notice in notices:
                if notice.get('native'):
                    turn = runs.get(notice['native'])
                    if turn:
                        if notice['type'] in {'RunContent', 'RunContentCompleted'}:
                            changed.add(turn['taskId'])
                        else:
                            refresh = True
                elif notice['table'] == 'af_events':
                    if notice['task'] in turns:
                        changed.add(notice['task'])
                        refresh |= notice['type'] not in {'model_content_delta', 'model_reasoning_delta'}
                elif notice['table'] in {'af_application_content', 'af_resource_sharing'}:
                    refresh = True
                elif notice.get('session') == identifier or owner in {notice.get('owner'), notice.get('recipient')}:
                    refresh = True
                elif notice.get('task') in turns:
                    refresh = True
            if refresh:
                current = await service.read(owner, identifier)
                if current != snapshot:
                    snapshot = current
                    yield frame('session', snapshot)
                watch()
            else:
                for task_id in changed:
                    turn = turns[task_id]
                    old = {event['id']: event for event in turn.get('events') or []}
                    last = max(old, default=0)
                    rows = await asyncio.to_thread(service.store.sql,
                        'SELECT * FROM af_events WHERE task_id=:task AND id>=:last ORDER BY id', task=task_id, last=last)
                    events = [{'id': row['id'], 'jobId': task_id, 'type': row['type'], 'message': row['message'],
                        'data': row['data'], 'createdAt': row['created_at']} for row in rows]
                    updated = [event for event in events if old.get(event['id']) != event]
                    if updated:
                        old.update({event['id']: event for event in updated})
                        turn['events'] = sorted(old.values(), key=lambda event: event['id'])
                        yield frame('turn_events', {'sessionId': identifier, 'turnId': turn['id'], 'events': updated})
    finally:
        listener.cancel()
        for task in watchers.values():
            task.cancel()
        await asyncio.gather(listener, *watchers.values(), return_exceptions=True)
