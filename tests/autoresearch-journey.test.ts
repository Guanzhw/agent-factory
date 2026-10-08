// @vitest-environment happy-dom
import { createHash, randomUUID } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AutoResearch, AutoResearchReview, prepareResearchReview, researchReviewMatches } from '../web/AutoResearch.js';
import type { ResearchPreset, StartResearch } from '../web/autoresearchState.js';

const ownerId = 'researcher@example.test';
const storageKey = `factory-autoresearch-v1:${encodeURIComponent(ownerId)}`;
const preset: ResearchPreset = { id: 'bounded', name: '受管公开实验', defaultGoal: '验证公开实验问题', ready: true, blockers: [], limits: { maxExperiments: 2, totalSeconds: 60, toolCalls: 8 } };
const acceptance = { modelExecuted: false, instructionsRead: false, agentDecision: false, managedExperiment: false, independentResult: false, nextDecision: false, scientificConclusionVerified: false };
function run(input: Partial<StartResearch> = {}) {
  return { id: 'run-one', ownerId, requestId: input.requestId ?? 'request-one', presetId: input.presetId ?? preset.id, goal: input.goal ?? preset.defaultGoal, status: 'RUNNING', steps: [], evidence: [], allowedActions: ['cancel'], acceptance };
}
function apiFixture() {
  return {
    presets: vi.fn(async () => [structuredClone(preset)]),
    start: vi.fn(async (input: StartResearch) => run(input)),
    get: vi.fn(async (_id: string) => run()),
    recover: vi.fn(async (_requestId: string): Promise<unknown | null> => null),
    cancel: vi.fn(async (_id: string, _input: { requestId: string }) => ({ ...run(), status: 'CANCELLED', allowedActions: [] })),
  };
}
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  // Deterministic microtask timing for hashing; retain SHA-256 and unique request ids.
  vi.stubGlobal('crypto', { randomUUID, subtle: { digest: async (_algorithm: string, value: Uint8Array) => { const hash = createHash('sha256').update(value).digest(); return hash.buffer.slice(hash.byteOffset, hash.byteOffset + hash.byteLength); } } });
  window.sessionStorage.clear(); window.localStorage.clear();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });
function button(label: string): HTMLButtonElement {
  const result = Array.from(host.querySelectorAll('button')).find(item => item.textContent === label);
  if (!result) throw new Error(`Missing button: ${label}`);
  return result;
}
async function click(label: string) { await act(async () => { button(label).click(); }); }
async function writeGoal(value: string) {
  const field = host.querySelector('textarea');
  if (!field) throw new Error('Missing goal input');
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')!.set!.call(field, value);
    field.dispatchEvent(new window.Event('input', { bubbles: true }));
  });
}
async function show(api: ReturnType<typeof apiFixture>, extra: { onOpenTasks?: () => void; runId?: string; onRun?: (id: string, passive?: boolean) => void } = {}) {
  await act(async () => root.render(createElement(AutoResearch, { ownerId, api, ...extra })));
}

