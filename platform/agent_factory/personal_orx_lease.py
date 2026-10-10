"""Refresh only an unchanged owner's expired ORX lease; never replay remote work.

The existing connection command ledger fences local renewal. Original references,
plans and command intents remain immutable. Health probes are existing GET-only
verification; native-session migration uses the existing guarded rebind protocol.
"""
from uuid import uuid4
from datetime import datetime, timedelta

from fastapi import HTTPException

from .personal_orx_transport import PERSONAL_ORX_PROVIDER_ID
from .store import digest, now


class PersonalOrxLease:
    def __init__(self, sessions):
        self.sessions = sessions
        self.connections = sessions.connections

    def _scope(self, conn, owner, reference, expected_fingerprint):
        service = self.connections
        original = service._row(conn, owner, reference)
        old = original['body']
        if original['fingerprint'] != expected_fingerprint or original['state'] != 'ACTIVE':
            raise HTTPException(409, 'ORX_LEASE_EXPLICIT_SELECTION_REQUIRED')
        if old['kind'] != 'orx' or old['taskId'] is not None or 'session:read' not in old['capabilities']:
            raise HTTPException(409, 'ORX_LEASE_EXPLICIT_SELECTION_REQUIRED')
        resource, config = service.personal._row(conn, owner, old['registrationRef'])
        provider = service.personal._provider(config)
        if config['providerId'] not in {PERSONAL_ORX_PROVIDER_ID, 'platform-openresearch-session-v1',
                'ssh-openresearch-session-v1'} or resource['state'] not in {'VERIFIED', 'FAILED'}:
            raise HTTPException(409, 'ORX_LEASE_EXPLICIT_SELECTION_REQUIRED')
        if not provider.authorized(owner, config['configuration']):
            raise HTTPException(409, 'REMOTE_CREDENTIAL_UNAVAILABLE')
        effective = provider.effective_capabilities(config['configuration'])
        verified = resource['verification']
        if (resource['state'] == 'VERIFIED' and (not isinstance(verified, dict) or digest(verified) != resource['verification_hash']
                or verified.get('configRevision') != config['revision']
                or verified.get('policyRevision') != config['policyRevision']
                or set(verified.get('capabilities', [])) != effective)
                or not set(old['capabilities']) <= effective):
            raise HTTPException(409, 'ORX_LEASE_EXPLICIT_SELECTION_REQUIRED')
        signature = digest({'operation': 'orx.lease-refresh', 'reference': reference,
            'originalFingerprint': expected_fingerprint, 'configuration': digest(config),
            'effectiveCapabilities': sorted(effective)})
        return original, resource, config, signature

    @staticmethod
    def _original_proof(owner, old, resource, config):
        verified = resource['verification']
        if (not isinstance(verified, dict) or digest(verified) != resource['verification_hash']
                or verified.get('configRevision') != config['revision']
                or verified.get('policyRevision') != config['policyRevision']):
            raise HTTPException(409, 'ORX_LEASE_EXPLICIT_SELECTION_REQUIRED')
        # Compare fresh health identity against the original proof as well. Only
        # the lease timestamp/revision may change, never instance/project/policy.
        current = verified
        verified = {**verified, 'revision': old['revision'], 'expiresAt': old['expiresAt'],
            'verifiedAt': (datetime.fromisoformat(old['expiresAt']) - timedelta(minutes=15)).isoformat()}
        # Reconstruct metadata only. Never construct or resolve an expired handle.
        trusted = {'owner': owner, 'kind': old['kind'], 'adapterRef': config['providerId'],
            'capabilities': sorted(verified['capabilities']), 'revision': verified['revision'],
            'expiresAt': verified['expiresAt'], 'available': True,
            'handleRef': 'remote-handle-' + digest({'configuration': config, 'verification': verified})}
        if digest(trusted) != old['trustedFingerprint']:
            raise HTTPException(409, 'ORX_LEASE_EXPLICIT_SELECTION_REQUIRED')
        return digest({**trusted, 'revision': current['revision'], 'expiresAt': current['expiresAt'],
            'handleRef': 'remote-handle-' + digest({'configuration': config, 'verification': current})})

    def refresh(self, owner, reference, expected_fingerprint, *, depth=0):
        service = self.connections
        service.auth.require(owner, 'run')
        if depth >= 32:
            raise HTTPException(409, 'ORX_LEASE_REFRESH_CHAIN_LIMIT')
        key = 'orx-lease-refresh:' + digest({'ref': reference, 'fingerprint': expected_fingerprint})[:40]
        with service._write() as conn:
            service._lock(conn, owner)
            original, resource, config, signature = self._scope(conn, owner, reference, expected_fingerprint)
            current = service._project(conn, owner, original)
            if current['available']:
                return current
            previous = service._command(conn, owner, key, signature)
            if previous is None:
                if current['status'] != 'expired':
                    raise HTTPException(409, 'ORX_LEASE_EXPLICIT_SELECTION_REQUIRED')
                self._original_proof(owner, original['body'], resource, config)
                conn.execute(service.commands.insert().values(owner_id=owner, request_id=key,
                    fingerprint=signature, action='orx.lease-refresh', result_ref=reference, created_at=now()))
            elif previous['action'] != 'orx.lease-refresh':
                raise HTTPException(409, 'IDEMPOTENCY_CONFLICT')
            elif previous['result_ref'] != reference:
                target = service._row(conn, owner, previous['result_ref'])
                if (target['body']['registrationRef'] != original['body']['registrationRef']
                        or target['body']['capabilities'] != original['body']['capabilities']
                        or target['body']['taskId'] is not None):
                    raise HTTPException(409, 'ORX_LEASE_EXPLICIT_SELECTION_REQUIRED')
                projected = service._project(conn, owner, target)
                if projected['available']:
                    return projected
                next_ref, next_fingerprint = target['ref'], target['fingerprint']
                # Do not hold the metadata transaction during bounded remote IO.
                target = None
            else:
                next_ref = None
            if previous is None or previous['result_ref'] == reference:
                next_ref = None
        if next_ref is not None:
            return self.refresh(owner, next_ref, next_fingerprint, depth=depth + 1)
        # A lost health response can repeat GET-only verification, never create,
        # prompt, interrupt or project operations. Each probe retains the 15m TTL.
        service.personal.verify(owner, config['registrationRef'], 'orx-lease-probe:' + uuid4().hex)
        with service._read() as conn:
            _, verified, checked, current_signature = self._scope(conn, owner, reference, expected_fingerprint)
            if current_signature != signature or checked != config:
                raise HTTPException(409, 'ORX_LEASE_EXPLICIT_SELECTION_REQUIRED')
            trusted_fingerprint = self._original_proof(owner, original['body'], verified, checked)
            revision = verified['verification']['revision']
        try:
            candidate = service.bind(owner, config['registrationRef'],
                'orx-lease-bind:' + digest({'old': reference, 'revision': revision})[:40],
                capabilities=original['body']['capabilities'],
                expected_trusted_revision=revision, expected_trusted_fingerprint=trusted_fingerprint)
        except HTTPException as error:
            if error.status_code == 409 and error.detail == 'CONNECTION_VERIFICATION_CHANGED':
                raise HTTPException(409, 'ORX_LEASE_EXPLICIT_SELECTION_REQUIRED') from None
            raise
        with service._write() as conn:
            service._lock(conn, owner)
            _, verified, checked, current_signature = self._scope(conn, owner, reference, expected_fingerprint)
            if current_signature != signature:
                raise HTTPException(409, 'ORX_LEASE_EXPLICIT_SELECTION_REQUIRED')
            current_proof = self._original_proof(owner, original['body'], verified, checked)
            if current_proof != trusted_fingerprint or verified['verification']['revision'] != revision:
                raise HTTPException(409, 'ORX_LEASE_EXPLICIT_SELECTION_REQUIRED')
            target = service._row(conn, owner, candidate['ref'])
            service._current(conn, owner, target)
            previous = service._command(conn, owner, key, signature)
            if previous['result_ref'] == reference:
                conn.execute(service.commands.update().where(service.commands.c.owner_id == owner,
                    service.commands.c.request_id == key, service.commands.c.result_ref == reference)
                    .values(result_ref=candidate['ref']))
            else:
                candidate = service._project(conn, owner, service._row(conn, owner, previous['result_ref']))
        if not candidate['available']:
            raise HTTPException(409, 'ORX_LEASE_REFRESH_UNAVAILABLE')
        return candidate

    def continue_session(self, owner, session_id, expected_fingerprint):
        self.connections.auth.require(owner, 'run')
        session = self.sessions.inspect(owner, session_id)
        if session['namespace'] != 'native-openresearch' or not session['nativeSessionId']:
            raise HTTPException(409, 'PERSONAL_SESSION_ACK_UNKNOWN')
        old = session['connectionPin']
        if old['fingerprint'] != expected_fingerprint:
            # Recover only our own completed local migration after a lost response.
            latest = session['bindingHistory'][-1] if session['bindingHistory'] else None
            if not latest or not latest['requestId'].startswith('orx-lease-continue:') or latest['oldConnectionPin']['fingerprint'] != expected_fingerprint:
                raise HTTPException(409, 'PERSONAL_REBIND_STALE_OLD_PIN')
            return {'state': 'ready' if session['bindingStatus'] == 'active' else 'unavailable', 'session': session}
        candidate = self.refresh(owner, old['ref'], old['fingerprint'])
        if candidate['ref'] == old['ref']:
            session = self.sessions.inspect(owner, session_id, refresh=True)
            with self.connections._read() as conn:
                blockers = self.sessions._rebind_blockers(conn, owner, self.sessions._session(owner, session_id))
            return {'state': 'waiting' if blockers else 'ready', 'session': session}
        preview = self.sessions.preview_rebind(owner, session_id, candidate['ref'], old['fingerprint'])
        if not preview['canRebind']:
            return {'state': 'waiting', 'blocker': preview['blocker'],
                'session': self.sessions.inspect(owner, session_id)}
        key = 'orx-lease-continue:' + digest({'session': session_id, 'old': old['fingerprint'],
            'new': candidate['fingerprint']})[:40]
        result = self.sessions.rebind(owner, session_id, candidate['ref'], key,
            expected_old_fingerprint=old['fingerprint'], expected_new_fingerprint=candidate['fingerprint'])
        return {'state': 'ready', 'session': result['session']}
