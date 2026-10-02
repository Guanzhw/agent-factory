import type { FactoryJob } from './models.js';
import type { ControlIntent } from './controlCommandStorage.js';

type Recovery = NonNullable<FactoryJob['recoveryDetail']>;
export function approvedRecovery(job: FactoryJob): Recovery | null {
  const value = job.recoveryDetail;
  if (job.status !== 'waiting_approval' || !job.allowedActions?.includes('resume_approved') || !value
      || typeof value.approvalCommandId !== 'string' || !/^[a-zA-Z0-9_.:-]{8,100}$/.test(value.approvalCommandId)
      || typeof value.requirementId !== 'string' || !value.requirementId
      || typeof value.runId !== 'string' || !value.runId || !Number.isSafeInteger(value.version) || value.version < 0
      || typeof value.scope !== 'string' || !value.scope) return null;
  return value;
}
export function ApprovedRecoveryPanel({ recovery, busy, submit }: {
  recovery: Recovery; busy: boolean; submit: (decision: Omit<ControlIntent, 'commandId'>) => void;
}) {
  return <section className="attention-panel"><h3>恢复已记录审批</h3><p>{recovery.scope}</p>
    <p className="quiet">原实验已经完成并停止。恢复后将继续本任务的后续步骤，推理调用仍受当前权限和预算约束。</p>
    <button className="primary" disabled={busy} onClick={() => submit({ action: 'resume_approved',
      approvalCommandId: recovery.approvalCommandId, requirementId: recovery.requirementId, version: recovery.version })}>恢复本次执行</button>
  </section>;
}
