// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError } from '../../../../web/api.js';
import { researchApi } from '../../web/api.js';
import { ResearchIterations } from '../../web/ResearchIterations.js';
import { defaultIterationCaps, readIterationPending, type IterationPreset, type IterationSnapshot } from '../../web/iterationState.js';
const caps = { rounds: 1, toolCalls: 3, tokenLimit: null, amountMicros: null, currency: null };
const preset: IterationPreset = { id: 'toy', name: '本地两轮', ready: true, blockers: [], roundCaps: caps, roundSeconds: 30, defaultTotalSeconds: 300, baseline: { metric: 'mean_squared_error', value: 16, kind: 'reviewedSeed' } };
const baseline = { kind: 'reviewedSeed', metricValue: 16, sha256: 'a'.repeat(64) };
const snapshot: IterationSnapshot = { activity: { id: 'activity', ownerId: 'alice', requestId: 'original', goal: '改善模型', status: 'running', stopReason: null, currentRoundId: 'round1', cancelRequested: false, caps: { ...caps, rounds: 2, toolCalls: 6 }, deadline: 9999999999, baselineSource: baseline }, rounds: [{ id: 'round1', ordinal: 1, previousRoundId: null, state: 'RUNNING', taskId: 'task1', baselineSource: baseline, observation: { approvalRequired: true } }], budget: { allocatedRounds: 1, heldToolCalls: 3, settledToolCalls: 0, metering: 'unavailable', usage: null, allocations: [{ state: 'RUNNING' }] } };
const api = researchApi.iterations;
let host: HTMLDivElement, root: Root;
const onTask = vi.fn();
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto); localStorage.clear(); onTask.mockClear();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.spyOn(api, 'presets').mockResolvedValue([preset]); vi.spyOn(api, 'list').mockResolvedValue({ items: [snapshot] });
  vi.spyOn(api, 'start').mockRejectedValue(new ApiError('offline', 0));
  vi.spyOn(api, 'recover').mockRejectedValue(new ApiError('missing', 404));
  vi.spyOn(api, 'advance').mockRejectedValue(new ApiError('offline', 0));
  vi.spyOn(api, 'get').mockResolvedValue(snapshot); vi.spyOn(api, 'reconcile').mockResolvedValue(snapshot); vi.spyOn(api, 'cancel').mockResolvedValue(snapshot);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount() { await act(async () => root.render(createElement(ResearchIterations, { ownerId: 'alice', onTask }))); }
