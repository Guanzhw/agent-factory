import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ScheduleDiagnostics } from '../web/ScheduleDiagnostics.js';
import { diagnosticCatalog, diagnosticPage, diagnosticReasons, DiagnosticsEpoch } from '../web/scheduleDiagnosticsState.js';
const owner = '研究员@example.com';
const schedule = '10000000-0000-4000-8000-000000000000';
const uuid = (number: number) => `20000000-0000-4000-8000-${String(number).padStart(12, '0')}`;
const at = '2026-10-04T08:30:00.123456+00:00';
const item = (number = 1) => ({ id: uuid(number), ownerId: owner, scheduleId: schedule, reasonCode: 'CLOCK_BUSY', source: 'native', observedAt: at });
const page = () => ({ schema: 1, ownerId: owner, scheduleId: schedule, items: [item()], nextCursor: null, retention: { days: 30, maxRecords: 100 }, coverage: 'retained-rejections-only', snapshot: false });
describe('schedule rejection diagnostics', () => {
  it('accepts all finite reasons and strips raw legacy fields', () => {
    for (const reasonCode of Object.keys(diagnosticReasons)) {
      const value = { ...page(), rawError: 'unsafe error', items: [{ ...item(), reasonCode, detail: 'unsafe audit', taskId: 'not trusted' }] };
      const result = diagnosticPage(value, owner, schedule);
      expect(result.items[0].reasonCode).toBe(reasonCode);
      expect(JSON.stringify(result)).not.toContain('unsafe');
      expect(result.items[0]).not.toHaveProperty('taskId');
    }
  });
  it('checks exact owner and schedule at envelope and each row', () => {
    expect(() => diagnosticPage(page(), 'bob', schedule)).toThrow();
    expect(() => diagnosticPage(page(), owner, uuid(9))).toThrow();
    for (const changed of [{ ownerId: 'bob' }, { scheduleId: uuid(9) }]) expect(() => diagnosticPage({ ...page(), items: [{ ...item(), ...changed }] }, owner, schedule)).toThrow();
  });
  it('rejects unknown reasons, inherited keys, unsafe IDs, timestamps and sources', () => {
    for (const changed of [{ reasonCode: 'raw-secret' }, { reasonCode: 'toString' }, { reasonCode: '__proto__' }, { source: 'automatic-retry' }, { id: '<script>' }, { observedAt: 'yesterday' }, { observedAt: '2026-10-04' }, { observedAt: '2026-99-99T25:00:00Z' }]) {
      expect(() => diagnosticPage({ ...page(), items: [{ ...item(), ...changed }] }, owner, schedule)).toThrow();
    }
    expect(diagnosticPage({ ...page(), items: [{ ...item(), source: 'manual' }] }, owner, schedule).items[0].source).toBe('manual');
  });
  it('preserves limited coverage for an empty page rather than declaring no executions', () => {
    const result = diagnosticPage({ ...page(), items: [] }, owner, schedule);
    expect(result.items).toEqual([]); expect(result.snapshot).toBe(false); expect(result.coverage).toBe('retained-rejections-only');
    for (const change of [{ snapshot: true }, { coverage: 'all-triggers' }, { retention: { days: 365, maxRecords: 100 } }, { retention: { days: 30, maxRecords: 101 } }]) expect(() => diagnosticPage({ ...page(), ...change }, owner, schedule)).toThrow();
  });
  it('enforces bounded ascending pages and exact last-row cursors', () => {
    const items = Array.from({ length: 20 }, (_, index) => item(index + 1));
    expect(diagnosticPage({ ...page(), items, nextCursor: uuid(20) }, owner, schedule).nextCursor).toBe(uuid(20));
    for (const changes of [{ items: [...items, item(21)] }, { items: [item(1), item(1)] }, { items: [item(2), item(1)] }, { items, nextCursor: uuid(19) }, { items: [], nextCursor: uuid(1) }]) expect(() => diagnosticPage({ ...page(), ...changes }, owner, schedule)).toThrow();
  });
  it('catalog accepts safe schedule identity without requiring editor metadata', () => {
    const result = diagnosticCatalog({ schema: 1, ownerId: owner, items: [{ id: schedule, createdAt: at, name: 'unsafe untrusted metadata' }], nextCursor: null }, owner);
    expect(result.items).toEqual([{ id: schedule, createdAt: at }]);
    expect(() => diagnosticCatalog({ ...result, ownerId: 'bob' }, owner)).toThrow();
    expect(() => diagnosticCatalog({ ...result, items: [{ id: schedule, createdAt: 'bad' }] }, owner)).toThrow();
  });
  it('invalidates responses across owner and schedule changes, including ABA', () => {
    const guard = new DiagnosticsEpoch();
    const first = guard.enter(owner, schedule); expect(guard.current(first)).toBe(true);
    const second = guard.enter(owner, uuid(2)); expect(guard.current(first)).toBe(false);
    const third = guard.enter('bob', schedule); expect(guard.current(second)).toBe(false);
    const fourth = guard.enter(owner, schedule); expect(guard.current(third)).toBe(false); expect(guard.current(first)).toBe(false); expect(guard.current(fourth)).toBe(true);
  });
  it('renders a standalone read-only selector with no editing authority or mutation controls', () => {
    const html = renderToStaticMarkup(createElement(ScheduleDiagnostics, { ownerId: owner, api: { list: async () => null, page: async () => null } }));
    expect(html).toContain('计划触发拒绝诊断'); expect(html).toContain('选择诊断计划'); expect(html).toContain('不需要计划编辑权限'); expect(html).toContain('执行时间修改尚未确认时仍可查看');
    expect(html).not.toContain('保存执行时间'); expect(html).not.toContain('重新运行');
  });
});
