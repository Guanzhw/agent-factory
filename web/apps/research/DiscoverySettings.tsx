import { useEffect, useRef, useState } from 'react';
import { factoryRequest } from '../../api.js';
import { researchSessionsApi, type SessionOptions } from './researchSessionsClient.js';

interface DiscoverySettingsValue { enabled: boolean; modelConnectionRef: string | null; instruction: string }
interface DiscoveryState extends DiscoverySettingsValue {
  sessionId: string | null;
  decisions: { id: string; eventId: string; contentId: string; ownerId: string; decision: 'ignore' | 'attach' | 'new'; reason: string; sessionId: string | null; discoverySessionId: string | null; createdAt: string; deliveryId: string | null; delivery: { state: string; error: string | null; turnId: string | null } | null; sourceUnavailable: boolean }[];
}
const labels = { ignore: '忽略', attach: '接入已有对话', new: '新建对话' };
const deliveryLabels: Record<string, string> = { pending: '等待执行', dispatched: '已发起', adopted: '已纳入模型请求', failed: '投递失败', stopped: '已停止触发' };
const describe = (error: unknown) => error instanceof Error ? error.message : '团队资料发现操作失败，请重试。';
const chatUrl = (sessionId: string) => `?${new URLSearchParams({ tab: 'research', researchSession: sessionId })}`;

export function DiscoverySettings({ ownerId, onModels }: { ownerId: string; onModels: () => void }) {
  const [state, setState] = useState<DiscoveryState | null>(null);
  const [draft, setDraft] = useState<DiscoverySettingsValue | null>(null);
  const [models, setModels] = useState<SessionOptions['models']>([]);
  const [error, setError] = useState('');
  const [modelError, setModelError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const requestId = useRef(crypto.randomUUID());
  const edited = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    void factoryRequest<DiscoveryState>('/research/discovery', 'GET', undefined, controller.signal, ownerId).then(value => {
      if (!controller.signal.aborted) { setState(value); setDraft(current => edited.current ? current : { enabled: value.enabled, modelConnectionRef: value.modelConnectionRef, instruction: value.instruction }); setError(''); }
    }).catch(reason => { if (!controller.signal.aborted) setError(describe(reason)); });
    void researchSessionsApi.options(ownerId, controller.signal).then(value => {
      if (!controller.signal.aborted) { setModels(value.models); setModelError(''); }
    }).catch(reason => { if (!controller.signal.aborted) setModelError(describe(reason)); });
    return () => controller.abort();
  }, [ownerId, refresh]);
  function change(value: Partial<DiscoverySettingsValue>) {
    edited.current = true; setDraft(current => current && { ...current, ...value }); requestId.current = crypto.randomUUID(); setNotice('');
  }
  async function save() {
    if (!draft) return;
    setBusy(true); setError(''); setNotice('');
    try {
      await factoryRequest('/research/discovery', 'POST', { requestId: requestId.current, ...draft }, undefined, ownerId);
      edited.current = false;
      setNotice('团队资料发现设置已保存。'); requestId.current = crypto.randomUUID(); setRefresh(value => value + 1);
    } catch (reason) { setError(describe(reason)); }
    finally { setBusy(false); }
  }
  return <section className="rs-discovery" aria-labelledby="discovery-title">
    <h2 id="discovery-title">团队资料发现</h2>
    <p>团队发布新资料时，助手按你的关注方向判断是否忽略、接入已有对话，或新建对话继续研究。</p>
    {state && <p>当前状态：{state.enabled ? '已启用' : '已关闭'}</p>}
    <div className="rw-actions"><button type="button" disabled={busy} onClick={() => setRefresh(value => value + 1)}>刷新发现记录</button>{state?.sessionId && <a href={chatUrl(state.sessionId)}>查看发现助手完整对话</a>}</div>
    {error && <p className="rw-error" role="alert">{error}</p>}
    {!state && !error && <p role="status">正在读取团队资料发现设置…</p>}
    {draft && <form className="rw-form" onSubmit={event => { event.preventDefault(); void save(); }}><fieldset disabled={busy}>
      <label className="rs-discovery-toggle"><input type="checkbox" checked={draft.enabled} onChange={event => change({ enabled: event.target.checked })}/>启用我的团队资料发现</label>
      <label>发现助手模型<select required={draft.enabled} value={draft.modelConnectionRef ?? ''} onChange={event => change({ modelConnectionRef: event.target.value || null })}>
        <option value="">选择模型</option>
        {draft.modelConnectionRef && !models.some(model => model.connectionRef === draft.modelConnectionRef) && <option value={draft.modelConnectionRef}>当前配置：{draft.modelConnectionRef}（不可用）</option>}
        {models.map(model => <option key={model.connectionRef} value={model.connectionRef} disabled={!model.available}>{model.provider} · {model.model}{!model.available && '（不可用）'}</option>)}
      </select></label>
      {modelError && <p className="rw-error" role="alert">模型列表读取失败：{modelError}</p>}
      <button type="button" onClick={onModels}>管理我的模型/API</button>
      <label>关注方向与处理指令<textarea rows={4} value={draft.instruction} placeholder="例如：关注 Agent 记忆研究；相关资料接入现有研究，没有合适对话时新建。" onChange={event => change({ instruction: event.target.value })}/></label>
      <button className="rw-primary" type="submit">{busy ? '正在保存…' : '保存发现设置'}</button>
    </fieldset></form>}
    {notice && <p role="status">{notice}</p>}
    {state && <><h3>发现决策 · {state.decisions.length}</h3>{!state.decisions.length && <p className="rw-muted">还没有发现决策。</p>}
      <ul className="rs-trigger-list">{state.decisions.map(decision => <li key={decision.id}>
        <strong>{labels[decision.decision]}</strong><time dateTime={decision.createdAt}>{new Date(decision.createdAt).toLocaleString('zh-CN')}</time>
        <p>{decision.reason}</p><p>来源资料：<code>{decision.contentId}</code> · 发布成员：<code>{decision.ownerId}</code></p>
        {decision.sourceUnavailable && <p role="status">来源资料当前不可用。</p>}
        {decision.delivery && <p role="status">后续执行：{deliveryLabels[decision.delivery.state] ?? decision.delivery.state}{decision.delivery.error && ` · ${decision.delivery.error}`}</p>}
        {decision.sessionId && <a href={chatUrl(decision.sessionId)}>打开目标对话</a>}
        {decision.discoverySessionId && <a href={chatUrl(decision.discoverySessionId)}>查看本次发现对话</a>}
        <details><summary>核对记录</summary><p>决策：{decision.id}</p><p>事件：{decision.eventId}</p>{decision.deliveryId && <p>投递：{decision.deliveryId}</p>}{decision.delivery?.turnId && <p>轮次：{decision.delivery.turnId}</p>}</details>
      </li>)}</ul>
    </>}
  </section>;
}
