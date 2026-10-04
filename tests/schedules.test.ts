import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { SchedulesPanel } from '../web/SchedulesPanel.js';
import { occurrencePage, scheduleMetadata, schedulePage, schedulePreview, scheduleReply, scheduleSummary, sendScheduleOnce, ScheduleGuard, type ScheduleApi, type ScheduleMutation } from '../web/scheduleState.js';
const hash = 'a'.repeat(64);
const row = { id: 'schedule-1', ownerId: 'alice', requestId: 'request-1', lastCommandId: 'request-1', name: '每日来源检查', cron: '0 8 * * *', timezone: 'Etc/UTC', enabled: false, planId: 'plan-1', planFingerprint: hash, planDigest: hash, definitionFingerprint: hash, nextRunAt: '2026-10-05T08:00:00Z', allowedActions: ['edit', 'enable'] };
const meta = { schema: 1, ownerId: 'alice', canManage: true, policy: { singlePoller: true, overlap: 'allow-with-current-budget-admission', missed: 'coalesce', pauseCancelsRunning: false, timeSemantics: 'cron-iana-timezone', maxUserTasks: 2, maxTotalTasks: 20 } };
const page = { schema: 1, ownerId: 'alice', items: [row], nextCursor: null, snapshot: false };
const occurrence = { id: 'occurrence-1', ownerId: 'alice', scheduleId: row.id, status: 'accepted', taskId: 'task-1', nativeRunId: 'run-1', createdAt: '2026-10-04T00:00:00Z', taskStatus: 'running', reasonCode: null };
const occurrences = { schema: 1, ownerId: 'alice', scheduleId: row.id, items: [occurrence], nextCursor: null, snapshot: false };
const intent: ScheduleMutation = { kind: 'create', requestId: row.requestId, planId: row.planId, planFingerprint: hash, name: row.name, cron: row.cron, timezone: row.timezone };
function api(): ScheduleApi { return { metadata: vi.fn().mockResolvedValue(meta), list: vi.fn().mockResolvedValue(page), recover: vi.fn().mockResolvedValue(row), inspect: vi.fn().mockResolvedValue(row), preview: vi.fn(), create: vi.fn().mockResolvedValue(row), update: vi.fn(), setEnabled: vi.fn(), occurrences: vi.fn().mockResolvedValue(occurrences) }; }
function preview() { return { schema: 1, cron: row.cron, timezone: row.timezone, previewedAtUtc: '2026-10-04T00:00:00Z', nextRuns: [5, 6, 7].map(day => { const utc = `2026-10-0${day}T08:00:00Z`; return { epoch: Date.parse(utc) / 1000, utc, local: utc.replace('Z', '+00:00'), utcOffsetSeconds: 0 }; }), semantics: { clock: 'agno-3.1.0/croniter-6.2.4/pytz', missed: 'coalesce-no-catch-up', overlap: 'allowed-subject-to-owner-and-global-budgets', dst: 'native-croniter-pytz', previewOnly: true } }; }
describe('schedule management boundaries', () => {
  it('validates exact owner, plan, definition and allowed action scope', () => {
    expect(scheduleSummary(row, 'alice', row.id).enabled).toBe(false);
    for (const patch of [{ ownerId: 'bob' }, { planFingerprint: 'invalid' }, { definitionFingerprint: 'invalid' }, { enabled: 'false' }, { allowedActions: ['trigger'] }]) expect(() => scheduleSummary({ ...row, ...patch }, 'alice')).toThrow();
    expect(() => scheduleSummary(row, 'alice', 'other')).toThrow();
  });
  it('requires the current permission metadata and declared native scheduling semantics', () => {
    expect(scheduleMetadata(meta, 'alice').policy.pauseCancelsRunning).toBe(false);
    for (const patch of [{ singlePoller: false }, { missed: 'catch-up' }, { pauseCancelsRunning: true }, { maxUserTasks: 0 }]) expect(() => scheduleMetadata({ ...meta, policy: { ...meta.policy, ...patch } }, 'alice')).toThrow();
    expect(scheduleMetadata({ ...meta, canManage: false }, 'alice').canManage).toBe(false);
  });
  it('accepts bounded owner pages while rejecting duplicate rows and wrong continuation', () => {
    expect(schedulePage(page, 'alice').items).toHaveLength(1);
    for (const patch of [{ items: [row, row] }, { nextCursor: 'wrong' }, { snapshot: true }, { ownerId: 'bob' }]) expect(() => schedulePage({ ...page, ...patch }, 'alice')).toThrow();
  });
  it('keeps admission distinct from native execution and scopes occurrence links', () => {
    expect(occurrencePage(occurrences, 'alice', row.id).items[0]).toMatchObject({ status: 'accepted', taskStatus: 'running' });
    for (const patch of [{ ownerId: 'bob' }, { scheduleId: 'other' }, { taskId: null }, { taskStatus: 'scientifically-verified' }]) expect(() => occurrencePage({ ...occurrences, items: [{ ...occurrence, ...patch }] }, 'alice', row.id)).toThrow();
    expect(occurrencePage({ ...occurrences, items: [{ ...occurrence, status: 'unknown', taskId: null, nativeRunId: null, taskStatus: null, reasonCode: 'ADMISSION_UNKNOWN' }] }, 'alice', row.id).items[0].status).toBe('unknown');
  });
  it('checks native preview clock, increasing UTC epochs, local offsets and normalized cron', () => {
    expect(schedulePreview(preview(), '0  8 * * *', row.timezone).nextRuns).toHaveLength(3);
    for (const patch of [{ epoch: 0 }, { utcOffsetSeconds: 3600 }, { local: '2026-10-05T09:00:00+00:00' }]) { const v = preview(); Object.assign(v.nextRuns[0], patch); expect(() => schedulePreview(v, row.cron, row.timezone)).toThrow(); }
    expect(() => schedulePreview({ ...preview(), semantics: { ...preview().semantics, dst: 'invented' } }, row.cron, row.timezone)).toThrow();
  });
  it('confirms only the original create request and paused immutable plan', () => {
    expect(scheduleReply(row, 'alice', intent).id).toBe(row.id);
    for (const patch of [{ lastCommandId: 'other' }, { requestId: 'other' }, { enabled: true }, { planId: 'other' }, { cron: '* * * * *' }]) expect(() => scheduleReply({ ...row, ...patch }, 'alice', intent)).toThrow();
  });
  it('reconciles a lost create ACK with only GET and never a second automatic POST', async () => {
    const client = api(); vi.mocked(client.create).mockRejectedValue(new Error('lost'));
    expect((await sendScheduleOnce(client, 'alice', intent)).id).toBe(row.id);
    expect(client.create).toHaveBeenCalledTimes(1); expect(client.recover).toHaveBeenCalledWith(intent.requestId); expect(client.list).not.toHaveBeenCalled();
  });
  it('recovers an original create outside the page even after a later edit or enable', async () => {
    const client = api(); vi.mocked(client.create).mockRejectedValue(new Error('lost'));
    vi.mocked(client.list).mockResolvedValue({ ...page, items: [] });
    vi.mocked(client.recover).mockResolvedValue({ ...row, lastCommandId: 'later-command', cron: '0 9 * * *', enabled: true });
    expect(await sendScheduleOnce(client, 'alice', intent)).toMatchObject({ requestId: intent.requestId, enabled: true, cron: '0 9 * * *' });
    expect(client.create).toHaveBeenCalledTimes(1); expect(client.list).not.toHaveBeenCalled();
    vi.mocked(client.recover).mockResolvedValue({ ...row, requestId: 'other-create' });
    await expect(sendScheduleOnce(client, 'alice', intent)).rejects.toThrow('lost');
  });
  it('does not misread another mutation as confirmation, or retry unknown PATCH/enable', async () => {
    const client = api(); const lost = new Error('SCHEDULE_EDITOR_UNKNOWN');
    vi.mocked(client.update).mockRejectedValue(lost); vi.mocked(client.setEnabled).mockRejectedValue(lost);
    const edit: ScheduleMutation = { kind: 'edit', requestId: 'new-request', scheduleId: row.id, expectedDefinitionFingerprint: hash, cron: row.cron, timezone: row.timezone };
    await expect(sendScheduleOnce(client, 'alice', edit)).rejects.toBe(lost); expect(client.update).toHaveBeenCalledTimes(1);
    await expect(sendScheduleOnce(client, 'alice', { kind: 'enabled', requestId: 'new-request', scheduleId: row.id, expectedDefinitionFingerprint: hash, enabled: true })).rejects.toBe(lost); expect(client.setEnabled).toHaveBeenCalledTimes(1);
  });
  it('locks double clicks and discards old owner responses after switching back', () => {
    const guard = new ScheduleGuard(); const old = guard.enter('alice'); expect(guard.claim(old)).toBe(true); expect(guard.claim(old)).toBe(false);
    guard.enter('bob'); const current = guard.enter('alice'); expect(guard.current(old)).toBe(false); expect(guard.claim(current)).toBe(true); guard.release(old); expect(guard.claim(current)).toBe(false);
  });
  it('renders no mutation authority until metadata arrives and communicates uncertainty', () => {
    const client = api(); const html = renderToStaticMarkup(createElement(SchedulesPanel, { ownerId: 'alice', canManage: true, api: client, onTask: vi.fn(), seed: { planId: row.planId, planFingerprint: hash, goal: '固定方案' } }));
    for (const words of ['暂停只停止后续准入', '不会取消', 'UNKNOWN', '不代表研究任务完成']) expect(html).toContain(words);
    expect(html).not.toContain('保存计划任务'); expect(client.create).not.toHaveBeenCalled(); expect(client.setEnabled).not.toHaveBeenCalled();
  });
});
