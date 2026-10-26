import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { publicationApi } from '../web/publicationApi.js';
import { clearBrowserSession, configureBrowserAuth } from '../web/browserAuth.js';

const application = { id: 'department/app', version: 2, sha256: 'a'.repeat(64), name: 'Synthetic shared application', modes: {} };
const material = { id: 'department/material', version: 2, sha256: 'b'.repeat(64), published: true };
const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200 });
beforeEach(() => { clearBrowserSession(); configureBrowserAuth({ enabled: false, oidcEnabled: false, localLoginEnabled: false, loginPath: '/api/factory/auth/login', logoutPath: '/api/factory/auth/logout' }); });
afterEach(() => { clearBrowserSession(); vi.unstubAllGlobals(); });

it('accepts the actual raw application publication shape and pins the request to its member', async () => {
  const fetch = vi.fn().mockResolvedValue(json(application)); vi.stubGlobal('fetch', fetch);
  await expect(publicationApi.publishApplication('alice', application.id, 2, 'publish-once')).resolves.toEqual(application);
  expect(fetch).toHaveBeenCalledWith('/api/factory/applications/department%2Fapp/versions/2/publish', expect.objectContaining({ method: 'POST', credentials: 'same-origin', redirect: 'error', headers: expect.objectContaining({ 'X-Factory-Expected-Owner': 'alice' }), body: JSON.stringify({ requestId: 'publish-once' }) }));
});
it('accepts the raw material publication shape and binds its request to the current owner', async () => {
  const fetch = vi.fn().mockResolvedValue(json(material)); vi.stubGlobal('fetch', fetch);
  await expect(publicationApi.publishMaterial('alice', material.id, 2, 'publish-once')).resolves.toEqual(material);
  expect(fetch).toHaveBeenCalledWith('/api/factory/material-governance/versions/department%2Fmaterial/2/publish', expect.objectContaining({ headers: expect.objectContaining({ 'X-Factory-Expected-Owner': 'alice' }) }));
  for (const change of [{ version: 3 }, { published: false }, { sha256: 'malformed' }]) {
    fetch.mockResolvedValueOnce(json({ ...material, ...change }));
    await expect(publicationApi.publishMaterial('alice', material.id, 2, 'publish-once')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  }
});
it('does not replay an unknown publication response', async () => {
  const fetch = vi.fn().mockRejectedValue(new Error('Synthetic lost reply')); vi.stubGlobal('fetch', fetch);
  await expect(publicationApi.publishApplication('alice', application.id, 2, 'publish-once')).rejects.toMatchObject({ code: 'OFFLINE' });
  expect(fetch).toHaveBeenCalledTimes(1);
});
it('rejects a publication receipt for a different application version', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({ ...application, version: 3 })));
  await expect(publicationApi.publishApplication('alice', application.id, 2, 'publish-once')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
});
