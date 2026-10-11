import { useEffect, useState } from 'react';
import { PersonalRemotes } from './PersonalRemotes.js';
import { PersonalCredentials } from './PersonalCredentials.js';
import { PersonalSSHServers } from './PersonalSSHServers.js';
import { api } from './api.js';
import { processExecutionState, processLeasePage, processLeaseState, processLeaseView, type ProcessLease } from './processLeaseView.js';
import { useCommandKeys } from './commandKeys.js';
import type { ConnectionRegistration, FactoryJob, User, UserConnection } from './models.js';

type Act = (name: string, work: () => Promise<void>) => Promise<void>;
const names: Record<string, string> = { model: '模型', tool: '工具', knowledge: '知识', environment: '环境', orx: '研究适配器' };
const states: Record<string, string> = { active: '可用于当前配置', available: '可绑定', unavailable: '当前配置不可用', expired: '已过期', revoked: '已撤销', changed: '配置已变更', missing: '登记已移除', task_ended: '绑定任务已结束' };
const message = (error: unknown) => error instanceof Error ? error.message : '连接状态无法确认。';
const date = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '未设置';

export function ProcessLeasePanel({ leases, owner }: { leases: unknown[]; owner: string }) {
  return <div aria-label="执行租约回执">{leases.map((value, index) => {
    const view = processLeaseView(value, owner);
    if (view.kind === 'invalid') return <p className="error-message" role="alert" key={index}>执行租约身份或进程回执尚未核实，不能确认停止或释放。</p>;
    const { lease, stopped, released } = view;
    const aggregate = lease.enforcement && 'schema' in lease.enforcement ? lease.enforcement : null;
    const evidence = lease.aggregateEvidence;
    const cgroupStopped = lease.stopEvidence?.kind === 'original-delegated-cgroup-empty-and-removed';
    return <article className="material-row review-row" key={lease.id} data-process-lease-id={lease.id}><div className="material-info" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
      <h3>执行租约</h3><p><span className={`badge ${released ? 'status-ready' : 'status-blocked'}`}>{processLeaseState(lease.state)}</span></p>
      <p className={['FAILED', 'LIMIT_STOPPED'].includes(lease.executionStatus ?? '') ? 'error-message' : 'quiet'}>{processExecutionState(lease.executionStatus)}{lease.exitCode !== null ? ` · 退出码 ${lease.exitCode}` : ''}。租约释放不代表进程成功。</p>
      <p role="status">{stopped ? lease.stopEvidence?.kind === 'never-dispatched' ? '服务端确认进程从未启动。' : cgroupStopped ? '服务端已记录原委派 cgroup 为空且已移除的停止证据。' : '服务端已记录原进程组停止证据。' : '进程停止证据尚未确认。'} {released ? '租约预约容量已释放。' : '预约容量仍保留；停止或任务终态不等于资源已释放。'}</p>
      {lease.state === 'UNKNOWN' && <p className="policy-note">原执行确认未知。保留原租约；页面读取不会重新启动进程或重放取消、回收。</p>}
      <dl className="plan-details"><dt>进程回执</dt><dd>{lease.providerJobId ?? '尚未取得进程回执'}</dd><dt>任务绑定</dt><dd>{lease.localTaskId}</dd><dt>原生运行</dt><dd>{lease.nativeRunId ?? '尚未确认'}</dd><dt>计划</dt><dd>{lease.planId}</dd><dt>进程与任务关联</dt><dd>{lease.processBinding ? '服务端回执中的任务、原生运行与计划已对应' : '尚未取得完整进程绑定，不能确认已集成执行'}</dd></dl>
      {aggregate ? <><h4>声明的聚合限额范围</h4><ul><li>CPU：cgroup cpu.max</li><li>内存与交换空间：cgroup memory.max / memory.swap.max</li><li>进程数：cgroup pids.max</li><li>文件大小：每个文件的 RLIMIT 限额</li><li>执行时长：原委派 cgroup 守护</li></ul><p className="quiet">配置声明不等于实际执行已受聚合限制；以下只展示服务端回读与进程附加证据。不提供磁盘总量配额、网络隔离或不可信代码安全沙箱。</p>
        <dl className="plan-details"><dt>限额回读</dt><dd>{evidence?.limitsReadbackVerified ? '服务端已记录内核限额回读核对通过' : '尚未确认内核限额回读'}</dd><dt>进程附加</dt><dd>{evidence?.attached ? '服务端已记录进程附加到原 cgroup' : '尚未确认进程附加，不宣称实际执行已受聚合限制'}</dd><dt>聚合资源释放证据</dt><dd>{evidence?.releasedProof ? '原 cgroup 已确认为空并移除；租约容量状态仍单独核对' : '尚未取得原 cgroup 为空且已移除的完整证据'}</dd></dl>
        {evidence?.state === 'UNKNOWN' && <p className="policy-note">聚合执行证据 UNKNOWN，不能据配置推断已限制、已停止或已释放。</p>}
        <details className="technical-detail"><summary>聚合限额证据绑定</summary><span>配置指纹 {aggregate.configurationSha256}</span>{evidence && <><span>记录状态 {evidence.state}</span><span>票据 {evidence.ticketId}</span><span>原根目录指纹 {evidence.rootPinSha256}</span><span>原进程组指纹 {evidence.groupPinSha256 ?? '尚未确认'}</span></>}</details>
      </> : lease.enforcement ? <><h4>已记录的限额范围</h4><ul><li>CPU 与内存：每个进程的 RLIMIT 限额</li><li>文件大小：每个文件的 RLIMIT 限额</li><li>执行时长：协作式进程组守护</li></ul><p className="quiet">这些限额不是进程组总量配额，不提供不可信代码安全沙箱或网络隔离。</p></> : <p className="quiet">尚未提供可核对的进程限额回执，不宣称内核限额已生效。</p>}
      <details className="technical-detail"><summary>租约与进程绑定依据</summary><span>租约 {lease.id}</span>{lease.processBinding && <span>绑定指纹 {lease.processBinding.bindingFingerprint}</span>}<span>停止证据 {stopped ? lease.stopEvidence?.kind === 'never-dispatched' ? '从未启动进程，不宣称发生进程回收' : cgroupStopped ? '原委派 cgroup 已确认为空且已移除' : '原始根进程已回收，未发现仍存活的进程组成员' : '未确认'}</span></details>
    </div></article>;
  })}</div>;
}

