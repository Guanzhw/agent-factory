// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Workspace, type WorkspaceContext } from '../web/App.js';
import { TaskDetail, TaskWorkspace } from '../web/TaskWorkspace.js';
import { api } from '../web/api.js';
import { mergeJobHistory } from '../web/jobHistory.js';
import type { JobDetail, JobPage, JobSummary } from '../web/models.js';

vi.mock('../web/api.js', async original => {
  const actual = await original<typeof import('../web/api.js')>();
  return { ...actual, api: { ...actual.api, status: vi.fn(), materials: vi.fn(), jobs: vi.fn(), executionTargets: vi.fn(), detail: vi.fn() } };
});
vi.mock('../web/ControlRecovery.js', () => ({ ControlRecovery: () => null }));
const job = (id: string, createdAt = '2026-01-02T00:00:00Z'): JobSummary => ({
  id, ownerId: 'member', definitionId: 'fixture', definitionVersion: 1,
  input: { topic: id, mode: 'fixture', scenario: 'normal' }, status: 'running',
  createdAt, updatedAt: createdAt, observedAt: createdAt,
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
let host: HTMLDivElement;
let root: Root;
let context: WorkspaceContext;
beforeEach(() => {
  vi.resetAllMocks(); vi.useFakeTimers();
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  window.history.replaceState(null, '', '/?tab=research');
  vi.mocked(api.status).mockResolvedValue({ mode: 'demo', activeWorkers: 1, queuedJobs: 0, maxWorkers: 2, integration: 'fixture', liveEnabled: false });
  vi.mocked(api.materials).mockResolvedValue([]); vi.mocked(api.executionTargets).mockResolvedValue([]);
  vi.mocked(api.jobs).mockResolvedValue({ items: [job('new')], nextCursor: 'older-cursor' });
  vi.mocked(api.detail).mockImplementation(async id => ({ job: { ...job(id) }, events: [], artifacts: [] }) as unknown as JobDetail);
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); });
async function render() {
  await act(async () => root.render(createElement(Workspace, {
    user: { id: 'member', name: 'Member', role: 'user' }, logout: () => {}, sessionBusy: false, sessionError: '',
    children: value => {
      context = value;
      return createElement(TaskWorkspace, { context: value, Detail: ({ detail }) => createElement('h2', { 'data-detail': true }, detail.job.id) });
    },
  })));
}
async function click(text: string) {
  const button = [...host.querySelectorAll('button')].find(element => element.textContent?.includes(text));
  expect(button).toBeTruthy(); await act(async () => button!.click());
}

it('updates jobs, status and targets when the catalog fails, and continues polling independently', async () => {
  vi.mocked(api.materials).mockRejectedValue(new Error('catalog unavailable'));
  await render();
  expect(context.jobs.map(value => value.id)).toEqual(['new']);
  expect(context.status?.activeWorkers).toBe(1);
  expect(api.executionTargets).toHaveBeenCalledOnce();
  expect(host.textContent).toContain('部分区域更新失败');
  vi.mocked(api.jobs).mockResolvedValue({ items: [job('newest'), job('new')], nextCursor: 'next' });
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(context.jobs.map(value => value.id)).toContain('newest');
  expect(api.materials).toHaveBeenCalledTimes(2);
});

it('loads earlier history, keeps it and its selection during refresh, and restores the URL task', async () => {
  await render();
  vi.mocked(api.jobs).mockImplementation(async (_signal, cursor) => cursor
    ? { items: [job('old', '2025-01-01T00:00:00Z')], nextCursor: null }
    : { items: [job('newest'), job('new')], nextCursor: 'new-frontier' });
  await click('加载更早任务');
  expect(api.jobs).toHaveBeenLastCalledWith(expect.any(AbortSignal), 'older-cursor');
  await click('old');
  expect(context.route.task).toBe('old');
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(context.jobs.map(value => value.id)).toEqual(['newest', 'new', 'old']);
  expect(context.route.task).toBe('old');
  expect(context.nextCursor).toBeNull();
  await click('newest');
  await act(async () => {
    window.history.replaceState(null, '', '/?tab=research&task=old');
    window.dispatchEvent(new PopStateEvent('popstate'));
  });
  expect(context.route.task).toBe('old');
  expect(host.querySelector('[data-detail]')?.textContent).toBe('old');
  const selected = host.querySelector('.task-row.selected');
  expect(selected?.tagName).toBe('BUTTON');
  expect(selected?.getAttribute('aria-pressed')).toBe('true');
  expect(host.textContent).toContain('状态记录于');
});

it('retains the cursor and existing rows after an earlier-page failure and allows retry', async () => {
  await render();
  vi.mocked(api.jobs).mockRejectedValueOnce(new Error('history unavailable'));
  await click('加载更早任务');
  expect(context.jobs).toHaveLength(1);
  expect(context.nextCursor).toBe('older-cursor');
  expect(host.textContent).toContain('更早任务读取失败');
  vi.mocked(api.jobs).mockResolvedValueOnce({ items: [job('old')], nextCursor: null });
  await click('加载更早任务');
  expect(context.historyError).toBe('');
  expect(context.jobs).toHaveLength(2);
});

it('aborts replaced polls and ignores responses that finish after refresh or unmount', async () => {
  const stale = deferred<JobPage>();
  vi.mocked(api.jobs).mockReturnValueOnce(stale.promise);
  await render();
  const firstSignal = vi.mocked(api.jobs).mock.calls[0][0]!;
  await act(async () => context.retry());
  expect(firstSignal.aborted).toBe(true);
  await act(async () => stale.resolve({ items: [job('stale')], nextCursor: 'stale' }));
  expect(context.jobs.map(value => value.id)).toEqual(['new']);
  const oldPage = deferred<JobPage>();
  vi.mocked(api.jobs).mockReturnValueOnce(oldPage.promise);
  await click('加载更早任务');
  const pageSignal = vi.mocked(api.jobs).mock.calls.at(-1)![0]!;
  await act(async () => root.unmount());
  expect(pageSignal.aborted).toBe(true);
  await act(async () => oldPage.resolve({ items: [job('late')], nextCursor: null }));
  expect(context.jobs.map(value => value.id)).toEqual(['new']);
});

it('does not let a stale older page replace a newer observation and deduplicates ties', () => {
  const newer = { ...job('same'), status: 'completed' as const, observedAt: '2026-02-01T00:00:00Z' };
  expect(mergeJobHistory([newer], [job('same'), job('z')])).toEqual([job('z'), newer]);
});

it('keeps other regions usable when jobs fail, and a pending catalog does not delay their next poll', async () => {
  vi.mocked(api.jobs).mockRejectedValue(new Error('jobs unavailable'));
  vi.mocked(api.materials).mockReturnValue(deferred<Awaited<ReturnType<typeof api.materials>>>().promise);
  await render();
  expect(context.status?.activeWorkers).toBe(1);
  expect(host.textContent).toContain('任务列表更新失败');
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(api.executionTargets).toHaveBeenCalledTimes(2);
  expect(api.status).toHaveBeenCalledTimes(2);
  expect(api.materials).toHaveBeenCalledOnce();
});

it('ignores a stale detail response after selecting another task and keeps the 2.5 second detail poll', async () => {
  const stale = deferred<JobDetail>();
  vi.mocked(api.detail).mockReturnValueOnce(stale.promise);
  await render();
  await act(async () => context.onTask('first'));
  const firstSignal = vi.mocked(api.detail).mock.calls[0][1]!;
  await act(async () => context.onTask('second'));
  expect(firstSignal.aborted).toBe(true);
  await act(async () => stale.resolve({ job: job('first'), events: [], artifacts: [] } as unknown as JobDetail));
  expect(context.detail?.job.id).toBe('second');
  await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
  expect(api.detail).toHaveBeenCalledTimes(3);
  expect(api.detail).toHaveBeenLastCalledWith('second', expect.any(AbortSignal));
});

it('bridges more than one page of insertions without losing loaded history, its tail cursor or selection', async () => {
  const rows = Array.from({ length: 150 }, (_, index) => job(`task-${String(150 - index).padStart(3, '0')}`));
  vi.mocked(api.jobs).mockImplementation(async (_signal, cursor) => {
    const offset = cursor ? rows.findIndex(value => value.id === cursor) + 1 : 0;
    const items = rows.slice(offset, offset + 50);
    return { items, nextCursor: offset + 50 < rows.length ? items.at(-1)!.id : null };
  });
  await render();
  await click('加载更早任务');
  await act(async () => context.onTask('task-060'));
  expect(context.nextCursor).toBe('task-051');
  rows.unshift(...Array.from({ length: 105 }, (_, index) => job(`task-${255 - index}`)));
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(context.jobs).toHaveLength(205);
  expect(new Set(context.jobs.map(value => value.id)).size).toBe(205);
  expect(context.jobs.map(value => value.id)).toEqual(rows.slice(0, 205).map(value => value.id));
  expect(context.nextCursor).toBe('task-051');
  expect(context.route.task).toBe('task-060');
  await click('加载更早任务');
  expect(context.jobs.map(value => value.id)).toEqual(rows.map(value => value.id));
  expect(context.nextCursor).toBeNull();
});

it('retries the missing bridge after failure instead of advancing past unseen insertions', async () => {
  await render();
  vi.mocked(api.jobs).mockImplementation(async (_signal, cursor) => {
    if (cursor) throw new Error('bridge unavailable');
    return { items: [job('newest')], nextCursor: 'bridge' };
  });
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(context.jobs.map(value => value.id)).toEqual(['new']);
  expect(context.jobsError).toContain('bridge unavailable');
  vi.mocked(api.jobs).mockImplementation(async (_signal, cursor) => cursor
    ? { items: [job('newer'), job('new')], nextCursor: 'older-cursor' }
    : { items: [job('newest')], nextCursor: 'bridge' });
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(context.jobs.map(value => value.id)).toEqual(['newest', 'newer', 'new']);
  expect(context.jobsError).toBe('');
});


it('labels finalizing as unconfirmed resource cleanup without completed actions or implicit authority', () => {
  const detail = { job: { ...job('finishing'), status: 'finalizing', allowedActions: ['reconcile'] },
    snapshot: { status: 'completed', delegationScope: { allowed: true, modes: ['fixture'] } },
    events: [], artifacts: [] } as unknown as JobDetail;
  host.innerHTML = renderToStaticMarkup(createElement(TaskDetail, {
    ownerId: 'member', detail, busy: '', act: async (_name, work) => work(),
    onNotice: () => {}, onSelect: () => {}, jobs: [], drafts: new Map(),
    completedNotice: createElement('button', null, 'Use completed material'),
  }));
  expect(host.querySelector('.badge')?.textContent).toBe('资源确认中');
  expect(host.textContent).toContain('资源停止与任务收尾仍待服务端确认');
  expect(host.textContent).not.toContain('Use completed material');
  const button = (text: string) => [...host.querySelectorAll('button')].find(value => value.textContent === text)!;
  expect(button('请求取消').disabled).toBe(true);
  expect(button('核对执行状态').disabled).toBe(false);
  expect(button('确认创建子任务').disabled).toBe(true);
});

it('continues polling finalizing details until the durable completed state arrives', async () => {
  const finishing = { job: { ...job('finishing'), status: 'finalizing' }, events: [], artifacts: [] } as unknown as JobDetail;
  vi.mocked(api.detail).mockResolvedValue(finishing);
  await render();
  await act(async () => context.onTask('finishing'));
  expect(context.detail?.job.status).toBe('finalizing');
  await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
  expect(api.detail).toHaveBeenCalledTimes(2);
  expect(context.detail?.job.status).toBe('finalizing');
  vi.mocked(api.detail).mockResolvedValue({ ...finishing, job: { ...finishing.job, status: 'completed' } });
  await act(async () => { await vi.advanceTimersByTimeAsync(2500); });
  expect(api.detail).toHaveBeenCalledTimes(3);
  expect(context.detail?.job.status).toBe('completed');
});
