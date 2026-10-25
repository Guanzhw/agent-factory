import { useState } from 'react';
import { IconFileDescription } from '@tabler/icons-react';
import { time } from '../../../workspaceUI.js';
import { AgreementEditor } from '../AgreementEditor.js';
import { useProjectCommand } from '../useProjectCommand.js';
import type { ResearchProject } from '../types.js';

export const projectStates = { draft: '待确认约定', ready: '约定已确认', ended: '研究已结束' };
export function ProjectDetails({ project, tab, onTab, onUpdate }: { project: ResearchProject; tab: string; onTab: (tab: string) => void; onUpdate: (project: ResearchProject) => void }) {
  const [editing, setEditing] = useState(false);
  const [ending, setEnding] = useState(false);
  const [reason, setReason] = useState('');
  const [outcome, setOutcome] = useState<'not_met' | 'cancelled'>('not_met');
  const current = project.goals.find(goal => goal.version === project.currentGoalVersion);
  const command = useProjectCommand(project.ownerId, project.id, result => { onUpdate(result); setEditing(false); setEnding(false); });
  return <section className="rw-project-card" aria-label={project.title}>
    <header><h2>{project.title}</h2><span className={`rw-state ${project.state}`}>{projectStates[project.state]}</span><small>{time(project.createdAt)}</small></header>
    <p className="rw-objective"><strong>目标：</strong>{current?.agreement.objective ?? '尚未建立研究约定'}</p>
    <div className="rw-tabs" role="tablist" aria-label="项目内容">{[['overview', '概览'], ['experiments', '实验'], ['evidence', '证据']].map(([id, name]) => <button key={id} role="tab" aria-selected={tab === id} onClick={() => onTab(id)}>{name}</button>)}</div>
    {command.feedback}
    {tab !== 'overview' ? <div className="rw-empty"><IconFileDescription size={32}/><h3>{tab === 'experiments' ? '运行记录接口正在接入' : '证据记录接口正在接入'}</h3><p>当前页面尚不能读取这些记录，不能据此判断没有运行或证据。目标约定与历史可在概览查看。</p><button onClick={() => onTab('overview')}>查看研究约定</button></div> : <>
      {current && <article className="rw-agreement"><h3>研究约定 · 版本 {current.version}</h3><dl><dt>评价与达标标准</dt><dd>{current.agreement.evaluation}</dd><dt>停止与放弃条件</dt><dd>{current.agreement.stopConditions}</dd><dt>共同预算</dt><dd>最多 {current.agreement.budget.rounds} 轮 / {current.agreement.budget.toolCalls} 次工具调用</dd></dl>
        <p>{current.confirmedAt ? `已确认于 ${time(current.confirmedAt)}` : '尚未确认；保存约定不会启动实验。'}</p>
        {!current.confirmedAt && project.state !== 'ended' && <button className="rw-primary" disabled={command.disabled || editing} onClick={() => void command.run({ action: 'confirm', body: { requestId: crypto.randomUUID(), expectedVersion: project.currentGoalVersion } })}>确认当前约定</button>}
      </article>}
      {project.state !== 'ended' && <><div className="rw-actions">{current && <button disabled={command.disabled} onClick={() => setEditing(value => !value)}>{editing ? '取消修订' : '修改目标'}</button>}<button disabled={command.disabled} onClick={() => { setEnding(value => !value); setOutcome(current ? 'not_met' : 'cancelled'); }}>{ending ? '取消结束' : '结束研究'}</button></div>
        {(!current || editing) && <AgreementEditor key={`${project.currentGoalVersion}:${editing}`} initial={current?.agreement} disabled={command.disabled} onSave={agreement => void command.run({ action: 'goal', body: { requestId: crypto.randomUUID(), expectedVersion: project.currentGoalVersion, agreement: { ...agreement, ...(current?.agreement.execution ? { execution: current.agreement.execution } : {}) } } })}/>}
        {ending && <form className="rw-form" aria-label="结束研究" onSubmit={event => { event.preventDefault(); void command.run({ action: 'end', body: { requestId: crypto.randomUUID(), expectedVersion: project.currentGoalVersion, outcome, reason: reason.trim() } }); }}><h3>记录结束依据</h3><p>结束将阻断项目的新执行；在途操作及资源清理仍需核对原状态。</p><fieldset disabled={command.disabled}><label>结束结果<select value={outcome} onChange={event => setOutcome(event.target.value as typeof outcome)}>{current && <option value="not_met">未达标结束</option>}<option value="cancelled">主动取消</option></select></label><label>结束依据与剩余问题<textarea required maxLength={4000} value={reason} onChange={event => setReason(event.target.value)}/></label><button className="rw-primary" disabled={!reason.trim()}>保存结束理由</button></fieldset></form>}
      </>}
      {project.ending && <article className="rw-agreement"><h3>{project.ending.outcome === 'not_met' ? '未达标结束' : '已取消研究'}</h3><p>{project.ending.reason}</p><p>依据目标版本 {project.ending.goalVersion} · {time(project.ending.endedAt)}</p><p>资源清理尚未核对；不代表在途操作已经停止。</p></article>}
      <h3 className="rw-history-title">目标历史</h3>{project.goals.length === 0 && <p>尚无研究约定。</p>}{project.goals.map(goal => <details className="rw-history" key={goal.version}><summary>版本 {goal.version} · {goal.confirmedAt ? '已确认' : '未确认'} · {time(goal.createdAt)}</summary><dl><dt>目标</dt><dd>{goal.agreement.objective}</dd><dt>评价</dt><dd>{goal.agreement.evaluation}</dd><dt>停止条件</dt><dd>{goal.agreement.stopConditions}</dd><dt>预算</dt><dd>{goal.agreement.budget.rounds} 轮 / {goal.agreement.budget.toolCalls} 次工具调用</dd></dl>{goal.agreement.budget.tokenLimit !== null && <p>{goal.agreement.budget.tokenLimit} Token / {goal.agreement.budget.amountMicros! / 1_000_000} {goal.agreement.budget.currency}</p>}<ul>{Object.entries(goal.agreement.resourceRefs).map(([slot, ref]) => <li key={slot}>{slot}：{ref}</li>)}</ul></details>)}
    </>}
  </section>;
}
