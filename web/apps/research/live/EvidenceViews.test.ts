// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError } from '../../../api.js';
import { clearBrowserSession } from '../../../browserAuth.js';
import { AssociationDetail, CreateDelivery, DeliveryDetail } from './EvidenceViews.js';
import { downloadResearchDelivery, evidenceApi, type ResearchDelivery } from './evidenceClient.js';
import { assistantApi } from './assistantClient.js';
let host: HTMLDivElement; let root: Root;
const selected = vi.fn();
const delivery: ResearchDelivery = { id: 'd1', ownerId: 'alice', createdAt: '2026-10-25T00:00:00Z', schema: 1, kind: 'research.delivery', projectId: 'p1', goalVersion: 2, sourceIds: ['record-a', 'record-b'], recordIds: ['record-a'], records: [{ outcome: 'not_met' }], missingEvidence: ['run_recipe'], verificationStatus: 'unverified', remainingQuestions: { status: 'not_provided' }, evidenceFormat: 'JSON envelopes', continuation: 'New budget; do not replay UNKNOWN' };
beforeEach(() => { vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); window.sessionStorage.clear(); host = document.createElement('div'); document.body.append(host); root = createRoot(host); selected.mockReset(); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const button = (name: string) => [...host.querySelectorAll('button')].find(item => item.textContent === name)!;
it('retains original delivery creation after 408 and remount', async () => {
  const create = vi.spyOn(evidenceApi, 'create').mockRejectedValueOnce(new ApiError('timeout', 408)).mockResolvedValue(delivery);
  const mount = (key: string) => root.render(createElement(CreateDelivery, { key, ownerId: 'alice', projectId: 'p1', version: 2, onCreated: selected }));
  await act(async () => mount('first')); await act(async () => button('生成成果清单').click()); const original = create.mock.calls[0];
  await act(async () => mount('second')); expect(create).toHaveBeenCalledTimes(1); await act(async () => button('重试原操作').click());
  expect(create.mock.calls[1]).toEqual(original); expect(selected).toHaveBeenCalledWith('d1');
});
it('shows negative results, explicit missing recipe and unavailable remaining questions without a completeness claim', async () => {
  vi.spyOn(evidenceApi, 'delivery').mockResolvedValue(delivery);
  await act(async () => root.render(createElement(DeliveryDetail, { ownerId: 'bob', id: 'd1' })));
  expect(host.textContent).toContain('成果不完整'); expect(host.textContent).toContain('run_recipe'); expect(host.textContent).toContain('not_met'); expect(host.textContent).toContain('不代表没有疑问');
  expect(host.textContent).not.toContain('复现成功');
});
it('hides the whole old manifest when an input is withdrawn', async () => {
  const read = vi.spyOn(evidenceApi, 'delivery').mockResolvedValueOnce(delivery).mockRejectedValue(new ApiError('来源不可用', 404));
  await act(async () => root.render(createElement(DeliveryDetail, { ownerId: 'bob', id: 'd1' })));
  await act(async () => button('核对成果与当前来源').click());
  expect(read).toHaveBeenCalledTimes(2); expect(host.textContent).toContain('旧成果正文与下载已隐藏'); expect(host.textContent).not.toContain('not_met'); expect(button('下载当前授权成果包')).toBeUndefined();
});
it('shows the exact original ending and preserves unobserved cleanup', async () => {
  const reason = '未达标；剩余问题：需要独立复现。\n完整原文';
  vi.spyOn(evidenceApi, 'delivery').mockResolvedValue({ ...delivery, ending: { ownerId: 'alice', sourceIds: ['record-b'], outcome: 'not_met', reason, goalVersion: 2, endedAt: '2026-10-25T00:00:00Z', resourceCleanup: 'not_observed' } });
  await act(async () => root.render(createElement(DeliveryDetail, { ownerId: 'bob', id: 'd1' })));
  expect(host.textContent).toContain(reason); expect(host.textContent).toContain('结束依据与剩余问题（原文）');
  expect(host.textContent).toContain('未确认资源停止'); expect(host.textContent).toContain('项目所有者：alice');
});
it('does not restore late association or source data after owner and selection change', async () => {
  const association = { id: 'a1', ownerId: 'alice', createdAt: '2026-10-25T00:00:00Z', sourceIds: ['source1'], inputContentIds: ['source1'], analysis: { answer: 'old analysis', citations: ['source1'], evidenceLevel: 'agent_analysis' as const, relation: 'related' } };
  vi.spyOn(evidenceApi, 'association').mockResolvedValueOnce(association).mockResolvedValueOnce(association).mockRejectedValue(new ApiError('不可读', 404));
  let resolve!: (value: Awaited<ReturnType<typeof assistantApi.source>>) => void;
  vi.spyOn(assistantApi, 'source').mockImplementation(() => new Promise(done => { resolve = done; }));
  await act(async () => root.render(createElement(AssociationDetail, { ownerId: 'alice', id: 'a1' })));
  await act(async () => button('source1').click());
  await act(async () => root.render(createElement(AssociationDetail, { ownerId: 'bob', id: 'a2' })));
  await act(async () => resolve({ id: 'source1', ownerId: 'alice', source: {}, content: { secret: 'late-canary' }, verificationStatus: 'unverified', createdAt: '' }));
  expect(host.textContent).not.toContain('late-canary'); expect(host.textContent).not.toContain('old analysis'); expect(host.textContent).toContain('不可读');
});
it('rejects a denied ZIP instead of emitting an error document as a download', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response('denied', { status: 403 })); vi.stubGlobal('fetch', fetcher);
  await expect(downloadResearchDelivery('bob', 'd1', new AbortController().signal)).rejects.toMatchObject({ status: 403 });
  expect(fetcher.mock.calls[0][1]).toMatchObject({ credentials: 'same-origin', redirect: 'error', headers: { 'X-Factory-Expected-Owner': 'bob' } });
});
it('discards ZIP bytes if the session changes while the body is arriving', async () => {
  let resolve!: (value: Blob) => void;
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, headers: new Headers({ 'Content-Type': 'application/zip' }), blob: () => new Promise(done => { resolve = done; }) }));
  const result = downloadResearchDelivery('alice', 'd1', new AbortController().signal);
  const rejected = expect(result).rejects.toMatchObject({ name: 'AbortError' });
  await Promise.resolve(); await Promise.resolve(); clearBrowserSession(); resolve(new Blob(['zip'])); await rejected;
});
