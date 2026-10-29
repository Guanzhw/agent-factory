import { api } from './api.js';
import { useEffect, useRef, useState } from 'react';
import { ownerModelApi, ModelRequestError, validOutputTokens, type ModelCapabilities, type OwnerModel } from './ownerModelApi.js';
import { personalRemoteApi, RemoteRequestError, definitivelyRejected } from './personalRemoteApi.js';
import { credentialReceipt } from './credentialManagement.js';
import type { PersonalCredential } from './personalRemoteApi.js';
import { useCommandKeys } from './commandKeys.js';
import { modelEndpoint, readModelSetup, readModelSetups, setupCredential, setupDispatched, setupMetadata, type ModelSetup } from './ownerModelSetup.js';
import { MODEL_PROVIDER_PRESETS } from './modelProviderConfig.js';
import { authEpoch } from './browserAuth.js';
import { clearModelSettingsDraft, readModelSettingsDraft, saveModelSettingsDraft } from './modelSettingsDraft.js';

export function ModelSettings({ ownerId, onBack, onCredentials, returnLabel = '返回工作区' }: { ownerId: string; onBack: () => void; onCredentials?: () => void; returnLabel?: string }) {
  const [draft] = useState(() => readModelSettingsDraft(ownerId));
  const [draftRestored, setDraftRestored] = useState(false);
  const epoch = useRef(authEpoch());
  const storage = `factory-model-setup:${encodeURIComponent(ownerId)}`;
  const [pending, setPending] = useState<ModelSetup | null>(() => { try { return readModelSetup(localStorage.getItem(storage), ownerId); } catch { return null; } });
  const unresolvedStorage = `${storage}:unresolved`;
  const [unresolved, setUnresolved] = useState<ModelSetup[]>(() => { try { return readModelSetups(localStorage.getItem(unresolvedStorage), ownerId); } catch { return []; } });
  const [confirmStopWaiting, setConfirmStopWaiting] = useState(false);
  const [records, setRecords] = useState<OwnerModel[]>([]);
  const [credentials, setCredentials] = useState<PersonalCredential[]>([]);
  const [capability, setCapability] = useState<ModelCapabilities>();
  const [provider, setProvider] = useState<OwnerModel['provider']>(draft?.provider ?? 'openai');
  const [protocol, setProtocol] = useState<OwnerModel['protocol']>(draft?.protocol);
  const [endpoint, setEndpoint] = useState(draft?.endpoint ?? 'https://api.openai.com/v1');
  const [model, setModel] = useState(draft?.model ?? ''); const [key, setKey] = useState('');
  const [credentialSource, setCredentialSource] = useState<'new' | 'saved' | 'none'>(draft?.credentialSource ?? 'new');
  const [savedReference, setSavedReference] = useState(draft?.savedReference ?? '');
  const [editing, setEditing] = useState<Extract<OwnerModel, { isOwner: true }> & { credentialRef: string; credentialRevision: string }>(); const [confirmRevoke, setConfirmRevoke] = useState('');
  const [outputEditing, setOutputEditing] = useState<Extract<OwnerModel, { isOwner: true }>>();
  const [outputTokens, setOutputTokens] = useState(draft?.outputTokens ?? '');
  const outputLimit = outputTokens.trim() ? Number(outputTokens) : undefined;
  const invalidOutput = outputLimit !== undefined && !validOutputTokens(outputLimit);
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0); const [ready, setReady] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [savedForReturn, setSavedForReturn] = useState(false);
  const sharingStorage = `factory-model-sharing:${encodeURIComponent(ownerId)}`;
  const [pendingSharing, setPendingSharing] = useState<{ requestId: string; reference: string; visibility: 'personal' | 'team' } | null>(() => {
    try { return JSON.parse(localStorage.getItem(sharingStorage) ?? 'null'); } catch { return null; }
  });
  const alive = useRef(true); const lock = useRef(false); const commandKeys = useCommandKeys(ownerId);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController(); setReady(false);
    void Promise.all([ownerModelApi.capabilities(controller.signal), ownerModelApi.list(ownerId, controller.signal)])
      .then(async ([cap, models]) => {
        const saved = cap.enabled && cap.credentialsEnabled !== false ? (await personalRemoteApi.credentials(controller.signal, ownerId)).map(credentialReceipt) : [];
        if (!controller.signal.aborted) { setCapability(cap); setRecords(models); setCredentials(saved); setReady(true); setError(''); }
      })
      .catch(() => { if (!controller.signal.aborted) setError('暂时无法读取模型设置。请重新连接；未确认的保存请求会保留。'); });
    return () => controller.abort();
  }, [ownerId, refresh]);
  useEffect(() => {
    if (!ready || draftRestored) return;
    const rotating = records.find(record => record.reference === draft?.editing);
    if (rotating?.isOwner && rotating.credentialRef && rotating.credentialRevision) setEditing({ ...rotating, credentialRef: rotating.credentialRef, credentialRevision: rotating.credentialRevision });
    const output = records.find(record => record.reference === draft?.outputEditing);
    if (output?.isOwner) setOutputEditing(output);
    setDraftRestored(true);
  }, [ready, draftRestored, records, draft]);
  useEffect(() => {
    if (!draftRestored || authEpoch() !== epoch.current) return;
    saveModelSettingsDraft(ownerId, { provider, protocol, endpoint, model, credentialSource, savedReference, outputTokens,
      editing: editing?.reference, outputEditing: outputEditing?.reference });
  }, [ownerId, draftRestored, provider, protocol, endpoint, model, credentialSource, savedReference, outputTokens, editing, outputEditing]);
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
  function finished(s: ModelSetup, submittedEditor: boolean) {
    if (!releaseActive(s)) return false;
    setConfirmStopWaiting(false);
    if (submittedEditor) { setEditing(undefined); setOutputEditing(undefined); setOutputTokens(''); setKey(''); setModel(''); setSubmitted(false); }
    setSavedForReturn(true); setRefresh(n => n + 1); return true;
  }
  function accountChanged() {
    clearModelSettingsDraft(ownerId); setDraftRestored(false);
    setKey(''); setModel(''); setEditing(undefined); setOutputEditing(undefined); setOutputTokens(''); setConfirmRevoke(''); setRecords([]); setPending(null); setReady(false);
    setCredentials([]); setUnresolved([]); setConfirmStopWaiting(false); setError('当前登录账户已改变。已清除输入，请刷新页面后重新进入自己的模型设置。');
  }
  async function verifyOwner() {
    const current = await api.session();
    if (!alive.current) throw new Error('Unmounted');
    if (current.id !== ownerId) { accountChanged(); throw new ModelRequestError(403, 'EXPECTED_OWNER_MISMATCH'); }
  }
  function matchModel(configured: OwnerModel, s: ModelSetup) {
    if (configured.provider !== s.provider || configured.baseURL !== s.baseURL || configured.model !== s.model || (configured.protocol ?? 'chat-completions') !== (s.protocol ?? 'chat-completions')
        || configured.thinkingMode !== s.thinkingMode || configured.maxOutputTokens !== s.maxOutputTokens || (configured.credentialRef ?? undefined) !== s.credential?.credentialRef
        || (configured.credentialRevision ?? undefined) !== s.credential?.credentialRevision || s.reference && configured.reference !== s.reference || !configured.available) throw new Error('模型保存回执无法核对。');
  }
  function matchDefault(selected: OwnerModel, s: ModelSetup) {
    if (selected.reference !== s.reference || (selected.protocol ?? 'chat-completions') !== (s.protocol ?? 'chat-completions') || selected.thinkingMode !== s.thinkingMode || selected.maxOutputTokens !== s.maxOutputTokens || !selected.isDefault || !selected.available) throw new Error('默认模型尚未确认；请核对原设置。');
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
    if (s.stage === 'default' && !setupDispatched(s, 'model')) return;
    setEditing(undefined); setOutputEditing(undefined); setKey('');
    if (s.credential) {
      setCredentials(values => [...values.filter(c => c.credentialRef !== s.credential!.credentialRef), s.credential!]);
      setCredentialSource('saved'); setSavedReference(s.credential.credentialRef);
    }
  }
  async function continueSetup(value: ModelSetup, recovering = false) {
    const submittedEditor = value.stage !== 'default' || setupDispatched(value, 'model');
    let s = value;
    let checkedOriginal = recovering;
    if (s.stage === 'credential') {
      const receipt = await personalRemoteApi.recoverCredential(s.credentialRequest, ownerId);
      if (!alive.current) return;
      checkedOriginal = true;
      s = retain({ ...s, credential: setupCredential(receipt, s), stage: 'model', dispatched: {} });
    }
    if (s.stage === 'model') {
      if (!s.credential && !s.noCredentials) throw new Error('缺少已确认的凭据引用。');
      let configured: OwnerModel;
      if (setupDispatched(s, 'model')) {
        configured = await recoverModel(s, 'model'); checkedOriginal = true;
      } else {
        s = retain({ ...s, dispatched: { ...s.dispatched, model: true } });
        try {
          configured = await ownerModelApi.configure(ownerId, { provider: s.provider, baseURL: s.baseURL, model: s.model,
            ...(s.credential ? { credentialRef: s.credential.credentialRef, credentialRevision: s.credential.credentialRevision } : {}), requestId: s.modelRequest,
            ...(s.protocol ? { protocol: s.protocol } : {}), ...(s.thinkingMode ? { thinkingMode: s.thinkingMode } : {}),
            ...(s.maxOutputTokens !== undefined ? { maxOutputTokens: s.maxOutputTokens } : {}) }, s.reference);
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
    if (!finished(s, submittedEditor)) return false;
    setNotice(!submittedEditor ? '默认模型已确认。当前表单中的未提交输入仍未保存。' : checkedOriginal ? '原保存已核对完成。当前默认模型以最新列表为准。' : s.rotating ? '密钥已更新。旧任务绑定会按服务端规则重新检查。' : s.chooseDefault ? '模型已保存并设为默认。可以返回工作区。' : '模型已保存。可以返回工作区。');
    return true;
  }
  function stopWaiting() {
    if (!pending || busy || unresolved.length >= 100) return;
    try {
      const previous = readModelSetups(localStorage.getItem(unresolvedStorage), ownerId);
      if (previous.length >= 100) throw new Error('未确认记录已满。');
      const next = [...previous.filter(s => s.modelRequest !== pending.modelRequest), setupMetadata(pending)];
      localStorage.setItem(unresolvedStorage, JSON.stringify(next)); releaseActive(pending);
      setUnresolved(next); setConfirmStopWaiting(false);
      if (pending.stage !== 'default' || setupDispatched(pending, 'model')) { setEditing(undefined); setOutputEditing(undefined); setOutputTokens(''); setKey(''); }
      setRefresh(n => n + 1);
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
    if (lock.current) return; lock.current = true; setBusy(true); setError(''); setNotice(''); setSavedForReturn(false);
    try { await verifyOwner(); await work(); }
    catch (e) { if (alive.current && (e instanceof ModelRequestError || e instanceof RemoteRequestError) && e.code === 'EXPECTED_OWNER_MISMATCH') accountChanged(); else if (alive.current) setError(e instanceof ModelRequestError || e instanceof RemoteRequestError ? e.message : '设置尚未确认，请核对原请求或重新读取设置。'); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  function save() {
    setSubmitted(true);
    if (pending || !ready || !capability?.enabled || invalidOutput || Object.keys(fieldErrors).length) return;
    let baseURL: string;
    try { baseURL = modelEndpoint(endpoint); }
    catch { return; }
    const selectedModel = model.trim();
    void run(async () => {
      const s = retain({ owner: ownerId, provider, baseURL, model: selectedModel,
        ...(protocol ? { protocol } : {}), dispatched: {},
        ...(editing?.thinkingMode ? { thinkingMode: editing.thinkingMode } : {}),
        ...(outputLimit !== undefined ? { maxOutputTokens: outputLimit } : {}),
        credentialRequest: crypto.randomUUID(), modelRequest: crypto.randomUUID(), defaultRequest: crypto.randomUUID(),
        stage: !editing && credentialSource !== 'new' ? 'model' : 'credential', chooseDefault: editing ? editing.isDefault : true,
        ...(!editing && credentialSource === 'none' ? { noCredentials: true as const } : {}),
        ...(!editing && credentialSource === 'saved' ? { credential: selectedCredential! } : {}),
        ...(editing ? { reference: editing.reference, rotating: { credentialRef: editing.credentialRef, credentialRevision: editing.credentialRevision } } : {}) }, { begin: true });
      if (s.credential || s.noCredentials) { await continueSetup(s); return; }
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
          ...(record.maxOutputTokens !== undefined ? { maxOutputTokens: record.maxOutputTokens } : {}),
          credentialRequest: crypto.randomUUID(), modelRequest: crypto.randomUUID(), defaultRequest: crypto.randomUUID(),
          stage: 'default', reference: record.reference, chooseDefault: true, dispatched: {} }, { begin: true }));
        if (completed) setNotice(model || outputEditing ? '默认模型已更新。当前表单中的未提交输入仍未保存。' : '默认模型已更新。'); return;
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
  function rotate(record: OwnerModel) { if (!record.isOwner || !record.credentialRef || !record.credentialRevision) return; setEditing({ ...record, credentialRef: record.credentialRef, credentialRevision: record.credentialRevision }); setOutputEditing(undefined); setOutputTokens(record.maxOutputTokens?.toString() ?? ''); setCredentialSource('new'); setSavedReference(''); setProvider(record.provider); setProtocol(record.protocol); setEndpoint(record.baseURL); setModel(record.model); setKey(''); setError(''); setNotice(''); }
  function editOutput(record: OwnerModel) {
    if (!record.isOwner) return;
    setOutputEditing(record); setEditing(undefined); setOutputTokens(record.maxOutputTokens?.toString() ?? ''); setKey(''); setError(''); setNotice('');
  }
  function saveOutput() {
    const record = outputEditing;
    if (!record || pending || invalidOutput || !ready || !capability?.enabled) return;
    void run(async () => {
      await continueSetup(retain({ owner: ownerId, provider: record.provider, baseURL: record.baseURL, model: record.model,
        ...(record.protocol ? { protocol: record.protocol } : {}), ...(record.thinkingMode ? { thinkingMode: record.thinkingMode } : {}),
        ...(outputLimit !== undefined ? { maxOutputTokens: outputLimit } : {}),
        credentialRequest: crypto.randomUUID(), modelRequest: crypto.randomUUID(), defaultRequest: crypto.randomUUID(),
        stage: 'model', reference: record.reference, chooseDefault: record.isDefault, dispatched: {},
        ...(record.credentialRef && record.credentialRevision ? { credential: {
          credentialRef: record.credentialRef, credentialRevision: record.credentialRevision,
          providerId: 'byok-chat-v1', destination: new URL(record.baseURL).origin, status: 'active',
        } } : { noCredentials: true as const }),
      }, { begin: true }));
    });
  }
  function currentCredential(record: OwnerModel) { return credentials.find(c => c.credentialRef === record.credentialRef && c.status === 'active' && c.providerId === 'byok-chat-v1' && c.destination === new URL(record.baseURL).origin && c.credentialRevision !== record.credentialRevision); }
  function rebind(record: OwnerModel) {
    if (!record.isOwner || !record.credentialRef || !record.credentialRevision) return;
    const rotating = { credentialRef: record.credentialRef, credentialRevision: record.credentialRevision };
    const credential = currentCredential(record); if (!credential || pending) return;
    void run(async () => {
      await continueSetup(retain({ owner: ownerId, provider: record.provider, baseURL: record.baseURL, model: record.model,
        ...(record.protocol ? { protocol: record.protocol } : {}), dispatched: {},
        ...(record.thinkingMode ? { thinkingMode: record.thinkingMode } : {}),
        ...(record.maxOutputTokens !== undefined ? { maxOutputTokens: record.maxOutputTokens } : {}),
        credentialRequest: crypto.randomUUID(), modelRequest: crypto.randomUUID(), defaultRequest: crypto.randomUUID(),
        stage: 'model', chooseDefault: record.isDefault, reference: record.reference, credential,
        rotating }, { begin: true }));
    });
  }
  async function sharing(record: OwnerModel) {
    await run(async () => {
      const visibility: 'personal' | 'team' = record.visibility === 'team' ? 'personal' : 'team';
      const key = await commandKeys(`sharing:${record.reference}`, { reference: record.reference, visibility });
      const pending = { requestId: key.requestId, reference: record.reference, visibility };
      localStorage.setItem(sharingStorage, JSON.stringify(pending)); setPendingSharing(pending);
      try { await ownerModelApi.sharing(ownerId, record.reference, visibility, key.requestId); }
      catch (error) {
        if (error instanceof ModelRequestError && definitivelyRejected(error.status)) {
          localStorage.removeItem(sharingStorage); setPendingSharing(null); key.acknowledged();
        }
        throw error;
      }
      key.acknowledged(); localStorage.removeItem(sharingStorage); setPendingSharing(null);
      setRefresh(n => n + 1); setNotice(visibility === 'team' ? '团队成员现在可使用此模型。' : '模型已设为个人使用。');
    });
  }
  async function recoverSharing() {
    if (!pendingSharing) return;
    await run(async () => {
      const receipt = await ownerModelApi.recover(ownerId, pendingSharing.requestId);
      if (receipt.action !== 'model.sharing' || receipt.result.reference !== pendingSharing.reference
          || receipt.result.visibility !== pendingSharing.visibility) throw new Error('共享原请求尚未确认');
      localStorage.removeItem(sharingStorage); setPendingSharing(null); setRefresh(n => n + 1);
      setNotice('原共享请求已核对。');
    });
  }
  const availableDefault = records.find(r => r.isDefault && r.available);
  const matchingCredentials = credentials.filter(c => {
    try { return c.status === 'active' && c.providerId === 'byok-chat-v1' && c.destination === new URL(modelEndpoint(endpoint)).origin; }
    catch { return false; }
  });
  const selectedCredential = matchingCredentials.find(c => c.credentialRef === savedReference);
  const fieldErrors: Record<string, string> = {};
  if (!model.trim()) fieldErrors.model = '填写账户可用的模型名称。';
  else if (!/^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,119}$/.test(model.trim()) || model.trim() === key.trim()) fieldErrors.model = '请核对模型名称；密钥只能填入 API 密钥字段。';
  try { modelEndpoint(endpoint); } catch { fieldErrors.endpoint = '填写有效的 HTTP 或 HTTPS API 地址。'; }
  if ((editing || credentialSource === 'new') && !key.trim()) fieldErrors.key = '填写 API 密钥，或选择无需认证 / 已保存的凭据。';
  if (!editing && credentialSource === 'saved' && !selectedCredential) fieldErrors.credential = '选择匹配此模型端点的有效凭据。';
  const outputField = <div><label>单次输出上限（token）<input aria-label="单次输出上限（token）" type="number" inputMode="numeric" min={1} step={1}
    aria-invalid={invalidOutput} aria-describedby={`model-output-help${invalidOutput ? ' model-output-error' : ''}`}
    value={outputTokens} onChange={e => setOutputTokens(e.target.value)} placeholder="默认 4096"/></label>
    <p id="model-output-help" className="quiet">留空使用 4096。推理也可能占用输出额度；实际支持范围由模型提供方决定。这不是费用上限。</p>
    {invalidOutput && <p id="model-output-error" className="error-message" role="alert">请输入正整数；数值不能超过浏览器可准确表示的整数范围。</p>}</div>;
  return <section className="model-settings" aria-labelledby="model-settings-title">
    <div className="page-heading"><div><p className="quiet">我的资源 · 模型</p><h1 id="model-settings-title">我的模型/API</h1><p>保存模型后，在研究中选择它；保存设置不会发起模型调用。</p></div><button className="secondary" onClick={onBack}>{returnLabel}</button></div>
    <p className="model-purpose">研究内容会发送给所选模型提供方，费用由你的提供方账户承担。密钥加密保存，不回显。</p>
    {onCredentials && <button className="secondary" disabled={busy} onClick={onCredentials}>管理我的凭据与连接</button>}
    {error && <div className="error-message" role="alert">{error}</div>}{notice && <div className="success-message" role="status">{notice}</div>}
    {savedForReturn && returnLabel === '返回原研究' && <div className="state-note"><p>设置已确认。返回后核对模型选择再开始，已有会话的模型绑定不会自动改变。</p><button className="primary" onClick={onBack}>继续原研究</button></div>}
    {pendingSharing && <p role="alert">共享请求尚未确认。<button disabled={busy} onClick={() => void recoverSharing()}>核对原共享请求</button></p>}
    {!ready && !error && <p role="status">正在读取模型设置…</p>}
    <button className="text-button" disabled={busy} onClick={() => { setError(''); setRefresh(n => n + 1); }}>重新读取设置</button>
    {ready && !capability?.enabled && <div className="state-note"><strong>此部署尚未启用安全模型设置。</strong><p>请联系部署管理员启用个人模型保险库。无需向管理员发送 API 密钥。</p></div>}
    {pending && <div className="state-note"><h2>上次保存尚未确认</h2><p>已保留原请求，密钥未保存在浏览器中。核对已发出的操作后，只继续尚未发送的后续设置。</p><button className="primary" disabled={busy} onClick={() => void run(() => continueSetup(pending, true))}>{busy ? '正在核对…' : '核对并继续原保存'}</button><button disabled={busy || unresolved.length >= 100} onClick={() => setConfirmStopWaiting(true)}>停止等待此保存</button>{confirmStopWaiting && <div><p>原操作仍可能已完成。停止等待只解除本页编辑锁，原请求保留供只读核对。</p><button disabled={busy} onClick={stopWaiting}>确认停止等待并保留原请求</button><button disabled={busy} onClick={() => setConfirmStopWaiting(false)}>继续等待</button></div>}</div>}
    {unresolved.length > 0 && <div className="state-note"><h2>未确认的原请求（{unresolved.length}）</h2>{unresolved.map(s => <div key={s.modelRequest}><p>{s.model} · {s.stage === 'credential' ? '凭据保存' : s.stage === 'model' ? '模型保存' : '默认选择'}</p><button disabled={busy} onClick={() => void run(() => checkArchived(s))}>核对保留的原请求</button></div>)}</div>}
    {records.length > 0 && <div className="model-records">{records.map(record => <article className="model-record" key={record.reference}><div><h2>{record.model}</h2><p>{record.visibility === 'team' ? '团队共享' : '个人'} · {record.ownerId}</p><p>{record.provider === 'openai' ? 'OpenAI' : '兼容 OpenAI 的服务'} · {new URL(record.baseURL).host}</p><p>单次输出上限：{record.maxOutputTokens ?? 4096} token{record.maxOutputTokens === undefined ? '（默认）' : ''}</p><span className={`badge status-${record.available ? 'completed' : 'failed'}`}>{record.isDefault && record.available ? '默认模型' : record.status === 'revoked' ? '已撤销' : record.available ? '已保存' : '密钥需更新'}</span></div>{record.status !== 'revoked' && <div className="button-row">{!record.isDefault && <button disabled={busy || !!pending || !record.available} onClick={() => command(record, 'default')}>设为默认</button>}{record.isOwner && currentCredential(record) && <button disabled={busy || !!pending} onClick={() => rebind(record)}>绑定更新后的凭据</button>}{record.isOwner && <><button disabled={busy || !!pending || !capability?.enabled || !record.available} onClick={() => editOutput(record)}>调整输出额度</button><button disabled={busy || !!pending || !capability?.enabled || !record.credentialRef || !!currentCredential(record)} onClick={() => rotate(record)}>更新密钥</button><button className="text-button danger" disabled={busy || !!pending} onClick={() => setConfirmRevoke(record.reference)}>撤销模型</button><button disabled={busy || !!pending || !!pendingSharing} onClick={() => void sharing(record)}>{record.visibility === 'team' ? '改为个人使用' : '共享给团队'}</button></>}</div>}{confirmRevoke === record.reference && <div className="state-note"><p>确认撤销 {record.model}？它将不能用于新任务，原任务会继续接受权限检查。</p><button className="secondary danger" disabled={busy} onClick={() => command(record, 'revoke')}>确认撤销</button><button disabled={busy} onClick={() => setConfirmRevoke('')}>保留模型</button></div>}</article>)}</div>}
    {ready && capability?.enabled && !pending && outputEditing && <form className="model-form" onSubmit={event => { event.preventDefault(); saveOutput(); }}>
      <h2>调整 {outputEditing.model} 的输出额度</h2>
      <p>保留当前凭据，无需重新输入密钥。新建研究会话会使用新设置；已有会话不会自动切换，请先核对原任务。</p>
      <fieldset disabled={busy}>{outputField}</fieldset>
      <div className="button-row"><button className="primary" disabled={busy || invalidOutput}>{busy ? '正在保存…' : '保存输出额度'}</button>
        <button type="button" disabled={busy} onClick={() => { setOutputEditing(undefined); setOutputTokens(''); }}>取消调整</button></div>
    </form>}
    {ready && capability?.enabled && !pending && !outputEditing && <form className="model-form" noValidate onSubmit={event => { event.preventDefault(); save(); }}>
      <h2>{editing ? `更新 ${editing.model} 的密钥` : availableDefault ? '添加另一个模型' : '设置默认模型'}</h2>
      <p className="quiet">未提交的模型名称和设置保留在此浏览器标签页。API 密钥只留在当前表单，离开或刷新后需重新输入。</p>
      {!editing && <label>快捷配置<select aria-label="模型快捷配置" value="" disabled={busy} onChange={e => {
        const preset = MODEL_PROVIDER_PRESETS.find(p => p.id === e.target.value); if (!preset) return;
        setProvider(preset.provider); setEndpoint(preset.baseURL); setModel(preset.model); setProtocol(preset.protocol); setKey(''); setSavedReference('');
      }}><option value="">手动配置，或选择一个预设</option>{MODEL_PROVIDER_PRESETS.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}</select></label>}
      <fieldset disabled={busy}><label>提供方<select aria-label="模型提供方" disabled={!!editing} value={provider} onChange={e => { setProvider(e.target.value as OwnerModel['provider']); setEndpoint(e.target.value === 'openai' ? 'https://api.openai.com/v1' : ''); }}><option value="openai">OpenAI</option><option value="openai-compatible">兼容 OpenAI 的服务</option></select></label>
      <label>API 协议<select aria-label="模型 API 协议" disabled={!!editing} value={protocol ?? 'chat-completions'} onChange={e => setProtocol(e.target.value as OwnerModel['protocol'])}><option value="chat-completions">Chat Completions</option><option value="responses">Responses</option></select></label>
      <label>模型名称<input aria-label="模型名称" aria-invalid={submitted && !!fieldErrors.model} aria-describedby={submitted && fieldErrors.model ? 'model-name-error' : undefined} autoComplete="off" required maxLength={120} disabled={!!editing} value={model} onChange={e => setModel(e.target.value)} placeholder="填写账户可用的模型名称"/></label>
      {submitted && fieldErrors.model && <p id="model-name-error" className="error-message" role="alert">{fieldErrors.model}</p>}
      {provider === 'openai-compatible' && <><label>API 端点<input aria-label="API 端点" aria-invalid={submitted && !!fieldErrors.endpoint} aria-describedby={submitted && fieldErrors.endpoint ? 'model-endpoint-error' : undefined} autoComplete="off" required disabled={!!editing} value={endpoint} onChange={e => setEndpoint(e.target.value)} placeholder="https://你的模型服务/v1"/></label>{submitted && fieldErrors.endpoint && <p id="model-endpoint-error" className="error-message" role="alert">{fieldErrors.endpoint}</p>}</>}
      <details><summary>输出设置（可选）</summary>{outputField}</details>
      {!editing && <label>凭据来源<select aria-label="模型凭据来源" value={credentialSource} onChange={e => { setCredentialSource(e.target.value as 'new' | 'saved' | 'none'); setKey(''); setSavedReference(''); }}><option value="none">无需认证</option><option value="new">直接输入新密钥</option><option value="saved">选择我的已保存凭据</option></select></label>}
      {!editing && credentialSource === 'saved' ? <><label>已保存的模型凭据<select aria-label="已保存的模型凭据" aria-invalid={submitted && !!fieldErrors.credential} aria-describedby={submitted && fieldErrors.credential ? 'model-credential-error' : undefined} value={selectedCredential ? savedReference : ''} onChange={e => setSavedReference(e.target.value)}><option value="">选择匹配此模型端点的凭据</option>{matchingCredentials.map(c => <option key={c.credentialRef} value={c.credentialRef}>{c.destination} · {c.credentialRef}</option>)}</select></label>{submitted && fieldErrors.credential && <p id="model-credential-error" className="error-message" role="alert">{fieldErrors.credential}</p>}<p className="quiet">只绑定当前用户的已保存凭据引用，不重新保存密钥。保存时仍由服务端核对归属、授权、目标和版本。{!matchingCredentials.length && '当前没有匹配的有效凭据；可更改端点、重新读取设置或直接输入新密钥。'}</p></> : credentialSource !== 'none' || editing ? <><label>API 密钥<input aria-label="API 密钥" aria-invalid={submitted && !!fieldErrors.key} aria-describedby={submitted && fieldErrors.key ? 'model-key-error' : undefined} type="password" autoComplete="new-password" required maxLength={4096} value={key} onChange={e => setKey(e.target.value)} placeholder={editing ? '输入新的密钥' : '输入自己的 API 密钥'}/></label>{submitted && fieldErrors.key && <p id="model-key-error" className="error-message" role="alert">{fieldErrors.key}</p>}</> : <p>此模型服务无需认证；不会发送 API 密钥。</p>}</fieldset>
      <div className="button-row"><button className="primary" disabled={busy || invalidOutput}>{busy ? '正在保存…' : editing ? '保存新密钥' : credentialSource === 'saved' ? '保存模型并设为默认' : '保存并设为默认'}</button>{editing && <button type="button" disabled={busy} onClick={() => { setEditing(undefined); setOutputTokens(''); setKey(''); setModel(''); }}>取消更新</button>}</div>
    </form>}
    <details className="technical-detail"><summary>兼容性与设置说明</summary><p>按提供方要求选择 Chat Completions 或 Responses，填写实际 HTTP 或 HTTPS API 地址。保存配置不会发送模型请求，也不证明远端模型兼容。</p><p>此默认模型用于 Agno 原生任务。已有远端服务继续使用其自身配置。</p><p>撤销模型不删除历史记录；密钥轮换后旧任务绑定需重新核对。</p></details>
  </section>;
}
