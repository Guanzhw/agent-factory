"""Read-only bootstrap compatibility; never initialize or repair persisted policy."""
from dataclasses import asdict
import json
from typing import Any, cast

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from .material_governance import GovernanceConfig
from .plan_policy import PlanPolicyConfig

_FIELDS = ('database', 'settings.mode', 'settings.material', 'settings.plan', 'bootstrap.mode',
    'material.current', 'material.currentConfig', 'material.expectedConfig',
    'plan.current', 'plan.currentConfig', 'plan.expectedConfig', 'plan.policyEnum')


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('INVALID_BODY')
        value[key] = item
    return value


def _body(value):
    if type(value) is str:
        if len(value.encode()) > 65536:
            raise ValueError('INVALID_BODY')
        value = json.loads(value, object_pairs_hook=_unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('INVALID_BODY')))
    if type(value) is not dict or len(json.dumps(value, allow_nan=False).encode()) > 65536:
        raise ValueError('INVALID_BODY')
    return value


def database_preflight(engine, settings):
    """Fixed public report; private settings/rows are never copied into output."""
    checks = {field: {'field': field, 'code': 'DEPENDENCY_NOT_VALID', 'status': 'NOT_CHECKED'} for field in _FIELDS}

    def report(field, status, code):
        checks[field] = {'field': field, 'status': status, 'code': code}

    def check(field, condition, code):
        report(field, 'PASS' if condition else 'BLOCKED', 'OK' if condition else code)
        return bool(condition)

    mode = getattr(settings, 'demo', None)
    check('settings.mode', type(mode) is bool, 'MODE_INVALID')
    expected = {}
    for label, constructor, params in (
        ('material', GovernanceConfig, {'review_mode': getattr(settings, 'material_review_mode', None),
            'revision': getattr(settings, 'material_policy_revision', None),
            'tool_contract': getattr(settings, 'runtime_tool_contract', None),
            'source_synthesis_enabled': getattr(settings, 'source_synthesis_enabled', None)}),
        ('plan', PlanPolicyConfig, {'name': getattr(settings, 'temporary_policy', None),
            'revision': getattr(settings, 'policy_revision', None),
            'review_ttl_seconds': getattr(settings, 'plan_review_ttl_seconds', None),
            'tool_contract': getattr(settings, 'runtime_tool_contract', None),
            'source_synthesis_enabled': getattr(settings, 'source_synthesis_enabled', None)})):
        try:
            config = constructor(**cast(Any, params))
            if ((label == 'material' and params['review_mode'] == 'demo-self-review')
                    or (label == 'plan' and params['name'] == 'bounded-synthetic')) and mode is not True:
                raise ValueError('MODE_INVALID')
            expected[label] = config
            report('settings.' + label, 'PASS', 'OK')
        except (ValueError, TypeError, AttributeError):
            report('settings.' + label, 'BLOCKED', 'CONFIG_INVALID')
    try:
        if engine.dialect.name not in {'postgresql', 'sqlite'}:
            report('database', 'BLOCKED', 'DIALECT_UNSUPPORTED')
        else:
            with engine.connect() as conn, conn.begin():
                if engine.dialect.name == 'postgresql':
                    conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
                    conn.execute(text("SET LOCAL statement_timeout = '5000ms'"))
                    conn.execute(text("SET LOCAL lock_timeout = '1000ms'"))
                def bounded(column, maximum):
                    expression = (f'octet_length(CAST({column} AS TEXT))' if engine.dialect.name == 'postgresql'
                                  else f'length(CAST({column} AS BLOB))')
                    return f'CASE WHEN {expression}<={maximum} THEN {column} ELSE NULL END AS {column}'

                inspector = inspect(conn)
                present = {name: inspector.has_table(name) for name in ('af_bootstrap',
                    'af_material_governance_current', 'af_material_governance_configs',
                    'af_plan_policy_state', 'af_plan_policy_configs')}
                report('database', 'PASS', 'READ_ONLY_OBSERVED')
                if not present['af_bootstrap']:
                    report('bootstrap.mode', 'NOT_CHECKED', 'NOT_INITIALIZED')
                else:
                    rows = conn.execute(text(f"SELECT {bounded('mode', 10)} FROM af_bootstrap WHERE id='mode' LIMIT 2")).mappings().all()
                    if not rows:
                        report('bootstrap.mode', 'NOT_CHECKED', 'NOT_INITIALIZED')
                    elif type(mode) is bool:
                        check('bootstrap.mode', len(rows) == 1 and rows[0]['mode'] == ('demo' if mode else 'production'), 'MODE_MISMATCH')

                for label, state, table, hash_column, constructor in (
                    ('material', 'af_material_governance_current', 'af_material_governance_configs', 'hash', GovernanceConfig),
                    ('plan', 'af_plan_policy_state', 'af_plan_policy_configs', 'policy_hash', PlanPolicyConfig)):
                    config = expected.get(label)

                    def registered(revision, field, *, current):
                        if not present[table]:
                            report(field, 'NOT_CHECKED', 'NOT_INITIALIZED')
                            return
                        # Identifiers are fixed module literals, never user input.
                        rows = conn.execute(text(f'SELECT {bounded("revision", 100)},{bounded(hash_column, 64)},{bounded("body", 65536)} FROM {table} WHERE revision=:revision LIMIT 2'),
                                            {'revision': revision}).mappings().all()
                        if not rows:
                            report(field, 'BLOCKED' if current else 'NOT_CHECKED',
                                   'CURRENT_CONFIG_MISSING' if current else 'NOT_REGISTERED')
                            return
                        try:
                            if len(rows) != 1:
                                raise ValueError('INVALID_BODY')
                            saved = constructor(**_body(rows[0]['body']))
                            valid = rows[0]['revision'] == saved.revision == revision and saved.fingerprint == rows[0][hash_column]
                            if not current and config is not None:
                                valid = valid and saved.fingerprint == config.fingerprint and asdict(saved) == asdict(config)
                            if isinstance(saved, PlanPolicyConfig) and current:
                                policy_valid = saved.name in {'unset', 'admin-review', 'read-only-auto', 'bounded-synthetic'}
                                check('plan.policyEnum', policy_valid and (saved.name != 'bounded-synthetic' or mode is True), 'POLICY_ENUM_OR_MODE_INVALID')
                            if isinstance(saved, GovernanceConfig) and saved.review_mode == 'demo-self-review' and mode is not True:
                                valid = False
                            check(field, valid, 'CONFIG_BODY_OR_HASH_MISMATCH')
                        except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
                            report(field, 'BLOCKED', 'CONFIG_BODY_INVALID')
                            if label == 'plan' and current:
                                report('plan.policyEnum', 'BLOCKED', 'POLICY_BODY_INVALID')

                    if not present[state]:
                        report(label + '.current', 'NOT_CHECKED', 'NOT_INITIALIZED')
                        report(label + '.currentConfig', 'NOT_CHECKED', 'NOT_INITIALIZED')
                    else:
                        rows = conn.execute(text(f"SELECT {bounded('id', 7)},{bounded('revision', 100)} FROM {state} LIMIT 2")).mappings().all()
                        if not rows:
                            report(label + '.current', 'NOT_CHECKED', 'NOT_INITIALIZED')
                            report(label + '.currentConfig', 'NOT_CHECKED', 'NOT_INITIALIZED')
                        elif len(rows) != 1 or rows[0]['id'] != 'current' or type(rows[0]['revision']) is not str:
                            report(label + '.current', 'BLOCKED', 'CURRENT_ROW_INVALID')
                        else:
                            if config is not None:
                                check(label + '.current', rows[0]['revision'] == config.revision, 'CURRENT_REVISION_MISMATCH')
                            registered(rows[0]['revision'], label + '.currentConfig', current=True)
                    if config is not None:
                        registered(config.revision, label + '.expectedConfig', current=False)
    except (SQLAlchemyError, ValueError, TypeError, AttributeError):
        report('database', 'BLOCKED', 'DATABASE_READ_FAILED')
    statuses = {row['status'] for row in checks.values()}
    status = 'BLOCKED' if 'BLOCKED' in statuses else 'NOT_CHECKED' if 'NOT_CHECKED' in statuses else 'PASS'
    return {'schema': 1, 'kind': 'RESEARCH_BOOTSTRAP_DATABASE_PREFLIGHT', 'executionVerified': False, 'status': status, 'checks': list(checks.values())}
