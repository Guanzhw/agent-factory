import { useEffect, useRef, useState, type ComponentType, type ReactNode } from 'react';
import { api } from './api.js';
import { ControlRecovery, commandNotice } from './ControlRecovery.js';
import { persistCommandPointer, type ControlIntent } from './controlCommandStorage.js';
import { ApprovedRecoveryPanel, approvedRecovery } from './ApprovedRecovery.js';
import { WorkflowPanel } from './WorkflowPanel.js';
import { EventTimeline } from './EventTimeline.js';
import { delegationModes } from './delegationModes.js';
import { RemoteHandoffPanel } from './RemoteHandoff.js';
import { nativeInteractionAvailable, remoteHandoffState } from './remoteHandoffState.js';
import { ArtifactDownload } from './VerifiedArtifactDownload.js';
import { UsageLedgerPanel } from './UsageLedger.js';
import { Badge, ErrorMessage, time } from './workspaceUI.js';
import { pendingApproval, pendingQuestion, statusNames, type Artifact, type FactoryJob, type JobSummary, type JobDetail, type DelegationGroup, type DelegationScope } from './models.js';
import type { ComposerSeed } from './ApplicationComposer.js';
import type { WorkspaceContext } from './App.js';

export function TaskWorkspace({ context, Detail = TaskDetail, title, modeLabels = {}, emptyContent }: {
  context: WorkspaceContext; Detail?: ComponentType<TaskDetailProps>;
  title?: (job: JobSummary) => string; modeLabels?: Readonly<Record<string, string>>; emptyContent?: ReactNode;
}) {
  const { user, route, jobs, status, detail, detailError, busy, act, notice: onNotice, onTask, jobsLoaded, jobsError, historyError, historyLoading, nextCursor, loadEarlier, retry, drafts, onCompose } = context;
  const selected = route.task;
  const panel = useRef<HTMLElement>(null);
  useEffect(() => { if (selected) panel.current?.focus(); }, [selected]);
  return <><ControlRecovery ownerId={user.id} onSelect={onTask} busy={busy} act={act}/>
    <div className="page-heading"><div><h1>任务与证据</h1><p>查看原任务、审批、执行进度与证据。</p></div><div className="worker-metrics"><span><b>{status?.activeWorkers ?? '—'}</b>执行中</span><span><b>{status?.queuedJobs ?? '—'}</b>排队</span><span><b>{status?.maxWorkers ?? '—'}</b>执行上限</span></div></div>
    <div className={`task-grid ${selected ? 'has-task' : 'new-task-layout'}`}><div className="task-left"><TaskList jobs={jobs} selected={selected} select={onTask} loading={!jobsLoaded} title={title} modeLabels={modeLabels}/><ErrorMessage message={jobsError && `任务列表更新失败：${jobsError}`} retry={retry}/><ErrorMessage message={historyError && `更早任务读取失败：${historyError}`} retry={loadEarlier}/>{nextCursor && <button className="secondary" disabled={historyLoading} onClick={loadEarlier}>{historyLoading ? '正在读取更早任务…' : '加载更早任务'}</button>}</div>
    <section className="task-panel" aria-label="任务详情" id="task-detail" ref={panel} tabIndex={-1}>
      {selected ? detail?.job.id === selected ? <Detail key={detail.job.id} detail={detail} busy={busy} act={act} onNotice={onNotice} onSelect={onTask} jobs={jobs} drafts={drafts} ownerId={user.id} onCompose={onCompose} modeLabels={modeLabels}/>
        : <div className="empty-state"><h2>{detailError ? '暂时无法读取任务' : '正在读取任务'}</h2><p>{detailError || '获取执行记录、事件与证据。'}</p><button className="secondary" onClick={retry}>重试</button></div>
        : <div className="empty-state"><div className="empty-glyph" aria-hidden="true">◎</div><h2>让每一步都有记录</h2>{emptyContent ?? <p>选择已有任务查看进度、待回答问题与证据。</p>}</div>}
      {detailError && detail && <ErrorMessage message={`记录更新失败：${detailError}`} retry={retry}/>}</section></div></>;
}

