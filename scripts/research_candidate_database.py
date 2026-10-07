"""Ephemeral connection routing anchored to retained logical database lineage.

No URL, credential, route pathname or hash thereof is persisted. An exact copy
of the original immutable records has the same logical lineage; this does not
attest physical PostgreSQL server identity.
"""
import json


def anchor_database(database_url, inputs):
    from sqlalchemy import create_engine, text
    from agent_factory.store import digest
    error = 'RESEARCH_CANDIDATE_DATABASE_BINDING_UNCONFIRMED'
    engine = None
    def require(ok):
        if not ok:
            raise ValueError(error)
    def body(value):
        return json.loads(value) if isinstance(value, str) else value
    try:
        proof = inputs['baselineReceipt']['imported']
        manifest = inputs['manifestSha256']
        executions = [proof['trainingExecution'], proof['evaluatorExecution']]
        require(executions[0]['taskId'] != executions[1]['taskId'])
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.begin() as connection:
            connection.execute(text('SET TRANSACTION READ ONLY'))
            connection.execute(text("SET LOCAL statement_timeout='5s'"))
            connection.execute(text("SET LOCAL lock_timeout='2s'"))
            def one(sql, **params):
                rows = connection.execute(text(sql), params).mappings().all()
                require(len(rows) == 1)
                return rows[0]
            for execution in executions:
                require(execution['ownerId'] == 'alice')
                task = one('SELECT * FROM af_tasks WHERE id=:id', id=execution['taskId'])
                require(task['owner_id'] == execution['ownerId']
                    and task['plan_id'] == execution['planId'] and task['run_id'] == execution['nativeRunId'])
                plan = one('SELECT * FROM af_plans WHERE id=:id', id=execution['planId'])
                value = body(plan['body'])
                require(plan['owner_id'] == execution['ownerId'] and digest(value) == plan['hash']
                    and value['id'] == execution['planId']
                    and value['fingerprint'] == execution['planFingerprint'])
                mapping = one('SELECT * FROM af_process_runs WHERE task_id=:task AND effect_key=:effect',
                    task=execution['taskId'], effect='research-process-run-v1')
                require(mapping['lease_id'] == execution['leaseId']
                    and mapping['owner_id'] == execution['ownerId']
                    and mapping['native_run_id'] == execution['nativeRunId'])
                lease = body(one('SELECT body FROM af_leases WHERE id=:id', id=execution['leaseId'])['body'])
                require(all(lease.get(key) == execution[field] for key, field in (
                    ('ownerId', 'ownerId'), ('localTaskId', 'taskId'), ('planId', 'planId'),
                    ('nativeRunId', 'nativeRunId'), ('providerJobId', 'providerJobId')))
                    and lease.get('planHash') == plan['hash']
                    and lease.get('executionGuard', {}).get('manifestSha256') == manifest)
    except Exception:
        raise ValueError(error) from None
    finally:
        if engine is not None:
            engine.dispose()


def resolve_database(inputs, database_url_file=None):
    from bootstrap_research_control import read_database_url
    path = database_url_file if database_url_file is not None else inputs['baselineConfig']['databaseUrlFile']
    database_url = read_database_url(path)
    anchor_database(database_url, inputs)
    return database_url
