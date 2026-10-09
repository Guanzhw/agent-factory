import { useEffect, useRef, useState } from 'react';
import { api } from './api.js';
import { personalRemoteApi, RemoteRequestError, type PersonalCredential } from './personalRemoteApi.js';
import { credentialDestination, credentialReceipt, matchCredentialReceipt, readCredentialCommand, type CredentialCommand } from './credentialManagement.js';

const providerName = (id: string) => ({ 'byok-chat-v1': 'Agno 模型 API', 'openresearch-personal-session-v1': 'OpenResearch 服务', 'opencode-serve-v1': 'OpenCode 服务（可选）' })[id] ?? id;
export function PersonalCredentials({ ownerId, onChanged, onModels }: { ownerId: string; onChanged: () => void; onModels?: () => void }) {
  const storage = `factory-credential-management:${encodeURIComponent(ownerId)}`;
  const [pending, setPending] = useState(() => { try { return readCredentialCommand(localStorage.getItem(storage), ownerId); } catch { return null; } });
  const [rows, setRows] = useState<PersonalCredential[]>([]); const [providers, setProviders] = useState<string[]>([]);
  const [ready, setReady] = useState(false); const [enabled, setEnabled] = useState(false); const [blocked, setBlocked] = useState(false);
  const [refresh, setRefresh] = useState(0); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [form, setForm] = useState(false); const [editing, setEditing] = useState<PersonalCredential>(); const [revoking, setRevoking] = useState<PersonalCredential>();
  const [providerId, setProviderId] = useState(''); const [destination, setDestination] = useState(''); const [kind, setKind] = useState('bearer');
  const [username, setUsername] = useState(''); const [password, setPassword] = useState(''); const [consent, setConsent] = useState(false);
  const lock = useRef(false); const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  function clearDraft() { setPassword(''); setUsername(''); setConsent(false); setEditing(undefined); setRevoking(undefined); setForm(false); }
  function accountChanged() { clearDraft(); setRows([]); setPending(null); setReady(false); setBlocked(true); setError('当前登录账户已改变。已清空输入，请刷新后管理自己的凭据。'); }
  async function verifyOwner() {
    const session = await api.session();
    if (!alive.current) throw new Error('Unmounted');
    if (session.id !== ownerId) { accountChanged(); throw new RemoteRequestError(true, 'EXPECTED_OWNER_MISMATCH'); }
  }
  useEffect(() => {
    const controller = new AbortController(); setReady(false);
    void (async () => {
      await verifyOwner();
      const capability = await personalRemoteApi.credentialAvailability(controller.signal);
      const records = capability.enabled ? await personalRemoteApi.credentials(controller.signal, ownerId) : [];
      if (typeof capability.enabled !== 'boolean' || !Array.isArray(capability.providerIds) || capability.providerIds.some(id => typeof id !== 'string' || !/^[A-Za-z0-9_.:@-]{1,200}$/.test(id))) throw new Error('Invalid capability');
      const safe = records.map(credentialReceipt);
      if (!controller.signal.aborted && alive.current) { setRows(safe); setProviders(capability.providerIds); setEnabled(capability.enabled); setReady(true); setError(''); }
    })().catch(e => { if (!controller.signal.aborted && alive.current) { if (e instanceof RemoteRequestError && e.code === 'EXPECTED_OWNER_MISMATCH') accountChanged(); else setError('暂时无法读取凭据。请重新读取；原凭据和任务记录保留。'); } });
    return () => controller.abort();
    // The parent mounts this panel with an owner key; a changed account blocks it.
  }, [ownerId, refresh]);
  function retain(command: CredentialCommand) { localStorage.setItem(storage, JSON.stringify(command)); setPending(command); }
  function accepted(value: unknown, command: CredentialCommand) {
    matchCredentialReceipt(value, command); localStorage.removeItem(storage); setPending(null); clearDraft(); setRefresh(n => n + 1); onChanged();
    setNotice(command.action === 'revoke' ? '凭据已撤销。关联连接的后续使用会被拒绝；原任务、上下文与结果保留。' : command.action === 'rotate' ? '凭据已更换。请在模型设置或远程连接中显式绑定新版本；原任务不会自动换用新凭据。' : '凭据已安全保存。可在模型设置或远程连接中绑定使用。');
  }
  async function run(work: () => Promise<void>) {
    if (lock.current || blocked) return; lock.current = true; setBusy(true); setError(''); setNotice('');
    try { await verifyOwner(); await work(); }
    catch (e) { if (alive.current) { setPassword(''); setUsername(''); setConsent(false); if (e instanceof RemoteRequestError && e.code === 'EXPECTED_OWNER_MISMATCH') accountChanged(); else setError('操作尚未确认。请核对原请求或重新读取状态。'); } }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  function save() {
    if (!ready || !enabled || pending || !consent || !password || providerId !== 'byok-chat-v1' && kind === 'basic' && !username) return;
    let origin: string; try { origin = credentialDestination(destination.trim()); } catch { setError('请输入不含路径、登录信息或查询参数的 HTTPS 服务源。'); return; }
    if (!providers.includes(providerId)) return;
    void run(async () => {
      const command: CredentialCommand = { owner: ownerId, action: editing ? 'rotate' : 'create', requestId: crypto.randomUUID(), providerId, destination: origin,
        ...(editing ? { credentialRef: editing.credentialRef, credentialRevision: editing.credentialRevision } : {}) };
      const secret = password; const login = providerId === 'byok-chat-v1' ? 'api-key' : kind === 'bearer' ? 'bearer' : username;
      retain(command); setPassword(''); setUsername('');
      try {
        const receipt = editing ? await personalRemoteApi.rotateCredential(editing, login, secret, command.requestId, ownerId)
          : await personalRemoteApi.saveCredential({ providerId, destination: origin, username: login, password: secret, requestId: command.requestId }, ownerId);
        if (alive.current) accepted(receipt, command);
      } catch (e) { if (e instanceof RemoteRequestError && e.rejected) { localStorage.removeItem(storage); if (alive.current) setPending(null); } throw e; }
    });
  }
  function revoke(record: PersonalCredential) {
    if (pending || !ready) return;
    void run(async () => {
      const command: CredentialCommand = { owner: ownerId, action: 'revoke', requestId: crypto.randomUUID(), providerId: record.providerId, destination: record.destination, credentialRef: record.credentialRef, credentialRevision: record.credentialRevision };
      retain(command);
      try { const receipt = await personalRemoteApi.revokeCredential(record, command.requestId, ownerId); if (alive.current) accepted(receipt, command); }
      catch (e) { if (e instanceof RemoteRequestError && e.rejected) { localStorage.removeItem(storage); if (alive.current) setPending(null); } throw e; }
    });
  }
  function edit(record?: PersonalCredential) { clearDraft(); setEditing(record); setProviderId(record?.providerId ?? ''); setDestination(record?.destination ?? ''); setKind('bearer'); setForm(true); setError(''); }
  const disabled = busy || blocked || !!pending || !ready;
  return <section className="personal-credentials" aria-labelledby="credential-title">
    <h2 id="credential-title">我的凭据</h2><p>统一管理自己的模型 API 密钥、服务令牌和登录凭据。加密保存在服务器，仅显示用途、目标和状态，不提供明文查看。</p>
    <p className="quiet">更换或撤销后，旧绑定不能继续使用。任务上下文与已有结果保留；不会自动重试任务，也不代表上游正在处理的请求已停止。正常个人资源使用无需管理员审批。已保存仅表示保险库存储状态，可用性以模型或连接检查为准。当前列表最多显示 100 条。</p>
    {error && <p className="error-message" role="alert">{error}</p>}{notice && <p className="success-message" role="status">{notice}</p>}
    <div className="button-row"><button disabled={busy || blocked} onClick={() => setRefresh(n => n + 1)}>重新读取凭据</button>{onModels && <button disabled={busy} onClick={onModels}>管理模型/API 设置</button>}</div>
    {!ready && !error && <p role="status">正在读取个人凭据…</p>}
    {ready && !enabled && <p className="state-note">此部署尚未启用安全凭据保险库。管理员仅需维护部署，不需要接收你的明文密钥。</p>}
    {pending && <div className="state-note"><h3>上次凭据操作尚未确认</h3><p>输入已清空，仅保留原请求标识。核对不会重发秘密、轮换或撤销。</p><button disabled={busy || blocked} onClick={() => void run(async () => { const receipt = await personalRemoteApi.recoverCredential(pending.requestId, ownerId); if (alive.current) accepted(receipt, pending); })}>核对原凭据操作</button></div>}
    {ready && !rows.length && <p className="list-empty">尚未保存个人凭据。可添加服务凭据，或在模型设置中一次保存模型与 API 密钥。</p>}
    {rows.map(row => <article className="model-record" key={row.credentialRef}><div><h3>{providerName(row.providerId)}</h3><p>{row.destination}</p><span className={`badge status-${row.status === 'active' ? 'completed' : 'failed'}`}>{row.status === 'active' ? '已保存' : '已撤销'}</span></div><details className="technical-detail"><summary>凭据引用与版本</summary><p>{row.credentialRef}</p><p>{row.credentialRevision}</p></details>{row.status === 'active' && <div className="button-row"><button disabled={disabled || !enabled || !providers.includes(row.providerId)} onClick={() => edit(row)}>更换凭据</button><button className="danger" disabled={disabled} onClick={() => { clearDraft(); setRevoking(row); }}>撤销凭据</button></div>}{revoking?.credentialRef === row.credentialRef && <div className="state-note"><p>确认撤销用于 {row.destination} 的凭据？所有关联连接的后续使用都将失效，历史记录保留。</p><button className="danger" disabled={disabled} onClick={() => revoke(row)}>确认撤销凭据</button><button disabled={busy} onClick={() => setRevoking(undefined)}>保留凭据</button></div>}</article>)}
    {ready && enabled && !pending && !form && <button disabled={disabled} onClick={() => edit()}>添加个人凭据</button>}
    {form && !pending && !blocked && <form className="model-form" aria-label="管理个人凭据" onSubmit={e => { e.preventDefault(); save(); }}><h3>{editing ? '更换已保存凭据' : '添加个人凭据'}</h3><fieldset disabled={disabled}>
      <label>用途<select aria-label="凭据用途" value={providerId} disabled={!!editing} onChange={e => setProviderId(e.target.value)}><option value="">选择已部署的用途</option>{providers.map(id => <option key={id} value={id}>{providerName(id)}</option>)}</select></label>
      <label>HTTPS 服务源<input aria-label="凭据服务源" value={destination} disabled={!!editing} autoComplete="off" maxLength={512} placeholder="https://你的服务" onChange={e => setDestination(e.target.value)}/></label>
      {providerId !== 'byok-chat-v1' && <label>认证方式<select aria-label="凭据认证方式" value={kind} onChange={e => { setKind(e.target.value); setUsername(''); setPassword(''); }}><option value="bearer">服务令牌</option><option value="basic">用户名与密码</option></select></label>}
      {providerId !== 'byok-chat-v1' && kind === 'basic' && <label>服务用户名<input aria-label="凭据用户名" autoComplete="off" value={username} onChange={e => setUsername(e.target.value)}/></label>}
      <label>{providerId === 'byok-chat-v1' ? 'API 密钥' : kind === 'bearer' ? '服务令牌' : '服务密码'}<input aria-label="新的凭据秘密" type="password" autoComplete="new-password" maxLength={4096} value={password} onChange={e => setPassword(e.target.value)}/></label>
      <label><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/>允许安全保存，并仅用于我绑定到此目标的已授权执行。</label></fieldset>
      <div className="button-row"><button className="primary" disabled={disabled || !providerId || !destination || !password || !consent || providerId !== 'byok-chat-v1' && kind === 'basic' && !username}>{busy ? '正在保存…' : editing ? '保存更换后的凭据' : '安全保存个人凭据'}</button><button type="button" disabled={busy} onClick={clearDraft}>取消并清空凭据输入</button></div>
    </form>}
  </section>;
}
