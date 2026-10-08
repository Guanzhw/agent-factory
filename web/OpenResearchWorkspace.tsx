import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api.js';
import { openresearchApi, type NativeProject, type ResearchCapabilities, type ResearchProject, type ResearchSession } from './openresearchApi.js';
import type { UserConnection } from './models.js';

const message = (e: unknown) => e instanceof ApiError && e.code ? `操作未确认：${e.code}` : '暂时无法核对服务状态，请刷新读取。';
export function OpenResearchWorkspace({ ownerId, onTask, onResources, onCatalog, selectedProject, onProject }: { selectedProject?: string; onProject?: (id: string) => void; ownerId: string; onTask: (id: string) => void; onResources: () => void; onCatalog: () => void }) {
  const [cap, setCap] = useState<ResearchCapabilities>();
  const [projects, setProjects] = useState<ResearchProject[]>([]);
  const [project, setProject] = useState<ResearchProject>();
  const [sessions, setSessions] = useState<ResearchSession[]>([]);
  const [sessionsReady, setSessionsReady] = useState(false);
  const [connections, setConnections] = useState<UserConnection[]>([]);
  const [connection, setConnection] = useState('');
  const [native, setNative] = useState<NativeProject[]>([]);
  const [name, setName] = useState(''); const [goal, setGoal] = useState(''); const [preset, setPreset] = useState('');
  const [busy, setBusy] = useState(false); const lock = useRef(false); const alive = useRef(true);
  const [ready, setReady] = useState(false); const [error, setError] = useState(''); const [revision, refresh] = useState(0);
  const storageKey = `factory-or-pending:${encodeURIComponent(ownerId)}`;
  const [pending, setPending] = useState(() => { try { return localStorage.getItem(storageKey) ?? ''; } catch { return ''; } });
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    const ctrl = new AbortController(); setReady(false);
    void Promise.all([api.session(ctrl.signal), openresearchApi.capabilities(ctrl.signal), openresearchApi.projects(ctrl.signal), api.userConnections(ctrl.signal)]).then(([who, c, p, refs]) => {
      if (ctrl.signal.aborted) return;
      if (who.id !== ownerId || refs.some(r => r.ownerId !== ownerId)) throw new Error('identity');
      setCap(c); setProjects(p); setConnections(refs); setReady(true); setError('');
    }).catch(e => { if (!ctrl.signal.aborted) setError(message(e)); });
    return () => ctrl.abort();
  }, [ownerId, revision]);
  const projectId = selectedProject !== undefined ? selectedProject : project?.id;
  function selectProject(next: ResearchProject | undefined) { setProject(next); onProject?.(next?.id ?? ''); }
  useEffect(() => {
    setSessionsReady(false);
    if (!projectId) { setProject(undefined); setSessions([]); return; }
    const ctrl = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [p, s] = await Promise.all([openresearchApi.project(projectId!, ctrl.signal), openresearchApi.sessions(projectId!, ctrl.signal)]);
        if (!ctrl.signal.aborted) { setProject(p); setSessions(s); setSessionsReady(true); }
      } catch (e) { if (!ctrl.signal.aborted) { setError(message(e)); setSessionsReady(false); } }
      if (!ctrl.signal.aborted) timer = setTimeout(() => void poll(), 5000);
    }
    setSessions([]); void poll(); return () => { ctrl.abort(); clearTimeout(timer); };
  }, [projectId, revision]);
  async function read(work: () => Promise<void>) {
    if (lock.current) return; lock.current = true; setBusy(true); setError('');
    try { await work(); } catch (e) { if (alive.current) setError(message(e)); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  async function mutate(work: (request: string) => Promise<void>) {
    if (pending || lock.current || !ready) return;
    const id = crypto.randomUUID();
    // Persist before any HTTP side effect. Storage failure prevents dispatch.
    try { localStorage.setItem(storageKey, id); } catch { setError('无法保存原请求标识，未提交。请允许本地存储后重试。'); return; }
    setPending(id);
    await read(async () => {
      try {
        await work(id);
        localStorage.removeItem(storageKey); if (alive.current) { setPending(''); refresh(n => n + 1); }
      } catch (e) {
        // Only a definitive client rejection permits a new intent. Unknown replies stay frozen across reloads.
        if (e instanceof ApiError && e.status >= 400 && e.status < 500 && ![408, 409].includes(e.status)) { localStorage.removeItem(storageKey); if (alive.current) setPending(''); }
        throw e;
      }
    });
  }
  const refs = connections.filter(c => c.ownerId === ownerId && c.kind === 'orx' && c.status === 'active' && c.available && c.taskId === null && c.capabilities.includes('project:read'));
  const workload = cap?.workloads.find(p => p.id === preset);
  const disabled = busy || !ready || !!pending;
  const unresolvedSession = sessions.some(s => s.taskId === null);
  return <section className="openresearch-workspace">
    <div className="workspace-crumbs"><button className="text-button" onClick={onCatalog}>Factory 应用目录</button><span>/ OpenResearch</span>{project && <><span>/</span><button className="text-button" onClick={() => selectProject(undefined)}>项目</button><span>/ {project.name}</span></>}</div>
    <div className="page-heading"><div><p className="quiet">OPENRESEARCH</p><h1>{project?.name ?? '研究工作区'}</h1><p>从自己的项目和资源出发，查看会话、任务与研究证据。</p></div><div className="or-actions"><button className="secondary" onClick={onResources}>管理我的资源</button><button className="secondary" disabled={busy} onClick={() => refresh(n => n + 1)}>刷新工作区</button></div></div>
    {error && <p className="error-message" role="alert">{error}</p>}
    {pending && <div className="policy-note" role="status">原请求尚待核对：{pending}。当前只读取记录，不自动重新提交、不创建替代任务。<button className="secondary" disabled={busy || !ready} onClick={() => void read(async () => {
      const found = await openresearchApi.recover(pending);
      if (found.project) selectProject(found.project);
      if (found.session) { selectProject(await openresearchApi.project(found.session.projectId)); setSessions([found.session]); }
      localStorage.removeItem(storageKey); setPending(''); refresh(n => n + 1);
    })}>核对原请求</button></div>}
    {!ready && <p role="status">正在核对当前身份、项目和能力；写入暂不可用。</p>}
    {!project ? <div className="or-project-layout"><div><h2>我的项目</h2>{!projects.length && ready && <div className="empty-state"><h3>还没有关联项目</h3><p>连接可信 OpenResearch 工作区后，读取并关联现有项目。</p></div>}{projects.map(p => <button key={p.id} className="or-project-card" onClick={() => { selectProject(p); setPreset(''); setGoal(''); }}><strong>{p.name}</strong><span className="quiet">{p.kind === 'native-openresearch' ? '原生 OpenResearch 项目 · 只读关联' : '受控工作负载分组 · Factory'}</span><span>{p.description || (p.kind === 'native-openresearch' ? `原项目 ${p.upstreamProjectId}` : '会话使用已批准预设的上下文')}</span></button>)}</div>
      <div><section className="material-editor"><h2>关联现有 OpenResearch 项目</h2><p className="quiet">只读取已授权原项目；不创建仓库、工作树或触发模型预热。</p><label>我的 OpenResearch 连接<select aria-label="我的 OpenResearch 连接" value={connection} disabled={busy || !ready} onChange={e => { setConnection(e.target.value); setNative([]); }}><option value="">选择可读取项目的连接</option>{refs.map(r => <option key={r.ref} value={r.ref}>{r.ref} · {r.revision}</option>)}</select></label>{ready && !refs.length && <p className="policy-note">尚未配置可用的原生工作区连接。OpenCode 环境连接不能替代 OpenResearch 连接。</p>}<button className="secondary" disabled={busy || !ready || !refs.some(r => r.ref === connection) || !cap?.nativeProjectAttachment} onClick={() => void read(async () => setNative(await openresearchApi.native(connection)))}>读取原生项目</button>{native.map(p => <div className="or-native-row" key={p.id}><strong>{p.name}</strong><small>原项目 {p.id} · 元数据已观察</small><button className="secondary" disabled={disabled} onClick={() => void mutate(async id => { const attached = await openresearchApi.attach(connection, p, id); if (alive.current) selectProject(attached); })}>关联此项目</button></div>)}<p className="quiet">原生项目创建暂不可用：模型调用预算与仓库发布授权尚未接入。</p></section>
      <details className="technical-detail"><summary>受控工作负载分组（独立入口）</summary><p>分组只整理已有受控预设任务，不创建原生 OpenResearch 项目，也不修改预设的仓库、模型或指令。</p><form onSubmit={e => { e.preventDefault(); void mutate(async id => { const p = await openresearchApi.create(name.trim(), id); if (alive.current) { selectProject(p); setName(''); } }); }}><label>分组名称<input aria-label="分组名称" maxLength={120} value={name} onChange={e => setName(e.target.value)} disabled={disabled}/></label><button className="secondary" disabled={disabled || !name.trim()}>创建受控分组</button></form></details></div></div> : <>
      <div className="state-note"><strong>{project.kind === 'native-openresearch' ? '原生项目 · 当前只读' : '受控工作负载分组'}</strong><p>{project.kind === 'native-openresearch' ? '关联保留原项目身份。项目身份哈希不是仓库内容哈希或科学结果证明。' : '会话上下文由已批准工作负载预设提供；分组名称不会重写研究上下文。'}</p><p>资源：{Object.entries(project.connectionRefs).map(([k, v]) => `${k}: ${v}`).join(' · ') || '采用受控预设的已批准资源，不从分组虚构连接'}</p></div>
      {project.kind === 'native-openresearch' ? <section className="material-editor"><h2>原生会话尚不可执行</h2><p>尚缺原项目、受管方案、模型预算与运行身份的执行绑定。</p><p className="policy-note">{project.sessionBlocker ?? 'NATIVE_PROJECT_GOVERNED_SESSION_BINDING_REQUIRED'}</p><button disabled className="primary">原生会话不可用</button><button className="secondary" disabled={busy || !ready} onClick={() => void read(async () => setProject(await openresearchApi.refresh(project.id)))}>刷新原项目元数据</button><p className="quiet">{project.nativeProject?.verificationStatus ?? '未核实'} · {project.nativeProject?.evidenceKind ?? '缺少证据'}</p></section> : <section className="material-editor"><h2>开始受控工作负载会话</h2><p>这不是原生项目会话。继续前核对预设、目标与限额；服务端仍执行授权、审批和共享预算检查。</p><label>已批准工作负载<select aria-label="已批准工作负载" value={preset} disabled={disabled} onChange={e => setPreset(e.target.value)}><option value="">选择受控预设</option>{cap?.workloads.map(p => <option key={p.id} value={p.id} disabled={!p.ready}>{p.name} · {p.ready ? '可提交准入' : '能力不足'}</option>)}</select></label>{!cap?.workloads.length && <p className="policy-note">尚未配置已批准工作负载，没有可启动的预设。</p>}{cap?.workloads.filter(p => !p.ready).map(p => <p className="quiet" key={p.id}>{p.name}：{p.blockers.join('、')}</p>)}{workload && <dl className="plan-details">{Object.entries(workload.limits).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{String(v)}</dd></div>)}</dl>}<label>研究目标<textarea aria-label="研究目标" maxLength={2000} value={goal} disabled={disabled} onChange={e => setGoal(e.target.value)}/></label><button className="primary" disabled={disabled || !sessionsReady || unresolvedSession || !workload?.ready || goal.trim().length < 2} onClick={() => void mutate(async id => { await openresearchApi.start(project.id, preset, goal.trim(), id); })}>确认范围并提交受控会话</button></section>}
      <section className="material-editor"><h2>会话与结果</h2>{unresolvedSession && <p className="policy-note">存在未核实准入的原会话。先核对原会话，暂不提交新的受控会话。</p>}{!sessions.length && <p className="quiet">尚无已登记会话。不会用演示结果填充空记录。</p>}{sessions.map(s => <article className="or-session-row" key={s.id}><div><h3>{s.goal}</h3><p>受控工作负载 · {s.state} · {s.verificationStatus}</p><small>原会话 {s.id} · {s.contextSource}</small></div><div className="or-actions"><button className="secondary" disabled={busy} onClick={() => void read(async () => { const next = await openresearchApi.reconcile(project.id, s.id); setSessions(all => all.map(old => old.id === next.id ? next : old)); })}>核对原会话</button>{s.taskId && <button className="primary" onClick={() => onTask(s.taskId!)}>任务、证据与取消</button>}</div></article>)}<p className="quiet">取消确认与资源停止证据分别核对。未知准入只核对原请求，不重新执行。</p></section>
    </>}
  </section>;
}
