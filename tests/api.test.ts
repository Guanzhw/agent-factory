import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../web/api.js';

afterEach(() => vi.unstubAllGlobals());

describe('factory HTTP boundary', () => {
  it('preserves the same admission key when a caller retries', async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ id: 'task' }), { status: 202 })));
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
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('rejects unexpected HTML and encodes artifact identifiers', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>fallback</html>', { status: 200 })));
    await expect(api.jobs()).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
    expect(api.artifactUrl('../foreign', 'a/b')).toBe('/api/factory/jobs/..%2Fforeign/artifacts/a%2Fb');
  });
});
