import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ProcessLeasePanel } from '../web/ConnectionsPanel.js';
import { processLeaseView } from '../web/processLeaseView.js';
const hash = 'a'.repeat(64);
function lease() {
  return { id: 'lease-1', ownerId: 'alice', localTaskId: 'task-1', planId: 'plan-1', nativeRunId: 'run-1', providerJobId: 'job-1',
    state: 'RUNNING', executionStatus: 'RUNNING', exitCode: null, capacityHeld: true,
    processBinding: { taskId: 'task-1', nativeRunId: 'run-1', planId: 'plan-1', bindingFingerprint: hash },
    enforcement: { schema: 2, backend: 'delegated-cgroup-v2', cpu: 'cgroup-v2-cpu.max', memory: 'cgroup-v2-memory.max+memory.swap.max', pids: 'cgroup-v2-pids.max',
      fileSize: 'per-file-RLIMIT_FSIZE', wall: 'original-delegated-cgroup-guardian', aggregateScopes: ['aggregate-cpu', 'aggregate-memory', 'aggregate-pids'],
      hostileCodeSandbox: false, networkIsolation: false, configurationSha256: hash },
    aggregateEvidence: { schema: 1, backend: 'delegated-cgroup-v2', ticketId: 'b'.repeat(32), bindingSha256: hash, configSha256: hash,
      rootPinSha256: hash, groupPinSha256: hash, state: 'ATTACHED', populated: true, limitsReadbackVerified: true, releasedProof: false, attached: true }, stopEvidence: null };
}
const render = (value: unknown) => renderToStaticMarkup(createElement(ProcessLeasePanel, { leases: [value], owner: 'alice' }));
const invalid = (value: unknown) => expect(processLeaseView(value, 'alice').kind).toBe('invalid');
describe('aggregate process evidence', () => {
  it('separates declared scopes from observed readback and attachment', () => {
    const value = lease(); expect(processLeaseView(value, 'alice').kind).toBe('verified');
    const html = render(value);
    for (const text of ['声明的聚合限额范围', '配置声明不等于实际执行', '内核限额回读核对通过', '进程附加到原 cgroup', '不提供磁盘总量配额', '网络隔离', '预约容量仍保留']) expect(html).toContain(text);
    expect(html).not.toContain('聚合限制已验收');
  });
  it('does not claim enforcement from configured-only or UNKNOWN receipts', () => {
    const value = lease(); Object.assign(value.aggregateEvidence, { state: 'READY', populated: false, attached: false });
    expect(render(value)).toContain('尚未确认进程附加，不宣称实际执行已受聚合限制');
    Object.assign(value, { state: 'UNKNOWN', executionStatus: 'UNKNOWN' }); Object.assign(value.aggregateEvidence, { state: 'UNKNOWN', populated: null, limitsReadbackVerified: false, attached: false });
    expect(render(value)).toContain('聚合执行证据 UNKNOWN'); expect(render(value)).toContain('预约容量仍保留');
  });
  it('preserves historical attachment when current control readback drifts', () => {
    const value = lease(); Object.assign(value, { state: 'UNKNOWN', executionStatus: 'UNKNOWN' }); Object.assign(value.aggregateEvidence, { state: 'UNKNOWN', limitsReadbackVerified: false });
    expect(processLeaseView(value, 'alice').kind).toBe('verified');
    const html = render(value); expect(html).toContain('服务端已记录进程附加到原 cgroup'); expect(html).toContain('尚未确认内核限额回读'); expect(html).toContain('预约容量仍保留');
  });
  it('allows pre-admission configuration with no job while rejecting missing evidence for a dispatched receipt', () => {
    invalid({ ...lease(), aggregateEvidence: null });
    const value = { ...lease(), providerJobId: null, aggregateEvidence: null, processBinding: null, state: 'RESERVED', executionStatus: null };
    expect(processLeaseView(value, 'alice').kind).toBe('verified'); expect(render(value)).toContain('尚未确认内核限额回读');
  });
  it('requires exact bindings, configurations, scopes and safe finite fields', () => {
    for (const patch of [{ bindingSha256: 'c'.repeat(64) }, { configSha256: 'c'.repeat(64) }, { rootPinSha256: '/private' }, { ticketId: '../ticket' }, { state: 'invented' }, { populated: 'false' }, { attached: true, groupPinSha256: null }, { secret: 'do-not-display' }]) invalid({ ...lease(), aggregateEvidence: { ...lease().aggregateEvidence, ...patch } });
    for (const patch of [{ aggregateQuota: true }, { networkIsolation: true }, { fileSize: 'aggregate-disk' }, { aggregateScopes: ['aggregate-cpu', 'aggregate-memory', 'aggregate-disk'] }]) invalid({ ...lease(), enforcement: { ...lease().enforcement, ...patch } });
  });
  it('requires original empty-and-removed proof for aggregate stop and release', () => {
    const value = { ...lease(), state: 'RECLAIMED', executionStatus: 'COMPLETED', exitCode: 0, capacityHeld: false,
      aggregateEvidence: { ...lease().aggregateEvidence, state: 'RELEASED', populated: false, releasedProof: true },
      stopEvidence: { allStopped: true, kind: 'original-delegated-cgroup-empty-and-removed' } };
    expect(processLeaseView(value, 'alice')).toMatchObject({ kind: 'verified', stopped: true, released: true });
    expect(render(value)).toContain('原委派 cgroup 为空且已移除'); expect(render(value)).toContain('租约预约容量已释放');
    for (const patch of [{ releasedProof: false }, { state: 'EMPTY' }, { populated: true }, { groupPinSha256: null }]) invalid({ ...value, aggregateEvidence: { ...value.aggregateEvidence, ...patch } });
    invalid({ ...value, stopEvidence: { allStopped: true, kind: 'original-root-reaped-and-no-live-process-group-members' } });
  });
  it('supports never-dispatched only before aggregate effects and preserves capacity distinction', () => {
    const value = { ...lease(), state: 'CANCEL_CONFIRMED', executionStatus: 'CANCELLED',
      aggregateEvidence: { ...lease().aggregateEvidence, state: 'NEW', groupPinSha256: null, populated: null, limitsReadbackVerified: false, attached: false },
      stopEvidence: { allStopped: true, kind: 'never-dispatched' } };
    expect(processLeaseView(value, 'alice').kind).toBe('verified'); expect(render(value)).toContain('从未启动'); expect(render(value)).toContain('预约容量仍保留');
    invalid({ ...value, aggregateEvidence: { ...value.aggregateEvidence, state: 'CREATE_INTENT' } });
  });
});
