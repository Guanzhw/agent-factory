"""Read-only checks of the existing database used by research bootstrap."""
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

# Core records needed to submit, recover and retain original work. Historical
# policy registration/review tables are not startup resources.
_REQUIRED_COLUMNS = {
    'af_bootstrap': ('id', 'mode'),
    'af_plans': ('id', 'owner_id', 'body', 'hash'),
    'af_tasks': ('id', 'owner_id', 'plan_id', 'request_id', 'fingerprint', 'run_id',
                 'admission', 'terminal', 'cancel_requested', 'body'),
    'af_effects': ('effect_key', 'task_id', 'run_id', 'fingerprint', 'status', 'result'),
    'af_artifacts': ('id', 'task_id', 'body', 'content'),
    'af_resources': ('id', 'owner_id', 'body'),
    'af_leases': ('id', 'owner_id', 'target_id', 'request_id', 'fingerprint', 'state', 'body'),
}
_FIELDS = ('database', 'namespace', 'settings.mode', 'bootstrap.mode',
           *('schema.' + name for name in _REQUIRED_COLUMNS))


def database_preflight(engine, settings):
    """Observe resources without initializing them or exposing settings/rows."""
    checks = {field: {'field': field, 'code': 'DEPENDENCY_NOT_VALID', 'status': 'NOT_CHECKED'}
              for field in _FIELDS}

    def report(field, status, code):
        checks[field] = {'field': field, 'status': status, 'code': code}

    mode = settings.demo
    report('settings.mode', 'PASS' if type(mode) is bool else 'BLOCKED',
           'OK' if type(mode) is bool else 'MODE_INVALID')
    try:
        dialect = engine.dialect.name
        if dialect not in {'postgresql', 'sqlite'}:
            report('database', 'BLOCKED', 'DIALECT_UNSUPPORTED')
        else:
            with engine.connect() as conn, conn.begin():
                if dialect == 'postgresql':
                    conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
                    conn.execute(text("SET LOCAL statement_timeout = '5000ms'"))
                    conn.execute(text("SET LOCAL lock_timeout = '1000ms'"))
                    namespace = conn.execute(text("SELECT current_schema() IS NOT NULL AND "
                        "has_schema_privilege(current_schema(), 'USAGE') AND "
                        "has_schema_privilege(current_schema(), 'CREATE')")).scalar()
                    report('namespace', 'PASS' if namespace else 'BLOCKED',
                           'OK' if namespace else 'NAMESPACE_UNAVAILABLE')
                else:
                    report('namespace', 'PASS', 'OK')
                inspector = inspect(conn)
                report('database', 'PASS', 'READ_ONLY_OBSERVED')
                bootstrap_present = False
                for name, required in _REQUIRED_COLUMNS.items():
                    field = 'schema.' + name
                    if not inspector.has_table(name):
                        report(field, 'NOT_CHECKED', 'NOT_INITIALIZED')
                        continue
                    columns = {column['name'] for column in inspector.get_columns(name)}
                    if not set(required) <= columns:
                        report(field, 'BLOCKED', 'REQUIRED_COLUMNS_MISSING')
                        continue
                    # Fixed identifiers; a zero-row read also checks SELECT access.
                    conn.execute(text('SELECT ' + ','.join(required) + ' FROM ' + name + ' LIMIT 0'))
                    report(field, 'PASS', 'OK')
                    bootstrap_present |= name == 'af_bootstrap'
                if bootstrap_present:
                    rows = conn.execute(text("SELECT mode FROM af_bootstrap WHERE id='mode' LIMIT 2")).mappings().all()
                    if not rows:
                        report('bootstrap.mode', 'NOT_CHECKED', 'NOT_INITIALIZED')
                    elif type(mode) is bool:
                        valid = len(rows) == 1 and rows[0]['mode'] == ('demo' if mode else 'production')
                        report('bootstrap.mode', 'PASS' if valid else 'BLOCKED', 'OK' if valid else 'MODE_MISMATCH')
                elif checks['schema.af_bootstrap']['code'] == 'NOT_INITIALIZED':
                    report('bootstrap.mode', 'NOT_CHECKED', 'NOT_INITIALIZED')
    except SQLAlchemyError:
        report('database', 'BLOCKED', 'DATABASE_READ_FAILED')
    statuses = {row['status'] for row in checks.values()}
    status = 'BLOCKED' if 'BLOCKED' in statuses else 'NOT_CHECKED' if 'NOT_CHECKED' in statuses else 'PASS'
    return {'schema': 1, 'kind': 'RESEARCH_BOOTSTRAP_DATABASE_PREFLIGHT', 'executionVerified': False,
            'status': status, 'checks': list(checks.values())}
