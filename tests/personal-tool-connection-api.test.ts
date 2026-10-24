import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, factoryRequest } from '../web/api.js';
import { personalToolConnectionApi as api, ToolConnectionError,
  type PersonalToolConnection, type PersonalToolDescriptor, type ToolConfiguration } from '../web/personalToolConnectionApi.js';
import type { UserConnection } from '../web/models.js';

vi.mock('../web/api.js', async importOriginal => ({
  ...await importOriginal<typeof import('../web/api.js')>(), factoryRequest: vi.fn(),
}));
const request = vi.mocked(factoryRequest);
const descriptor: PersonalToolDescriptor = {
  adapterId: 'fixture-cli-v1', revision: 'descriptor-1', toolName: 'fixture_lookup', description: 'Synthetic local lookup',
  inputSchema: { type: 'object', properties: { query: { type: 'string' } }, required: ['query'] }, transport: 'cli',
  credentialProviderId: 'fixture-tools-v1', credentialDestination: 'https://tools.example.invalid',
  capabilities: ['lookup:read'], permission: 'lookup:read', readOnly: true, timeoutSeconds: 30, maxOutputBytes: 65536,
};
const tool: PersonalToolConnection = {
  ownerId: 'alice', visibility: 'personal', isOwner: true, registrationRef: 'owner-tool-one', adapterId: descriptor.adapterId,
  revision: 'owner-configuration-1', descriptorRevision: descriptor.revision, kind: 'tool',
  toolName: descriptor.toolName, transport: 'cli', credentialRef: 'owner-credential', credentialRevision: 'credential-1',
  status: 'configured', available: true, capabilities: ['lookup:read'], createdAt: '2026-10-13T00:00:00Z',
  expiresAt: null, allowedActions: ['inspect', 'revoke', 'bind'],
};
const configuration: ToolConfiguration = {
  adapterId: tool.adapterId, credentialRef: tool.credentialRef!, credentialRevision: tool.credentialRevision!, requestId: 'configure:one',
};
const connection: UserConnection = {
  ref: 'connection-one', ownerId: 'alice', kind: 'tool', version: 1, revision: tool.revision,
  fingerprint: 'a'.repeat(64), registrationRef: tool.registrationRef, capabilities: ['lookup:read'], taskId: null,
  status: 'active', available: true, allowedActions: ['inspect', 'revoke'], createdAt: tool.createdAt, expiresAt: null, revokedAt: null,
};
const revoked = { ...tool, status: 'revoked' as const, available: false, allowedActions: ['inspect' as const] };
beforeEach(() => request.mockReset());

