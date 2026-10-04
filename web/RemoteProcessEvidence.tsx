import { ProcessLeasePanel } from './ConnectionsPanel.js';
import type { JobDetail } from './models.js';
import { remoteProcessEvidenceState } from './remoteProcessEvidenceState.js';

export function RemoteProcessEvidence({ detail }: { detail: JobDetail }) {
  const state = remoteProcessEvidenceState(detail);
  if (state.kind === 'missing') return null;
  if (state.kind === 'invalid') return <section className="attention-panel" aria-label="接收端进程证据"><h3>接收端进程租约</h3><p role="alert">接收端租约快照、身份或绑定尚未完整核对，不能确认停止或容量释放。</p></section>;
  return <section aria-label="接收端进程证据" style={{ minWidth: 0, overflowWrap: 'anywhere' }}><h3>接收端进程租约</h3>
    <p className="state-note">以下是接收端原始租约与进程记录，不是当前站点的本地租约。任务完成、进程停止与容量释放分别记录；页面读取不会创建、取消或回收进程。</p>
    <dl className="plan-details"><dt>接收端身份</dt><dd>{state.receiverOwner}</dd><dt>接收端任务</dt><dd>{state.receiverTaskId}</dd><dt>接收端原生运行</dt><dd>{state.receiverRunId}</dd><dt>接收端计划</dt><dd>{state.receiverPlanId}</dd></dl>
    {state.leases.length ? state.leases.map(lease => <div key={lease.id} data-remote-process-lease-id={lease.id}>
      <ProcessLeasePanel leases={[lease]} owner={state.receiverOwner}/>
      <dl className="plan-details"><dt>接收端容量池</dt><dd>{lease.poolId}</dd><dt>准入预约预算</dt><dd>CPU {lease.limits.cpu} · 内存 {lease.limits.memoryMb} MiB · 磁盘 {lease.limits.diskMb} MiB · 时长 {lease.limits.seconds} 秒</dd></dl>
      <p className="quiet">预约预算不是内核强制总量配额；每进程和每文件限额不能证明整个进程组受总量限制。</p>
      <details className="technical-detail"><summary>接收端容量池依据</summary><span>容量池指纹 {lease.poolFingerprint}</span></details>
    </div>) : <p className="list-empty">当前接收端快照尚无进程租约记录，不能据此推断容量已释放。</p>}
  </section>;
}
