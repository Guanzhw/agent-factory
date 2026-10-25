import { useEffect, useRef, useState } from 'react';
import './research.css';
import { ApiError } from '../../api.js';
import { time } from '../../workspaceUI.js';
import { AgreementEditor } from './AgreementEditor.js';
import { researchApi, sendProjectCommand, type ProjectCommand } from './client.js';
import type { AssistantSummary, Page, ResearchProject, ResearchProjectSummary } from './types.js';

export interface ResearchWorkspaceProps {
  ownerId: string;
  projectId?: string;
  onProject: (id: string | null) => void;
  onResources: () => void;
}
const stateNames = { draft: '待确认约定', ready: '约定已确认', ended: '研究已结束' };
const message = (error: unknown) => error instanceof Error ? error.message : '研究项目请求失败。';

function useProjectCommand(ownerId: string, projectId: string | undefined, onSuccess: (project: ResearchProject) => void) {
  const storageKey = `factory:research-command:${encodeURIComponent(ownerId)}:${projectId ? encodeURIComponent(projectId) : 'new'}`;
  const [recovery] = useState(() => {
    try {
      const raw = window.sessionStorage.getItem(storageKey);
      if (!raw) return { pending: null, error: '' };
      const saved = JSON.parse(raw) as ProjectCommand;
      const actions = projectId ? ['goal', 'confirm', 'end'] : ['create'];
      if (!saved || !actions.includes(saved.action) || typeof saved.body?.requestId !== 'string' || !saved.body.requestId) throw new Error('invalid command');
      return { pending: saved, error: '' };
    } catch { return { pending: null, error: '无法读取原研究请求；请保留本页存储并排查，暂不提交新请求。' }; }
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(recovery.error);
  const [pending, setPending] = useState<ProjectCommand | null>(recovery.pending);
  const active = useRef(false);
  const running = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  async function run(command: ProjectCommand) {
    if (running.current || recovery.error) return;
    try { window.sessionStorage.setItem(storageKey, JSON.stringify(command)); }
    catch { setError('无法保存原请求，尚未提交。请检查浏览器存储后重试。'); return; }
    running.current = true; setBusy(true); setError(''); setPending(command);
    try {
      const result = await sendProjectCommand(ownerId, projectId, command);
      window.sessionStorage.removeItem(storageKey);
      if (active.current) { setPending(null); onSuccess(result); }
    } catch (reason) {
      let uncertain = pending !== null || !(reason instanceof ApiError) || reason.status === 0 || reason.status === 408 || reason.status >= 500 || reason.code === 'INVALID_RESPONSE';
      if (!uncertain) {
        try { window.sessionStorage.removeItem(storageKey); }
        catch { uncertain = true; }
      }
      if (active.current) {
        setPending(uncertain ? command : null);
        setError(uncertain ? `操作结果尚未确认。请重试原请求，避免重复创建。${message(reason)}` : message(reason));
      }
    } finally { running.current = false; if (active.current) setBusy(false); }
  }
  return { run, disabled: busy || pending !== null || !!recovery.error, feedback: <>{error && <p role="alert">{error}</p>}{pending && <div><p>已保留尚未确认的原请求。刷新或返回本页后，可使用原请求核对结果。</p><button disabled={busy} className="secondary" onClick={() => void run(pending)}>重试原操作</button></div>}{busy && <p role="status">正在保存…</p>}</> };
}

function Overview({ ownerId, onProject, onResources }: ResearchWorkspaceProps) {
  const [page, setPage] = useState<Page<ResearchProjectSummary> | null>(null);
  const [after, setAfter] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState('');
  const [assistants, setAssistants] = useState<AssistantSummary[]>([]);
  const [assistantAfter, setAssistantAfter] = useState('');
  const [assistantNext, setAssistantNext] = useState<string | null>(null);
  const [assistantError, setAssistantError] = useState('');
  const [title, setTitle] = useState('');
  const [assistantId, setAssistantId] = useState('');
  const command = useProjectCommand(ownerId, undefined, project => onProject(project.id));
  useEffect(() => {
    const controller = new AbortController(); setPage(null); setError('');
    void researchApi.projects(ownerId, after, controller.signal).then(result => { if (!controller.signal.aborted) setPage(result); }).catch(reason => { if (!controller.signal.aborted) setError(message(reason)); });
    return () => controller.abort();
  }, [ownerId, after, refresh]);
  useEffect(() => {
    const controller = new AbortController(); setAssistantError('');
    void researchApi.assistants(ownerId, assistantAfter, controller.signal).then(result => {
      if (!controller.signal.aborted) {
        const own = result.items.filter(item => item.ownerId === ownerId && item.enabled);
        setAssistants(previous => assistantAfter ? [...previous, ...own] : own); setAssistantNext(result.nextCursor);
      }
    }).catch(reason => { if (!controller.signal.aborted) setAssistantError(message(reason)); });
    return () => controller.abort();
  }, [ownerId, assistantAfter, refresh]);
  return <section aria-labelledby="research-title"><div className="page-heading"><div><h1 id="research-title">我的研究助手</h1><p>在独立的项目空间中保留研究目标、约定和历史。</p></div><button className="secondary" onClick={onResources}>配置模型与资源</button></div>
    <p>研究执行尚未接入。现在可以建立项目与确认研究约定；确认不会启动实验。</p>
    {command.feedback}
    <form className="material-editor" aria-label="新建研究项目" onSubmit={event => { event.preventDefault(); const body = { requestId: crypto.randomUUID(), title: title.trim(), assistantId: assistantId || null }; void command.run({ action: 'create', body }); }}>
      <h2>建立研究项目</h2><fieldset disabled={command.disabled}><label>项目名称<input required maxLength={120} value={title} onChange={event => setTitle(event.target.value)}/></label>
        <label>关联我的助手<select value={assistantId} onChange={event => setAssistantId(event.target.value)}><option value="">暂不关联</option>{assistants.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        {assistantNext && <button type="button" onClick={() => setAssistantAfter(assistantNext)}>加载更多助手</button>}{assistantError && <p role="alert">助手列表读取失败：{assistantError}</p>}
        <button className="primary" type="submit">创建项目</button>
      </fieldset>
    </form>
    <div className="page-heading"><h2>项目概览</h2><button className="secondary" onClick={() => { setAssistantAfter(''); setRefresh(value => value + 1); }}>刷新项目</button></div>
    {error && <p role="alert">{error}</p>}{!page && !error && <p role="status">正在读取项目…</p>}
    {page && !page.items.length && <div className="empty-state"><h3>{after ? '本页没有项目' : '还没有研究项目'}</h3><p>先建立项目并写下研究约定。模型和连接可在资源中心配置。</p><button className="secondary" onClick={onResources}>打开资源中心</button></div>}
    {page?.items.map(project => <article className="research-card" key={project.id}><h3><button className="text-button" onClick={() => onProject(project.id)}>{project.title}</button></h3><p>{stateNames[project.state]} · 目标版本 {project.currentGoalVersion} · {time(project.createdAt)}</p></article>)}
    <div className="material-actions">{after && <button onClick={() => setAfter('')}>返回第一页</button>}{page?.nextCursor && <button onClick={() => setAfter(page.nextCursor!)}>下一页项目</button>}</div>
  </section>;
}

function ProjectDetail({ ownerId, projectId, onProject, onResources }: ResearchWorkspaceProps & { projectId: string }) {
  const [project, setProject] = useState<ResearchProject | null>(null);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [editing, setEditing] = useState(false);
  const [ending, setEnding] = useState(false);
  const [outcome, setOutcome] = useState<'not_met' | 'cancelled'>('not_met');
  const [reason, setReason] = useState('');
  const command = useProjectCommand(ownerId, projectId, result => { setProject(result); setEditing(false); setEnding(false); });
  useEffect(() => {
    const controller = new AbortController(); setProject(null); setError('');
    void researchApi.project(ownerId, projectId, controller.signal).then(result => { if (!controller.signal.aborted) setProject(result); }).catch(reason => { if (!controller.signal.aborted) setError(message(reason)); });
    return () => controller.abort();
  }, [ownerId, projectId, refresh]);
  const current = project?.goals.find(goal => goal.version === project.currentGoalVersion);
  return <section aria-labelledby="project-title"><div className="material-actions"><button className="secondary" onClick={() => onProject(null)}>返回项目概览</button><button className="secondary" onClick={onResources}>配置模型与资源</button><button className="secondary" disabled={command.disabled} onClick={() => { setEditing(false); setRefresh(value => value + 1); }}>刷新项目详情</button></div>
    {error && <p role="alert">{error}</p>}{!project && !error && <p role="status">正在读取项目…</p>}{command.feedback}
    {project && <><div className="page-heading"><div><h1 id="project-title">{project.title}</h1><p>{stateNames[project.state]} · {project.assistantId ? `已关联助手：${project.assistantId}` : '尚未关联助手'}</p></div></div>
      {!project.execution.available && <p role="status">研究执行尚未接入；确认约定不会启动实验。</p>}
      {current && <article className="research-card"><h2>当前目标 · 版本 {current.version}</h2><p>{current.agreement.objective}</p><h3>评价与达标标准</h3><p>{current.agreement.evaluation}</p><h3>停止与放弃条件</h3><p>{current.agreement.stopConditions}</p><p>最多 {current.agreement.budget.rounds} 轮实验，{current.agreement.budget.toolCalls} 次工具调用</p>
        {current.confirmedAt ? <p>已确认：{time(current.confirmedAt)}</p> : <p>尚未确认</p>}
        {!current.confirmedAt && project.state !== 'ended' && <button className="primary" disabled={command.disabled || editing} onClick={() => { const body = { requestId: crypto.randomUUID(), expectedVersion: project.currentGoalVersion }; void command.run({ action: 'confirm', body }); }}>确认当前约定</button>}
      </article>}
      {project.state !== 'ended' && <><div className="material-actions">{current && <button className="secondary" disabled={command.disabled} onClick={() => setEditing(value => !value)}>{editing ? '取消修订' : '修改目标'}</button>}<button className="secondary" disabled={command.disabled} onClick={() => { setEnding(value => !value); setOutcome(current ? 'not_met' : 'cancelled'); }}>结束研究</button></div>
        {(!current || editing) && <AgreementEditor key={`${project.currentGoalVersion}:${editing}`} initial={current?.agreement} disabled={command.disabled} onSave={agreement => { const body = { requestId: crypto.randomUUID(), expectedVersion: project.currentGoalVersion, agreement }; void command.run({ action: 'goal', body }); }}/>}
        {ending && <form className="material-editor" aria-label="结束研究" onSubmit={event => { event.preventDefault(); const body = { requestId: crypto.randomUUID(), expectedVersion: project.currentGoalVersion, outcome, reason: reason.trim() }; void command.run({ action: 'end', body }); }}><h2>记录研究结束</h2><p>这里只记录项目结束理由，不代表运行已停止或资源已释放。</p><fieldset disabled={command.disabled}><label>结束结果<select value={outcome} onChange={event => setOutcome(event.target.value as typeof outcome)}>{current && <option value="not_met">未达标结束</option>}<option value="cancelled">主动取消研究</option></select></label><label>结束依据与剩余问题<textarea required maxLength={4000} value={reason} onChange={event => setReason(event.target.value)}/></label><button className="primary" type="submit">保存结束理由</button></fieldset></form>}
      </>}
      {project.ending && <article className="research-card"><h2>{project.ending.outcome === 'not_met' ? '未达标结束' : '已取消研究'}</h2><p>{project.ending.reason}</p><p>依据目标版本 {project.ending.goalVersion} · {time(project.ending.endedAt)}</p><p>资源清理状态：尚未核对。项目结束不代表资源已释放。</p></article>}
      <h2>目标历史</h2>{!project.goals.length && <p>尚无研究约定。</p>}{project.goals.map(goal => <details className="research-card" key={goal.version}><summary>目标版本 {goal.version} · {goal.confirmedAt ? '已确认' : '未确认'} · {time(goal.createdAt)}</summary><p>目标：{goal.agreement.objective}</p><p>评价：{goal.agreement.evaluation}</p><p>停止：{goal.agreement.stopConditions}</p><p>预算：{goal.agreement.budget.rounds} 轮 / {goal.agreement.budget.toolCalls} 次工具调用</p>{goal.agreement.budget.tokenLimit !== null && <p>模型上限：{goal.agreement.budget.tokenLimit} Token / {goal.agreement.budget.amountMicros! / 1_000_000} {goal.agreement.budget.currency}</p>}<ul>{Object.entries(goal.agreement.resourceRefs).map(([slot, ref]) => <li key={slot}>{slot}：{ref}</li>)}</ul></details>)}
    </>}
  </section>;
}

export function ResearchWorkspace(props: ResearchWorkspaceProps) {
  return props.projectId ? <ProjectDetail key={`${props.ownerId}:${props.projectId}`} {...props} projectId={props.projectId}/> : <Overview key={props.ownerId} {...props}/>;
}
