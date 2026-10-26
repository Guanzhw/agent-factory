import { useState } from 'react';
import { time } from '../../../workspaceUI.js';
import { AgreementEditor } from '../AgreementEditor.js';
import { SetupPanel } from './SetupPanel.js';
import type { ExecutionSelection } from './setupClient.js';
import { ExecutionEditor } from './ExecutionEditor.js';
import { CreateDelivery } from './EvidenceViews.js';
import { RunRecords } from './RunRecords.js';
import { useProjectCommand } from '../useProjectCommand.js';
import type { ResearchProject } from '../types.js';

export const projectStates = { draft: '待确认约定', ready: '约定已确认', ended: '研究已结束' };
export function ProjectDetails({ onDelivery, project, tab, onTab, onUpdate, onTask, onApplications, onResources, setupId, onSetup, onMaterials }: { onDelivery: (id: string) => void; project: ResearchProject; tab: string; onTab: (tab: string) => void; onUpdate: (project: ResearchProject) => void; onTask: (id: string) => void; onApplications: () => void; onResources: () => void; setupId?: string; onSetup: (id: string) => void; onMaterials: () => void }) {
  const [editing, setEditing] = useState(false);
  const [configuring, setConfiguring] = useState(!!setupId);
  const [preparing, setPreparing] = useState(!!setupId);
  const [selection, setSelection] = useState<ExecutionSelection>();
  const [ending, setEnding] = useState(false);
  const [reason, setReason] = useState('');
  const [outcome, setOutcome] = useState<'not_met' | 'cancelled'>('not_met');
  const goal = project.goals.find(goal => goal.version === project.currentGoalVersion);
  const current = goal && !goal.sourceUnavailable ? goal : undefined;
  const command = useProjectCommand(project.ownerId, project.id, result => { onUpdate(result); setEditing(false); setEnding(false); setConfiguring(false); });
  if (project.sourceUnavailable) return <section className="rw-project-card" aria-label={project.title}><h2>{project.title}</h2><p role="status">来源不可用，目标、分析及派生成果已隐藏。</p><p className="rw-id">项目：{project.id} · 目标版本 {project.currentGoalVersion}</p>{project.ending && <p>原终态记录存在；不代表资源已确认停止。</p>}{command.feedback}{project.state !== 'ended' && <button disabled={command.disabled} onClick={() => void command.run({ action: 'end', body: { requestId: crypto.randomUUID(), expectedVersion: project.currentGoalVersion, outcome: 'cancelled', reason: '来源不可用，成员明确请求取消原研究' } })}>取消原研究</button>}<h3>目标历史</h3>{project.goals.map(goal => <p key={goal.version}>版本 {goal.version} · {goal.confirmedAt ? '已确认' : '未确认'} · 正文不可用</p>)}<RunRecords ownerId={project.ownerId} projectId={project.id} evidence={false} onTask={onTask}/></section>;
  return <section className="rw-project-card" aria-label={project.title}>
    <header><h2>{project.title}</h2><span className={`rw-state ${project.state}`}>{projectStates[project.state]}</span><small>{time(project.createdAt)}</small></header>
    <p className="rw-objective"><strong>目标：</strong>{current?.agreement.objective ?? '尚未建立研究约定'}</p>
    <div className="rw-tabs" role="tablist" aria-label="项目内容">{[['overview', '概览'], ['experiments', '实验'], ['evidence', '证据'], ['delivery', '成果']].map(([id, name]) => <button key={id} role="tab" aria-selected={tab === id} onClick={() => onTab(id)}>{name}</button>)}</div>
    {command.feedback}
    {tab === 'delivery' ? <CreateDelivery key={`${project.ownerId}:${project.id}`} ownerId={project.ownerId} projectId={project.id} version={project.currentGoalVersion} onCreated={onDelivery}/> : tab !== 'overview' ? <RunRecords ownerId={project.ownerId} projectId={project.id} evidence={tab === 'evidence'} onTask={onTask}/> : <>
      {current && <article className="rw-agreement"><h3>研究约定 · 版本 {current.version}</h3><dl><dt>评价与达标标准</dt><dd>{current.agreement.evaluation}</dd><dt>停止与放弃条件</dt><dd>{current.agreement.stopConditions}</dd><dt>共同预算</dt><dd>最多 {current.agreement.budget.rounds} 轮 / {current.agreement.budget.toolCalls} 次工具调用</dd></dl>
        <p>{current.confirmedAt ? `已确认于 ${time(current.confirmedAt)}` : '尚未确认；保存约定不会启动实验。'}</p>
        {!current.confirmedAt && project.state !== 'ended' && <button className="rw-primary" disabled={command.disabled || editing || configuring} onClick={() => void command.run({ action: 'confirm', body: { requestId: crypto.randomUUID(), expectedVersion: project.currentGoalVersion } })}>确认当前约定</button>}
      </article>}
      {project.state !== 'ended' && <>
        {project.execution.available && current?.confirmedAt && <div className="rw-actions"><button className="rw-primary" disabled={command.disabled || editing || configuring || ending} onClick={() => void command.run({ action: 'start', body: { requestId: crypto.randomUUID(), expectedVersion: project.currentGoalVersion } })}>按当前约定启动或续接研究</button><p>将使用已确认配置与预算；准入不代表执行完成。</p></div>}
        {current && <div className="rw-actions"><button disabled={command.disabled || editing || ending} onClick={() => setConfiguring(value => !value)}>{configuring ? '取消配置' : '配置研究执行'}</button></div>}
        {configuring && current && <><div className="rw-actions"><button onClick={() => setPreparing(value => !value)}>{preparing ? '选择已有发布版本' : '准备新的研究执行配置'}</button></div>{preparing ? <SetupPanel key={`${project.ownerId}:${setupId ?? 'new'}`} ownerId={project.ownerId} setupId={setupId} onSetup={onSetup} onResources={onResources} onMaterials={onMaterials} onPublished={value => { setSelection(value); setPreparing(false); }}/> : <ExecutionEditor key={`${project.currentGoalVersion}:${selection?.applicationRef.sha256 ?? ''}`} ownerId={project.ownerId} agreement={current.agreement} selection={selection} disabled={command.disabled} onApplications={onApplications} onResources={onResources} onSave={agreement => void command.run({ action: 'goal', body: { requestId: crypto.randomUUID(), expectedVersion: project.currentGoalVersion, agreement } })}/>}</>}

        {!project.execution.available && <p className="rw-muted">当前不能开始新运行：{project.execution.reason === 'RESEARCH_ORIGINAL_ATTEMPT_REQUIRED' ? '已有原运行，请在实验页核对其状态。' : project.execution.reason === 'RESEARCH_NATIVE_COMPONENT_REQUIRED' ? '请选择兼容当前研究组件的执行配置；可从原任务记录核对与清理运行。' : project.execution.reason === 'RESEARCH_EXECUTION_NOT_INSTALLED' ? '当前未安装研究执行组件；可从原任务记录核对与清理运行。' : project.execution.reason === 'RESEARCH_EXECUTION_CONFIGURATION_REQUIRED' ? '尚未保存执行配置。' : project.execution.reason === 'RESEARCH_CONFIRMED_GOAL_REQUIRED' ? '请先确认当前研究约定。' : project.execution.reason}</p>}
<div className="rw-actions">{current && <button disabled={command.disabled || configuring || ending} onClick={() => setEditing(value => !value)}>{editing ? '取消修订' : '修改目标'}</button>}<button disabled={command.disabled || editing || configuring} onClick={() => { setEnding(value => !value); setOutcome(current ? 'not_met' : 'cancelled'); }}>{ending ? '取消结束' : '结束研究'}</button></div>
        {(!current || editing) && <AgreementEditor ownerId={project.ownerId} onMaterials={onMaterials} key={`${project.currentGoalVersion}:${editing}`} initial={current?.agreement} disabled={command.disabled} onSave={agreement => void command.run({ action: 'goal', body: { requestId: crypto.randomUUID(), expectedVersion: project.currentGoalVersion, agreement: { ...agreement, ...(current?.agreement.execution ? { execution: current.agreement.execution } : {}) } } })}/>}
        {ending && <form className="rw-form" aria-label="结束研究" onSubmit={event => { event.preventDefault(); void command.run({ action: 'end', body: { requestId: crypto.randomUUID(), expectedVersion: project.currentGoalVersion, outcome, reason: reason.trim() } }); }}><h3>记录结束依据</h3><p>结束将阻断项目的新执行；在途操作及资源清理仍需核对原状态。</p><fieldset disabled={command.disabled}><label>结束结果<select value={outcome} onChange={event => setOutcome(event.target.value as typeof outcome)}>{current && <option value="not_met">未达标结束</option>}<option value="cancelled">主动取消</option></select></label><label>结束依据与剩余问题<textarea required maxLength={4000} value={reason} onChange={event => setReason(event.target.value)}/></label><button className="rw-primary" disabled={!reason.trim()}>保存结束理由</button></fieldset></form>}
      </>}
      {project.ending && !('state' in project.ending) && <article className="rw-agreement"><h3>{project.ending.outcome === 'met' ? '助手判断达标 · 尚需验证' : project.ending.outcome === 'not_met' ? '未达标结束' : '已取消研究'}</h3><p>{project.ending.reason}</p><p>依据目标版本 {project.ending.goalVersion} · {time(project.ending.endedAt)}</p><p>{project.ending.resourceCleanup === 'stopped' ? '后端已记录原运行停止；科学结论仍需独立核对。' : '资源清理尚未核对；不代表在途操作已经停止。'}</p></article>}
      <p>修订目标保留原执行与预算；保存、确认或取消接纳都不等于原运行已停止。</p><h3 className="rw-history-title">目标历史</h3>{project.goals.length === 0 && <p>尚无研究约定。</p>}{project.goals.map(goal => goal.sourceUnavailable ? <p key={goal.version}>版本 {goal.version} · 来源不可用</p> : <details className="rw-history" key={goal.version}><summary>版本 {goal.version} · {goal.confirmedAt ? '已确认' : '未确认'} · {time(goal.createdAt)}</summary><dl><dt>目标</dt><dd>{goal.agreement.objective}</dd><dt>评价</dt><dd>{goal.agreement.evaluation}</dd><dt>停止条件</dt><dd>{goal.agreement.stopConditions}</dd><dt>预算</dt><dd>{goal.agreement.budget.rounds} 轮 / {goal.agreement.budget.toolCalls} 次工具调用</dd></dl>{goal.agreement.budget.tokenLimit !== null && <p>{goal.agreement.budget.tokenLimit} Token / {goal.agreement.budget.amountMicros! / 1_000_000} {goal.agreement.budget.currency}</p>}<p>精选证据：{goal.agreement.evidence ? `${goal.agreement.evidence.toolMaterial.id} v${goal.agreement.evidence.toolMaterial.version} · ${Object.entries(goal.agreement.evidence.fields).map(([role, field]) => `${role}=${field}`).join("、")}` : "未配置"}</p><ul>{Object.entries(goal.agreement.resourceRefs).map(([slot, ref]) => <li key={slot}>{slot}：{ref}</li>)}</ul></details>)}
    </>}
  </section>;
}