function TaskList({ jobs, selected, select, loading, title = job => job.input.topic, modeLabels = {} }: { jobs: JobSummary[]; selected: string; select: (id: string) => void; loading: boolean; title?: (job: JobSummary) => string; modeLabels?: Readonly<Record<string, string>> }) {
  return <section className="task-list" aria-labelledby="task-list-title"><div className="section-heading"><h2 id="task-list-title">我的任务</h2><span className="quiet">已加载 {jobs.length} 项</span></div><p className="quiet">列表展示已保存的状态；执行与停止确认请查看任务详情。</p>{jobs.length ? <div className="task-list-items">{jobs.map(job => <button className={`task-row ${selected === job.id ? 'selected' : ''}`} key={job.id} onClick={() => select(job.id)} aria-pressed={selected === job.id}><div><strong>{title(job)}</strong><small>{time(job.createdAt)} · {(modeLabels[job.input.mode] ?? job.input.mode)}</small><small>{job.observedAt ? `状态记录于 ${time(job.observedAt)}` : '尚无执行观察记录'}</small></div><Badge value={job.status} /></button>)}</div> : <p className="list-empty">{loading ? '正在读取任务…' : '尚无任务。在应用中提交目标后，在此查看进度与结果。'}</p>}</section>;
}

function DelegationPanel({ detail, busy, act, onNotice, onSelect, jobs, drafts, modeLabels }: { modeLabels: Readonly<Record<string, string>>; detail: JobDetail; busy: string; act: (name: string, work: () => Promise<void>) => Promise<void>; onNotice: (message: string) => void; onSelect: (id: string) => void; jobs: JobSummary[]; drafts: Map<string, ChildDraft> }) {
  const id = detail.job.id;
  const [draft, setDraft] = useState<ChildDraft>(() => drafts.get(id) ?? { goal: '', mode: '', requestId: '' });
  const rawGroup = detail.snapshot?.delegation;
  const observed = rawGroup && typeof rawGroup === 'object' ? rawGroup as DelegationGroup : undefined;
  const [queried, setQueried] = useState<DelegationGroup>();
  useEffect(() => { setQueried(undefined); }, [rawGroup]);
  const group = queried ?? observed;
  const rawScope = detail.snapshot?.delegationScope;
  const scope = rawScope && typeof rawScope === 'object' ? rawScope as DelegationScope : undefined;
  const modeChoices = delegationModes(scope, draft.mode, !!draft.requestId);
  const canCreate = modeChoices.available && scope?.allowed === true && detail.job.allowedActions?.includes('delegate') === true && ['queued', 'running', 'waiting_input', 'waiting_approval'].includes(detail.job.status);
  const edit = (changes: Partial<ChildDraft>) => {
    const next = { ...draft, ...changes, requestId: '' };
    setDraft(next); drafts.set(id, next);
  };
  const submit = () => {
    if (!canCreate || draft.goal.trim().length < 2) return;
    const next = { ...draft, mode: modeChoices.selected, requestId: draft.requestId || crypto.randomUUID() };
    setDraft(next); drafts.set(id, next);
    void act('delegate', async () => {
      const receipt = await api.createChild(id, next.goal.trim(), next.mode, next.requestId);
      onNotice(receipt.duplicate ? '已核对原子任务请求；请查看子任务的实际状态。' : '子任务请求已确认；执行状态以服务端记录为准。');
    });
  };
  const count = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value : '未提供';
  function childStatus(child: DelegationGroup['parent']) {
    if (child.unknown) return '状态待核对';
    if (child.failed) return `执行或权限检查失败 · ${child.stopped ? '已确认停止' : '停止尚未确认'}`;
    const native: Record<string, string> = { pending: '排队中', paused: '等待继续', cancelled: '已取消', error: '执行失败' };
    const status = statusNames[child.nativeStatus ?? ''] ?? native[child.nativeStatus ?? ''] ?? '状态未提供';
    return `${status} · ${child.stopped ? '已确认停止' : '停止尚未确认'}`;
  }
  return <section className="delegation-panel"><div className="section-heading"><h3>任务委托</h3><button className="text-button" disabled={!!busy} onClick={() => void act('group', async () => { setQueried(await api.group(id)); onNotice('已读取任务组的实际状态。'); })}>核对任务组</button></div><p className="quiet">子任务受父任务与根任务的不可变权限约束，共享工具预算。取消当前任务会向其后代发出取消请求，全部停止仍需确认。</p>{scope ? <><div className="delegation-budget"><span>共享工具调用 <b>{count(scope.sharedBudget?.toolCallsUsed)} / {count(scope.sharedBudget?.toolCallsLimit)}</b></span><span>累计子任务 <b>{count(scope.sharedBudget?.childrenUsed)} / {count(scope.sharedBudget?.childrenLimit)}</b></span><span>当前深度 <b>{count(scope.depth)} / {count(scope.sharedBudget?.maxDepth)}</b></span></div><details className="technical-detail"><summary>不可变范围与共享预算</summary><span>父任务：{scope.parentTaskId ?? '未提供'}</span><span>根任务：{scope.rootTaskId ?? '未提供'}</span><span>能力范围：{scope.capabilities?.join('、') || '未提供'}</span><span>工具范围：{scope.tools?.join('、') || '未提供'}</span><pre>{JSON.stringify(scope.budget ?? {}, null, 2)}</pre>{draft.requestId && <span>创建请求：{draft.requestId}</span>}</details></> : <p className="quiet">后端尚未提供委托权限与共享预算，暂不能创建子任务。</p>}{group ? <><p className="delegation-state">{group.unknown ? '任务组存在未确认状态' : group.allStopped ? '任务组已确认全部停止' : group.pending ? '仍有子任务待完成或停止确认' : '父任务停止结果仍待确认'}</p>{group.children?.length ? <ul className="delegation-children">{group.children.map((child, i) => <li key={child.taskId ?? child.link?.request_id ?? i}><div><strong>{jobs.find(job => job.id === child.taskId)?.input.topic ?? '已登记的子任务'}</strong><small>{childStatus(child)}{child.link?.depth !== undefined ? ` · 深度 ${child.link.depth}` : ''}</small></div><button className="secondary" disabled={!!busy || !child.taskId} onClick={() => child.taskId && onSelect(child.taskId)}>查看子任务</button></li>)}</ul> : <p className="quiet">当前没有后代任务记录。</p>}</> : <p className="quiet">任务组状态尚未提供。</p>}{scope && !modeChoices.available && <p className="quiet">当前固定应用没有可用的子任务方式；原请求记录保留，不会改为其他方式。</p>}<form className="delegation-form" onSubmit={event => { event.preventDefault(); submit(); }}><label htmlFor="child-goal">子任务目标</label><textarea id="child-goal" rows={2} maxLength={2000} value={draft.goal} disabled={!!busy || !canCreate} onChange={event => edit({ goal: event.target.value })} placeholder="将当前目标拆分为一个有边界的子任务"/><div className="delegation-form-actions"><label>执行方式<select aria-label="子任务执行方式" value={modeChoices.selected} disabled={!!busy || !canCreate} onChange={event => edit({ mode: event.target.value as ChildDraft['mode'] })}>{modeChoices.modes.map(mode => <option key={mode} value={mode}>{(modeLabels[mode] ?? mode)}</option>)}{draft.requestId && !modeChoices.available && <option value={draft.mode}>原请求 {(modeLabels[draft.mode] ?? draft.mode)}（当前不可委派）</option>}</select></label><button className="primary" disabled={!!busy || !canCreate || draft.goal.trim().length < 2}>{busy === 'delegate' ? '等待创建确认…' : draft.requestId ? '核对原创建请求' : '确认创建子任务'}</button></div></form><p className="quiet">通常每人最多 2 个活跃任务，父任务会占用一个名额；累计子任务与深度限制由服务端检查。{!canCreate && scope && '当前任务没有可用的委托授权。'}</p></section>;
}

