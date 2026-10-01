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
