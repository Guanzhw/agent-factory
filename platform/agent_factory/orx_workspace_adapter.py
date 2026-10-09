"""Read/attach actual pinned OpenResearch projects through a trusted owner handle.

Source contract: alphaXiv/OpenResearch f336b121, src/commands/up.rs project_json,
list_projects, get_project and create_chat_session. Project create is deliberately
unavailable: that revision unconditionally warms starter prompts with a model
call. No Factory shadow project, SQLite provisioner or model loop is introduced.

Only operator code may construct this handle. The installer must establish an
owner-exclusive instance and canonical source-path pins on that host. A user
cannot attest isolation, select a port, install a path or expand session profiles
through this adapter. The authorize callback rechecks the original connection's
owner, immutable configuration and revocation before and after each observation.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import inspect
from pathlib import PurePosixPath
from types import MappingProxyType

import httpx

from .orx_research_session import (
    OpenResearchHTTP, OpenResearchSessionHTTP, OrxSessionError,
    UPSTREAM_COMMIT, _encoded, _id, _require,
)

ADAPTER_ID = 'openresearch-workspace-v1'
CAPABILITIES = ('project:read',)
SESSION_ADMISSION_BLOCKERS = (
    'NATIVE_PROJECT_APPROVED_PLAN_BINDING_REQUIRED',
    'NATIVE_SESSION_BROKER_ACCOUNTING_REQUIRED',
    'NATIVE_SESSION_ORIGINAL_CUSTODY_REQUIRED',
)


def _source_path(value):
    # This is an exact remote-host pin, not a local filesystem resolution.
    # Canonicalization/symlink validation belong to the trusted installer.
    _require(type(value) is str and 1 <= len(value) <= 4096 and '\\' not in value
             and not any(ord(c) < 32 for c in value))
    path = PurePosixPath(value)
    _require(path.is_absolute() and '..' not in path.parts and str(path) == value and value != '/')
    return value


@dataclass(frozen=True)
class SessionProfile:
    """Operator-approved native options, not a free-form user/model selection."""
    harness: str
    model: str
    permission_mode: str | None = None
    service_tier: str | None = None
    reasoning_level: str | None = None
    plan_mode: bool | None = None

    def options(self):
        return {'harness': self.harness, 'model': self.model,
                'permission_mode': self.permission_mode, 'service_tier': self.service_tier,
                'reasoning_level': self.reasoning_level, 'plan_mode': self.plan_mode}


class _WorkspaceSessionHTTP(OpenResearchSessionHTTP):
    """Retained transports cannot outlive original owner/source authorization."""
    def __init__(self, workspace, owner, project_id, profile):
        super().__init__(workspace._port, project_id=project_id,
                         **profile.options(), transport=workspace._transport)
        self._workspace, self._owner = workspace, owner

    async def _guard(self, operation):
        self._workspace._check(self._owner, operation)
        await self._workspace.inspect_project(self._owner, self.project_id)
        self._workspace._check(self._owner, operation)

    async def _request(self, method, path, *, body=None, params=None):
        operation = ('session:read' if method == 'GET' else
                     'session:create' if path == '/api/chat/sessions' else
                     'session:message' if path.endswith('/message') else
                     'session:interrupt' if path.endswith('/interrupt') else 'session:update')
        await self._guard(operation)
        result = await super()._request(method, path, body=body, params=params)
        await self._guard(operation)
        return result

    async def events(self, session_id: str, *, max_events: int = 32):
        await self._guard('session:read')
        result = await super().events(session_id, max_events=max_events)
        await self._guard('session:read')
        return result


class OpenResearchWorkspaceAdapter:
    adapter_ref = ADAPTER_ID
    kind = 'orx'
    capabilities = CAPABILITIES

    def __init__(self, *, owner_id: str, port: int, project_paths: Mapping[str, str],
                 session_profiles: Mapping[str, SessionProfile], authorize: Callable,
                 upstream_revision: str, owner_exclusive: bool,
                 transport: httpx.AsyncBaseTransport | None = None):
        _id(owner_id)
        _require(upstream_revision == UPSTREAM_COMMIT and owner_exclusive is True and callable(authorize))
        _require(isinstance(project_paths, Mapping) and 1 <= len(project_paths) <= 100)
        paths = {_id(key): _source_path(value) for key, value in project_paths.items()}
        _require(len(set(paths.values())) == len(paths))
        _require(isinstance(session_profiles, Mapping) and len(session_profiles) <= 30)
        profiles = {}
        for ref, profile in session_profiles.items():
            _id(ref)
            _require(isinstance(profile, SessionProfile))
            # Validate inert pins through the same client constructor; no IO.
            OpenResearchSessionHTTP(port, project_id=next(iter(paths)), **profile.options())
            profiles[ref] = profile
        self.owner_id, self.upstream_revision = owner_id, upstream_revision
        self._port, self._transport, self._authorize = port, transport, authorize
        self._paths, self._profiles = MappingProxyType(paths), MappingProxyType(profiles)
        self._http = OpenResearchHTTP(port, transport=transport)

    def _check(self, owner, operation='project:read'):
        if owner != self.owner_id:
            raise OrxSessionError('ORX_WORKSPACE_OWNER_MISMATCH')
        result = self._authorize(owner, operation)
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise OrxSessionError('ORX_WORKSPACE_AUTHORIZATION_REQUIRED')
        if result is not True:
            raise OrxSessionError('ORX_WORKSPACE_AUTHORIZATION_REQUIRED')

    def describe(self, owner):
        self._check(owner)
        return {'adapterId': ADAPTER_ID, 'upstreamRevision': self.upstream_revision,
            'projectKind': 'native-openresearch', 'projectCreationAvailable': False,
            'projectCreationBlockedReason': 'ORX_PROJECT_CREATE_MODEL_BUDGET_REQUIRED',
            'projectCreationSideEffects': ['starter-prompt-model-call'],
            'githubPublicationAvailable': False, 'liveIntegrationVerified': False,
            'sessionProfiles': [{'id': ref, **profile.options()} for ref, profile in self._profiles.items()],
            'sessionAdmission': 'requires-original-governed-factory-binding',
            'sessionAdmissionAvailable': False,
            'sessionAdmissionBlockers': list(SESSION_ADMISSION_BLOCKERS)}

    def _project(self, value, expected=None):
        _require(type(value) is dict)
        identifier = _id(value.get('id'))
        _require(expected is None or identifier == expected)
        path = self._paths.get(identifier)
        if path is None:
            raise OrxSessionError('ORX_WORKSPACE_PROJECT_NOT_ALLOWED')
        # project_json exposes both repoPath (serde) and path (UI alias).
        _require(value.get('repoPath') == path and value.get('path') == path)
        name, slug = value.get('name'), value.get('slug')
        _require(type(name) is str and 1 <= len(name) <= 512)
        _require(type(slug) is str and 1 <= len(slug) <= 512)
        identity = {'upstreamRevision': self.upstream_revision, 'projectId': identifier, 'repoPath': path}
        return {'id': identifier, 'name': name, 'slug': slug,
            'projectIdentityHash': hashlib.sha256(_encoded(identity)).hexdigest(),
            'upstreamRevision': self.upstream_revision, 'projectKind': 'native-openresearch',
            'evidenceKind': 'native-project-metadata', 'verificationStatus': 'metadata-observed'}

    async def list_projects(self, owner):
        self._check(owner)
        value = await self._http._request('GET', '/api/projects')
        self._check(owner)
        rows = value.get('projects')
        _require(type(rows) is list and len(rows) <= 4096)
        seen, result = set(), []
        for row in rows:
            if not isinstance(row, dict):
                raise OrxSessionError()
            identifier = _id(row.get('id'))
            _require(identifier not in seen)
            seen.add(identifier)
            if identifier in self._paths:
                result.append(self._project(row))
        return result

    async def inspect_project(self, owner, project_id):
        self._check(owner)
        _id(project_id)
        if project_id not in self._paths:
            raise OrxSessionError('ORX_WORKSPACE_PROJECT_NOT_ALLOWED')
        value = await self._http._request('GET', '/api/projects/' + project_id)
        self._check(owner)
        return self._project(value.get('project'), project_id)

    async def session_client(self, owner, project_id, profile_ref):
        """Construct original-project transport for the trusted Factory executor.

        This is not an HTTP inference endpoint or an execution grant. Caller must
        bind its exact project/source/profile to the immutable approved plan and
        preserve existing durable admission, budget and commit_intent controls.
        """
        await self.inspect_project(owner, project_id)
        profile = self._profiles.get(profile_ref)
        if profile is None:
            raise OrxSessionError('ORX_WORKSPACE_PROFILE_NOT_ALLOWED')
        self._check(owner, 'session:create')
        return _WorkspaceSessionHTTP(self, owner, project_id, profile)

    async def create_project(self, owner, **_request):
        self._check(owner)
        # No HTTP, no paths, no GitHub push, no model warmup, no approval boolean.
        # Existing task usage accounting cannot bound this upstream background call.
        raise OrxSessionError('ORX_PROJECT_CREATE_MODEL_BUDGET_REQUIRED')
