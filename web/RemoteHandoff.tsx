import { api } from './api.js';
import { remoteHandoffState } from './remoteHandoffState.js';
import type { JobDetail } from './models.js';

type Act = (name: string, work: () => Promise<void>) => Promise<void>;
const kindNames: Record<string, string> = { model: '模型', environment: '环境', tool: '工具', knowledge: '知识' };
const account = (value: string) => value.length > 8 ? `…${value.slice(-8)}` : `…${value.slice(-4)}`;

export function RemoteHandoffPanel({ detail, busy, act, onNotice }: { detail: JobDetail; busy: string; act: Act; onNotice: (message: string) => void }) {
  const state = remoteHandoffState(detail);
  if (state.kind === 'none') return null;
  if (state.kind === 'invalid') return <section className="attention-panel" aria-label="远端凭据待核对"><h3>远端凭据待核对</h3><p role="alert">{state.message}</p></section>;
  const { evidence } = state;
  async function resume() {
    await act('resume-remote', async () => {
      const job = await api.resumeRemote(detail);
      onNotice(job.executionPlacement?.state === 'PREPARING' ? '接收端仍等待管理员审查；原请求和固定方案已保留。' : '已核对并继续原远端请求。执行状态以接收端记录为准。');
    });
  }
  const provenance = <details className="technical-detail"><summary>远端方案与绑定来源</summary><span>接收端方案 {evidence.receiverPlanId}</span><span>当前任务方案 {evidence.sourcePlanId ?? '未提供'}</span><span>源身份 {account(evidence.sourceOwner)} → 接收端身份 {account(evidence.receiverOwner)}</span><span>绑定证据 SHA-256 {evidence.proofHash}</span><span>原始范围 SHA-256 {evidence.manifestHash}</span><span>源配置版本 {evidence.sourceConfiguration.revision}</span><span>源配置 SHA-256 {evidence.sourceConfiguration.sha256}</span><span>接收端配置版本 {evidence.receiverConfiguration.revision}</span><span>接收端配置 SHA-256 {evidence.receiverConfiguration.sha256}</span>
    {evidence.bindings.map((binding, i) => <div className="remote-binding-evidence" key={`${binding.kind}:${binding.materialRef.id}:${i}`}><strong>{kindNames[binding.kind]} · {binding.sourceAdapter}@{binding.sourceRevision} → {binding.receiverAdapter}@{binding.receiverRevision}</strong><span>固定材料 {binding.materialRef.id}@{binding.materialRef.version}</span><span>材料 SHA-256 {binding.materialRef.sha256}</span>{binding.mappingReference ? <><span>映射版本 {binding.mappingReference}@{binding.mappingRevision}</span><span>映射 SHA-256 {binding.mappingSha256}</span></> : <span>使用接收端相同的已注册适配器</span>}</div>)}
    <span>原请求 {evidence.requestId}</span><span>接收记录 {evidence.receiptId}</span>{evidence.receiverTaskId && <span>接收端根任务 {evidence.receiverTaskId}</span>}
  </details>;
  if (state.kind === 'execution') return <section className="remote-provenance" aria-label="远端执行来源">{provenance}</section>;
  return <section className="attention-panel" aria-label="接收端方案审查"><h3>等待接收端管理员审查</h3><p>接收端需要独立审查这份固定方案与绑定范围，尚未创建接收端执行任务。</p><p className="quiet">这是方案准入审查。接收端同意后，任务内需要确认的工具调用仍会另行询问。</p><p>接收端方案 <code className="remote-plan-reference">{evidence.receiverPlanId}</code></p>{provenance}<button className="primary" disabled={!!busy || !detail.job.allowedActions?.includes('resume_remote')} onClick={() => void resume()}>{busy === 'resume-remote' ? '等待远端确认…' : '核对接收端审批并继续'}</button><p className="quiet">此操作沿用原请求。你也可以取消该请求或核对状态；不会替管理员批准方案。</p></section>;
}
