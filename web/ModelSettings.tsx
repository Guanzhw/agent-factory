import { api } from './api.js';
import { useEffect, useRef, useState } from 'react';
import { ownerModelApi, ModelRequestError, type ModelCapabilities, type OwnerModel } from './ownerModelApi.js';
import { personalRemoteApi, RemoteRequestError, definitivelyRejected } from './personalRemoteApi.js';
import { credentialReceipt } from './credentialManagement.js';
import type { PersonalCredential } from './personalRemoteApi.js';
import { useCommandKeys } from './commandKeys.js';
import { modelEndpoint, readModelSetup, readModelSetups, setupCredential, setupDispatched, setupMetadata, type ModelSetup } from './ownerModelSetup.js';
import { MODEL_PROVIDER_PRESETS } from './modelProviderConfig.js';

export function ModelSettings({ ownerId, onResearch, onCredentials }: { ownerId: string; onResearch: () => void; onCredentials?: () => void }) {
  const storage = `factory-model-setup:${encodeURIComponent(ownerId)}`;
  const [pending, setPending] = useState<ModelSetup | null>(() => { try { return readModelSetup(localStorage.getItem(storage), ownerId); } catch { return null; } });
  const unresolvedStorage = `${storage}:unresolved`;
  const [unresolved, setUnresolved] = useState<ModelSetup[]>(() => { try { return readModelSetups(localStorage.getItem(unresolvedStorage), ownerId); } catch { return []; } });
  const [confirmStopWaiting, setConfirmStopWaiting] = useState(false);
  const [records, setRecords] = useState<OwnerModel[]>([]);
  const [credentials, setCredentials] = useState<PersonalCredential[]>([]);
  const [capability, setCapability] = useState<ModelCapabilities>();
  const [provider, setProvider] = useState<OwnerModel['provider']>('openai');
  const [protocol, setProtocol] = useState<OwnerModel['protocol']>();
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
  function retain(value: ModelSetup, { begin = false }: { begin?: boolean } = {}) {
    const safe = setupMetadata(value);
    const previous = readModelSetup(localStorage.getItem(storage), ownerId);
    if (previous && previous.modelRequest !== safe.modelRequest) { setPending(previous); throw new Error('另一个模型保存仍待核对。'); }
    // Only a new user intent can claim an empty slot. A delayed response cannot
    // reclaim it after another tab stopped waiting and settled the archive.
    if (!begin && previous?.modelRequest !== safe.modelRequest) { setPending(previous); throw new Error('原保存已停止等待或已完成。'); }
    if (readModelSetups(localStorage.getItem(unresolvedStorage), ownerId).some(s => s.modelRequest === safe.modelRequest)) throw new Error('原保存已停止等待。');
    localStorage.setItem(storage, JSON.stringify(safe)); setPending(safe); return safe;
  }
  function releaseActive(s: ModelSetup) {
    const owned = readModelSetup(localStorage.getItem(storage), ownerId)?.modelRequest === s.modelRequest;
    if (owned) localStorage.removeItem(storage);
    setPending(readModelSetup(localStorage.getItem(storage), ownerId));
    return owned;
  }
  function finished(s: ModelSetup) {
    if (!releaseActive(s)) return false;
    setConfirmStopWaiting(false); setEditing(undefined); setKey(''); setRefresh(n => n + 1); return true;
  }
  function accountChanged() {
    setKey(''); setModel(''); setEditing(undefined); setConfirmRevoke(''); setRecords([]); setPending(null); setReady(false);
    setCredentials([]); setUnresolved([]); setConfirmStopWaiting(false); setError('当前登录账户已改变。已清除输入，请刷新页面后重新进入自己的模型设置。');
  }
  async function verifyOwner() {
    const current = await api.session();
    if (!alive.current) throw new Error('Unmounted');
    if (current.id !== ownerId) { accountChanged(); throw new ModelRequestError(403, 'EXPECTED_OWNER_MISMATCH'); }
  }
  function matchModel(configured: OwnerModel, s: ModelSetup) {
    if (configured.provider !== s.provider || configured.baseURL !== s.baseURL || configured.model !== s.model || (configured.protocol ?? 'chat-completions') !== (s.protocol ?? 'chat-completions')
        || configured.thinkingMode !== s.thinkingMode || configured.credentialRef !== s.credential?.credentialRef
        || configured.credentialRevision !== s.credential?.credentialRevision || s.reference && configured.reference !== s.reference || !configured.available) throw new Error('模型保存回执无法核对。');
  }
  function matchDefault(selected: OwnerModel, s: ModelSetup) {
    if (selected.reference !== s.reference || (selected.protocol ?? 'chat-completions') !== (s.protocol ?? 'chat-completions') || selected.thinkingMode !== s.thinkingMode || !selected.isDefault || !selected.available) throw new Error('默认模型尚未确认；请核对原设置。');
  }
  async function recoverModel(s: ModelSetup, stage: 'model' | 'default') {
    const requestId = stage === 'model' ? s.modelRequest : s.defaultRequest;
    const receipt = await ownerModelApi.recover(ownerId, requestId);
    if (receipt.action !== (stage === 'model' ? 'model.configure' : 'model.default')) throw new Error('原请求回执不匹配。');
    if (stage === 'model') matchModel(receipt.result, s); else matchDefault(receipt.result, s);
    return receipt.result;
  }
  function releaseRejected(s: ModelSetup, failure: unknown) {
    // Only the first POST's explicit rejection settles that attempt. Recovery
    // errors, including 403/404, never prove an earlier request did not commit.
    if (!(failure instanceof ModelRequestError) || ![403, 422].includes(failure.status)) return;
    if (!releaseActive(s)) return;
    setEditing(undefined); setKey('');
    if (s.credential) {
      setCredentials(values => [...values.filter(c => c.credentialRef !== s.credential!.credentialRef), s.credential!]);
      setCredentialSource('saved'); setSavedReference(s.credential.credentialRef);
    }
  }
  async function continueSetup(value: ModelSetup, recovering = false) {
    let s = value;
    let checkedOriginal = recovering;
    if (s.stage === 'credential') {
      const receipt = await personalRemoteApi.recoverCredential(s.credentialRequest, ownerId);
      if (!alive.current) return;
      checkedOriginal = true;
      s = retain({ ...s, credential: setupCredential(receipt, s), stage: 'model', dispatched: {} });
    }
    if (s.stage === 'model') {
      if (!s.credential) throw new Error('缺少已确认的凭据引用。');
      let configured: OwnerModel;
      if (setupDispatched(s, 'model')) {
        configured = await recoverModel(s, 'model'); checkedOriginal = true;
      } else {
        s = retain({ ...s, dispatched: { ...s.dispatched, model: true } });
        try {
          configured = await ownerModelApi.configure(ownerId, { provider: s.provider, baseURL: s.baseURL, model: s.model,
            credentialRef: s.credential!.credentialRef, credentialRevision: s.credential!.credentialRevision, requestId: s.modelRequest,
            ...(s.protocol ? { protocol: s.protocol } : {}), ...(s.thinkingMode ? { thinkingMode: s.thinkingMode } : {}) }, s.reference);
        } catch (failure) { if (alive.current) releaseRejected(s, failure); throw failure; }
      }
      if (!alive.current) return;
      matchModel(configured, s);
      s = retain({ ...s, reference: configured.reference, stage: 'default', dispatched: { ...s.dispatched, model: true } });
    }
    if (s.chooseDefault) {
      let selected: OwnerModel;
      if (setupDispatched(s, 'default')) {
        selected = await recoverModel(s, 'default'); checkedOriginal = true;
      } else {
        s = retain({ ...s, dispatched: { ...s.dispatched, default: true } });
        try { selected = await ownerModelApi.default(ownerId, s.reference!, s.defaultRequest); }
        catch (failure) { if (alive.current) releaseRejected(s, failure); throw failure; }
      }
      if (!alive.current) return;
      matchDefault(selected, s);
    }
    if (!alive.current) return;
    if (!finished(s)) return false;
    setNotice(checkedOriginal ? '原保存已核对完成。当前默认模型以最新列表为准。' : s.rotating ? '密钥已更新。旧任务绑定会按服务端规则重新检查。' : s.chooseDefault ? '模型已保存并设为默认。可以返回工作区。' : '模型已保存。可以返回工作区。');
    return true;
  }
  function stopWaiting() {
    if (!pending || busy || unresolved.length >= 100) return;
    try {
      const previous = readModelSetups(localStorage.getItem(unresolvedStorage), ownerId);
      if (previous.length >= 100) throw new Error('未确认记录已满。');
      const next = [...previous.filter(s => s.modelRequest !== pending.modelRequest), setupMetadata(pending)];
      localStorage.setItem(unresolvedStorage, JSON.stringify(next)); releaseActive(pending);
      setUnresolved(next); setConfirmStopWaiting(false); setEditing(undefined); setKey(''); setRefresh(n => n + 1);
      setNotice('已停止等待，原请求仍保留。原操作可能已完成；核对记录不会重放写入或执行尚未发送的后续设置。');
    } catch { setError('暂时无法保留原请求，请继续等待或稍后重试。'); }
  }
  async function checkArchived(s: ModelSetup) {
    if (s.stage === 'credential') setupCredential(await personalRemoteApi.recoverCredential(s.credentialRequest, ownerId), s);
    else if (setupDispatched(s, s.stage)) await recoverModel(s, s.stage);
    if (!alive.current) return;
    const next = readModelSetups(localStorage.getItem(unresolvedStorage), ownerId).filter(value => value.modelRequest !== s.modelRequest);
    localStorage.setItem(unresolvedStorage, JSON.stringify(next)); setUnresolved(next); setRefresh(n => n + 1);
    setNotice('原阶段已核对。尚未发送的后续设置不会自动执行；当前模型以最新列表为准。');
  }
  async function run(work: () => Promise<unknown>) {
    if (lock.current) return; lock.current = true; setBusy(true); setError(''); setNotice('');
    try { await verifyOwner(); await work(); }
    catch (e) { if (alive.current && (e instanceof ModelRequestError || e instanceof RemoteRequestError) && e.code === 'EXPECTED_OWNER_MISMATCH') accountChanged(); else if (alive.current) setError(e instanceof ModelRequestError || e instanceof RemoteRequestError ? e.message : '设置尚未确认，请核对原请求或重新读取设置。'); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  function save() {
    if (pending || !ready || !capability?.enabled || !model.trim() || (editing || credentialSource === 'new' ? !key.trim() : !selectedCredential)) return;
    let baseURL: string;
    try { baseURL = modelEndpoint(endpoint); }
    catch { setError('请输入 HTTPS /v1 端点或官方 Go 端点。'); return; }
    const selectedModel = model.trim();
    if (!/^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,119}$/.test(selectedModel) || selectedModel === key.trim()) { setError('请核对模型名称；密钥只能填入 API 密钥字段。'); return; }
    void run(async () => {
      const s = retain({ owner: ownerId, provider, baseURL, model: selectedModel,
        ...(protocol ? { protocol } : {}), dispatched: {},
        ...(editing?.thinkingMode ? { thinkingMode: editing.thinkingMode } : {}),
        credentialRequest: crypto.randomUUID(), modelRequest: crypto.randomUUID(), defaultRequest: crypto.randomUUID(),
        stage: !editing && credentialSource === 'saved' ? 'model' : 'credential', chooseDefault: editing ? editing.isDefault : true,
        ...(!editing && credentialSource === 'saved' ? { credential: selectedCredential! } : {}),
        ...(editing ? { reference: editing.reference, rotating: { credentialRef: editing.credentialRef, credentialRevision: editing.credentialRevision } } : {}) }, { begin: true });
      if (s.credential) { await continueSetup(s); return; }
      const secret = key; setKey('');
      let credential;
      try {
        credential = editing
          ? await personalRemoteApi.rotateCredential({ credentialRef: editing.credentialRef, credentialRevision: editing.credentialRevision,
            providerId: 'byok-chat-v1', destination: new URL(baseURL).origin, status: 'active' }, 'api-key', secret, s.credentialRequest, ownerId)
          : await personalRemoteApi.saveCredential({ providerId: 'byok-chat-v1', destination: new URL(baseURL).origin, username: 'api-key', password: secret, requestId: s.credentialRequest }, ownerId);
      } catch (failure) {
        if (alive.current && (failure instanceof RemoteRequestError && failure.rejected || failure instanceof ModelRequestError && definitivelyRejected(failure.status))) releaseActive(s);
        throw failure;
      }
      if (!alive.current) return;
      await continueSetup(retain({ ...s, credential: setupCredential(credential, s), stage: 'model' }));
    });
  }
  function command(record: OwnerModel, action: 'default' | 'revoke') {
    void run(async () => {
      if (action === 'default') {
        const completed = await continueSetup(retain({ owner: ownerId, provider: record.provider, baseURL: record.baseURL, model: record.model,
          ...(record.protocol ? { protocol: record.protocol } : {}), ...(record.thinkingMode ? { thinkingMode: record.thinkingMode } : {}),
          credentialRequest: crypto.randomUUID(), modelRequest: crypto.randomUUID(), defaultRequest: crypto.randomUUID(),
          stage: 'default', reference: record.reference, chooseDefault: true, dispatched: {} }, { begin: true }));
        if (completed) setNotice('默认模型已更新。'); return;
      }
      const scope = `${action}:${record.reference}:${record.revision}`;
      const key = await commandKeys(scope, { reference: record.reference, revision: record.revision });
      if (!alive.current) return;
      const result = await ownerModelApi[action](ownerId, record.reference, key.requestId);
      if (!alive.current) return;
      if (result.reference !== record.reference || result.status !== 'revoked') throw new Error('操作结果尚未确认。');
      key.acknowledged(); setConfirmRevoke(''); setRefresh(n => n + 1); setNotice('模型已撤销，不能用于新任务。');
    });
  }
  function rotate(record: OwnerModel) { setEditing(record); setCredentialSource('new'); setSavedReference(''); setProvider(record.provider); setProtocol(record.protocol); setEndpoint(record.baseURL); setModel(record.model); setKey(''); setError(''); setNotice(''); }
  function currentCredential(record: OwnerModel) { return credentials.find(c => c.credentialRef === record.credentialRef && c.status === 'active' && c.providerId === 'byok-chat-v1' && c.destination === new URL(record.baseURL).origin && c.credentialRevision !== record.credentialRevision); }
  function rebind(record: OwnerModel) {
    const credential = currentCredential(record); if (!credential || pending) return;
    void run(async () => {
      await continueSetup(retain({ owner: ownerId, provider: record.provider, baseURL: record.baseURL, model: record.model,
        ...(record.protocol ? { protocol: record.protocol } : {}), dispatched: {},
        ...(record.thinkingMode ? { thinkingMode: record.thinkingMode } : {}),
        credentialRequest: crypto.randomUUID(), modelRequest: crypto.randomUUID(), defaultRequest: crypto.randomUUID(),
        stage: 'model', chooseDefault: record.isDefault, reference: record.reference, credential,
        rotating: { credentialRef: record.credentialRef, credentialRevision: record.credentialRevision } }, { begin: true }));
    });
  }
  const availableDefault = records.find(r => r.isDefault && r.available);
  const matchingCredentials = credentials.filter(c => {
    try { return c.status === 'active' && c.providerId === 'byok-chat-v1' && c.destination === new URL(modelEndpoint(endpoint)).origin; }
    catch { return false; }
  });
  const selectedCredential = matchingCredentials.find(c => c.credentialRef === savedReference);
  return <section className="model-settings" aria-labelledby="model-settings-title">
    <div className="page-heading"><div><p className="quiet">个人设置 · 我的默认模型</p><h1 id="model-settings-title">我的模型/API</h1><p>保存一次自己的模型，平台准备的 OpenResearch 与原生任务使用默认设置。</p></div><button className="secondary" onClick={onResearch} disabled={busy}>返回工作区</button></div>
    <p className="model-purpose">研究内容会发送给所选模型提供方，费用由你的提供方账户承担。密钥加密保存，不回显。</p>
    {onCredentials && <button className="secondary" disabled={busy} onClick={onCredentials}>管理我的凭据与连接</button>}
    {error && <div className="error-message" role="alert">{error}</div>}{notice && <div className="success-message" role="status">{notice}</div>}
    {!ready && !error && <p role="status">正在读取模型设置…</p>}
    <button className="text-button" disabled={busy} onClick={() => { setError(''); setRefresh(n => n + 1); }}>重新读取设置</button>
    {ready && !capability?.enabled && <div className="state-note"><strong>此部署尚未启用安全模型设置。</strong><p>请联系部署管理员启用个人模型保险库。无需向管理员发送 API 密钥。</p></div>}
    {pending && <div className="state-note"><h2>上次保存尚未确认</h2><p>已保留原请求，密钥未保存在浏览器中。核对已发出的操作后，只继续尚未发送的后续设置。</p><button className="primary" disabled={busy} onClick={() => void run(() => continueSetup(pending, true))}>{busy ? '正在核对…' : '核对并继续原保存'}</button><button disabled={busy || unresolved.length >= 100} onClick={() => setConfirmStopWaiting(true)}>停止等待此保存</button>{confirmStopWaiting && <div><p>原操作仍可能已完成。停止等待只解除本页编辑锁，原请求保留供只读核对。</p><button disabled={busy} onClick={stopWaiting}>确认停止等待并保留原请求</button><button disabled={busy} onClick={() => setConfirmStopWaiting(false)}>继续等待</button></div>}</div>}
    {unresolved.length > 0 && <div className="state-note"><h2>未确认的原请求（{unresolved.length}）</h2>{unresolved.map(s => <div key={s.modelRequest}><p>{s.model} · {s.stage === 'credential' ? '凭据保存' : s.stage === 'model' ? '模型保存' : '默认选择'}</p><button disabled={busy} onClick={() => void run(() => checkArchived(s))}>核对保留的原请求</button></div>)}</div>}
    {records.length > 0 && <div className="model-records">{records.map(record => <article className="model-record" key={record.reference}><div><h2>{record.model}</h2><p>{record.provider === 'openai' ? 'OpenAI' : '兼容 OpenAI 的服务'} · {new URL(record.baseURL).host}</p><span className={`badge status-${record.available ? 'completed' : 'failed'}`}>{record.isDefault && record.available ? '默认模型' : record.status === 'revoked' ? '已撤销' : record.available ? '已保存' : '密钥需更新'}</span></div>{record.status !== 'revoked' && <div className="button-row">{!record.isDefault && <button disabled={busy || !!pending || !record.available} onClick={() => command(record, 'default')}>设为默认</button>}{currentCredential(record) && <button disabled={busy || !!pending} onClick={() => rebind(record)}>绑定更新后的凭据</button>}<button disabled={busy || !!pending || !capability?.enabled || !!currentCredential(record)} onClick={() => rotate(record)}>更新密钥</button><button className="text-button danger" disabled={busy || !!pending} onClick={() => setConfirmRevoke(record.reference)}>撤销模型</button></div>}{confirmRevoke === record.reference && <div className="state-note"><p>确认撤销 {record.model}？它将不能用于新任务，原任务会继续接受权限检查。</p><button className="secondary danger" disabled={busy} onClick={() => command(record, 'revoke')}>确认撤销</button><button disabled={busy} onClick={() => setConfirmRevoke('')}>保留模型</button></div>}</article>)}</div>}
    {ready && capability?.enabled && !pending && <form className="model-form" onSubmit={event => { event.preventDefault(); save(); }}>
      <h2>{editing ? `更新 ${editing.model} 的密钥` : availableDefault ? '添加另一个模型' : '设置默认模型'}</h2>
      {!editing && <label>快捷配置<select aria-label="模型快捷配置" value="" disabled={busy} onChange={e => {
        const preset = MODEL_PROVIDER_PRESETS.find(p => p.id === e.target.value); if (!preset) return;
        setProvider(preset.provider); setEndpoint(preset.baseURL); setModel(preset.model); setProtocol(preset.protocol); setKey(''); setSavedReference('');
      }}><option value="">手动配置，或选择一个预设</option>{MODEL_PROVIDER_PRESETS.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}</select></label>}
      <fieldset disabled={busy}><label>提供方<select aria-label="模型提供方" disabled={!!editing} value={provider} onChange={e => { setProvider(e.target.value as OwnerModel['provider']); setEndpoint(e.target.value === 'openai' ? 'https://api.openai.com/v1' : ''); }}><option value="openai">OpenAI</option><option value="openai-compatible">兼容 OpenAI 的服务</option></select></label>
      <label>API 协议<select aria-label="模型 API 协议" disabled={!!editing} value={protocol ?? 'chat-completions'} onChange={e => setProtocol(e.target.value as OwnerModel['protocol'])}><option value="chat-completions">Chat Completions</option><option value="responses">Responses</option></select></label>
      <label>模型名称<input aria-label="模型名称" autoComplete="off" required maxLength={120} disabled={!!editing} value={model} onChange={e => setModel(e.target.value)} placeholder="填写账户可用的模型名称"/></label>
      {provider === 'openai-compatible' && <label>API 端点<input aria-label="API 端点" autoComplete="off" required disabled={!!editing} value={endpoint} onChange={e => setEndpoint(e.target.value)} placeholder="https://你的模型服务/v1"/></label>}
      {!editing && <label>凭据来源<select aria-label="模型凭据来源" value={credentialSource} onChange={e => { setCredentialSource(e.target.value as 'new' | 'saved'); setKey(''); setSavedReference(''); }}><option value="new">直接输入新密钥</option><option value="saved">选择我的已保存凭据</option></select></label>}
      {!editing && credentialSource === 'saved' ? <><label>已保存的模型凭据<select aria-label="已保存的模型凭据" value={selectedCredential ? savedReference : ''} onChange={e => setSavedReference(e.target.value)}><option value="">选择匹配此模型端点的凭据</option>{matchingCredentials.map(c => <option key={c.credentialRef} value={c.credentialRef}>{c.destination} · {c.credentialRef}</option>)}</select></label><p className="quiet">只绑定当前用户的已保存凭据引用，不重新保存密钥。保存时仍由服务端核对归属、授权、目标和版本。{!matchingCredentials.length && '当前没有匹配的有效凭据；可更改端点、重新读取设置或直接输入新密钥。'}</p></> : <label>API 密钥<input aria-label="API 密钥" type="password" autoComplete="new-password" required maxLength={4096} value={key} onChange={e => setKey(e.target.value)} placeholder={editing ? '输入新的密钥' : '输入自己的 API 密钥'}/></label>}</fieldset>
      <div className="button-row"><button className="primary" disabled={busy || !model.trim() || (editing || credentialSource === 'new' ? !key.trim() : !selectedCredential)}>{busy ? '正在保存…' : editing ? '保存新密钥' : credentialSource === 'saved' ? '保存模型并设为默认' : '保存并设为默认'}</button>{editing && <button type="button" disabled={busy} onClick={() => { setEditing(undefined); setKey(''); setModel(''); }}>取消更新</button>}</div>
    </form>}
    <details className="technical-detail"><summary>兼容性与设置说明</summary><p>按提供方要求选择 Chat Completions 或 Responses。支持 HTTPS /v1，以及官方 Go https://opencode.ai/inference/go/v1；旧 Go /zen/go/v1 配置保留。保存配置不会发送模型请求，也不证明远端模型兼容。</p><p>此默认模型用于平台 OpenResearch 环境及 Agno 原生任务。已有远端 OpenResearch 服务继续使用其自身配置。</p><p>撤销模型不删除历史记录；密钥轮换后旧任务绑定需重新核对。</p></details>
  </section>;
}
