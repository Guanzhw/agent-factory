import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../web/api.js';

afterEach(() => vi.unstubAllGlobals());

describe('factory HTTP boundary', () => {
  it('preserves the same admission key when a caller retries', async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ id: 'task', planId: 'immutable-plan' }), { status: 202 })));
    vi.stubGlobal('fetch', fetch);
    await api.instantiate('immutable-plan', 'stable-request');
    await api.instantiate('immutable-plan', 'stable-request');
    expect(fetch.mock.calls[0][1].body).toBe(fetch.mock.calls[1][1].body);
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ planId: 'immutable-plan', requestId: 'stable-request' });
    expect(fetch.mock.calls[0][1].credentials).toBe('same-origin');
  });
  it('retains server conflict details instead of interpreting an error as success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ message: 'Stale requirement', code: 'STALE_REQUIREMENT' }), { status: 409 })));
    await expect(api.approve('task', 'requirement', 123, true)).rejects.toMatchObject({ status: 409, code: 'STALE_REQUIREMENT', message: 'Stale requirement' });
  });
  it('makes connection failure explicit and does not retry a mutating request', async () => {
    const fetch = vi.fn().mockRejectedValue(new TypeError('offline'));
    vi.stubGlobal('fetch', fetch);
    await expect(api.instantiate('plan', 'request')).rejects.toBeInstanceOf(ApiError);
    expect(fetch.mock.calls.filter(call => call[1].method === 'POST')).toHaveLength(1);
    expect(fetch.mock.calls[1][0]).toBe('/api/factory/requests/request');
    expect(fetch.mock.calls[1][1].method).toBe('GET');
  });
  it('rejects unexpected HTML and encodes artifact identifiers', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>fallback</html>', { status: 200 })));
    await expect(api.jobs()).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
    expect(api.artifactUrl('../foreign', 'a/b')).toBe('/api/factory/jobs/..%2Fforeign/artifacts/a%2Fb');
  });
});

describe('ambiguous admission recovery', () => {
  function recoveryFetch(first: Response, receiptPlan = 'plan') {
    return vi.fn().mockResolvedValueOnce(first)
      .mockResolvedValueOnce(new Response(JSON.stringify({requestId:'key', taskId:'task', planId:receiptPlan})))
      .mockResolvedValueOnce(new Response(JSON.stringify({job:{id:'task', planId:'plan', status:'waiting_input'}})));
  }
  it('recovers an acknowledged task by read after a server error without another mutation', async () => {
    const fetch = recoveryFetch(new Response('uncertain', {status:503}));
    vi.stubGlobal('fetch', fetch);
    await expect(api.instantiate('plan', 'key')).resolves.toMatchObject({id:'task', status:'waiting_input'});
    expect(fetch.mock.calls.map(call => call[1].method)).toEqual(['POST','GET','GET']);
    expect(fetch.mock.calls[1][0]).toBe('/api/factory/requests/key');
    expect(fetch.mock.calls[2][0]).toBe('/api/factory/jobs/task');
  });
  it('recovers an ambiguous successful response through the same read path', async () => {
    const fetch = recoveryFetch(new Response(JSON.stringify({accepted:true}), {status:202}));
    vi.stubGlobal('fetch', fetch);
    await expect(api.instantiate('plan', 'key')).resolves.toMatchObject({id:'task'});
    expect(fetch.mock.calls.filter(call => call[1].method === 'POST')).toHaveLength(1);
  });
  it('does not hide a changed-plan receipt behind an earlier task', async () => {
    const fetch = recoveryFetch(new Response('uncertain', {status:503}), 'different-plan');
    vi.stubGlobal('fetch', fetch);
    await expect(api.instantiate('plan', 'key')).rejects.toMatchObject({status:503});
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it('preserves a known idempotency conflict without recovery reads', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:'IDEMPOTENCY_CONFLICT'}), {status:409}));
    vi.stubGlobal('fetch', fetch);
    await expect(api.instantiate('plan', 'key')).rejects.toMatchObject({status:409});
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

describe('remote admission recovery binds the selected execution target', () => {
  it('reads the original remote task after acknowledgement loss without dispatching twice', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(new Response('uncertain', {status:503}))
      .mockResolvedValueOnce(new Response(JSON.stringify({requestId:'key', taskId:'task', planId:'plan', executionTargetRef:'trusted-receiver'})))
      .mockResolvedValueOnce(new Response(JSON.stringify({job:{id:'task', planId:'plan', status:'waiting_input', executionPlacement:{targetRef:'trusted-receiver'}}})));
    vi.stubGlobal('fetch', fetch);
    await expect(api.instantiate('plan', 'key', 'trusted-receiver')).resolves.toMatchObject({id:'task', executionPlacement:{targetRef:'trusted-receiver'}});
    expect(fetch.mock.calls.map(call => call[1].method)).toEqual(['POST','GET','GET']);
    expect(JSON.parse(fetch.mock.calls[0][1].body).executionTargetRef).toBe('trusted-receiver');
  });
  it('preserves uncertainty when the original key belongs to a different target', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(new Response('uncertain', {status:503}))
      .mockResolvedValueOnce(new Response(JSON.stringify({requestId:'key', taskId:'task', planId:'plan', executionTargetRef:'earlier-target'})));
    vi.stubGlobal('fetch', fetch);
    await expect(api.instantiate('plan', 'key', 'requested-target')).rejects.toMatchObject({status:503});
    expect(fetch.mock.calls.map(call => call[1].method)).toEqual(['POST','GET']);
  });
});

