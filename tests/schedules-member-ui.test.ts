// @vitest-environment happy-dom
import { webcrypto } from 'node:crypto';
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Workspace } from '../web/composition.js';
import { api } from '../web/api.js';
import { SchedulesPanel, type SchedulesPanelProps } from '../web/SchedulesPanel.js';
import type { ScheduleMetadata, ScheduleSummary } from '../web/scheduleState.js';

const owner = { id: 'alice', name: 'Alice', role: 'user' as const };
const hash = 'a'.repeat(64);
const baseRow: ScheduleSummary = { id: 'schedule-member', ownerId: owner.id, requestId: 'original-create', lastCommandId: 'original-create', name: '本人合成计划', cron: '0 8 * * *', timezone: 'Etc/UTC', enabled: false, planId: 'plan-member', planFingerprint: hash, planDigest: hash, definitionFingerprint: hash, nextRunAt: '2026-10-15T08:00:00Z', allowedActions: ['edit', 'enable'] };
const baseMetadata: ScheduleMetadata = { schema: 1, ownerId: owner.id, canManage: true, policy: { singlePoller: true, overlap: 'allow-with-current-budget-admission', missed: 'coalesce', pauseCancelsRunning: false, timeSemantics: 'cron-iana-timezone', maxUserTasks: 2, maxTotalTasks: 20 } };
const seed = { planId: baseRow.planId, planFingerprint: hash, goal: '固定本人方案' };
const pointerKey = 'factory-schedule-pending-v1:alice';
let row: ScheduleSummary; let metadata: ScheduleMetadata; let host: HTMLDivElement; let root: Root;
const client = api.schedules;
const button = (text: string) => [...host.querySelectorAll('button')].find(item => item.textContent === text);
async function click(text: string) {
  expect(button(text), text).toBeDefined();
  await act(async () => button(text)!.click());
}
async function settle(assertion: () => void) { await vi.waitFor(async () => { await act(async () => {}); assertion(); }); }
async function field(label: string, value: string) {
  await act(async () => {
    const input = host.querySelector<HTMLInputElement>(`[aria-label="${label}"]`)!;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
async function panel(props: Partial<SchedulesPanelProps> = {}) {
  await act(async () => root.render(createElement(SchedulesPanel, { ownerId: owner.id, canManage: true, api: client, onTask: vi.fn(), ...props })));
}
async function inspect() { await click(`查看计划任务 ${row.name}`); }
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.stubGlobal('crypto', webcrypto);
  localStorage.clear(); sessionStorage.clear(); window.history.replaceState(null, '', '/?tab=catalog');
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  row = structuredClone(baseRow); metadata = structuredClone(baseMetadata);
  vi.spyOn(api, 'status').mockResolvedValue({ mode: 'demo', activeWorkers: 0, queuedJobs: 0, maxWorkers: 2 } as Awaited<ReturnType<typeof api.status>>);
  vi.spyOn(api, 'materials').mockResolvedValue([]); vi.spyOn(api, 'jobs').mockResolvedValue({ items: [], nextCursor: null }); vi.spyOn(api, 'executionTargets').mockResolvedValue([]);
  vi.spyOn(api.scheduleDiagnostics, 'list').mockResolvedValue({ schema: 1, ownerId: owner.id, items: [], nextCursor: null });
  vi.spyOn(client, 'metadata').mockImplementation(async () => metadata);
  vi.spyOn(client, 'list').mockImplementation(async () => ({ schema: 1, ownerId: row.ownerId, items: [row], nextCursor: null, snapshot: false }));
  vi.spyOn(client, 'inspect').mockImplementation(async () => row);
  vi.spyOn(client, 'recover').mockRejectedValue(new Error('No original receipt'));
  vi.spyOn(client, 'occurrences').mockImplementation(async () => ({ schema: 1, ownerId: row.ownerId, scheduleId: row.id, items: [], nextCursor: null, snapshot: false }));
  vi.spyOn(client, 'preview').mockImplementation(async input => ({ schema: 1, ...input, previewedAtUtc: '2026-10-14T00:00:00Z', nextRuns: [15, 16, 17].map(day => {
    const utc = `2026-10-${day}T${input.cron.split(' ')[1].padStart(2, '0')}:00:00Z`;
    return { epoch: Date.parse(utc) / 1000, utc, local: utc.replace('Z', '+00:00'), utcOffsetSeconds: 0 };
  }), semantics: { clock: 'agno-3.1.0/croniter-6.2.4/pytz', missed: 'coalesce-no-catch-up', overlap: 'allowed-subject-to-owner-and-global-budgets', dst: 'native-croniter-pytz', previewOnly: true } }));
  vi.spyOn(client, 'create').mockImplementation(async input => { row = { ...baseRow, ...input, lastCommandId: input.requestId }; return row; });
  vi.spyOn(client, 'update').mockImplementation(async (_id, input) => { row = { ...row, cron: input.cron, timezone: input.timezone, lastCommandId: input.requestId }; return row; });
  vi.spyOn(client, 'setEnabled').mockImplementation(async (_id, input) => { row = { ...row, enabled: input.enabled, lastCommandId: input.requestId, allowedActions: ['edit', input.enabled ? 'disable' : 'enable'] }; return row; });
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('lets an ordinary member reach their schedule from the actual workspace and edit, resume and pause it', async () => {
  await act(async () => root.render(createElement(Workspace, { user: owner, logout: vi.fn(), sessionBusy: false, sessionError: '' })));
  await click('计划任务'); expect(window.location.search).toContain('tab=schedules'); await inspect();
  expect(button('预览下次执行时间')).toBeDefined(); expect(host.textContent).not.toContain('管理员权限');
  await field('Cron表达式', '0 9 * * *'); await click('预览下次执行时间'); await click('保存执行时间');
  await settle(() => expect(client.update).toHaveBeenCalledTimes(1));
  expect(client.update).toHaveBeenCalledWith(row.id, { cron: '0 9 * * *', timezone: row.timezone, expectedDefinitionFingerprint: hash, requestId: expect.any(String) });
  await settle(() => expect(button('恢复计划任务')?.disabled).toBe(false)); await click('恢复计划任务');
  await settle(() => expect(button('暂停计划任务')?.disabled).toBe(false)); await click('暂停计划任务');
  await settle(() => expect(button('恢复计划任务')?.disabled).toBe(false));
  expect(vi.mocked(client.setEnabled).mock.calls.map(call => call[1].enabled)).toEqual([true, false]);
  expect(new Set(vi.mocked(client.setEnabled).mock.calls.map(call => call[1].requestId)).size).toBe(2);
  expect(client.create).not.toHaveBeenCalled(); expect(localStorage.getItem(pointerKey)).toBeNull();
});

it('creates a member-owned schedule paused after a time preview without automatically enabling it', async () => {
  await panel({ seed }); await field('计划任务名称', '新的本人计划'); await click('预览下次执行时间');
  await click('保存计划任务'); await settle(() => expect(client.create).toHaveBeenCalledTimes(1));
  expect(client.create).toHaveBeenCalledWith({ planId: seed.planId, name: '新的本人计划', cron: '0 8 * * *', timezone: 'Etc/UTC', requestId: expect.any(String) });
  expect(row.enabled).toBe(false); expect(client.setEnabled).not.toHaveBeenCalled();
});

it.each([[false, true], [true, false]])('requires both local authority (%s) and server metadata (%s)', async (canManage, serverCanManage) => {
  metadata.canManage = serverCanManage;
  await panel({ canManage, seed }); await inspect();
  expect(button('预览下次执行时间')).toBeUndefined(); expect(button('恢复计划任务')).toBeUndefined();
  expect(host.textContent).toContain('当前身份只能读取自己的计划与历史'); expect(host.textContent).not.toContain('管理员权限');
  expect(client.create).not.toHaveBeenCalled(); expect(client.update).not.toHaveBeenCalled(); expect(client.setEnabled).not.toHaveBeenCalled();
});

it('keeps mutation controls unavailable until exact-owner permission metadata arrives', async () => {
  let resolve!: (value: unknown) => void;
  vi.mocked(client.metadata).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  await panel({ seed }); expect(button('保存计划任务')).toBeUndefined();
  await act(async () => resolve({ ...metadata, ownerId: 'bob' }));
  expect(button('保存计划任务')).toBeUndefined(); expect(host.textContent).toContain('当前管理权限无法核对');
  expect(client.create).not.toHaveBeenCalled();
});

it('locks editing after run permission is revoked and still checks row-level allowed actions', async () => {
  row.allowedActions = [];
  await panel(); await inspect(); await click('预览下次执行时间');
  expect(button('保存执行时间')?.disabled).toBe(true); expect(button('恢复计划任务')?.disabled).toBe(true);
  metadata.canManage = false; await click('刷新计划任务');
  expect(button('保存执行时间')).toBeUndefined(); expect(button('恢复计划任务')).toBeUndefined();
  expect(client.update).not.toHaveBeenCalled(); expect(client.setEnabled).not.toHaveBeenCalled();
});

it('does not apply a delayed owner response after switching to another member', async () => {
  let resolve!: (value: unknown) => void;
  vi.mocked(client.inspect).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  await panel(); await inspect();
  const aliceRow = row; row = { ...baseRow, ownerId: 'bob', id: 'schedule-bob', name: 'Bob 本人计划' };
  metadata = { ...metadata, ownerId: 'bob' }; await panel({ ownerId: 'bob' });
  await act(async () => resolve(aliceRow));
  expect(host.textContent).not.toContain(aliceRow.name); expect(button('恢复计划任务')).toBeUndefined();
  expect(client.update).not.toHaveBeenCalled(); expect(client.setEnabled).not.toHaveBeenCalled();
});

it('preserves an unknown original mutation across refresh and remount without a second write', async () => {
  vi.mocked(client.setEnabled).mockRejectedValue(new Error('Synthetic lost acknowledgement'));
  await panel(); await inspect(); await click('恢复计划任务');
  await settle(() => expect(localStorage.getItem(pointerKey)).not.toBeNull());
  const requestId = vi.mocked(client.setEnabled).mock.calls[0][1].requestId;
  await settle(() => expect(button('刷新计划任务')?.disabled).toBe(false)); await click('刷新计划任务');
  expect(client.setEnabled).toHaveBeenCalledTimes(1); expect(localStorage.getItem(pointerKey)).toContain(requestId);
  await act(async () => root.unmount()); root = createRoot(host); await panel();
  expect(client.setEnabled).toHaveBeenCalledTimes(1); expect(localStorage.getItem(pointerKey)).toContain(requestId);
  expect(button('显式重试原变更请求')).toBeUndefined(); expect(button('恢复计划任务')).toBeUndefined();
});
