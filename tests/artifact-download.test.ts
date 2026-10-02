import { afterEach, describe, expect, it, vi } from 'vitest';
import { createHash } from 'node:crypto';
import { maxVerifiedDownloadBytes, safeDownloadName, verifiedArtifact } from '../web/artifactDownload.js';
const content = 'task-owned deterministic evaluator evidence';
const sha256 = createHash('sha256').update(content).digest('hex');
const artifact = { id: 'artifact/1', jobId: 'task', name: 'evidence.json', mediaType: 'application/json', size: Buffer.byteLength(content), sha256, createdAt: '2026-10-02T00:00:00Z' };
afterEach(() => vi.unstubAllGlobals());
describe('verified scoped artifact download', () => {
  it('checks downloaded bytes against persisted size/hash before creating a blob', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(content, { headers: { 'X-Content-SHA256': sha256, 'Content-Length': String(artifact.size) } }));
    vi.stubGlobal('fetch', fetch);
    const blob = await verifiedArtifact('task', artifact);
    expect(await blob.text()).toBe(content);
    expect(fetch.mock.calls[0]).toEqual(['/api/factory/jobs/task/artifacts/artifact%2F1', { credentials: 'same-origin', redirect: 'error', signal: undefined }]);
  });
  it('does not request foreign or oversized artifacts', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    await expect(verifiedArtifact('foreign-task', artifact)).rejects.toMatchObject({ code: 'ARTIFACT_UNVERIFIED' });
    await expect(verifiedArtifact('task', { ...artifact, size: maxVerifiedDownloadBytes + 1 })).rejects.toMatchObject({ code: 'ARTIFACT_UNVERIFIED' });
    expect(fetch).not.toHaveBeenCalled();
  });
  it('rejects corrupted equal-sized bytes, a missing header, and incomplete content', async () => {
    for (const [body, headers] of [[content.replace('task', 'fake'), { 'X-Content-SHA256': sha256 }], [content, {}], [content.slice(0, -1), { 'X-Content-SHA256': sha256 }]] as const) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { headers })));
      await expect(verifiedArtifact('task', artifact)).rejects.toMatchObject({ code: 'ARTIFACT_UNVERIFIED' });
    }
  });
  it('bounds chunked downloads even when content length is omitted', async () => {
    let canceled = false;
    const stream = new ReadableStream<Uint8Array>({ pull(controller) { controller.enqueue(new TextEncoder().encode(content + ' extra')); }, cancel() { canceled = true; } });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(stream, { headers: { 'X-Content-SHA256': sha256 } })));
    await expect(verifiedArtifact('task', artifact)).rejects.toMatchObject({ code: 'ARTIFACT_UNVERIFIED' });
    expect(canceled).toBe(true);
  });
  it('keeps read errors separate from successful or zero-size downloads', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('not authorized', { status: 403 })); vi.stubGlobal('fetch', fetch);
    await expect(verifiedArtifact('task', artifact)).rejects.toMatchObject({ code: 'ARTIFACT_UNAVAILABLE', status: 403 });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(safeDownloadName('../unsafe\\name\n.json')).toBe('.._unsafe_name_.json');
  });
});