export function ConnectionsPanel({ user, jobs, busy, act, onNotice, onTask, onModels, onResearch }: { user: User; jobs: FactoryJob[]; busy: string; act: Act; onNotice: (message: string) => void; onTask?: (id: string) => void; onModels?: () => void; onResearch?: () => void }) {
  const [connections, setConnections] = useState<UserConnection[]>([]);
  const [registrations, setRegistrations] = useState<ConnectionRegistration[]>([]);
  const [registrationRef, setRegistrationRef] = useState('');
  const [capabilities, setCapabilities] = useState<string[]>([]);
  const [taskId, setTaskId] = useState('');
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [leases, setLeases] = useState<ProcessLease[]>([]);
  const [leaseError, setLeaseError] = useState('');
  const [leasesReady, setLeasesReady] = useState(false);
  const [after, setAfter] = useState<string | undefined>();
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const keys = useCommandKeys(user.id);
  const registration = registrations.find(item => item.registrationRef === registrationRef);
  const activeJobs = jobs.filter(job => !['completed', 'failed', 'canceled'].includes(job.status));
  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [session, next, installed] = await Promise.all([api.session(controller.signal), api.userConnections(controller.signal), api.connectionRegistrations(controller.signal)]);
        if (session.id !== user.id || next.some(item => item.ownerId !== user.id)) throw new Error('当前身份或连接归属无法核对；暂时禁用操作。');
        if (controller.signal.aborted) return;
        setConnections(next); setRegistrations(installed); setReady(true); setError('');
      } catch (e) { if (!controller.signal.aborted) { setError(message(e)); setReady(false); } }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 5000);
    }
    void poll(); return () => { controller.abort(); clearTimeout(timer); };
  }, [user.id, refresh]);
  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    setLeasesReady(false); setLeaseError('');
    async function poll() {
      try {
        const [session, raw] = await Promise.all([api.session(controller.signal), api.resourceLeases(after, controller.signal)]);
        if (session.id !== user.id) throw new Error('当前身份无法核对，暂不展示执行租约。');
        const page = processLeasePage(raw, user.id);
        if (controller.signal.aborted) return;
        setLeases(page.leases); setNextCursor(page.nextCursor); setLeasesReady(true); setLeaseError('');
      } catch (e) { if (!controller.signal.aborted) { setLeaseError(message(e)); setLeasesReady(false); } }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 5000);
    }
    void poll(); return () => { controller.abort(); clearTimeout(timer); };
  }, [user.id, refresh, after]);
  function selectRegistration(ref: string) { setRegistrationRef(ref); setCapabilities(registrations.find(item => item.registrationRef === ref)?.capabilities ?? []); }
  async function bind() {
    if (!ready || !registration?.available || !registration.allowedActions.includes('bind')) return;
    const payload = { registrationRef, capabilities: [...capabilities].sort(), ...(taskId ? { taskId } : {}) };
    await act('bind-connection', async () => {
      const key = await keys('bind-connection', payload);
      const result = await api.bindConnection(registrationRef, key.requestId, payload.capabilities, taskId || undefined);
      if (result.ownerId !== user.id) throw new Error('连接确认归属不一致；请核对原请求。');
      key.acknowledged(); setRefresh(n => n + 1); setRegistrationRef(''); setTaskId(''); setCapabilities([]);
      onNotice('连接引用已登记；可用状态仅代表当前配置，不代表已验证真实提供商。');
    });
  }
  async function revoke(item: UserConnection) {
    if (!ready || !item.allowedActions.includes('revoke')) return;
    await act('revoke-connection', async () => {
      const key = await keys('revoke-connection', { ref: item.ref, fingerprint: item.fingerprint });
      const result = await api.revokeConnection(item.ref, key.requestId);
      if (result.ownerId !== user.id) throw new Error('撤销确认归属不一致。');
      key.acknowledged(); setRefresh(n => n + 1); onNotice('连接已撤销。后续执行会重新检查绑定；已有证据保留。');
    });
  }
  return <section className="connections-page"><div className="page-heading"><div><h1>我的凭据与连接</h1><p>管理自己的凭据、远程服务与资源绑定。</p></div><button className="secondary" disabled={!!busy} onClick={() => setRefresh(n => n + 1)}>刷新资源</button></div>
    <PersonalSSHServers key={user.id} ownerId={user.id} revision={refresh} onChanged={() => setRefresh(n => n + 1)} onResearch={onResearch}/>
    <PersonalCredentials key={user.id} ownerId={user.id} revision={refresh} onChanged={() => setRefresh(n => n + 1)} onModels={onModels}/>
    <PersonalRemotes key={`${user.id}:${refresh}`} user={user} jobs={jobs} onTask={onTask} onChanged={() => setRefresh(n => n + 1)} />
    {error && <div role="alert" className="error-message">资源列表暂不可用。请刷新资源；原绑定保留，未自动重试绑定。<span>{error}</span></div>}
    <details><summary>高级：绑定已有可信登记</summary><p className="state-note">兼容管理员已配置的资源登记；不创建云资源。可用状态不代表真实提供商已验证。</p>
    <form className="material-editor" onSubmit={event => { event.preventDefault(); void bind(); }}><h2>绑定可信资源</h2><div className="editor-grid"><label>可信登记<select aria-label="可信登记" value={registrationRef} disabled={!!busy || !ready} onChange={event => selectRegistration(event.target.value)}><option value="">选择已授权登记</option>{registrations.map(item => <option key={item.registrationRef} value={item.registrationRef} disabled={!item.available || !item.allowedActions.includes('bind')}>{names[item.kind]} · {item.registrationRef} · {states[item.status]}</option>)}</select></label><label>任务范围<select aria-label="连接任务范围" value={taskId} disabled={!!busy || !ready} onChange={event => setTaskId(event.target.value)}><option value="">我的用户范围</option>{activeJobs.map(job => <option key={job.id} value={job.id}>{job.input.topic}</option>)}</select></label></div>
      {registration && <><fieldset className="dependency-picker" disabled={!!busy || !ready}><legend>允许能力（可缩小）</legend>{registration.capabilities.length ? registration.capabilities.map(capability => <label key={capability}><input type="checkbox" checked={capabilities.includes(capability)} onChange={event => setCapabilities(current => event.target.checked ? [...current, capability] : current.filter(item => item !== capability))}/>{capability}</label>) : <p className="quiet">此登记没有附加能力。</p>}</fieldset><p className="quiet">配置版本 {registration.revision} · 到期 {date(registration.expiresAt)}</p></>}
      {!registrations.length && <p className="quiet">{ready ? '当前没有可供你绑定的可信登记。请联系管理员配置资源。' : '正在核对可信登记。'}</p>}
      <button className="primary" disabled={!!busy || !ready || !registration?.available || !registration.allowedActions.includes('bind')}>{busy === 'bind-connection' ? '等待绑定确认…' : '确认绑定'}</button>
    </form></details>
    <h2>我的连接引用</h2>{connections.length ? connections.map(item => <article className="material-row review-row" key={item.ref}><div className="material-info"><h3>{names[item.kind]} · {item.registrationRef}</h3><p><span className={`badge ${item.available ? 'status-ready' : 'status-blocked'}`}>{states[item.status]}</span></p><dl className="plan-details"><dt>允许能力</dt><dd>{item.capabilities.join('、') || '无附加能力'}</dd><dt>绑定范围</dt><dd>{item.taskId ? jobs.find(job => job.id === item.taskId)?.input.topic ?? '已绑定任务' : '我的用户范围'}</dd><dt>到期</dt><dd>{date(item.expiresAt)}</dd></dl><details className="technical-detail"><summary>连接凭据与版本</summary><span>引用 {item.ref}</span><span>版本 {item.revision}</span><span>指纹 {item.fingerprint}</span><span>创建 {date(item.createdAt)}</span>{item.revokedAt && <span>撤销 {date(item.revokedAt)}</span>}{item.taskId && <span>任务 {item.taskId}</span>}</details></div><div className="material-actions"><button className="secondary danger" disabled={!!busy || !ready || !item.allowedActions.includes('revoke')} onClick={() => void revoke(item)}>{item.status === 'revoked' ? '已撤销' : '撤销此连接'}</button></div></article>) : <p className="list-empty">{error ? '连接列表暂不可用。请查看上方错误并刷新资源。' : ready ? '你尚未绑定连接引用。合成演示无需真实提供商连接。' : '正在读取自己的连接。'}</p>}
    <section aria-label="我的执行租约"><h2>我的执行租约</h2><p className="quiet">展示当前页服务端记录的租约，每页最多 100 条。停止证据、执行终态与预约容量释放分别核对；此页面不会分配或启动进程。</p>
      {leaseError ? <p className="error-message" role="alert">{leaseError}</p> : !leasesReady ? <p className="list-empty">正在核对执行租约…</p> : leases.length ? <ProcessLeasePanel leases={leases} owner={user.id}/> : <p className="list-empty">当前页没有可见执行租约。</p>}
      <div className="material-actions">{after && <button className="secondary" onClick={() => setAfter(undefined)}>返回第一页</button>}{nextCursor && <button className="secondary" disabled={!leasesReady || !!leaseError} onClick={() => setAfter(nextCursor)}>查看下一页</button>}</div>
      {leasesReady && <p className="quiet">当前页 {leases.length} 条；分页读取不是完整快照。可返回第一页重新核对。</p>}
    </section>
  </section>;
}