describe('bounded owner-scoped Factory event replay', () => {
  const receipt = () => ({ events: [{ id: 17, jobId: 'task', sequence: 1, type: 'fixture', message: 'Synthetic evidence', data: {}, createdAt: '2026-10-01T00:00:00Z', payloadSha256: 'a'.repeat(64) }],
    nextCursor: 'opaque-signed-cursor', streamId: 'b1696e85-12ef-4e58-910d-a4eebf26b0f1', schema: 1, nativeCursor: false,
    source: 'factory-af_events', hasMore: false, highWatermark: 17, highWatermarkSequence: 1, afterSequence: 0,
    startSequence: 1, endSequence: 1, payloadSha256: 'b'.repeat(64), payloadBytes: 300 });
  it('uses one read with encoded task and exact opaque cursor', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(receipt())));
    vi.stubGlobal('fetch', fetch);
    await expect(api.events('task', 'signed+cursor/=')).resolves.toMatchObject({ endSequence: 1 });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe('/api/factory/jobs/task/events?limit=100&cursor=signed%2Bcursor%2F%3D');
    expect(fetch.mock.calls[0][1].method).toBe('GET');
  });
  it('fails closed for foreign task, noncontiguous sequence, native-cursor claim, and malformed page', async () => {
    for (const changed of [ { ...receipt(), events: [{ ...receipt().events[0], jobId: 'foreign' }] },
      { ...receipt(), events: [{ ...receipt().events[0], sequence: 9 }] },
      { ...receipt(), nativeCursor: true }, { ...receipt(), hasMore: true }, { events: [] } ]) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(changed))));
      await expect(api.events('task')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
    }
  });
  it('preserves prefix-change recovery details without repeating or mutating work', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({message:'Earlier commits changed cursor prefix',code:'EVENT_PREFIX_CHANGED'}),{status:409}));
    vi.stubGlobal('fetch', fetch);
    await expect(api.events('task', 'old-cursor')).rejects.toMatchObject({ status:409,code:'EVENT_PREFIX_CHANGED' });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][1].method).toBe('GET');
  });
});

describe('trusted user connection lifecycle boundary', () => {
  const connection = () => ({ ref: 'owned-reference', ownerId: 'alice', version: 1, fingerprint: 'a'.repeat(64), kind: 'tool', revision: 'test-1', capabilities: ['research:read'], taskId: null, registrationRef: 'operator-installed', expiresAt: null, createdAt: '2026-10-02T00:00:00Z', revokedAt: null, status: 'active', available: true, allowedActions: ['inspect', 'revoke'] });
  it('binds only a trusted registration with an explicit narrowed scope and retained request ID', async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(connection()), { status: 201 })));
    vi.stubGlobal('fetch', fetch);
    await api.bindConnection('operator-installed', 'same-key', ['research:read']);
    await api.bindConnection('operator-installed', 'same-key', ['research:read']);
    expect(fetch.mock.calls.map(call => JSON.parse(call[1].body))).toEqual([{ registrationRef: 'operator-installed', requestId: 'same-key', capabilities: ['research:read'] }, { registrationRef: 'operator-installed', requestId: 'same-key', capabilities: ['research:read'] }]);
  });
  it('rejects changed registration or task confirmation and contradictory availability', async () => {
    for (const changed of [{ ...connection(), registrationRef: 'other' }, { ...connection(), taskId: 'other-task' }, { ...connection(), status: 'revoked' }]) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(changed))));
      await expect(api.bindConnection('operator-installed', 'key', ['research:read'])).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
    }
  });
  it('does not turn a foreign or unconfirmed revoke acknowledgement into success', async () => {
    for (const changed of [connection(), { ...connection(), ref: 'foreign', status: 'revoked', available: false }]) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(changed))));
      await expect(api.revokeConnection('owned-reference', 'key')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
    }
    const fetch = vi.fn().mockRejectedValue(new TypeError('offline'));
    vi.stubGlobal('fetch', fetch);
    await expect(api.revokeConnection('owned-reference', 'key')).rejects.toMatchObject({ code: 'OFFLINE' });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('fails closed on unrecognized registration metadata without accepting credential contents', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify([{ registrationRef: 'operator-installed', kind: 'tool', revision: 'test-1', capabilities: [], available: true, status: 'changed', expiresAt: null, allowedActions: ['bind'] }]))));
    await expect(api.connectionRegistrations()).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  });
});