export interface ChildDraft { goal: string; mode: string; requestId: string }
export interface TaskDetailProps {
  ownerId: string; detail: JobDetail; busy: string;
  act: (name: string, work: () => Promise<void>) => Promise<void>;
  onNotice: (message: string) => void; onSelect: (id: string) => void;
  jobs: JobSummary[]; drafts: Map<string, ChildDraft>;
  onCompose?: (seed: ComposerSeed, notice: string) => void;
  modeLabels?: Readonly<Record<string, string>>; title?: string; source?: string; artifacts?: Artifact[];
  evidenceBefore?: ReactNode; evidenceAfter?: ReactNode;
  approvalAllowed?: boolean; approvalNotice?: ReactNode; completedNotice?: ReactNode;
}
export function TaskDetail({ detail, busy, act, onNotice, onSelect, jobs, drafts, ownerId,
  modeLabels = {}, title, source, artifacts = detail.artifacts, evidenceBefore, evidenceAfter,
  approvalAllowed = true, approvalNotice, completedNotice }: TaskDetailProps) {
  const { job, events } = detail;
  const [answer, setAnswer] = useState('');
  const question = pendingQuestion(detail);
  const approval = pendingApproval(detail);
  const recordedRecovery = approvedRecovery(job);
  const inferenceRecovery = job.approvalDetail?.toolName === 'factory_resume_inference';
  const workflowWaiting = job.approvalDetail?.toolName === 'workflow_wait';
  const remoteState = remoteHandoffState(detail);
  const nativeAvailable = nativeInteractionAvailable(detail);
  const awaitingReceiver = !nativeAvailable;
  useEffect(() => { setAnswer(''); }, [question?.id, question?.version]);
  const allowed = (action: string) => job.allowedActions?.includes(action) === true;
  const terminal = ['canceled', 'completed', 'failed'].includes(job.status);
  const mutate = (name: string, work: () => Promise<FactoryJob>, notice: string) => void act(name, async () => { await work(); onNotice(notice); });
  const control = (decision: Omit<ControlIntent, 'commandId'>) => void act(decision.action, async () => {
    const pointer = await persistCommandPointer(job.ownerId, job.id, decision);
    window.dispatchEvent(new Event('factory-controls-changed'));
    try {
      const receipt = await api.submitControl(job.ownerId, job.id, { ...decision, commandId: pointer.commandId });
      onNotice(commandNotice(receipt));
      if (decision.action === 'answer') setAnswer('');
    } finally { window.dispatchEvent(new Event('factory-controls-changed')); }
  });
  const metrics = detail.snapshot?.metrics;
  const metricEntries = metrics && typeof metrics === 'object' ? Object.entries(metrics as Record<string, unknown>).filter(([key, value]) => /^(tokens|inputTokens|outputTokens|elapsedSeconds|steps|durationMs|attempts|workerSeconds)$/.test(key) && (typeof value === 'number' || typeof value === 'string')) : [];
  const evidence = <>{evidenceBefore}<section><div className="section-heading"><h3>证据与产物</h3><span className="quiet">{job.evidenceKind ?? '证据类型未提供'}</span></div>{artifacts.length ? <ul className="artifact-list">{artifacts.map(artifact => <li key={artifact.id}><ArtifactDownload jobId={job.id} artifact={artifact}/><details className="technical-detail"><summary>完整性与记录时间</summary><span>SHA-256 {artifact.sha256}</span><span>记录于 {time(artifact.createdAt)}</span></details></li>)}</ul> : <p className="list-empty">尚无产物。执行完成也不自动代表已有有效证据。</p>}</section>{evidenceAfter}</>;
  return <><div className="task-title"><div className="section-heading"><span className="quiet">任务记录</span><Badge value={job.status} label={remoteState.kind === 'pending' ? '接收端准备待核对' : remoteState.kind === 'invalid' ? '远端状态待核对' : undefined}/></div><h2>{title ?? job.input.topic}</h2><p>{source ?? (job.runtime === 'demo' ? '确定性演示 · 结果为合成数据' : '执行结果与验证状态见任务记录')}</p>{job.executionPlacement && <p className="remote-placement">执行位置：{job.executionPlacement.targetRef} · {job.executionPlacement.kind === 'remote-factory' ? '远端 Factory' : job.executionPlacement.kind}。执行结果与停止确认以接收端记录为准。</p>}<div className="task-facts"><span>创建 {time(job.createdAt)}</span><span>尝试 {job.attempt ?? '未知'}</span><span>验证 {job.validationStatus ?? '未提供'}</span></div></div><div className="task-controls">{!terminal && <button className="secondary danger" disabled={!!busy || !allowed('cancel') || job.status === 'canceling'} onClick={() => control({ action: 'cancel' })}>{job.status === 'canceling' ? '等待取消结果' : '请求取消'}</button>}<button className="secondary" disabled={!!busy || !allowed('reconcile')} onClick={() => mutate('reconcile', () => api.reconcile(job.id), '已请求核对状态，以新的任务记录为准。')}>核对执行状态</button>{!job.allowedActions && <span className="quiet">可用操作待服务端确认</span>}</div>{job.error && <ErrorMessage message={job.error}/>} {job.status === 'canceling' && <div className="state-note">服务端已接受取消请求，不代表执行已经停止。状态更新后才能确认释放结果。</div>}{job.status === 'finalizing' && <div className="state-note">执行阶段已结束，资源停止与任务收尾仍待服务端确认。此时尚未确认任务完成；请等待状态更新后再使用完成后的操作。</div>}{job.status === 'completed' && <div className="state-note">{completedNotice ?? <>执行已完成。验证状态：{job.validationStatus ?? '后端尚未提供验证结论'}。</>}</div>}{nativeAvailable && job.status === 'waiting_input' && <section className="attention-panel"><h3>需要你的回答</h3><p>{question?.text ?? job.question ?? '问题内容尚未提供。'}</p>{question ? <form onSubmit={event => { event.preventDefault(); control({ action: 'answer', requirementId: question.id, version: question.version, answer: answer.trim() }); }}><label htmlFor="job-answer">回答</label><textarea id="job-answer" value={answer} onChange={event => setAnswer(event.target.value)} rows={3} disabled={!!busy}/><button className="primary" disabled={!!busy || !allowed('answer') || !answer.trim()}>提交回答</button></form> : <p className="quiet">缺少问题标识或版本，暂不能安全提交。</p>}</section>}{nativeAvailable && recordedRecovery && <ApprovedRecoveryPanel recovery={recordedRecovery} busy={!!busy} submit={control}/>}
    {nativeAvailable && !recordedRecovery && !workflowWaiting && job.status === 'waiting_approval' && <section className="attention-panel"><h3>{inferenceRecovery ? '推理服务暂时不可用' : '等待执行审批'}</h3><p>{approval?.scope ?? job.approval?.scope ?? '审批范围尚未提供。'}</p><p className="quiet">此决定只针对本次执行，不会发布共享材料。</p>{approvalNotice}{approval ? <div className="button-row"><button className="primary" disabled={!!busy || !allowed('approve') || !approvalAllowed} onClick={() => control({ action: 'approve', requirementId: approval.id, version: approval.version, approved: true })}>{inferenceRecovery ? '恢复本次推理' : '同意本次请求'}</button><button className="secondary" disabled={!!busy || !allowed('approve')} onClick={() => control({ action: 'approve', requirementId: approval.id, version: approval.version, approved: false })}>{inferenceRecovery ? '停止本任务' : '拒绝'}</button></div> : <p className="quiet">缺少审批标识或版本，暂不能安全提交。</p>}</section>}<RemoteHandoffPanel detail={detail} busy={busy} act={act} onNotice={onNotice}/><div className="detail-sections">{terminal && evidence}<WorkflowPanel ownerId={ownerId} taskId={job.id} api={api.workflows} disabled={!!busy}/>{!awaitingReceiver && (terminal ? <details className="task-secondary-detail"><summary>任务委托与子任务记录</summary><DelegationPanel detail={detail} busy={busy} act={act} onNotice={onNotice} onSelect={onSelect} jobs={jobs} drafts={drafts} modeLabels={modeLabels}/></details> : <DelegationPanel detail={detail} busy={busy} act={act} onNotice={onNotice} onSelect={onSelect} jobs={jobs} drafts={drafts} modeLabels={modeLabels}/>)}{terminal ? <details className="task-secondary-detail"><summary>执行时间线与完整历史</summary><EventTimeline key={job.id} jobId={job.id} latest={events} replayAvailable={!awaitingReceiver}/></details> : <EventTimeline key={job.id} jobId={job.id} latest={events} replayAvailable={!awaitingReceiver}/>}{!terminal && evidence}<UsageLedgerPanel detail={detail}/><section><h3>执行指标</h3>{metricEntries.length ? <dl className="execution-metrics">{metricEntries.map(([key, value]) => <div key={key}><dt>{({ tokens: '令牌总数', inputTokens: '输入令牌', outputTokens: '输出令牌', elapsedSeconds: '耗时（秒）', steps: '执行步骤', durationMs: '耗时（毫秒）', attempts: '尝试次数', workerSeconds: '工作耗时（秒）' } as Record<string, string>)[key] ?? key}{job.runtime === 'demo' ? '（合成）' : ''}</dt><dd>{String(value)}</dd></div>)}</dl> : <p className="list-empty">后端尚未提供执行指标。</p>}</section><details className="technical-detail"><summary>任务引用</summary><span>任务 {job.id}</span><span>方案 {job.planId ?? '未提供'}</span><span>定义 {job.definitionId} v{job.definitionVersion}</span></details></div></>;
}
