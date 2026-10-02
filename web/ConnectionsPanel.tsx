import { useEffect, useState } from 'react';
import { api } from './api.js';
import { useCommandKeys } from './commandKeys.js';
import type { ConnectionRegistration, FactoryJob, User, UserConnection } from './models.js';

type Act = (name: string, work: () => Promise<void>) => Promise<void>;
const names: Record<string, string> = { model: '模型', tool: '工具', knowledge: '知识', environment: '环境', orx: '研究适配器' };
const states: Record<string, string> = { active: '可用于当前配置', available: '可绑定', unavailable: '当前配置不可用', expired: '已过期', revoked: '已撤销', changed: '配置已变更', missing: '登记已移除', task_ended: '绑定任务已结束' };
const message = (error: unknown) => error instanceof Error ? error.message : '连接状态无法确认。';
const date = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '未设置';

export function ConnectionsPanel({ user, jobs, busy, act, onNotice }: { user: User; jobs: FactoryJob[]; busy: string; act: Act; onNotice: (message: string) => void }) {
  const [connections, setConnections] = useState<UserConnection[]>([]);
  const [registrations, setRegistrations] = useState<ConnectionRegistration[]>([]);
  const [registrationRef, setRegistrationRef] = useState('');
  const [capabilities, setCapabilities] = useState<string[]>([]);
  const [taskId, setTaskId] = useState('');
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  const [refresh, setRefresh] = useState(0);
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
  return <section className="connections-page"><div className="page-heading"><div><h1>我的资源连接</h1><p>从可信登记中绑定自己的资源，并按需缩小能力和任务范围。</p></div><button className="secondary" disabled={!!busy} onClick={() => setRefresh(n => n + 1)}>刷新连接</button></div>
    <div className="state-note">此处管理用户自己的连接引用。可信资源由管理员预先配置；页面不收集密钥，也不创建云资源。可用状态不代表真实提供商已验证。</div>
    {error && <div role="alert" className="error-message">{error}</div>}
    <form className="material-editor" onSubmit={event => { event.preventDefault(); void bind(); }}><h2>绑定可信资源</h2><div className="editor-grid"><label>可信登记<select aria-label="可信登记" value={registrationRef} disabled={!!busy || !ready} onChange={event => selectRegistration(event.target.value)}><option value="">选择已授权登记</option>{registrations.map(item => <option key={item.registrationRef} value={item.registrationRef} disabled={!item.available || !item.allowedActions.includes('bind')}>{names[item.kind]} · {item.registrationRef} · {states[item.status]}</option>)}</select></label><label>任务范围<select aria-label="连接任务范围" value={taskId} disabled={!!busy || !ready} onChange={event => setTaskId(event.target.value)}><option value="">我的用户范围</option>{activeJobs.map(job => <option key={job.id} value={job.id}>{job.input.topic}</option>)}</select></label></div>
      {registration && <><fieldset className="dependency-picker" disabled={!!busy || !ready}><legend>允许能力（可缩小）</legend>{registration.capabilities.length ? registration.capabilities.map(capability => <label key={capability}><input type="checkbox" checked={capabilities.includes(capability)} onChange={event => setCapabilities(current => event.target.checked ? [...current, capability] : current.filter(item => item !== capability))}/>{capability}</label>) : <p className="quiet">此登记没有附加能力。</p>}</fieldset><p className="quiet">配置版本 {registration.revision} · 到期 {date(registration.expiresAt)}</p></>}
      {!registrations.length && <p className="quiet">{ready ? '当前没有可供你绑定的可信登记。请联系管理员配置资源。' : '正在核对可信登记。'}</p>}
      <button className="primary" disabled={!!busy || !ready || !registration?.available || !registration.allowedActions.includes('bind')}>{busy === 'bind-connection' ? '等待绑定确认…' : '确认绑定'}</button>
    </form>
    <h2>我的连接引用</h2>{connections.length ? connections.map(item => <article className="material-row review-row" key={item.ref}><div className="material-info"><h3>{names[item.kind]} · {item.registrationRef}</h3><p><span className={`badge ${item.available ? 'status-ready' : 'status-blocked'}`}>{states[item.status]}</span></p><dl className="plan-details"><dt>允许能力</dt><dd>{item.capabilities.join('、') || '无附加能力'}</dd><dt>绑定范围</dt><dd>{item.taskId ? jobs.find(job => job.id === item.taskId)?.input.topic ?? '已绑定任务' : '我的用户范围'}</dd><dt>到期</dt><dd>{date(item.expiresAt)}</dd></dl><details className="technical-detail"><summary>连接凭据与版本</summary><span>引用 {item.ref}</span><span>版本 {item.revision}</span><span>指纹 {item.fingerprint}</span><span>创建 {date(item.createdAt)}</span>{item.revokedAt && <span>撤销 {date(item.revokedAt)}</span>}{item.taskId && <span>任务 {item.taskId}</span>}</details></div><div className="material-actions"><button className="secondary danger" disabled={!!busy || !ready || !item.allowedActions.includes('revoke')} onClick={() => void revoke(item)}>{item.status === 'revoked' ? '已撤销' : '撤销此连接'}</button></div></article>) : <p className="list-empty">{ready ? '你尚未绑定连接引用。合成演示无需真实提供商连接。' : '正在读取自己的连接。'}</p>}
  </section>;
}
