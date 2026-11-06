import { time } from '../../../workspaceUI.js';
import { RunRecords } from './RunRecords.js';
import type { ResearchProject } from '../types.js';

export const projectStates = { draft: '历史草稿', ready: '约定已确认', ended: '研究已结束' };
type Props = { project: ResearchProject; tab: string; onTab: (tab: string) => void; onTask: (id: string) => void };
export function ProjectDetails({ project, tab, onTab, onTask }: Props) {
  const goal = project.goals.find(item => item.version === project.currentGoalVersion);
  const current = !project.sourceUnavailable && goal && !goal.sourceUnavailable ? goal : undefined;
  return <section className="rw-project-card" aria-label={project.title}>
    <header><h2>{project.title}</h2><span className={`rw-state ${project.state}`}>{projectStates[project.state]}</span><small>{time(project.createdAt)}</small></header>
    <details><summary>项目标识</summary><code>{project.id}</code></details>
    <p>原项目记录与证据。新工作请回到助手，说明目标及需要引用的项目。</p>
    {project.sourceUnavailable ? <p role="status">来源不可用；目标、分析和成果正文已隐藏。</p> : <p className="rw-objective"><strong>目标：</strong>{current?.agreement.objective ?? '尚无已保存的研究约定'}</p>}
    <div className="rw-tabs" role="tablist" aria-label="项目历史">{[['overview', '目标历史'], ['experiments', '执行记录'], ['evidence', '证据']].map(([id, name]) => <button key={id} role="tab" aria-selected={tab === id} onClick={() => onTab(id)}>{name}</button>)}</div>
    {tab !== 'overview' ? <RunRecords ownerId={project.ownerId} projectId={project.id} evidence={!project.sourceUnavailable && tab === 'evidence'} onTask={onTask}/> : <>
      {project.ending && !project.sourceUnavailable && !('state' in project.ending) && <article className="rw-agreement"><h3>原结束记录</h3><p>{project.ending.reason}</p><p>目标版本 {project.ending.goalVersion} · {time(project.ending.endedAt)}</p><p>{project.ending.resourceCleanup === 'stopped' ? '原记录报告资源已停止。' : '资源是否停止尚未核对。'}</p></article>}
      {project.sourceUnavailable && project.ending && <p>原终态记录存在，不代表资源已确认停止。</p>}
      <h3>目标历史</h3>{project.goals.length === 0 && <p>暂无研究约定。</p>}{project.goals.map(item => project.sourceUnavailable || item.sourceUnavailable ? <p key={item.version}>版本 {item.version} · 来源不可用</p> : <details className="rw-history" key={item.version}><summary>版本 {item.version} · {item.confirmedAt ? '已确认' : '未确认'} · {time(item.createdAt)}</summary><dl><dt>目标</dt><dd>{item.agreement.objective}</dd><dt>评价</dt><dd>{item.agreement.evaluation}</dd><dt>停止条件</dt><dd>{item.agreement.stopConditions}</dd><dt>预算</dt><dd>{item.agreement.budget.rounds} 轮 / {item.agreement.budget.toolCalls} 次工具调用</dd></dl><details><summary>原约定详情</summary><pre>{JSON.stringify(item.agreement, null, 2)}</pre></details></details>)}
    </>}
  </section>;
}