describe('Auto-Research first-use journey', () => {
  it('offers useful empty-state and blocked-state exits without starting anything', async () => {
    const api = apiFixture(); const onOpenTasks = vi.fn(); api.presets.mockResolvedValueOnce([]);
    await show(api, { onOpenTasks });
    expect(host.textContent).toContain('Auto-Research 实验尚未配置');
    expect(host.textContent).toContain('联系管理员');
    expect(host.textContent).not.toContain('确认并开始研究');
    await click('选择其他应用'); expect(onOpenTasks).toHaveBeenCalledOnce();
    api.presets.mockResolvedValueOnce([{ ...preset, ready: false, blockers: ['管理员尚未配置研究连接'] }]);
    await click('重新读取研究设置');
    expect(host.textContent).toContain('管理员尚未配置研究连接');
    expect(host.textContent).toContain('最多实验'); expect(host.textContent).toContain('60');
    expect(button('检查默认目标').disabled).toBe(true);
    expect(button('检查我的目标').disabled).toBe(true);
    expect(api.start).not.toHaveBeenCalled();
  });
  it('recovers a settings-read error without showing endless loading or invoking start', async () => {
    const api = apiFixture(); api.presets.mockRejectedValueOnce(new Error('unavailable'));
    await show(api, { onOpenTasks: vi.fn() });
    expect(host.textContent).toContain('暂时无法读取研究设置');
    expect(host.textContent).not.toContain('正在读取研究设置');
    await click('重新读取研究设置');
    expect(button('检查默认目标').disabled).toBe(false); expect(api.start).not.toHaveBeenCalled();
  });
  it('requires review, preserves the goal on Back, and submits only the newly reviewed goal', async () => {
    const api = apiFixture(); const onRun = vi.fn(); await show(api, { onRun });
    await writeGoal('第一个研究目标'); await click('检查我的目标');
    expect(host.textContent).toContain('开始前确认'); expect(host.textContent).toContain('第一个研究目标');
    expect(host.textContent).toContain('最多实验'); expect(host.textContent).toContain('60');
    expect(document.activeElement?.textContent).toBe('开始前确认');
    expect(api.start).not.toHaveBeenCalled();
    await click('返回修改'); expect(host.querySelector('textarea')?.value).toBe('第一个研究目标');
    await writeGoal('  更新后的研究目标  '); await click('检查我的目标');
    expect(host.textContent).toContain('更新后的研究目标'); expect(api.start).not.toHaveBeenCalled();
    await click('确认并开始研究');
    expect(api.start).toHaveBeenCalledOnce();
    expect(api.start.mock.calls[0][0]).toEqual({ presetId: preset.id, goal: '更新后的研究目标', requestId: expect.any(String) });
    expect(onRun).toHaveBeenCalledWith('run-one'); expect(host.textContent).toContain('研究中');
  });
  it('keeps the default-goal payload contract and does not navigate while the start is uncertain', async () => {
    const api = apiFixture(); const onRun = vi.fn();
    let complete!: (value: ReturnType<typeof run>) => void;
    api.start.mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }));
    api.recover.mockResolvedValue(run());
    await show(api, { onRun }); await writeGoal('不会用于默认目标的输入'); await click('检查默认目标');
    expect(host.textContent).toContain('默认研究目标'); expect(host.textContent).toContain(preset.defaultGoal);
    await click('确认并开始研究');
    expect(api.start).toHaveBeenCalledOnce(); const original = api.start.mock.calls[0][0];
    expect(original).not.toHaveProperty('goal'); expect(api.recover).not.toHaveBeenCalled();
    expect(onRun).not.toHaveBeenCalled(); expect(button('读取原请求').disabled).toBe(true);
    await act(async () => { complete(run(original)); });
    expect(onRun).toHaveBeenCalledWith('run-one'); expect(api.start).toHaveBeenCalledOnce();
  });
  it('retries the exact uncertain request without creating a new intent', async () => {
    const api = apiFixture(); const onRun = vi.fn(); api.start.mockRejectedValueOnce(new Error('lost acknowledgement'));
    await show(api, { onRun }); await writeGoal('保留原研究目标'); await click('检查我的目标'); await click('确认并开始研究');
    expect(api.start).toHaveBeenCalledOnce(); const original = api.start.mock.calls[0][0];
    expect(api.recover).toHaveBeenCalledWith(original.requestId, expect.any(AbortSignal));
    expect(host.querySelector('textarea')).toBeNull(); expect(onRun).not.toHaveBeenCalled();
    await click('重试原请求');
    expect(api.start).toHaveBeenCalledTimes(2); expect(api.start.mock.calls[1][0]).toEqual(original);
    expect(api.presets).toHaveBeenCalledTimes(2); // Initial load and first-start preflight; retries keep the original request.
    expect(onRun).toHaveBeenCalledWith('run-one');
  });
  it('rechecks settings before a first start and requires a new review if the displayed limits changed', async () => {
    const api = apiFixture(); await show(api); await click('检查默认目标');
    const updated = { ...preset, limits: { ...preset.limits, totalSeconds: 30 } };
    api.presets.mockResolvedValue([updated]); await click('确认并开始研究');
    expect(api.presets).toHaveBeenCalledTimes(2); expect(api.start).not.toHaveBeenCalled();
    expect(host.textContent).toContain('研究设置已变化或暂不可用');
    expect(host.textContent).toContain('60'); expect(button('确认并开始研究').disabled).toBe(true);
    await click('返回修改'); await click('检查默认目标');
    expect(host.textContent).toContain('30'); await click('确认并开始研究');
    expect(api.start).toHaveBeenCalledOnce();
  });
  it('blocks a first start when its fresh settings check fails without treating it as an uncertain write', async () => {
    const api = apiFixture(); await show(api); await click('检查默认目标');
    api.presets.mockRejectedValueOnce(new Error('preflight offline')); await click('确认并开始研究');
    expect(host.textContent).toContain('开始前无法核对最新研究设置');
    expect(host.textContent).not.toContain('重试原请求'); expect(api.start).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem(storageKey)).toBeNull();
    await click('重新读取研究设置'); expect(button('确认并开始研究').disabled).toBe(false);
  });
  it('opens a linked run by id only after owner validation and preserves another uncertain pointer', async () => {
    const api = apiFixture(); const onRun = vi.fn();
    const pending = JSON.stringify({ requestId: 'pending-request' }); window.sessionStorage.setItem(storageKey, pending);
    api.get.mockResolvedValueOnce({ ...run(), ownerId: 'someone-else', goal: 'private foreign goal' });
    await show(api, { runId: 'run-one', onRun });
    expect(api.get).toHaveBeenCalledWith('run-one', expect.any(AbortSignal));
    expect(host.textContent).not.toContain('private foreign goal'); expect(host.textContent).not.toContain('停止研究');
    expect(host.textContent).not.toContain('检查默认目标'); expect(onRun).not.toHaveBeenCalled();
    await click('读取最新状态');
    expect(host.textContent).toContain('研究中'); expect(onRun).toHaveBeenCalledWith('run-one', true);
    expect(window.sessionStorage.getItem(storageKey)).toBe(pending);
    expect(api.start).not.toHaveBeenCalled(); expect(api.cancel).not.toHaveBeenCalled();
  });
  it('recovers an owner-scoped session request when no run link is supplied', async () => {
    const api = apiFixture(); const onRun = vi.fn();
    window.sessionStorage.setItem(storageKey, JSON.stringify({ requestId: 'request-one' }));
    api.recover.mockResolvedValueOnce(run()); await show(api, { onRun });
    expect(api.recover).toHaveBeenCalledWith('request-one', expect.any(AbortSignal));
    expect(host.textContent).toContain('研究中'); expect(onRun).toHaveBeenCalledWith('run-one', true);
    expect(api.start).not.toHaveBeenCalled();
  });
  it('marks restoration as passive and opens a record URL only on explicit navigation', async () => {
    const api = apiFixture(); api.recover.mockResolvedValue(run());
    window.sessionStorage.setItem(storageKey, JSON.stringify({ requestId: 'request-one' }));
    const push = vi.fn(); const passive = vi.fn();
    await show(api, { onRun: (id, recovered) => { if (recovered) passive(id); else push(id); } });
    expect(passive).toHaveBeenCalledWith('run-one'); expect(push).not.toHaveBeenCalled();
    await click('打开研究记录'); expect(push).toHaveBeenCalledWith('run-one');
    expect(api.start).not.toHaveBeenCalled();
  });
  it('binds a review to its visible settings and disables confirmation after blockers or limits change', async () => {
    const source = structuredClone(preset); const review = prepareResearchReview(source, '  研究目标  ')!;
    source.limits.toolCalls = 99; expect(review.preset.limits.toolCalls).toBe(8); expect(review.goal).toBe('研究目标');
    expect(researchReviewMatches(review, preset)).toBe(true);
    expect(researchReviewMatches(review, source)).toBe(false);
    expect(prepareResearchReview({ ...preset, ready: false })).toBeUndefined();
    expect(prepareResearchReview({ ...preset, blockers: ['still blocked'] })).toBeUndefined();
    expect(prepareResearchReview(preset, '   ')).toBeUndefined();
    const onStart = vi.fn();
    await act(async () => root.render(createElement(AutoResearchReview, { review, currentPreset: { ...preset, ready: false, blockers: ['研究连接已撤销'] }, checking: false, error: '', busy: false, onBack: vi.fn(), onStart, onRetry: vi.fn() })));
    expect(host.textContent).toContain('研究连接已撤销'); expect(host.textContent).toContain('最多工具调用');
    expect(button('确认并开始研究').disabled).toBe(true); await click('确认并开始研究'); expect(onStart).not.toHaveBeenCalled();
  });
});
