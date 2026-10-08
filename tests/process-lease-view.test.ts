import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ProcessLeasePanel } from '../web/ConnectionsPanel.js';
import { processLeasePage, processLeaseView, type ProcessLease } from '../web/processLeaseView.js';
function lease(): ProcessLease {
  return { id: 'lease-1', ownerId: 'alice', localTaskId: 'task-1', planId: 'plan-1', nativeRunId: 'run-1', state: 'RUNNING',
    executionStatus: 'RUNNING', exitCode: null, capacityHeld: true, providerJobId: 'process-1', processBinding: { taskId: 'task-1', planId: 'plan-1', nativeRunId: 'run-1', bindingFingerprint: 'a'.repeat(64) },
    enforcement: { cpu: 'per-process-RLIMIT_CPU', memory: 'per-process-RLIMIT_AS', fileSize: 'per-file-RLIMIT_FSIZE',
      wall: 'cooperative-process-group-guardian', aggregateQuota: false, hostileCodeSandbox: false, networkIsolation: false },
    stopEvidence: { allStopped: false, kind: 'original-root-reaped-and-no-live-process-group-members' } };
}
const render = (value: unknown) => renderToStaticMarkup(createElement(ProcessLeasePanel, { leases: [value], owner: 'alice' }));
const invalid = (value: unknown) => { expect(processLeaseView(value, 'alice').kind).toBe('invalid'); expect(render(value)).toContain('尚未核实'); expect(render(value)).not.toContain('预约容量已释放'); };
describe('process lease receipt view', () => {
  it('shows receipt identities and precise per-process/file enforcement scope', () => {
    const html = render(lease());
    for (const text of ['process-1', 'task-1', 'run-1', 'plan-1', '每个进程', '每个文件', '协作式进程组守护', '不是进程组总量配额', '不可信代码安全沙箱或网络隔离', '进程停止证据尚未确认', '预约容量仍保留']) expect(html).toContain(text);
    expect(html).not.toContain('租约预约容量已释放');
    expect(html).toContain('overflow-wrap:anywhere');
  });
  it('distinguishes stopped-held from released and never infers stop from completion', () => {
    const value = lease(); value.state = 'COMPLETED'; value.executionStatus = 'COMPLETED'; value.exitCode = 0;
    expect(render(value)).toContain('进程停止证据尚未确认');
    value.stopEvidence!.allStopped = true;
    expect(render(value)).toContain('原进程组停止证据'); expect(render(value)).toContain('预约容量仍保留');
    value.state = 'RECLAIMING'; expect(render(value)).toContain('回收确认待核对');
    value.state = 'RECLAIMED'; value.capacityHeld = false;
    expect(render(value)).toContain('租约预约容量已释放'); expect(render(value)).not.toContain('预约容量仍保留');
  });
  it('distinguishes never-dispatched from root-reaped stop evidence', () => {
    const value = lease(); value.state = 'CANCEL_CONFIRMED'; value.executionStatus = 'CANCELLED'; value.stopEvidence = { allStopped: true, kind: 'never-dispatched' };
    expect(render(value)).toContain('服务端确认进程从未启动'); expect(render(value)).not.toContain('原始根进程已回收'); expect(render(value)).toContain('预约容量仍保留');
  });
  it('shows pre-binding UNKNOWN as held with no integrated-execution claim', () => {
    const value = lease(); Object.assign(value, { state: 'UNKNOWN', processBinding: null, providerJobId: null, enforcement: null, stopEvidence: null });
    const html = render(value);
    for (const text of ['UNKNOWN', '尚未取得进程回执', '不能确认已集成执行', '不宣称内核限额已生效', '预约容量仍保留', '不会重新启动进程']) expect(html).toContain(text);
    expect(processLeaseView(value, 'alice').kind).toBe('verified');
  });
  it('keeps absent process receipts unverified', () => {
    const value = { id: 'lease-1', ownerId: 'alice', localTaskId: 'task-1', planId: 'plan-1', state: 'UNKNOWN', capacityHeld: true };
    expect(render(value)).toContain('进程停止证据尚未确认');
    expect(render(value)).toContain('不能确认已集成执行');
  });
  it('rejects owner and binding mismatches, malformed hashes and unsafe identifiers', () => {
    for (const update of [{ ownerId: 'bob' }, { id: '<script>alert(1)</script>' }, { localTaskId: 'other-task' },
      { planId: 'other-plan' }, { nativeRunId: 'other-run' }, { providerJobId: '/host/private/path' }]) invalid({ ...lease(), ...update });
    invalid({ ...lease(), processBinding: { ...lease().processBinding, bindingFingerprint: 'bad' } });
    invalid({ ...lease(), processBinding: { ...lease().processBinding, extra: 'private' } });
  });
  it('rejects contradictory capacity, stop and enforcement claims', () => {
    invalid({ ...lease(), capacityHeld: false }); invalid({ ...lease(), state: 'RECLAIMED' });
    invalid({ ...lease(), stopEvidence: { ...lease().stopEvidence, allStopped: true } });
    invalid({ ...lease(), stopEvidence: { allStopped: true } });
    invalid({ ...lease(), stopEvidence: { allStopped: false, kind: ['never-dispatched'] } });
    invalid({ ...lease(), state: 'COMPLETED', stopEvidence: { ...lease().stopEvidence, allStopped: true }, processBinding: null });
    for (const update of [{ aggregateQuota: true }, { networkIsolation: true }, { cpu: 'aggregate-cgroup' }, { fileSize: 'disk-quota' }]) invalid({ ...lease(), enforcement: { ...lease().enforcement, ...update } });
  });
  it('keeps failed or limit-stopped outcomes visible after releasing capacity', () => {
    for (const executionStatus of ['FAILED', 'LIMIT_STOPPED']) {
      const value = lease(); Object.assign(value, { state: 'RECLAIMED', capacityHeld: false, executionStatus, exitCode: 1 });
      value.stopEvidence!.allStopped = true;
      const html = render(value);
      expect(html).toContain('租约预约容量已释放'); expect(html).toContain('租约释放不代表进程成功');
      expect(html).toContain(executionStatus === 'FAILED' ? '进程失败' : '进程触发限额后停止');
    }
    invalid({ ...lease(), state: 'RECLAIMED', capacityHeld: false });
    invalid({ ...lease(), exitCode: 256 }); invalid({ ...lease(), exitCode: true }); invalid({ ...lease(), executionStatus: 'successful' });
  });
  it('accepts bounded filtered pages and raw-row cursor, rejecting unsafe pages', () => {
    expect(processLeasePage({ leases: [lease()], nextCursor: 'last-raw-lease' }, 'alice').leases).toHaveLength(1);
    expect(processLeasePage({ leases: [], nextCursor: 'last-filtered-lease' }, 'alice').nextCursor).toBe('last-filtered-lease');
    expect(processLeasePage({ leases: [], nextCursor: null }, 'alice')).toEqual({ leases: [], nextCursor: null });
    for (const value of [{ leases: [lease(), lease()], nextCursor: null }, { leases: Array.from({ length: 101 }, lease), nextCursor: null },
      { leases: [lease()], nextCursor: '../unsafe' }, { leases: [lease()], nextCursor: undefined }, { leases: [{ ...lease(), ownerId: 'bob' }], nextCursor: null }]) expect(() => processLeasePage(value, 'alice')).toThrow();
  });
  it('does not render raw extra metadata, arbitrary provider text, paths or HTML', () => {
    const html = render({ ...lease(), stdout: '<script>private</script>', credential: 'synthetic-private', path: '/host/private' });
    expect(html).not.toContain('synthetic-private'); expect(html).not.toContain('/host/private'); expect(html).not.toContain('<script>');
    invalid({ ...lease(), state: '<img src=x>' });
  });
});
