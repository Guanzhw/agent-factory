import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api.js';
import { applicationEnvironmentApi, type ApplicationEnvironment, type EnvironmentBindingReceipt, type EnvironmentContinuation as Continuation } from './applicationEnvironmentApi.js';

type Pending = { requestId: string; previewHash: string; projectId: string; environmentId: string };
type Props = { ownerId: string; environment: ApplicationEnvironment; disabled: boolean; onPending: (value: boolean) => void; onChanged: (environment: ApplicationEnvironment) => void; onNewEnvironment: () => void };

export function EnvironmentContinuation(props: Props) { return <ContinuationPanel key={`${props.ownerId}:${props.environment.id}`} {...props} />; }
function ContinuationPanel({ ownerId, environment, disabled, onPending, onChanged, onNewEnvironment }: Props) {
  const storage = `factory-environment-binding:${encodeURIComponent(ownerId)}:${environment.id}`;
  const [pending, setPending] = useState<Pending | null>(() => {
    try {
      const value: unknown = JSON.parse(localStorage.getItem(storage) ?? 'null');
      if (!value || typeof value !== 'object') return null;
      const item = value as Record<string, unknown>;
      return typeof item.requestId === 'string' && /^[A-Za-z0-9_.:-]{8,80}$/.test(item.requestId)
        && typeof item.previewHash === 'string' && /^[a-f0-9]{64}$/.test(item.previewHash)
        && item.environmentId === environment.id && item.projectId === environment.projectId ? item as Pending : null;
    } catch { return null; }
  });
  const [preview, setPreview] = useState<Continuation>(); const [notice, setNotice] = useState(''); const [busy, setBusy] = useState(false);
  const lock = useRef(false); const live = useRef(true);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  useEffect(() => { onPending(!!pending); return () => onPending(false); }, [pending, onPending]);
  useEffect(() => { setPreview(undefined); }, [environment.state, environment.credentialBindingFingerprint]);
  async function work(operation: () => Promise<void>) {
    if (lock.current) return; lock.current = true; setBusy(true);
    try {
      const owner = await api.session(); if (!live.current || owner.id !== ownerId) return;
      await operation();
    } catch { if (live.current) setNotice('恢复条件或绑定结果尚未确认。原环境、会话和请求保留；请读取原记录。'); }
    finally { lock.current = false; if (live.current) setBusy(false); }
  }
  async function inspect() {
    if (disabled || pending) return;
    await work(async () => {
      const value = await applicationEnvironmentApi.continuation(ownerId, environment.id);
      if (!live.current) return;
      if (value.environmentId !== environment.id || value.projectId !== environment.projectId
          || value.originalWorkReplay !== false || value.researchSubmitted !== false) throw new Error('scope');
      setPreview(value); setNotice(value.message);
    });
  }
  function accept(value: EnvironmentBindingReceipt, original: Pending) {
    if (value.requestId !== original.requestId || value.state !== 'committed'
        || value.environment.id !== original.environmentId || value.environment.projectId !== original.projectId
        || value.runtimePrepared !== false || value.researchSubmitted !== false) throw new Error('scope');
    localStorage.removeItem(storage); setPending(null); setPreview(undefined); onChanged(value.environment);
    setNotice('新凭据绑定已保存。此请求未恢复环境或发送目标；请核对当前环境状态，再明确恢复并续接原会话。');
  }
  async function confirm() {
    if (disabled || pending || !preview?.canRebind || !preview.previewHash) return;
    const reviewed = preview;
    await work(async () => {
      // Re-read the exact displayed choice immediately before the first write.
      const current = await applicationEnvironmentApi.continuation(ownerId, environment.id);
      if (!live.current) return;
      if (current.environmentId !== environment.id || current.projectId !== environment.projectId
          || current.originalWorkReplay !== false || current.researchSubmitted !== false) throw new Error('scope');
      if (!current.canRebind || current.previewHash !== reviewed.previewHash) {
        setPreview(current); setNotice('恢复条件已变化。请重新读取并确认。'); return;
      }
      const original = { requestId: crypto.randomUUID(), previewHash: reviewed.previewHash!, projectId: environment.projectId, environmentId: environment.id };
      localStorage.setItem(storage, JSON.stringify(original)); onPending(true); setPending(original);
      let result;
      try { result = await applicationEnvironmentApi.rebind(ownerId, environment.id, original.requestId, original.previewHash); }
      catch (error) {
        // These exact 409s precede the journal commit. Unknown transport or
        // post-commit receipt failures keep the original request for GET only.
        if (live.current && error instanceof ApiError && error.status === 409
            && ['ENVIRONMENT_BINDING_PREVIEW_CHANGED', 'ENVIRONMENT_MODEL_CHANGED', 'ENVIRONMENT_STOP_REQUIRED',
              'ENVIRONMENT_CURRENT_CREDENTIAL_UNAVAILABLE', 'ENVIRONMENT_BINDING_HISTORY_LIMIT'].some(code => code === error.code || code === error.message)) {
          localStorage.removeItem(storage); setPending(null); setPreview(undefined);
          setNotice('新绑定未保存：恢复条件已变化。请重新读取并确认；原记录保留。'); return;
        }
        throw error;
      }
      if (live.current) accept(result, original);
    });
  }
  async function recover() {
    if (!pending || busy) return;
    const original = pending;
    await work(async () => {
      const result = await applicationEnvironmentApi.bindingRequest(ownerId, original.requestId);
      if (live.current) accept(result, original);
    });
  }
  return <section aria-label="环境恢复条件">
    {notice && <p role="status">{notice}</p>}
    {pending ? <><p>原绑定请求待核对。读取记录不会重发绑定或研究目标。</p><button disabled={busy} onClick={() => void recover()}>核对原绑定请求</button></>
      : <button disabled={disabled || busy} onClick={() => void inspect()}>核对恢复条件</button>}
    {preview?.canRebind && <><p>将使用当前已验证的个人凭据，保留同一环境、项目和会话数据。原生轮次是否可继续仍须另行核对。</p>{preview.currentModelChoice && <p>将使用的模型：{preview.currentModelChoice.name}{preview.currentModelChoice.endpoint ? ` · ${preview.currentModelChoice.endpoint}` : ''}。原模型与版本记录保留。</p>}<button disabled={disabled || busy || !!pending} onClick={() => void confirm()}>确认新凭据绑定</button></>}
    {preview?.nextAction === 'new-environment' && <button disabled={disabled || busy || !!pending} onClick={onNewEnvironment}>创建新环境，保留旧结果</button>}
    {preview && <details><summary>恢复诊断</summary><p>{preview.reason} · {preview.classification}</p><p>不会重放原研究；尚未验证原生检查点续跑。</p></details>}
  </section>;
}
