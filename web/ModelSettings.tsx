import { api } from './api.js';
import { useEffect, useRef, useState } from 'react';
import { ownerModelApi, ModelRequestError, type ModelCapabilities, type OwnerModel } from './ownerModelApi.js';
import { personalRemoteApi, RemoteRequestError, definitivelyRejected } from './personalRemoteApi.js';
import { credentialReceipt } from './credentialManagement.js';
import type { PersonalCredential } from './personalRemoteApi.js';
import { useCommandKeys } from './commandKeys.js';
import { modelEndpoint, readModelSetup, setupCredential, setupMetadata, type ModelSetup } from './ownerModelSetup.js';

export function ModelSettings({ ownerId, onResearch, onCredentials }: { ownerId: string; onResearch: () => void; onCredentials?: () => void }) {
  const storage = `factory-model-setup:${encodeURIComponent(ownerId)}`;
  const [pending, setPending] = useState<ModelSetup | null>(() => { try { return readModelSetup(localStorage.getItem(storage), ownerId); } catch { return null; } });
  const [records, setRecords] = useState<OwnerModel[]>([]);
  const [credentials, setCredentials] = useState<PersonalCredential[]>([]);
  const [capability, setCapability] = useState<ModelCapabilities>();
  const [provider, setProvider] = useState<OwnerModel['provider']>('openai');
  const [endpoint, setEndpoint] = useState('https://api.openai.com/v1');
  const [model, setModel] = useState(''); const [key, setKey] = useState('');
  const [credentialSource, setCredentialSource] = useState<'new' | 'saved'>('new');
  const [savedReference, setSavedReference] = useState('');
  const [editing, setEditing] = useState<OwnerModel>(); const [confirmRevoke, setConfirmRevoke] = useState('');
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0); const [ready, setReady] = useState(false);
  const alive = useRef(true); const lock = useRef(false); const commandKeys = useCommandKeys(ownerId);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController(); setReady(false);
    void Promise.all([ownerModelApi.capabilities(controller.signal), ownerModelApi.list(ownerId, controller.signal)])
      .then(async ([cap, models]) => {
        const saved = cap.enabled ? (await personalRemoteApi.credentials(controller.signal, ownerId)).map(credentialReceipt) : [];
        if (!controller.signal.aborted) { setCapability(cap); setRecords(models); setCredentials(saved); setReady(true); setError(''); }
      })
      .catch(() => { if (!controller.signal.aborted) setError('暂时无法读取模型设置。请重新连接；未确认的保存请求会保留。'); });
    return () => controller.abort();
  }, [ownerId, refresh]);
  function retain(value: ModelSetup) {
    const safe = setupMetadata(value); localStorage.setItem(storage, JSON.stringify(safe)); setPending(safe); return safe;
  }
  function finished() { localStorage.removeItem(storage); setPending(null); setEditing(undefined); setKey(''); setRefresh(n => n + 1); }
  function accountChanged() {
    setKey(''); setModel(''); setEditing(undefined); setConfirmRevoke(''); setRecords([]); setPending(null); setReady(false);
    setCredentials([]); setError('当前登录账户已改变。已清除输入，请刷新页面后重新进入自己的模型设置。');
  }
  async function verifyOwner() {
    const current = await api.session();
    if (!alive.current) throw new Error('Unmounted');
    if (current.id !== ownerId) { accountChanged(); throw new ModelRequestError(403, 'EXPECTED_OWNER_MISMATCH'); }
  }
  async function continueSetup(value: ModelSetup) {
    let s = value;
    await verifyOwner();
    if (!s.credential) {
      const receipt = await personalRemoteApi.recoverCredential(s.credentialRequest, ownerId);
      if (!alive.current) return;
      s = retain({ ...s, credential: setupCredential(receipt, s), stage: 'model' });
    }
    if (s.stage === 'model') {
      await verifyOwner();
      const configured = await ownerModelApi.configure(ownerId, { provider: s.provider, baseURL: s.baseURL, model: s.model,
        credentialRef: s.credential!.credentialRef, credentialRevision: s.credential!.credentialRevision, requestId: s.modelRequest }, s.reference);
      if (!alive.current) return;
      if (configured.provider !== s.provider || configured.baseURL !== s.baseURL || configured.model !== s.model || configured.credentialRef !== s.credential!.credentialRef || configured.credentialRevision !== s.credential!.credentialRevision || !configured.available) throw new Error('模型保存回执无法核对。');
      s = retain({ ...s, reference: configured.reference, stage: 'default' });
    }
    if (s.chooseDefault) {
      await verifyOwner();
      const selected = await ownerModelApi.default(ownerId, s.reference!, s.defaultRequest);
      if (!alive.current) return;
      if (selected.reference !== s.reference || !selected.isDefault || !selected.available) throw new Error('默认模型尚未确认；请核对原设置。');
    }
    if (!alive.current) return;
    finished(); setNotice(s.rotating ? '密钥已更新。旧任务绑定会按服务端规则重新检查。' : s.chooseDefault ? '模型已保存并设为默认。可以返回工作区。' : '模型已保存。可以返回工作区。');
  }
  async function run(work: () => Promise<void>) {
    if (lock.current) return; lock.current = true; setBusy(true); setError(''); setNotice('');
    try { await work(); }
    catch (e) { if (alive.current && (e instanceof ModelRequestError || e instanceof RemoteRequestError) && e.code === 'EXPECTED_OWNER_MISMATCH') accountChanged(); else if (alive.current) setError(e instanceof ModelRequestError || e instanceof RemoteRequestError ? e.message : '设置尚未确认，请核对原请求或重新读取设置。'); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  function save() {
    if (pending || !ready || !capability?.enabled || !model.trim() || (editing || credentialSource === 'new' ? !key.trim() : !selectedCredential)) return;
    let baseURL: string;
    try { baseURL = modelEndpoint(endpoint); }
    catch { setError('请输入 HTTPS 模型端点，路径为 /v1。'); return; }
    const selectedModel = model.trim();
    if (!/^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,119}$/.test(selectedModel) || selectedModel === key.trim()) { setError('请核对模型名称；密钥只能填入 API 密钥字段。'); return; }
    void run(async () => {
      await verifyOwner();
      const s = retain({ owner: ownerId, provider, baseURL, model: selectedModel,
        credentialRequest: crypto.randomUUID(), modelRequest: crypto.randomUUID(), defaultRequest: crypto.randomUUID(),
        stage: !editing && credentialSource === 'saved' ? 'model' : 'credential', chooseDefault: editing ? editing.isDefault : true,
        ...(!editing && credentialSource === 'saved' ? { credential: selectedCredential! } : {}),
        ...(editing ? { reference: editing.reference, rotating: { credentialRef: editing.credentialRef, credentialRevision: editing.credentialRevision } } : {}) });
      if (s.credential) { await continueSetup(s); return; }
      const secret = key; setKey('');
      let credential;
      try {
        credential = editing
          ? await ownerModelApi.rotateCredential(ownerId, editing.credentialRef, editing.credentialRevision, secret, s.credentialRequest)
          : await personalRemoteApi.saveCredential({ providerId: 'byok-chat-v1', destination: new URL(baseURL).origin, username: 'api-key', password: secret, requestId: s.credentialRequest }, ownerId);
      } catch (failure) {
        if (failure instanceof RemoteRequestError && failure.rejected || failure instanceof ModelRequestError && definitivelyRejected(failure.status)) { localStorage.removeItem(storage); if (alive.current) setPending(null); }
        throw failure;
      }
      if (!alive.current) return;
      await continueSetup(retain({ ...s, credential: setupCredential(credential, s), stage: 'model' }));
    });
  }
  function command(record: OwnerModel, action: 'default' | 'revoke') {
    void run(async () => {
      await verifyOwner();
      const scope = `${action}:${record.reference}:${record.revision}`;
      const key = await commandKeys(scope, { reference: record.reference, revision: record.revision });
      if (!alive.current) return;
      const result = await ownerModelApi[action](ownerId, record.reference, key.requestId);
      if (!alive.current) return;
      if (result.reference !== record.reference || action === 'default' && (!result.isDefault || !result.available) || action === 'revoke' && result.status !== 'revoked') throw new Error('操作结果尚未确认。');
      key.acknowledged(); setConfirmRevoke(''); setRefresh(n => n + 1); setNotice(action === 'default' ? '默认模型已更新。' : '模型已撤销，不能用于新任务。');
    });
  }
  function rotate(record: OwnerModel) { setEditing(record); setCredentialSource('new'); setSavedReference(''); setProvider(record.provider); setEndpoint(record.baseURL); setModel(record.model); setKey(''); setError(''); setNotice(''); }
  function currentCredential(record: OwnerModel) { return credentials.find(c => c.credentialRef === record.credentialRef && c.status === 'active' && c.providerId === 'byok-chat-v1' && c.destination === new URL(record.baseURL).origin && c.credentialRevision !== record.credentialRevision); }
  function rebind(record: OwnerModel) {
    const credential = currentCredential(record); if (!credential || pending) return;
    void run(async () => {
      await verifyOwner();
      await continueSetup(retain({ owner: ownerId, provider: record.provider, baseURL: record.baseURL, model: record.model,
        credentialRequest: crypto.randomUUID(), modelRequest: crypto.randomUUID(), defaultRequest: crypto.randomUUID(),
        stage: 'model', chooseDefault: record.isDefault, reference: record.reference, credential,
        rotating: { credentialRef: record.credentialRef, credentialRevision: record.credentialRevision } }));
    });
  }
  const availableDefault = records.find(r => r.isDefault && r.available);
  const matchingCredentials = credentials.filter(c => {
    try { return c.status === 'active' && c.providerId === 'byok-chat-v1' && c.destination === new URL(modelEndpoint(endpoint)).origin; }
    catch { return false; }
  });
  const selectedCredential = matchingCredentials.find(c => c.credentialRef === savedReference);
  return <section className="model-settings" aria-labelledby="model-settings-title">
    <div className="page-heading"><div><p className="quiet">个人设置 · Agno 原生任务</p><h1 id="model-settings-title">我的模型/API</h1><p>保存一次自己的模型，后续原生任务使用默认设置。</p></div><button className="secondary" onClick={onResearch} disabled={busy}>返回工作区</button></div>
    <p className="model-purpose">研究内容会发送给所选模型提供方，费用由你的提供方账户承担。密钥加密保存，不回显。</p>
    {onCredentials && <button className="secondary" disabled={busy} onClick={onCredentials}>管理我的凭据与连接</button>}
    {error && <div className="error-message" role="alert">{error}</div>}{notice && <div className="success-message" role="status">{notice}</div>}
    {!ready && !error && <p role="status">正在读取模型设置…</p>}
    <button className="text-button" disabled={busy} onClick={() => { setError(''); setRefresh(n => n + 1); }}>重新读取设置</button>
    {ready && !capability?.enabled && <div className="state-note"><strong>此部署尚未启用安全模型设置。</strong><p>请联系部署管理员启用个人模型保险库。无需向管理员发送 API 密钥。</p></div>}
    {pending && <div className="state-note"><h2>上次保存尚未确认</h2><p>已保留原请求，密钥未保存在浏览器中。核对后继续相同设置，不创建新的密钥请求。</p><button className="primary" disabled={busy} onClick={() => void run(() => continueSetup(pending))}>{busy ? '正在核对…' : '核对并继续原保存'}</button></div>}
    {records.length > 0 && <div className="model-records">{records.map(record => <article className="model-record" key={record.reference}><div><h2>{record.model}</h2><p>{record.provider === 'openai' ? 'OpenAI' : '兼容 OpenAI 的服务'} · {new URL(record.baseURL).host}</p><span className={`badge status-${record.available ? 'completed' : 'failed'}`}>{record.isDefault && record.available ? '默认模型' : record.status === 'revoked' ? '已撤销' : record.available ? '已保存' : '密钥需更新'}</span></div>{record.status !== 'revoked' && <div className="button-row">{!record.isDefault && <button disabled={busy || !!pending || !record.available} onClick={() => command(record, 'default')}>设为默认</button>}{currentCredential(record) && <button disabled={busy || !!pending} onClick={() => rebind(record)}>绑定更新后的凭据</button>}<button disabled={busy || !!pending || !capability?.enabled || !!currentCredential(record)} onClick={() => rotate(record)}>更新密钥</button><button className="text-button danger" disabled={busy || !!pending} onClick={() => setConfirmRevoke(record.reference)}>撤销模型</button></div>}{confirmRevoke === record.reference && <div className="state-note"><p>确认撤销 {record.model}？它将不能用于新任务，原任务会继续接受权限检查。</p><button className="secondary danger" disabled={busy} onClick={() => command(record, 'revoke')}>确认撤销</button><button disabled={busy} onClick={() => setConfirmRevoke('')}>保留模型</button></div>}</article>)}</div>}
    {ready && capability?.enabled && !pending && <form className="model-form" onSubmit={event => { event.preventDefault(); save(); }}>
      <h2>{editing ? `更新 ${editing.model} 的密钥` : availableDefault ? '添加另一个模型' : '设置默认模型'}</h2>
      <fieldset disabled={busy}><label>提供方<select aria-label="模型提供方" disabled={!!editing} value={provider} onChange={e => { setProvider(e.target.value as OwnerModel['provider']); setEndpoint(e.target.value === 'openai' ? 'https://api.openai.com/v1' : ''); }}><option value="openai">OpenAI</option><option value="openai-compatible">兼容 OpenAI 的服务</option></select></label>
      <label>模型名称<input aria-label="模型名称" autoComplete="off" required maxLength={120} disabled={!!editing} value={model} onChange={e => setModel(e.target.value)} placeholder="填写账户可用的模型名称"/></label>
      {provider === 'openai-compatible' && <label>API 端点<input aria-label="API 端点" autoComplete="off" required disabled={!!editing} value={endpoint} onChange={e => setEndpoint(e.target.value)} placeholder="https://你的模型服务/v1"/></label>}
      {!editing && <label>凭据来源<select aria-label="模型凭据来源" value={credentialSource} onChange={e => { setCredentialSource(e.target.value as 'new' | 'saved'); setKey(''); setSavedReference(''); }}><option value="new">直接输入新密钥</option><option value="saved">选择我的已保存凭据</option></select></label>}
      {!editing && credentialSource === 'saved' ? <><label>已保存的模型凭据<select aria-label="已保存的模型凭据" value={selectedCredential ? savedReference : ''} onChange={e => setSavedReference(e.target.value)}><option value="">选择匹配此模型端点的凭据</option>{matchingCredentials.map(c => <option key={c.credentialRef} value={c.credentialRef}>{c.destination} · {c.credentialRef}</option>)}</select></label><p className="quiet">只绑定当前用户的已保存凭据引用，不重新保存密钥。保存时仍由服务端核对归属、授权、目标和版本。{!matchingCredentials.length && '当前没有匹配的有效凭据；可更改端点、重新读取设置或直接输入新密钥。'}</p></> : <label>API 密钥<input aria-label="API 密钥" type="password" autoComplete="new-password" required maxLength={4096} value={key} onChange={e => setKey(e.target.value)} placeholder={editing ? '输入新的密钥' : '输入自己的 API 密钥'}/></label>}</fieldset>
      <div className="button-row"><button className="primary" disabled={busy || !model.trim() || (editing || credentialSource === 'new' ? !key.trim() : !selectedCredential)}>{busy ? '正在保存…' : editing ? '保存新密钥' : credentialSource === 'saved' ? '保存模型并设为默认' : '保存并设为默认'}</button>{editing && <button type="button" disabled={busy} onClick={() => { setEditing(undefined); setKey(''); setModel(''); }}>取消更新</button>}</div>
    </form>}
    <details className="technical-detail"><summary>兼容性与设置说明</summary><p>支持 HTTPS /v1 的文本与工具调用 Chat Completions。保存配置不会发送模型请求，也不证明远端模型兼容。</p><p>这是 Agno 原生模型设置；OpenResearch 原生远程会话继续使用其服务自身的模型配置。</p><p>撤销模型不删除历史记录；密钥轮换后旧任务绑定需重新核对。</p></details>
  </section>;
}
