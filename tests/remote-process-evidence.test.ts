import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { JobDetail } from '../web/models.js';
import { RemoteProcessEvidence } from '../web/RemoteProcessEvidence.js';
import { RemoteHandoffPanel } from '../web/RemoteHandoff.js';
import { remoteProcessEvidenceState, type RemoteProcessLease } from '../web/remoteProcessEvidenceState.js';
const sourceTask = '11111111-1111-4111-8111-111111111111';
const sourcePlan = '22222222-2222-4222-8222-222222222222';
const receiverTask = '33333333-3333-4333-8333-333333333333';
const receiverPlan = '44444444-4444-4444-8444-444444444444';
const receiverRun = '55555555-5555-4555-8555-555555555555';
const receiptId = '66666666-6666-4666-8666-666666666666';
const hash = 'a'.repeat(64);
function lease(): RemoteProcessLease {
  return { id: 'receiver-lease-1', ownerId: 'receiver-owner', localTaskId: receiverTask, planId: receiverPlan, nativeRunId: receiverRun,
    state: 'RECLAIMED', capacityHeld: false, providerJobId: 'receiver-process-1', executionStatus: 'COMPLETED', exitCode: 0,
    processBinding: { taskId: receiverTask, nativeRunId: receiverRun, planId: receiverPlan, bindingFingerprint: hash },
    enforcement: { cpu: 'per-process-RLIMIT_CPU', memory: 'per-process-RLIMIT_AS', fileSize: 'per-file-RLIMIT_FSIZE',
      wall: 'cooperative-process-group-guardian', aggregateQuota: false, hostileCodeSandbox: false, networkIsolation: false },
    stopEvidence: { allStopped: true, kind: 'original-root-reaped-and-no-live-process-group-members' },
    poolId: 'receiver-capacity-pool', poolFingerprint: hash, limits: { cpu: 1, memoryMb: 128, diskMb: 1, seconds: 5 } };
}
function fixture(): JobDetail {
  const entries = ['model', 'environment'].map(kind => {
    const spec = { materialRef: { id: kind, version: 1, sha256: hash }, adapterId: kind, revision: '1', config: {} };
    return { kind, sourceSpec: spec, effectiveSpec: spec, mappingReference: null, mappingRevision: null, mappingSha256: null };
  });
  const configuration = { revision: '1', sha256: hash };
  return { job: { id: sourceTask, ownerId: 'source-owner', planId: sourcePlan, status: 'completed',
    executionPlacement: { kind: 'remote-factory', targetRef: 'receiver', originTaskId: sourceTask,
      remoteTaskId: receiverTask, remoteRootTaskId: receiverTask, remoteRunId: receiverRun, state: 'ACCEPTED' } },
    snapshot: { remoteHandoff: { id: receiptId, originRef: 'origin', originTaskId: sourceTask, originOwnerId: 'source-owner',
      remoteOwnerId: 'receiver-owner', remoteTaskId: receiverTask, remoteRunId: receiverRun, remotePlanId: receiverPlan,
      requestId: 'request-1', state: 'ACCEPTED', manifestHash: hash,
      receiverBindingProof: { schema: 1, originRef: 'origin', receiptId, originTaskId: sourceTask, originOwner: 'source-owner',
        receiverOwner: 'receiver-owner', receiverPlanId: receiverPlan, manifestHash: hash,
        sourceConfiguration: configuration, receiverConfiguration: configuration, entries, sha256: hash },
      processLeases: { schema: 1, complete: true, leases: [lease()] } } }, events: [], artifacts: [] } as unknown as JobDetail;
}
const receipt = (detail: JobDetail) => detail.snapshot!.remoteHandoff as Record<string, unknown>;
const projection = (detail: JobDetail) => receipt(detail).processLeases as { schema: number; complete: boolean; leases: RemoteProcessLease[] };
const render = (detail: JobDetail) => renderToStaticMarkup(createElement(RemoteProcessEvidence, { detail }));
function invalid(detail: JobDetail) {
  expect(remoteProcessEvidenceState(detail).kind).toBe('invalid');
  expect(render(detail)).toContain('不能确认停止或容量释放');
  expect(render(detail)).not.toContain('租约预约容量已释放');
}
describe('receiver process lease evidence remains in receiver scope', () => {
  it('preserves original receiver identities and renders inside existing handoff panel without actions', () => {
    const detail = fixture();
    expect(remoteProcessEvidenceState(detail).kind).toBe('verified');
    const html = renderToStaticMarkup(createElement(RemoteHandoffPanel, { detail, busy: '', act: async () => {}, onNotice: () => {} }));
    for (const text of ['接收端进程租约', 'receiver-owner', receiverTask, receiverRun, receiverPlan, 'receiver-lease-1',
      'receiver-capacity-pool', '不是当前站点的本地租约', '预约预算不是内核强制总量配额', '每进程和每文件', '租约预约容量已释放']) expect(html).toContain(text);
    expect(html).not.toContain('<button');
    expect(html).not.toContain('/resources/leases/');
    expect(render(detail)).not.toContain(sourceTask);
    expect(render(detail)).not.toContain(sourcePlan);
  });
  it('leaves historical absent projections invisible and distinguishes an empty complete snapshot', () => {
    const detail = fixture(); delete receipt(detail).processLeases;
    expect(render(detail)).toBe(''); expect(remoteProcessEvidenceState(detail).kind).toBe('missing');
    receipt(detail).processLeases = { schema: 1, complete: true, leases: [] };
    expect(render(detail)).toContain('尚无进程租约记录');
    expect(render(detail)).toContain('不能据此推断容量已释放');
    expect(render(detail)).not.toContain('租约预约容量已释放');
  });
  it('rejects remapped origin identities and mismatched receiver task/run/plan/owner', () => {
    for (const fields of [{ ownerId: 'source-owner' }, { ownerId: 'another-receiver' }, { localTaskId: sourceTask },
      { nativeRunId: 'other-run' }, { planId: sourcePlan }]) {
      const detail = fixture(); Object.assign(projection(detail).leases[0], fields); invalid(detail);
    }
    const child = fixture(); child.job.id = sourceTask + '~' + receiverTask; invalid(child);
    const wrongPlacement = fixture(); wrongPlacement.job.executionPlacement!.remoteTaskId = sourceTask; invalid(wrongPlacement);
    const wrongRun = fixture(); wrongRun.job.executionPlacement!.remoteRunId = 'different'; invalid(wrongRun);
  });
  it('requires complete accepted root handoff and valid independent binding proof', () => {
    const incomplete = fixture(); projection(incomplete).complete = false; invalid(incomplete);
    const schema = fixture(); projection(schema).schema = 2; invalid(schema);
    const badProof = fixture(); (receipt(badProof).receiverBindingProof as Record<string, unknown>).receiverOwner = 'forged'; invalid(badProof);
    const unknown = fixture(); receipt(unknown).state = 'UNKNOWN'; invalid(unknown);
    const missingRun = fixture(); receipt(missingRun).remoteRunId = null; invalid(missingRun);
  });
  it('keeps failed and UNKNOWN receiver outcomes separate from release', () => {
    const failed = fixture(); projection(failed).leases[0].executionStatus = 'FAILED'; projection(failed).leases[0].exitCode = 1;
    expect(render(failed)).toContain('进程失败'); expect(render(failed)).toContain('租约预约容量已释放');
    const unknown = fixture(); Object.assign(projection(unknown).leases[0], { state: 'UNKNOWN', capacityHeld: true, executionStatus: 'UNKNOWN', exitCode: null, stopEvidence: null });
    expect(render(unknown)).toContain('UNKNOWN'); expect(render(unknown)).toContain('预约容量仍保留');
    expect(render(unknown)).not.toContain('租约预约容量已释放');
  });
  it('validates bounded pool fingerprints and positive admission limits', () => {
    for (const update of [{ poolId: '/private/pool' }, { poolFingerprint: 'bad' }, { limits: { cpu: 1, memoryMb: 128, diskMb: 1 } },
      { limits: { cpu: true, memoryMb: 128, diskMb: 1, seconds: 5 } }, { limits: { cpu: 1, memoryMb: -1, diskMb: 1, seconds: 5 } },
      { limits: { cpu: 1, memoryMb: 128, diskMb: 1, seconds: 2 ** 32 } }]) {
      const detail = fixture(); Object.assign(projection(detail).leases[0], update); invalid(detail);
    }
    const repeated = fixture(); projection(repeated).leases.push(lease()); invalid(repeated);
    const second = fixture(); projection(second).leases.push({ ...lease(), id: 'receiver-lease-2', providerJobId: 'receiver-process-2' }); invalid(second);
    const oversized = fixture(); projection(oversized).leases = Array.from({ length: 101 }, lease); invalid(oversized);
  });
  it('fails closed on incomplete process stop proof or claimed aggregate enforcement', () => {
    const noStop = fixture(); projection(noStop).leases[0].stopEvidence = null; invalid(noStop);
    const aggregate = fixture(); Object.assign(projection(aggregate).leases[0].enforcement!, { aggregateQuota: true }); invalid(aggregate);
  });
  it('never renders arbitrary provider metadata and escapes bounded receiver identity as text', () => {
    const detail = fixture(); Object.assign(projection(detail).leases[0], { rawBody: '<script>private</script>', path: '/host/private' });
    expect(render(detail)).not.toContain('<script>'); expect(render(detail)).not.toContain('/host/private');
    const identity = '<img src=x onerror=alert(1)>';
    receipt(detail).remoteOwnerId = identity;
    (receipt(detail).receiverBindingProof as Record<string, unknown>).receiverOwner = identity;
    projection(detail).leases[0].ownerId = identity;
    expect(render(detail)).toContain('&lt;img'); expect(render(detail)).not.toContain('<img');
  });
});