async function open() { await mount(); await act(async () => { const details = host.querySelector('details')!; details.open = true; details.dispatchEvent(new Event('toggle')); }); }
const button = (text: string) => Array.from(host.querySelectorAll('button')).find(b => b.textContent === text)!;
async function click(text: string) { await act(async () => button(text).click()); }
async function field(label: string, value: string) { await act(async () => {
  const input = host.querySelector<HTMLInputElement | HTMLSelectElement>(`[aria-label="${label}"]`)!;
  const select = input.tagName === 'SELECT'; Object.getOwnPropertyDescriptor(select ? HTMLSelectElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(input, value);
  input.dispatchEvent(new Event(select ? 'change' : 'input', { bubbles: true }));
}); }
it('loads only on expansion and never advances or approves through reads; exposes original task controls', async () => {
  await mount(); expect(api.list).not.toHaveBeenCalled();
  await act(async () => { const d = host.querySelector('details')!; d.open = true; d.dispatchEvent(new Event('toggle')); });
  await field('选择迭代活动', 'activity'); expect(host.textContent).toContain('MSE 16'); expect(host.textContent).toContain('不可计量（不代表消耗为 0）');
  await click('前往原生任务处理待批准操作'); expect(onTask).toHaveBeenCalledWith('task1');
  await click('读取当前活动'); expect(api.get).toHaveBeenCalledWith('alice', 'activity');
  expect(api.start).not.toHaveBeenCalled(); expect(api.advance).not.toHaveBeenCalled(); expect(api.reconcile).not.toHaveBeenCalled();
});
it('persists an exact original deadline/body and recovers only with GET across remount and missing receipts', async () => {
  await open(); await field('迭代预设', 'toy'); await field('迭代目标', '改善模型'); await field('迭代总秒数', '300');
  const before = Date.now() / 1000; await click('创建两轮活动');
  const original = vi.mocked(api.start).mock.calls[0][1]; expect(original.deadline).toBeGreaterThanOrEqual(before + 300); expect(original.deadline).toBeLessThan(before + 305);
  expect(original.caps).toEqual({ ...caps, rounds: 2, toolCalls: 6 });
  const stored = localStorage.getItem('factory-research-iteration:alice');
  await act(async () => root.unmount()); root = createRoot(host); await mount();
  expect(api.start).toHaveBeenCalledTimes(1); await click('核对原迭代请求');
  expect(api.recover).toHaveBeenCalledWith('alice', original.requestId); expect(localStorage.getItem('factory-research-iteration:alice')).toBe(stored);
  vi.mocked(api.recover).mockResolvedValue({ ...snapshot, activity: { ...snapshot.activity, requestId: original.requestId } });
  await click('核对原迭代请求'); expect(localStorage.getItem('factory-research-iteration:alice')).toBeNull(); expect(api.start).toHaveBeenCalledTimes(1);
});
it('requires explicit next round and preserves its request until the exact advance mapping is observed', async () => {
  const ready = { ...snapshot, activity: { ...snapshot.activity, status: 'ready' }, rounds: [{ ...snapshot.rounds[0], state: 'SETTLED', decision: 'improved' }] };
  vi.mocked(api.list).mockResolvedValue({ items: [ready] }); await open(); await field('选择迭代活动', 'activity'); await click('继续下一轮');
  const body = vi.mocked(api.advance).mock.calls[0][2]; expect(body.previousRoundId).toBe('round1');
  await click('核对原迭代请求'); expect(localStorage.getItem('factory-research-iteration:alice')).not.toBeNull();
  vi.mocked(api.get).mockResolvedValue({ ...ready, activity: { ...ready.activity, advanceRequests: { [body.requestId]: 'round1' } } });
  await click('核对原迭代请求'); expect(localStorage.getItem('factory-research-iteration:alice')).toBeNull(); expect(api.advance).toHaveBeenCalledTimes(1);
});
it('does not offer continuation for ties and treats metering absence as unavailable', async () => {
  vi.mocked(api.list).mockResolvedValue({ items: [{ ...snapshot, activity: { ...snapshot.activity, status: 'stopped', stopReason: 'tie' } }] });
  await open(); await field('选择迭代活动', 'activity'); expect(button('继续下一轮').disabled).toBe(true); expect(host.textContent).toContain('持平，停止');
  expect(defaultIterationCaps(preset).tokenLimit).toBeNull(); expect(defaultIterationCaps({ ...preset, roundCaps: { ...caps, tokenLimit: 20, amountMicros: 30, currency: 'USD' } })).toMatchObject({ tokenLimit: 40, amountMicros: 60, currency: 'USD' });
  expect(readIterationPending(JSON.stringify({ owner: 'bob', kind: 'start', body: {} }), 'alice')).toBeNull();
});
it('shows total-budget authorization and a clear rejected-budget error without an automatic retry', async () => {
  vi.mocked(api.start).mockRejectedValue(new ApiError('LOCAL_BUDGET_EXHAUSTED', 429));
  await open(); expect(host.textContent).toContain('严格降低'); expect(host.textContent).toContain('自动开始下一轮');
  await field('迭代预设', 'toy'); await field('迭代目标', '改善模型'); await click('创建两轮活动');
  expect(host.textContent).toContain('权限、预设、总预算与截止时间'); expect(api.start).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem('factory-research-iteration:alice')).toBeNull();
});
it('aborts obsolete reads and does not replace the new catalog with a late response', async () => {
  let resolve!: (value: unknown) => void;
  vi.mocked(api.list).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  await open(); const signal = vi.mocked(api.list).mock.calls[0][1]!;
  await click('重新读取迭代'); expect(signal.aborted).toBe(true);
  await act(async () => resolve({ items: [{ ...snapshot, activity: { ...snapshot.activity, id: 'stale', goal: '过期结果' } }] }));
  expect(host.querySelector('[aria-label="选择迭代活动"]')!.textContent).not.toContain('过期结果');
});
