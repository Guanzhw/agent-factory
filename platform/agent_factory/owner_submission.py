"""Persist exact owner submissions for ordinary personal business actions.

This does not approve shared resources, publication, platform models, arbitrary
code, remote Factory placement, or permissions not granted by native identity.
"""
from fastapi import HTTPException
from sqlalchemy import Column, MetaData, String, Table, select

from .byok_model import ADAPTER_ID, CAPABILITY
from .store import digest, now


class OwnerSubmissions:
    def __init__(self, store):
        self.store = store
        metadata = MetaData()
        self.submissions = Table('af_owner_submissions', metadata,
            Column('plan_id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('plan_hash', String, nullable=False), Column('created_at', String, nullable=False))
        metadata.create_all(store.engine)
        self.personal_sessions = self.personal_projects = None
        if getattr(store.settings, 'personal_agent_commands_enabled', False):
            from .personal_agent_sessions import PersonalAgentSessions
            from .personal_orx_projects import PersonalOrxProjects
            def deny(owner, intent): raise HTTPException(403, 'PERSONAL_NATIVE_COMMAND_REQUIRED')
            self.personal_sessions = PersonalAgentSessions(store.connections, admission=deny)
            self.personal_projects = PersonalOrxProjects(store.connections, admission=deny)

    def _scope(self, owner, plan, *, require_consent=True):
        from .personal_command_profile import APPLICATION_ID, PROJECT_APPLICATION_ID, command_from_plan
        if plan['ownerId'] != owner or plan.get('remoteHandoff') or plan.get('delegation'):
            raise HTTPException(403, 'OWNER_SUBMISSION_SCOPE_DENIED')
        manifest = self.store.execution_bindings.inspect(plan)
        if plan.get('application') in {APPLICATION_ID, PROJECT_APPLICATION_ID}:
            command = command_from_plan(plan)
            pin = command['connectionPin']
            capability = 'project:create' if command['action'] == 'project_create' else 'session:' + command['action']
            if self.personal_sessions is None: raise HTTPException(403, 'OWNER_SUBMISSION_SCOPE_DENIED')
            self.personal_sessions._handle(owner, pin, capability=capability)
            with self.store.connections._read() as conn:
                row = self.store.connections._row(conn, owner, pin['ref'])
                if not row['registration_ref'].startswith('remote-'):
                    raise HTTPException(403, 'OWNER_SUBMISSION_SHARED_RESOURCE_DENIED')
            if command['action'] == 'project_create' and require_consent:
                if self.personal_projects is None: raise HTTPException(403, 'OWNER_SUBMISSION_SCOPE_DENIED')
                self.personal_projects.require_approval(
                    owner, command['requestId'], plan['id'], command['projectBundle'])
            return
        model = manifest['model']
        # Only approved read-only research tools plus an owner BYOK model. Code
        # execution/writes/shared environments stay under their existing policy.
        policy = self.store.plan_policy.current()
        from .plan_policy import PlanPolicyConfig
        # Current configuration is read through the policy's immutable decoder.
        with self.store.plan_policy._execution_connection() as conn:
            config: PlanPolicyConfig = self.store.plan_policy._current(conn)
        if (model['adapterId'] != ADAPTER_ID or model['revision'] != '1'
                or not set(plan['tools']) <= config.read_only_tools
                or not set(plan['capabilities']) <= config.read_only_capabilities
                or plan.get('nativeComponent') is not None or policy['name'] == 'unset'):
            raise HTTPException(403, 'OWNER_SUBMISSION_SCOPE_DENIED')
        pins = [spec.get('connection') for _, spec in self.store.execution_bindings._items(manifest)]
        for pin in pins:
            if pin is None: continue
            with self.store.connections._read() as conn:
                row = self.store.connections._row(conn, owner, pin['ref'])
                if not row['registration_ref'].startswith(('owner-model-', 'remote-')):
                    raise HTTPException(403, 'OWNER_SUBMISSION_SHARED_RESOURCE_DENIED')
        if not model.get('connection') or CAPABILITY not in model['connection']['capabilities']:
            raise HTTPException(403, 'OWNER_SUBMISSION_MODEL_REQUIRED')

    def can_submit(self, owner, plan):
        try:
            self._scope(owner, plan, require_consent=False)
            return self.store.plan_policy.current()['name'] != 'unset'
        except HTTPException as error:
            if error.status_code in {403, 404, 409}: return False
            raise

    def approve(self, owner, plan):
        self.store.auth.require(owner, 'run')
        stored = self.store.plan(plan['id'], owner)
        if stored != plan or stored['status'] != 'ready': raise HTTPException(409, 'OWNER_SUBMISSION_PLAN_CHANGED')
        self._scope(owner, stored)
        with self.store.transaction() as conn:
            old = conn.execute(select(self.submissions).where(self.submissions.c.plan_id == plan['id'])).mappings().first()
            if old:
                if old['owner_id'] != owner or old['plan_hash'] != digest(stored):
                    raise HTTPException(409, 'OWNER_SUBMISSION_INTEGRITY')
            else:
                conn.execute(self.submissions.insert().values(plan_id=plan['id'], owner_id=owner,
                    plan_hash=digest(stored), created_at=now()))

    def approve_personal(self, owner, plan):
        from .personal_command_profile import APPLICATION_ID, PROJECT_APPLICATION_ID
        spec = (plan.get('executionBindings') or {}).get('model') or {}
        if plan.get('application') not in {APPLICATION_ID, PROJECT_APPLICATION_ID} and spec.get('adapterId') != ADAPTER_ID:
            return False
        try:
            self.approve(owner, plan)
        except HTTPException as error:
            if error.detail in {'OWNER_SUBMISSION_SCOPE_DENIED', 'OWNER_SUBMISSION_SHARED_RESOURCE_DENIED'}:
                return False  # Existing organization/admin review still applies.
            raise
        return True

    def approved(self, conn, owner, plan):
        row = conn.execute(select(self.submissions).where(self.submissions.c.plan_id == plan['id'],
            self.submissions.c.owner_id == owner)).mappings().first()
        if row is None: return False
        if row['plan_hash'] != digest(plan): raise HTTPException(409, 'OWNER_SUBMISSION_INTEGRITY')
        self._scope(owner, plan)
        return True
