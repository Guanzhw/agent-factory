import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api.js';
import { PlanReviewGate } from './PlanReviews.js';
import { ORX_PERSONAL_PROVIDER } from './personalAgentApi.js';
import { personalRemoteApi, definitivelyRejected } from './personalRemoteApi.js';
import { personalOrxProjectApi, checkOrxProjectPrepared, checkOrxProjectReceipt, type OrxProjectInput, type OrxProjectReceipt } from './personalOrxProjectApi.js';
import type { Plan, UserConnection } from './models.js';

type Pending = { requestId: string; planId?: string; startAttempt?: boolean };
type Props = { ownerId: string; onTask?: (id: string) => void; onConnected: (ref: string) => void; initialConnectionRef?: string; researchSetup?: boolean; refreshRevision?: number };
export function PersonalOrxProjects(props: Props) { return <Projects key={props.ownerId} {...props} />; }
function Projects({ ownerId, onTask, onConnected, initialConnectionRef, researchSetup = false, refreshRevision = 0 }: Props) {
  const storage = `factory-orx-project-create:${encodeURIComponent(ownerId)}`;
  const [pending, setPending] = useState<Pending | null>(() => { try { const value = JSON.parse(localStorage.getItem(storage) ?? 'null'); return value && /^[a-zA-Z0-9_.:-]{8,100}$/.test(value.requestId) ? { requestId: value.requestId, ...(value.planId ? { planId: value.planId } : {}), ...(value.startAttempt === true ? { startAttempt: true } : {}) } : null; } catch { return null; } });
  const [connections, setConnections] = useState<UserConnection[]>([]); const [selected, setSelected] = useState('');
  const [connectionNames, setConnectionNames] = useState<Record<string, string>>({});
  const [createOpen, setCreateOpen] = useState(false); const [taskId, setTaskId] = useState('');
  const [connectedProject, setConnectedProject] = useState<OrxProjectReceipt['result']>(null);
  const [ready, setReady] = useState(false); const [busy, setBusy] = useState(''); const [notice, setNotice] = useState('');
  const [name, setName] = useState(researchSetup ? '我的研究' : ''); const [remotePath, setPath] = useState(''); const [source, setSource] = useState<OrxProjectInput['source']>('empty');
  const [repo, setRepo] = useState(''); const [paper, setPaper] = useState('');
  const [plan, setPlan] = useState<Plan>(); const [receipt, setReceipt] = useState<OrxProjectReceipt>();
  const [consent, setConsent] = useState(false); const [allowed, setAllowed] = useState(false);
  const [harness, setHarness] = useState(''); const [model, setModel] = useState('');
  const lock = useRef(false); const live = useRef(true);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  useEffect(() => {
    const ctrl = new AbortController(); setReady(false);
    void Promise.all([api.session(ctrl.signal), api.userConnections(ctrl.signal), personalRemoteApi.list(ctrl.signal)]).then(([who, refs, remotes]) => {
      if (ctrl.signal.aborted) return;
      if (who.id !== ownerId || refs.some(r => r.ownerId !== ownerId)) throw new Error('owner');
      const personal = new Set(remotes.filter(r => r.providerId === ORX_PERSONAL_PROVIDER).map(r => r.registrationRef));
      setConnectionNames(Object.fromEntries(refs.map(ref => { const remote = remotes.find(r => r.registrationRef === ref.registrationRef && r.providerId === ORX_PERSONAL_PROVIDER); return [ref.ref, remote ? `${remote.origin} · 创建新项目 · ${ref.ref.slice(0, 8)}` : `创建连接 ${ref.ref}`]; })));
      const eligible = refs.filter(r => personal.has(r.registrationRef) && r.available && r.status === 'active' && r.taskId === null && r.kind === 'orx' && r.capabilities.includes('project:create'));
      setConnections(eligible); setSelected(old => eligible.some(c => c.ref === old) ? old : ''); setReady(true);
    }).catch(() => { if (!ctrl.signal.aborted) { setConnections([]); setSelected(''); setNotice('项目创建连接暂不可用。请先在资源中明确启用创建、验证并绑定。'); } });
    return () => ctrl.abort();
  }, [ownerId, initialConnectionRef, refreshRevision]);
  useEffect(() => {
    if (initialConnectionRef && connections.some(c => c.ref === initialConnectionRef)) { setSelected(initialConnectionRef); setCreateOpen(true); }
  }, [initialConnectionRef, connections]);
  function remember(next: Pending | null) { if (next) localStorage.setItem(storage, JSON.stringify(next)); else localStorage.removeItem(storage); setPending(next); }
  async function act(label: string, work: () => Promise<void>) {
    if (lock.current) return; lock.current = true; setBusy(label);
    try { const who = await api.session(); if (!live.current || who.id !== ownerId) return; await work(); }
    catch { if (live.current) setNotice('结果尚未核实。保留原请求，只读核对；不会重发项目创建请求。'); }
    finally { lock.current = false; if (live.current) setBusy(''); }
  }
  async function prepare() {
    if (pending || !ready || !selected || !name.trim() || !remotePath.trim()) return;
    await act('prepare', async () => {
      const requestId = crypto.randomUUID(); remember({ requestId });
      const project: OrxProjectInput = { name: name.trim(), path: remotePath.trim(), source, ...(source === 'clone' ? { cloneUrl: repo.trim() } : {}), ...(source === 'paper' ? { paperId: paper.trim() } : {}) };
      try {
        const value = checkOrxProjectPrepared(await personalOrxProjectApi.prepare({ requestId, connectionRef: selected, project }), requestId, ownerId);
        if (!live.current) return;
        remember({ requestId, planId: value.plan.id }); setPlan(value.plan); setReceipt(value.receipt); setCreateOpen(false); setConnectedProject(null); setTaskId(''); setConsent(false); setAllowed(false); setNotice('创建方案已固定。预览没有创建项目、clone 或调用模型。');
      } catch (e) {
        if (live.current && e instanceof ApiError && definitivelyRejected(e.status)) { remember(null); setNotice('创建预览已明确拒绝，请检查输入与当前绑定。'); return; }
        throw e;
      }
    });
  }
  async function start() {
    if (!pending || pending.startAttempt || !plan || !receipt || !consent || !allowed || !['awaiting', 'approved'].includes(receipt.consentState)) return;
    await act('start', async () => {
      remember({ ...pending, startAttempt: true }); setConsent(false); setAllowed(false);
      const job = await personalOrxProjectApi.submit(pending.requestId, receipt.preview.previewHash, plan.id);
      if (!live.current) return;
      if (job.ownerId !== ownerId) throw new Error('owner');
      setTaskId(job.id); setNotice('原生创建任务已受理，正在只读核对结果。确认项目后可在此继续关联会话，也可查看任务进度。');
    });
  }
  async function cancel() {
    if (!pending || !receipt || pending.startAttempt) return;
    await act('cancel', async () => {
      const value = checkOrxProjectReceipt(await personalOrxProjectApi.decide(pending.requestId, receipt.preview.previewHash, false), pending.requestId, ownerId, pending.planId);
      if (!live.current) return;
      if (value.consentState !== 'cancelled') throw new Error('decision');
      remember(null); setPlan(undefined); setReceipt(undefined); setConsent(false); setAllowed(false); setNotice('已取消此创建批准，未提交项目创建。');
    });
  }
  async function recover() {
    if (!pending) return;
    await act('recover', async () => {
      const value = await personalOrxProjectApi.recover(pending.requestId); if (!live.current) return;
      const result = checkOrxProjectPrepared({ plan: value.plan, authorization: value.authorization, receipt: value.receipt! }, pending.requestId, ownerId);
      if (pending.planId && value.plan.id !== pending.planId || value.job && value.job.ownerId !== ownerId) throw new Error('scope');
      setPlan(result.plan); setReceipt(result.receipt); if (value.job) setTaskId(value.job.id); setConsent(false); setAllowed(false);
      if (result.receipt.consentState === 'cancelled') { remember(null); setNotice('原取消已核实，未重放创建。'); }
      else { remember({ ...pending, planId: result.plan.id, ...(value.job ? { startAttempt: true } : {}) }); setNotice(result.receipt.state === 'ack_unknown' ? '原创建确认 UNKNOWN；候选项目仅供远端人工核对，不能证明属于此请求。禁止重发。' : result.receipt.state === 'acknowledged' ? '已取得原项目 ID。下一步明确选择会话 harness 与模型，关联后即可选择会话并提交研究目标。' : pending.startAttempt ? '尚未找到原任务不代表未提交，继续核对，不重发。' : '原预览已找到，请核对创建副作用后确认提交。'); }
    });
  }
  // Observation only: refreshing a submitted request never calls decide/start.
  useEffect(() => {
    if (!ready || !pending?.startAttempt || receipt?.state === 'acknowledged' || receipt?.state === 'ack_unknown' || receipt?.consentState === 'cancelled') return;
    const timer = setInterval(() => { if (!lock.current) void recover(); }, 2500);
    return () => clearInterval(timer);
  }, [ready, pending?.requestId, pending?.startAttempt, receipt?.state, receipt?.consentState]);
  async function reconcile() {
    if (!pending || receipt?.state !== 'ack_unknown') return;
    await act('reconcile', async () => { const value = checkOrxProjectReceipt(await personalOrxProjectApi.reconcile(pending.requestId), pending.requestId, ownerId, pending.planId); if (live.current) setReceipt(value); });
  }
  async function connect() {
    if (!pending || receipt?.state !== 'acknowledged' || !harness || !model.trim()) return;
    await act('connect', async () => {
      const connection = await personalOrxProjectApi.connect(pending.requestId, harness, model.trim()); if (!live.current) return;
      if (connection.ownerId !== ownerId) throw new Error('owner');
      setConnectedProject(receipt.result); remember(null); setPlan(undefined); setReceipt(undefined); setConsent(false); setAllowed(false); onConnected(connection.ref);
      setNotice('已绑定新项目。请在下方选择或创建原生会话，然后提交研究目标并在原会话查看结果。');
    });
  }
  const disabled = !!busy || !!pending || !ready;
  return <section aria-label="新建原生 OpenResearch 项目"><h2>{researchSetup ? '设置我的研究项目' : '新建原生 OpenResearch 项目'}</h2>
    <p>使用明确启用的项目创建连接。创建先预览，再确认一次固定副作用；现有项目连接不会自动扩权。</p>
    {connectedProject && <div className="success-message" role="status"><strong>已关联项目：{connectedProject.name}</strong><p>{connectedProject.path} · 原生 ID {connectedProject.nativeProjectId}</p><p>项目与模型选择已保存。回到研究目标，点击开始才会创建会话并发送目标；模型可用性由服务执行确认。</p></div>}
    <details open={createOpen} onToggle={e => setCreateOpen(e.currentTarget.open)} className="project-create-form"><summary>填写新项目创建输入</summary>
    <label>项目创建资源<select aria-label="项目创建资源" disabled={disabled} value={selected} onChange={e => setSelected(e.target.value)}><option value="">选择已验证、绑定的创建资源</option>{connections.map(c => <option key={c.ref} value={c.ref}>{connectionNames[c.ref] ?? c.ref}</option>)}</select></label>
    {ready && !connections.length && <p>请在资源管理中选择 OpenResearch，启用“用于创建新项目”后验证、绑定。</p>}
    <label>项目名称<input aria-label="项目名称" maxLength={120} disabled={disabled} value={name} onChange={e => setName(e.target.value)} /></label>
    <label>{researchSetup ? '项目保存位置（服务上的文件夹）' : '远端项目绝对路径'}<input aria-label="远端项目绝对路径" maxLength={512} disabled={disabled} value={remotePath} onChange={e => setPath(e.target.value)} /></label>
    <p className="quiet">填写你授权远端服务操作的绝对路径，例如 /workspace/my-project；这不是当前浏览器或 Factory 主机上的路径。</p>
    <label>项目来源<select aria-label="项目来源" disabled={disabled} value={source} onChange={e => setSource(e.target.value as OrxProjectInput['source'])}><option value="empty">新建空目录</option><option value="existing">已有远端目录</option><option value="clone">公开 GitHub 仓库</option><option value="paper">arXiv 论文</option></select></label>
    {source === 'clone' && <label>公开仓库 HTTPS URL<input aria-label="公开仓库 HTTPS URL" disabled={disabled} value={repo} onChange={e => setRepo(e.target.value)} /></label>}
    {source === 'paper' && <label>arXiv 论文 ID<input aria-label="arXiv 论文 ID" disabled={disabled} value={paper} onChange={e => setPaper(e.target.value)} /></label>}
    <button className="primary" disabled={disabled || !selected || !name.trim() || !remotePath.trim()} onClick={() => void prepare()}>预览项目创建</button></details>
    {notice && <p role="status">{notice}</p>}
    {pending && <p className="project-request">原请求 {pending.requestId}<button disabled={!!busy} onClick={() => void recover()}>核对原项目创建请求</button></p>}
    {taskId && onTask && <button className="secondary" onClick={() => onTask(taskId)}>查看原创建任务进度与结果</button>}
    {receipt && <article aria-label="项目创建副作用预览"><h3>{receipt.preview.request.name}</h3><p>目标路径：{receipt.preview.request.path}</p><p>仓库：{receipt.preview.request.cloneUrl ?? '未指定'} · 论文：{receipt.preview.request.paperId ?? '未指定'}</p>
      <details open={!pending?.startAttempt} className="project-disclosure"><summary>固定创建输入与副作用</summary>
      <p>{receipt.preview.disclosure.clone ? '远端服务将 clone 此公开仓库到目标路径：新目录或已有空目录，并登记项目。' : receipt.preview.request.createFolder ? '将在远端新建目录并登记项目。' : '将登记已有远端目录。'}{receipt.preview.disclosure.paperDownload && '远端服务将下载论文 PDF。'}{receipt.preview.disclosure.gitInitialization && '将在该目录初始化 Git。'}GitHub 自动同步明确关闭，不自动开展实验。</p>
      {receipt.preview.disclosure.clone && <p>clone 可能修改已有空目录。目标路径及父目录中的符号链接会指向实际写入位置；上游 clone 分支不保证目标为全新目录，Factory 未检查或锁定远端路径。请确认你批准此路径及其实际目标的写入。</p>}
      {!receipt.preview.request.createFolder && <p>已有目录会按上游规则解析到所在 Git 仓库的根目录；符号链接也会解析到实际位置。请填写你允许远端模型读取的预期仓库根路径。</p>}
      <p>上游可能为聊天页生成 4 条项目建议。它可能将 README、部分代码、文件清单或论文摘要发送给远端偏好或可用 harness 的模型。空项目、缓存命中或无可用 harness 时可能不调用模型。</p>
      </details>
      {plan && !pending?.startAttempt && ['awaiting', 'approved'].includes(receipt.consentState) && <><PlanReviewGate ownerId={ownerId} plan={plan} busy={busy} act={act} onAllowed={setAllowed} /><label><input type="checkbox" aria-label="批准此次项目创建副作用" disabled={!!busy} checked={consent} onChange={e => setConsent(e.target.checked)} />我确认此次项目输入、远端写入或 clone，以及可能的远端模型请求。</label><button disabled={!!busy || !consent || !allowed} onClick={() => void start()}>批准并提交此次创建</button><button disabled={!!busy} onClick={() => void cancel()}>取消此次创建批准</button></>}
      {receipt.state === 'ack_unknown' && <><p role="alert">创建确认 UNKNOWN，不能重新提交。候选项目与原请求的关联未经证明。</p><p>请在你的 OpenResearch 服务用上方原请求、项目名称和目标路径核对记录。不要重新创建同名项目或将候选项目当作成功回执。此处只读取候选；刷新与返回也不会重发。</p><button disabled={!!busy} onClick={() => void reconcile()}>只读核对远端候选项目</button>{receipt.candidates.map(p => <p key={p.nativeProjectId}>候选原生 ID {p.nativeProjectId} · {p.name} · {p.path}</p>)}</>}
      {receipt.result && <section className="project-created" aria-label="项目已确认，可继续关联会话"><h3>项目已确认，继续关联会话</h3><p><strong>{receipt.result.name}</strong> · {receipt.result.path}</p><p>已确认原生项目 ID：{receipt.result.nativeProjectId}</p><label>{researchSetup ? '研究工具（与服务设置一致）' : '新会话 harness'}<select aria-label="新会话 harness" value={harness} disabled={!!busy} onChange={e => setHarness(e.target.value)}><option value="">明确选择</option><option value="opencode">OpenCode（可选）</option><option value="codex">Codex</option><option value="claude-code">Claude Code</option></select></label><label>{researchSetup ? '模型名称（与服务设置一致）' : '新会话模型 ID'}<input aria-label="新会话模型 ID" maxLength={200} disabled={!!busy} value={model} onChange={e => setModel(e.target.value)} /></label><p>请填写此服务实际配置的完整模型名称。当前连接不提供可用模型列表，工具选项不代表已安装。Factory 的模型/API 设置不会传到这里；关联只验证项目并保存选择，不验证模型可用性、不创建会话或发送目标。</p><button className="primary" disabled={!!busy || !harness || !model.trim()} onClick={() => void connect()}>关联新项目并进入原生会话</button></section>}
    </article>}
  </section>;
}
