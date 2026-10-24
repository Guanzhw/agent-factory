"""Explicit, bounded capture of an ended owner ORX session's real text files.

Original ORX discovers git changes and reads bytes. Factory never parses chat
filenames or accepts host paths, and stores immutable bytes through its existing
artifact writer/download boundary. This is a session snapshot, not proof of
scientific success or exclusive attribution of each file to one prompt.
"""
import hashlib
from pathlib import PurePosixPath
from typing import Callable, cast

from fastapi import HTTPException
from sqlalchemy import select

from .personal_command_profile import command_from_plan, validate_intent
from .personal_orx_transport import PersonalOrxHandle
from agent_factory.personal_remote_provider import RemoteConnectionError
from agent_factory.store import digest

MAX_FILES = 16


def require(value, code):
    if not value: raise HTTPException(409, code)


def transcript_fingerprint(observation):
    return digest({key: observation.get(key) for key in ('messages', 'busy', 'queued', 'activeLeafId')})


class NativeResearchArtifacts:
    def __init__(self, sessions):
        self.sessions, self.store, self.auth = sessions, sessions.store, sessions.auth

    def _scope(self, owner, task_id, request_id, expected_pin):
        self.auth.require_member(owner)
        task = self.store.task(task_id, owner)
        command = command_from_plan(self.store.plan(task['plan_id'], owner))
        require(command['action'] == 'prompt' and command['requestId'] == request_id, 'NATIVE_ARTIFACT_TASK_MISMATCH')
        receipt = self.sessions._command(owner, request_id)
        require(receipt is not None and receipt['state'] == 'result_observed', 'NATIVE_ARTIFACT_TURN_UNRESOLVED')
        validate_intent(command, receipt['intent'])
        identity = {'executionContract': 'personal-external-v1', 'taskId': task_id,
            'planId': task['plan_id'], 'nativeRunId': task['run_id']}
        require(task['terminal'] and receipt['identity'] == identity, 'NATIVE_ARTIFACT_TASK_MISMATCH')
        row = self.sessions._session(owner, command['factorySessionId'])
        body = row['body']
        require(body['namespace'] == 'native-openresearch' and body['nativeSessionId'] == command['nativeSessionId']
            and body['nativeProjectId'] == command['nativeProjectId']
            and body['connectionPin']['fingerprint'] == expected_pin, 'NATIVE_ARTIFACT_SESSION_CHANGED')
        with self.store.engine.connect() as conn:
            require(not self.sessions._rebind_blockers(conn, owner, row), 'NATIVE_ARTIFACT_TURN_UNRESOLVED')
        require(self.store.latest_personal_task(owner, row['id'], body['nativeProjectId'], body['nativeSessionId']) == identity,
            'NATIVE_ARTIFACT_LATER_TURN')
        return command, row, receipt

    def capture(self, owner, task_id, request_id, expected_pin):
        _command, row, receipt = self._scope(owner, task_id, request_id, expected_pin)
        body = row['body']
        handle, _ = self.sessions._handle(owner, body['connectionPin'])
        require(type(handle) is PersonalOrxHandle and handle.provider.provider_id == 'platform-openresearch-session-v1',
            'NATIVE_ARTIFACT_ADAPTER_REQUIRED')
        skipped, files = [], []
        limit = self.store.settings.experiment_output_bytes
        try:
            before = handle.observe_session(body['nativeSessionId'])
            require(before.get('busy') is False and not before.get('queued')
                and transcript_fingerprint(before) == transcript_fingerprint(row['observation']), 'NATIVE_ARTIFACT_SESSION_CHANGED')
            paths = handle.worktree_files(body['nativeSessionId'])
            for path in paths[MAX_FILES:]: skipped.append({'path': path, 'reason': 'FILE_COUNT_LIMIT'})
            total = 0
            for path in paths[:MAX_FILES]:
                try:
                    raw = handle.worktree_file(body['nativeSessionId'], path)
                except RemoteConnectionError:
                    skipped.append({'path': path, 'reason': 'FILE_UNAVAILABLE_OR_INCOMPLETE'})
                    continue
                if len(raw) > limit or total + len(raw) > limit:
                    skipped.append({'path': path, 'reason': 'OUTPUT_BYTE_LIMIT'})
                    continue
                total += len(raw)
                files.append((path, raw))
            after = handle.observe_session(body['nativeSessionId'])
            require(transcript_fingerprint(before) == transcript_fingerprint(after), 'NATIVE_ARTIFACT_SESSION_CHANGED')
        except RemoteConnectionError:
            raise HTTPException(409, 'NATIVE_ARTIFACT_READ_UNCONFIRMED') from None
        cast(Callable, handle.recheck)(('project:read', 'session:read'))
        captured = []
        # Remote reads finish before holding the existing owner command lock.
        # It also excludes a concurrent prompt/rebind/interrupt while saving.
        with self.store.transaction() as conn:
            self.sessions.connections._lock(conn, 'personal-agent:' + owner)
            self.auth.require_member(owner)
            current = conn.execute(select(self.sessions.sessions).where(self.sessions.sessions.c.owner_id == owner,
                self.sessions.sessions.c.id == row['id'])).mappings().one()
            current_command = conn.execute(select(self.sessions.commands).where(self.sessions.commands.c.owner_id == owner,
                self.sessions.commands.c.request_id == request_id)).mappings().one()
            require(current['body_hash'] == row['body_hash'] and digest(current['body']) == row['body_hash']
                and not self.sessions._rebind_blockers(conn, owner, current)
                and current_command['state'] == 'result_observed' and current_command['fingerprint'] == receipt['fingerprint']
                and digest(current_command['intent']) == receipt['fingerprint']
                and current_command['identity_hash'] == receipt['identity_hash']
                and digest(current_command['identity']) == receipt['identity_hash'], 'NATIVE_ARTIFACT_SESSION_CHANGED')
            require(self.store.latest_personal_task(owner, row['id'], body['nativeProjectId'], body['nativeSessionId']) == receipt['identity'],
                'NATIVE_ARTIFACT_LATER_TURN')
            cast(Callable, handle.recheck)(('project:read', 'session:read'))
            existing = self.store.artifacts(task_id)
            used = sum(item['size'] for item in existing)
            for path, raw in files:
                fingerprint = hashlib.sha256(raw).hexdigest()
                prior = next((item for item in existing if item.get('provenance', {}).get('sourcePath') == path
                    and item.get('provenance', {}).get('nativeSessionId') == body['nativeSessionId']
                    and item.get('provenance', {}).get('commandRequestId') == request_id
                    and item.get('provenance', {}).get('source') == 'native-orx-file-api'
                    and item.get('sha256') == fingerprint), None)
                if prior:
                    self.store.artifact(task_id, prior['id'])  # Recheck stored bytes; never conceal corruption.
                    captured.append(prior)
                    continue
                if used + len(raw) > limit or len(existing) >= MAX_FILES:
                    skipped.append({'path': path, 'reason': 'TASK_OUTPUT_LIMIT'})
                    continue
                name = PurePosixPath(path).name
                if '/' in path: name = hashlib.sha256(path.encode()).hexdigest()[:8] + '--' + name[-110:]
                media = {'json': 'application/json', 'csv': 'text/csv', 'md': 'text/markdown'}.get(
                    name.rsplit('.', 1)[-1].lower(), 'text/plain')
                item = self.store.artifact_write(task_id, name, raw, media, metadata={
                    'evidenceKind': 'native-worktree-file', 'verificationStatus': 'bytes-captured',
                    'scientificConclusionVerified': False, 'attribution': 'session-worktree-snapshot',
                    'source': 'native-orx-file-api', 'sourcePath': path, 'sourceSHA256': fingerprint,
                    'nativeProjectId': body['nativeProjectId'], 'nativeSessionId': body['nativeSessionId'],
                    'factorySessionId': row['id'], 'commandRequestId': request_id,
                    'nativeTurnId': (receipt['result'] or {}).get('nativeTurnId'),
                    'connectionPinFingerprint': expected_pin})
                existing.append(item); captured.append(item); used += len(raw)
            self.auth.require_member(owner)
        return {'taskId': task_id, 'ownerId': owner, 'commandRequestId': request_id,
            'nativeProjectId': body['nativeProjectId'], 'nativeSessionId': body['nativeSessionId'],
            'artifacts': captured, 'skipped': skipped, 'scientificConclusionVerified': False}