describe('personal CLI/MCP public metadata', () => {
  it('reads both static transports with owner scope and cancellation, projecting out secret/process fields', async () => {
    const signal = new AbortController().signal;
    request.mockResolvedValueOnce([{ ...descriptor, password: 'synthetic-secret', executable: '/private/executable' },
      { ...descriptor, adapterId: 'fixture-mcp-v1', transport: 'mcp', headers: { Authorization: 'synthetic-secret' } }]);
    expect(await api.descriptors('alice', signal)).toEqual([descriptor, { ...descriptor, adapterId: 'fixture-mcp-v1', transport: 'mcp' }]);
    expect(request).toHaveBeenCalledExactlyOnceWith('/personal-tools/descriptors', 'GET', undefined, signal, 'alice');
  });

  it('rejects malformed descriptors without accepting process configuration as an adapter declaration', async () => {
    for (const value of [{}, [{ ...descriptor, transport: 'shell' }], [{ ...descriptor, inputSchema: [] }],
      [{ ...descriptor, capabilities: ['lookup:read', 'lookup:read'] }], [{ ...descriptor, readOnly: 'true' }],
      [{ ...descriptor, timeoutSeconds: 0 }], [{ ...descriptor, maxOutputBytes: 1.5 }]]) {
      request.mockResolvedValueOnce(value);
      await expect(api.descriptors('alice')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
    }
  });

  it('reads current and historical registrations without confusing owner configuration and descriptor revisions', async () => {
    const signal = new AbortController().signal;
    const unavailable = { ...tool, status: 'credential_unavailable', available: false, allowedActions: ['inspect', 'revoke'] };
    const changed = { ...unavailable, status: 'adapter_changed' };
    request.mockResolvedValueOnce([{ ...tool, secret: 'synthetic-secret' }, revoked, unavailable, changed]);
    expect(await api.list('alice', signal)).toEqual([tool, revoked, unavailable, changed]);
    expect(request).toHaveBeenCalledExactlyOnceWith('/personal-tools', 'GET', undefined, signal, 'alice');
  });

  it('rejects foreign registrations, unknown states, and impossible availability or bind permissions', async () => {
    for (const value of [{ ...tool, ownerId: 'bob' }, { ...tool, kind: 'model' }, { ...tool, status: 'verified' },
      { ...tool, available: false }, { ...revoked, allowedActions: ['inspect', 'bind'] },
      { ...tool, createdAt: 'invalid' }, { ...tool, capabilities: 'lookup:read' }]) {
      request.mockResolvedValueOnce([value]);
      await expect(api.list('alice')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
    }
  });
});

describe('owner tool configuration and original receipt recovery', () => {
  it('accepts team metadata for another member while keeping owner credential references absent', async () => {
    const publicTool = { ...tool }; delete publicTool.credentialRef; delete publicTool.credentialRevision;
    const shared = { ...publicTool, visibility: 'team', isOwner: false, allowedActions: ['inspect', 'bind'] };
    request.mockResolvedValueOnce([shared]);
    expect(await api.list('bob')).toEqual([shared]);
    request.mockResolvedValueOnce([{ ...shared, credentialRef: 'owner-private-reference', credentialRevision: 'owner-private-revision' }]);
    await expect(api.list('bob')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  });

  it('saves sharing with its own request identity and recovers the original receipt read-only', async () => {
    const shared = { ...tool, visibility: 'team' as const, allowedActions: ['inspect', 'revoke', 'bind', 'sharing'] };
    request.mockResolvedValueOnce(shared);
    expect(await api.sharing('alice', tool.registrationRef, 'team', 'share:one')).toEqual(shared);
    expect(request).toHaveBeenLastCalledWith(`/personal-tools/${tool.registrationRef}/sharing`, 'POST',
      { visibility: 'team', requestId: 'share:one' }, undefined, 'alice');
    request.mockResolvedValueOnce({ requestId: 'share:one', action: 'tool.sharing', tool: shared });
    expect(await api.recover('alice', 'share:one')).toEqual({ requestId: 'share:one', action: 'tool.sharing', tool: shared });
    expect(request.mock.calls.map(call => call[1])).toEqual(['POST', 'GET']);
  });
  it('sends only immutable credential references once, with expected owner and original request ID', async () => {
    request.mockResolvedValueOnce({ ...tool, token: 'synthetic-secret' });
    expect(await api.configure('alice', { ...configuration, password: 'must-not-send', endpoint: 'https://untrusted.invalid' } as ToolConfiguration)).toEqual(tool);
    expect(request).toHaveBeenCalledExactlyOnceWith('/personal-tools', 'POST', configuration, undefined, 'alice');
  });

  it('does not accept a changed adapter/credential binding or revoked configuration as a successful new setup', async () => {
    for (const value of [{ ...tool, adapterId: 'another-adapter' }, { ...tool, credentialRef: 'another-credential' },
      { ...tool, credentialRevision: 'credential-2' }, revoked, { ...tool, ownerId: 'bob' }]) {
      request.mockResolvedValueOnce(value);
      await expect(api.configure('alice', configuration)).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
    }
  });

  it('recovers only the original tool action by GET, including its currently revoked projection', async () => {
    const receipt = { requestId: configuration.requestId, action: 'tool.configure', tool: revoked };
    request.mockResolvedValueOnce({ ...receipt, password: 'synthetic-secret' });
    expect(await api.recover('alice', configuration.requestId)).toEqual(receipt);
    expect(request).toHaveBeenCalledExactlyOnceWith('/personal-tools/requests/configure%3Aone', 'GET', undefined, undefined, 'alice');
    for (const value of [{ ...receipt, requestId: 'different' }, { ...receipt, action: 'connection.bind' },
      { ...receipt, tool: { ...tool, ownerId: 'bob' } }]) {
      request.mockResolvedValueOnce(value);
      await expect(api.recover('alice', configuration.requestId)).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
    }
  });

  it('confirms only the requested registration was revoked', async () => {
    request.mockResolvedValueOnce(revoked);
    expect(await api.revoke('alice', tool.registrationRef, 'revoke:one')).toEqual(revoked);
    expect(request).toHaveBeenCalledExactlyOnceWith('/personal-tools/owner-tool-one/revoke', 'POST', { requestId: 'revoke:one' }, undefined, 'alice');
    for (const value of [tool, { ...revoked, registrationRef: 'foreign-registration' }]) {
      request.mockResolvedValueOnce(value);
      await expect(api.revoke('alice', tool.registrationRef, 'revoke:one')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
    }
  });
});

describe('existing reusable connection binding boundary', () => {
  it('binds the requested tool registration and exact capabilities through the existing owner-scoped API', async () => {
    request.mockResolvedValueOnce({ ...connection, secret: 'synthetic-secret' });
    expect(await api.bind('alice', tool.registrationRef, 'bind:one', ['lookup:read'])).toEqual(connection);
    expect(request).toHaveBeenCalledExactlyOnceWith('/user-connections', 'POST', {
      registrationRef: tool.registrationRef, requestId: 'bind:one', capabilities: ['lookup:read'],
    }, undefined, 'alice');
  });

  it('rejects another owner/registration, non-tool or task-scoped binding, expanded permissions, and inactive results', async () => {
    for (const value of [{ ...connection, ownerId: 'bob' }, { ...connection, kind: 'environment' },
      { ...connection, registrationRef: 'foreign' }, { ...connection, taskId: 'some-task' },
      { ...connection, capabilities: ['lookup:read', 'write:any'] }, { ...connection, capabilities: [] },
      { ...connection, status: 'revoked', available: false }, { ...connection, fingerprint: 'not-a-hash' }]) {
      request.mockResolvedValueOnce(value);
      await expect(api.bind('alice', tool.registrationRef, 'bind:one', ['lookup:read'])).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
    }
  });

  it('reads a lost binding receipt without re-binding, preserving its current unavailable state', async () => {
    const receipt = { requestId: 'bind:one', action: 'bind', connection: { ...connection, status: 'changed', available: false } };
    request.mockResolvedValueOnce(receipt);
    expect(await api.recoverBinding('alice', 'bind:one')).toEqual(receipt);
    expect(request).toHaveBeenCalledExactlyOnceWith('/user-connections/requests/bind%3Aone', 'GET', undefined, undefined, 'alice');
    for (const value of [{ ...receipt, requestId: 'foreign' }, { ...receipt, action: 'revoke' },
      { ...receipt, connection: { ...connection, ownerId: 'bob' } }]) {
      request.mockResolvedValueOnce(value);
      await expect(api.recoverBinding('alice', 'bind:one')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
    }
  });
});

describe('safe tool connection request failures', () => {
  it('preserves precise bind precondition codes without leaking raw response details or replaying the request', async () => {
    for (const code of ['PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE', 'PERSONAL_TOOL_REVOKED', 'PERSONAL_TOOL_ADAPTER_UNAVAILABLE', 'PERSONAL_TOOL_ADAPTER_CHANGED']) {
      request.mockRejectedValueOnce(new ApiError('synthetic private credential detail', 409, code));
      const failure = await api.bind('alice', tool.registrationRef, 'bind:one', ['lookup:read']).catch(error => error);
      expect(failure).toBeInstanceOf(ToolConnectionError); expect(failure).toMatchObject({ status: 409, code });
      expect(failure.message).not.toContain('synthetic');
    }
    expect(request).toHaveBeenCalledTimes(4); expect(request.mock.calls.every(call => call[1] === 'POST')).toBe(true);
  });

  it('never retries or recovers a mutation automatically and exposes no raw error content', async () => {
    request.mockRejectedValueOnce(new ApiError('synthetic credential in upstream stderr', 503, 'synthetic credential code'));
    const failure = await api.configure('alice', configuration).catch(error => error);
    expect(failure).toBeInstanceOf(ToolConnectionError);
    expect(failure).toMatchObject({ status: 503, code: undefined });
    expect(failure.message).not.toContain('synthetic');
    expect(JSON.stringify(failure)).not.toContain('synthetic');
    expect(request).toHaveBeenCalledTimes(1);
  });

  it('preserves an expected-owner rejection and keeps failed recovery read-only', async () => {
    request.mockRejectedValueOnce(new ApiError('private response detail', 403, 'EXPECTED_OWNER_MISMATCH'));
    await expect(api.bind('alice', tool.registrationRef, 'bind:one', ['lookup:read'])).rejects.toMatchObject({ status: 403, code: 'EXPECTED_OWNER_MISMATCH' });
    request.mockRejectedValueOnce(new ApiError('private lookup detail', 404));
    await expect(api.recover('alice', 'configure:one')).rejects.toMatchObject({ status: 404 });
    expect(request.mock.calls.map(call => call[1])).toEqual(['POST', 'GET']);
  });

  it('rejects invalid configuration references and duplicate binding capabilities before any request', async () => {
    await expect(api.configure('alice', { ...configuration, credentialRef: '' })).rejects.toMatchObject({ status: 422 });
    await expect(api.bind('alice', tool.registrationRef, 'bind:one', ['lookup:read', 'lookup:read'])).rejects.toMatchObject({ status: 422 });
    expect(request).not.toHaveBeenCalled();
  });
});