describe('governed application and immutable proposal boundary', () => {
  const pin = { id: 'application', version: 1, sha256: 'a'.repeat(64) };
  const material = { id: 'prompt', version: 1, sha256: 'b'.repeat(64) };
  const budget = { toolCalls: 8, maxDepth: 2, maxChildren: 4, experimentSeconds: 8, outputBytes: 65536 };
  const application = () => ({ ...pin, name: 'Synthetic application', description: 'Synthetic fixture', discoveryKeywords: ['fixture'], defaultForDiscovery: false, defaultMode: 'literature', modes: { literature: { materialRefs: [material], materialChoices: {}, capabilities: ['research:read'], budget, config: {}, toolOrder: ['literature_search'], connectionRequirements: [] } } });
  const proposal = () => ({ id: 'proposal', ownerId: 'alice', createdAt: '2026-10-02T00:00:00Z', parentId: null, input: { goal: 'Bounded fixture' }, candidate: { ownerId: 'alice', application: 'application', applicationRef: pin, mode: 'literature', normalizedGoal: 'Bounded fixture', materialRefs: [material], materials: [material], tools: ['literature_search'], capabilities: ['research:read'], budget, config: {}, instructions: 'Synthetic', status: 'ready', missing: [], policy: {}, syntheticFixture: true, executionBindings: {}, bindingManifest: {}, fingerprint: 'c'.repeat(64) }, selection: { method: 'explicit-application', matchedKeywords: [] }, fingerprint: 'd'.repeat(64), state: 'pending', planId: null, allowedActions: ['revise', 'reject', 'accept'] });
  it('sends bounded exact choices and connection references; revision has a distinct immutable parent', async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(proposal()), { status: 201 })));
    vi.stubGlobal('fetch', fetch);
    const input = { goal: 'Bounded fixture', applicationRef: pin, materialChoices: { prompt: material }, connectionRefs: { research: 'owned-reference' } };
    await api.propose(input, 'propose-key'); await api.reviseProposal('old/proposal', input, 'revision-key');
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ ...input, requestId: 'propose-key' });
    expect(fetch.mock.calls[1][0]).toBe('/api/factory/compositions/proposals/old%2Fproposal/revise');
  });
  it('rejects material pin substitution, incomplete candidates, and a foreign inspected proposal', async () => {
    for (const changed of [{ ...proposal(), candidate: { ...proposal().candidate, materials: [{ ...material, sha256: 'f'.repeat(64) }] } }, { ...proposal(), candidate: { ...proposal().candidate, bindingManifest: null } }, { ...proposal(), id: 'foreign' }]) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(changed))));
      await expect(api.inspectProposal('proposal')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
    }
  });
  it('requires distinct-administrator publication evidence bound to the same immutable body', async () => {
    const review = { id: 'review', applicationRef: pin, authorId: 'manager', reviewerId: null, decision: 'pending', application: application(), state: 'draft', separateAdministratorRequired: true, taskApprovalSeparate: true };
    for (const changed of [{ ...review, separateAdministratorRequired: false }, { ...review, applicationRef: { ...pin, sha256: 'f'.repeat(64) } }]) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify([changed]))));
      await expect(api.applicationReviews()).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
    }
  });
  it('retains conflict codes and sends one acceptance mutation on offline or stale approval', async () => {
    const fetch = vi.fn().mockRejectedValue(new TypeError('offline'));
    vi.stubGlobal('fetch', fetch);
    await expect(api.acceptProposal('proposal', 'stable-key')).rejects.toMatchObject({ code: 'OFFLINE' });
    expect(fetch).toHaveBeenCalledTimes(1);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:'APPLICATION_WITHDRAWN'}), {status:409})));
    await expect(api.acceptProposal('proposal', 'stable-key')).rejects.toMatchObject({status:409, message:'APPLICATION_WITHDRAWN'});
  });
});
