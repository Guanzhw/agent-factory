"""SQLite driver adaptation for real Store artifact/event methods, not native execution."""
import json
import re
from types import MethodType
from uuid import uuid4

from sqlalchemy import Column, Integer, JSON, LargeBinary, MetaData, String, Table

from agent_factory.store import Store


def install_artifacts(store, *, task_id=None, run_id=None, owner='alice'):
    metadata = MetaData()
    tasks = Table('af_tasks', metadata, Column('id', String, primary_key=True),
        Column('owner_id', String), Column('run_id', String))
    Table('af_artifacts', metadata, Column('id', String, primary_key=True),
        Column('task_id', String), Column('body', JSON), Column('content', LargeBinary))
    Table('af_events', metadata, Column('id', Integer, primary_key=True, autoincrement=True),
        Column('task_id', String), Column('type', String), Column('message', String),
        Column('data', JSON), Column('created_at', String))
    metadata.create_all(store.engine)
    def sql(self, statement, **params):
        statement = re.sub(r'CAST\((:[a-z_]+) AS JSONB\)', r'\1', statement)
        rows = Store.sql(self, statement, **params)
        for row in rows:
            for key in ('body', 'data'):
                if isinstance(row.get(key), str):
                    row[key] = json.loads(row[key])
        return rows
    store.sql = MethodType(sql, store)
    for name in ('transaction', 'task', 'event', 'events', 'artifact_write', 'artifact', 'artifacts'):
        setattr(store, name, MethodType(getattr(Store, name), store))
    store.remote_bindings = None
    task_id, run_id = task_id or str(uuid4()), run_id or str(uuid4())
    with store.transaction() as conn:
        conn.execute(tasks.insert().values(id=task_id, owner_id=owner, run_id=run_id))
    return task_id, run_id


def artifact_ref(store, run_id, raw, *, name='body.json'):
    item = store.artifact_write(run_id, name, raw)
    return {'taskId': item['jobId'], 'artifactId': item['id'], 'sha256': item['sha256']}
