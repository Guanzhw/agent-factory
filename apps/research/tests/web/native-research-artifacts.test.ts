import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { captureNativeArtifacts } from '../../web/nativeResearchArtifacts.js';
import { clearBrowserSession, configureBrowserAuth } from '../../../../web/browserAuth.js';
import type { JobDetail, UserConnection } from '../../../../web/models.js';
import type { PersonalSession } from '../../web/personalAgentApi.js';

const detail = { job: { id: 'task-original', ownerId: 'alice' } } as JobDetail;
const session = { id: 'factory-session', nativeProjectId: 'project-original', nativeSessionId: 'chat-original',
  connectionPin: { fingerprint: 'a'.repeat(64) } as UserConnection } as PersonalSession;
const artifact = { id: 'artifact-original', jobId: detail.job.id, name: 'general-output.tsv', mediaType: 'text/plain',
  size: 17, sha256: 'b'.repeat(64), createdAt: '2026-10-13T00:00:00Z',
  provenance: { source: 'native-orx-file-api', nativeProjectId: session.nativeProjectId,
    nativeSessionId: session.nativeSessionId, commandRequestId: 'original-request', scientificConclusionVerified: false } };
const receipt = { taskId: detail.job.id, ownerId: 'alice', commandRequestId: 'original-request',
  nativeProjectId: session.nativeProjectId, nativeSessionId: session.nativeSessionId,
  scientificConclusionVerified: false, artifacts: [artifact], skipped: [] };
beforeEach(() => { clearBrowserSession(); configureBrowserAuth({ enabled: false, loginPath: '/api/factory/auth/login', logoutPath: '/api/factory/auth/logout' }); });
afterEach(() => vi.unstubAllGlobals());
it('captures only the recorded command and pin with expected-owner protection, never submits research', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(receipt))); vi.stubGlobal('fetch', fetch);
  expect(await captureNativeArtifacts(detail, session, 'original-request')).toEqual({ artifacts: [artifact], skipped: 0 });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][0]).toBe('/api/factory/personal-agent/tasks/task-original/artifacts');
  const options = fetch.mock.calls[0][1];
  expect(options.headers['X-Factory-Expected-Owner']).toBe('alice');
  expect(JSON.parse(options.body)).toEqual({ commandRequestId: 'original-request', expectedFingerprint: 'a'.repeat(64) });
});
it('rejects foreign or malformed file receipts and refuses to claim scientific verification', async () => {
  for (const value of [{ ...receipt, ownerId: 'bob' }, { ...receipt, nativeSessionId: 'foreign' },
    { ...receipt, scientificConclusionVerified: true }, { ...receipt, password: 'synthetic-test-only' },
    { ...receipt, artifacts: [{ ...artifact, jobId: 'foreign' }] }, { ...receipt, artifacts: [{ ...artifact, sha256: 'invalid' }] },
    { ...receipt, artifacts: [artifact, artifact] }, { ...receipt, artifacts: [{ ...artifact, name: '../private' }] },
    { ...receipt, skipped: [{ path: 'output.txt', reason: 'unexpected' }] }]) {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(value))));
    await expect(captureNativeArtifacts(detail, session, 'original-request')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  }
});
it('requires a confirmed native session pin and distinguishes skipped files from collected files', async () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
  await expect(captureNativeArtifacts(detail, { ...session, connectionPin: undefined }, 'original-request')).rejects.toMatchObject({ code: 'NATIVE_SESSION_UNCONFIRMED' });
  expect(fetch).not.toHaveBeenCalled();
  fetch.mockResolvedValue(new Response(JSON.stringify({ ...receipt, skipped: [{ path: 'large.txt', reason: 'OUTPUT_BYTE_LIMIT' }] })));
  expect((await captureNativeArtifacts(detail, session, 'original-request')).skipped).toBe(1);
});
