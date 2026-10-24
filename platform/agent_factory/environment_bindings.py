"""Explicit Factory credential continuation; native identity/data stay frozen.

Only a positively stopped environment can acquire a new current binding.
This journal never prepares compute, submits a goal or resumes a native turn.
"""
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import Column, JSON, String, Table, select

from .store import digest, now

SERVER_KEYS = ('location', 'serverRef', 'serverRevision', 'serverPin', 'identityPin',
               'remoteDirectory', 'serverScopePin')


class EnvironmentBindings:
    def __init__(self, service, metadata):
        self.service = service
        self.current_table = Table('af_environment_credential_bindings', metadata,
            Column('environment_id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('body', JSON, nullable=False), Column('body_hash', String, nullable=False))
        self.changes = Table('af_environment_binding_changes', metadata,
            Column('owner_id', String, primary_key=True), Column('request_id', String, primary_key=True),
            Column('environment_id', String, nullable=False), Column('fingerprint', String, nullable=False),
            Column('old_binding', JSON, nullable=False), Column('new_binding', JSON, nullable=False),
            Column('created_at', String, nullable=False), Column('body_hash', String, nullable=False))

    @staticmethod
    def checked_change(row):
        value = dict(row)
        expected = digest({key: value[key] for key in ('owner_id', 'request_id', 'environment_id', 'fingerprint',
            'old_binding', 'new_binding', 'created_at')})
        if value['body_hash'] != expected: raise HTTPException(409, 'ENVIRONMENT_BINDING_HISTORY_INTEGRITY')
        return value

    @staticmethod
    def original(row):
        body = row['body']
        return {'schema': 1, 'ownerId': row['owner_id'], 'environmentId': row['id'],
            'originalBodyHash': row['body_hash'], 'modelReference': body['modelReference'],
            'modelRevision': body['modelRevision'],
            'serverSelection': {key: body[key] for key in SERVER_KEYS if key in body}
                if body.get('location') == 'ssh' else {}}

    def current(self, conn, row):
        binding = conn.execute(select(self.current_table).where(
            self.current_table.c.environment_id == row['id'], self.current_table.c.owner_id == row['owner_id'])).mappings().first()
        if binding is None: return self.original(row)
        body = binding['body']
        if (digest(body) != binding['body_hash'] or body['ownerId'] != row['owner_id']
                or body['environmentId'] != row['id'] or body['originalBodyHash'] != row['body_hash']):
            raise HTTPException(409, 'ENVIRONMENT_BINDING_INTEGRITY')
        return deepcopy(body)

    @staticmethod
    def selection(body, selection):
        # Legacy snapshots did not record stable host/login/root scope. They may
        # keep identical server pins, but cannot infer a safe key/host migration.
        return {key: value for key, value in selection.items()
                if key != 'serverScopePin' or 'serverScopePin' in body}

    def preview(self, owner, identifier):
        service = self.service
        service.auth.require_member(owner)
        with service.db.read() as conn: row = service._row(conn, owner, identifier)
        body, previous = row['body'], row['credential_binding']
        result = {'environmentId': identifier, 'projectId': body['projectId'], 'dataRetained': True,
            'originalBodyHash': row['body_hash'], 'currentBindingFingerprint': digest(previous),
            'packageVersion': body['packageVersion'], 'environmentState': row['state'].lower(),
            'classification': 'results-only', 'canRebind': False, 'requiresCredentialRebind': False,
            'nativeCheckpointContinuationVerified': False, 'sessionRebindRequired': False,
            'originalWorkReplay': False, 'researchSubmitted': False}
        package = service._package(row['application_id'], body)
        if package is None:
            return {**result, 'reason': 'ENVIRONMENT_PACKAGE_UNAVAILABLE', 'nextAction': 'new-environment',
                'message': '原运行包不可用。保留已有结果；选择当前可用运行位置创建新环境。'}
        if package.version != body['packageVersion']:
            if body.get('location') == 'ssh':
                return {**result, 'reason': 'ENVIRONMENT_SSH_PACKAGE_UPDATE_UNSUPPORTED',
                    'availablePackageVersion': package.version, 'nextAction': 'choose-new-location',
                    'message': '此服务器目录的固定运行包不支持原地升级。原数据保留；请明确选择另一个已授权私有目录或运行位置创建新环境。'}
            return {**result, 'classification': 'needs-new-run', 'reason': 'ENVIRONMENT_PACKAGE_CHANGED',
                'availablePackageVersion': package.version, 'nextAction': 'new-environment',
                'message': '运行包版本已变化，不能自动迁移原生检查点。创建新环境使用当前版本，原项目与结果保留。'}
        try:
            model = service.models.default(owner)
            result['currentModelChoice'] = {'reference': model['reference'], 'revision': model['revision'],
                'name': model.get('model', model['reference']), 'provider': model.get('provider', ''),
                'endpoint': model.get('baseURL', '')}
            proposed = {**previous, 'modelReference': model['reference'], 'modelRevision': model['revision']}
            if body.get('location') == 'ssh':
                selected = self.selection(body, package.selection(owner, body['serverRef'], body['remoteDirectory']))
                old_server = previous['serverSelection']
                if selected != old_server and (not body.get('serverScopePin')
                        or selected.get('serverScopePin') != body['serverScopePin']):
                    return {**result, 'classification': 'needs-new-run', 'reason': 'ENVIRONMENT_SERVER_SCOPE_CHANGED',
                        'nextAction': 'new-environment',
                        'message': '无法核对同一主机、登录用户和私有目录范围。保留原数据，选择已验证的服务器创建新环境。'}
                proposed['serverSelection'] = selected
        except Exception:
            return {**result, 'reason': 'ENVIRONMENT_CURRENT_CREDENTIAL_UNAVAILABLE', 'nextAction': 'repair-credentials',
                'message': '当前凭据尚未通过核对。更新并验证自己的模型或服务器凭据后，再读取此记录。'}
        changed = proposed != previous
        result.update(classification='can-continue', requiresCredentialRebind=changed,
            proposedBinding=proposed, proposedBindingFingerprint=digest(proposed),
            canRebind=changed and row['state'] == 'STOPPED', sessionRebindRequired=changed)
        if row['state'] in {'UNKNOWN', 'PREPARING', 'STOPPING'}:
            result.update(classification='results-only', reason='ENVIRONMENT_ORIGINAL_OUTCOME_UNCONFIRMED',
                nextAction='read-original-request', message='原操作结果尚未确认。先核对原请求；不会重发研究目标。')
        elif changed and row['state'] != 'STOPPED':
            result.update(reason='ENVIRONMENT_STOP_REQUIRED', nextAction='stop-environment',
                message='凭据已变化。先确认原环境已停止，再单独确认新绑定；原请求与会话仍须核对。')
        elif changed:
            result.update(reason='ENVIRONMENT_EXPLICIT_BINDING_REQUIRED', nextAction='rebind-credentials',
                message='原环境已停止。单独确认新凭据绑定后，可恢复同一环境；已有会话另行核对并续接。')
        else:
            result.update(reason='ENVIRONMENT_BINDING_CURRENT', nextAction='read-session' if row['state'] == 'READY' else 'restore-environment',
                message='可继续使用或恢复同一环境。原生会话的轮次和检查点状态以原请求核对结果为准。')
        result['previewHash'] = digest(result)
        return result

    def rebind(self, owner, identifier, request_id, preview_hash):
        service = self.service
        service.auth.require_member(owner); service.connections._key(request_id)
        fingerprint = digest({'environmentId': identifier, 'previewHash': preview_hash})
        with service._fence(identifier):
            with service.db.read() as conn:
                old = conn.execute(select(self.changes).where(self.changes.c.owner_id == owner,
                    self.changes.c.request_id == request_id)).mappings().first()
            if old:
                self.checked_change(old)
                if old['environment_id'] != identifier or old['fingerprint'] != fingerprint:
                    raise HTTPException(409, 'IDEMPOTENCY_CONFLICT')
                return self.request(owner, request_id)
            preview = self.preview(owner, identifier)
            if preview.get('previewHash') != preview_hash: raise HTTPException(409, 'ENVIRONMENT_BINDING_PREVIEW_CHANGED')
            if not preview['canRebind']: raise HTTPException(409, preview['reason'])
            proposed = preview['proposedBinding']
            # Verify current model authority, never resolve/send its key here.
            with service.models.db.read() as conn:
                model = service.models.binding(conn, owner, proposed['modelReference'])
                if model.revision != proposed['modelRevision']: raise HTTPException(409, 'ENVIRONMENT_MODEL_CHANGED')
                model.opaque_handle.check()
            service.auth.require_member(owner)
            with service.db.write() as conn:
                row = service._row(conn, owner, identifier)
                if row['state'] != 'STOPPED' or digest(row['credential_binding']) != preview['currentBindingFingerprint']:
                    raise HTTPException(409, 'ENVIRONMENT_BINDING_PREVIEW_CHANGED')
                if len(self.history(owner, identifier, conn=conn)) >= 1024:
                    raise HTTPException(409, 'ENVIRONMENT_BINDING_HISTORY_LIMIT')
                service.auth.require_member(owner)
                current = conn.execute(select(self.current_table).where(self.current_table.c.environment_id == identifier)).first()
                values = {'environment_id': identifier, 'owner_id': owner, 'body': proposed, 'body_hash': digest(proposed)}
                if current:
                    conn.execute(self.current_table.update().where(self.current_table.c.environment_id == identifier,
                        self.current_table.c.owner_id == owner).values(body=proposed, body_hash=digest(proposed)))
                else: conn.execute(self.current_table.insert().values(**values))
                change = {'owner_id': owner, 'request_id': request_id, 'environment_id': identifier,
                    'fingerprint': fingerprint, 'old_binding': row['credential_binding'], 'new_binding': proposed, 'created_at': now()}
                conn.execute(self.changes.insert().values(**change, body_hash=digest(change)))
            return self.request(owner, request_id)

    def history(self, owner, identifier, *, conn=None):
        query = select(self.changes).where(self.changes.c.owner_id == owner,
            self.changes.c.environment_id == identifier).order_by(self.changes.c.created_at).limit(1024)
        if conn is not None: return [self.checked_change(row) for row in conn.execute(query).mappings()]
        with self.service.db.read() as current: return [self.checked_change(row) for row in current.execute(query).mappings()]

    def request(self, owner, request_id):
        service = self.service; service.auth.require_member(owner)
        with service.db.read() as conn:
            row = conn.execute(select(self.changes).where(self.changes.c.owner_id == owner,
                self.changes.c.request_id == request_id)).mappings().first()
            if row is None: raise HTTPException(404, 'ENVIRONMENT_BINDING_REQUEST_NOT_FOUND')
            self.checked_change(row)
            environment = service._public(service._row(conn, owner, row['environment_id']))
        return {'requestId': request_id, 'state': 'committed', 'environment': environment,
            'oldBinding': row['old_binding'], 'newBinding': row['new_binding'],
            'researchSubmitted': False, 'runtimePrepared': False}


class EnvironmentModelHandle:
    def __init__(self, service, owner, environment, binding, delegate):
        self._service, self._owner, self._environment = service, owner, environment
        self._binding, self._delegate = deepcopy(binding), delegate
        self.body, self.service = getattr(delegate, 'body', {}), getattr(delegate, 'service', None)
        # Keep the delegate's exact approved route through an explicit session
        # credential/model rebind; absence must not silently select direct.
        self.trusted_proxy = getattr(delegate, 'trusted_proxy', None)
        # A change to either model or SSH credentials yields a new public
        # connection pin and therefore requires the existing session rebind.
        self.environment_credential_revision = 'env-binding-' + digest(binding)
        self.environment_selection = deepcopy(binding['serverSelection'])

    def __repr__(self): return 'EnvironmentModelHandle(credentials=<redacted>)'

    def check(self):
        self._service.auth.require_member(self._owner)
        with self._service.db.read() as conn:
            row = self._service._row(conn, self._owner, self._environment['id'])
            if row['body'] != self._environment or row['credential_binding'] != self._binding:
                raise HTTPException(409, 'ENVIRONMENT_BINDING_CHANGED')
        self._delegate.check()
        if getattr(self._delegate, 'trusted_proxy', None) is not self.trusted_proxy:
            raise HTTPException(409, 'ENVIRONMENT_MODEL_ROUTE_CHANGED')

    def credential(self):
        self.check(); lease = self._delegate.credential(); self.check(); return lease
