import { useEffect, useState } from 'react';
import { api } from '../../../api.js';
import type { FactoryApplication, UserConnection } from '../../../models.js';
import { setupApi, type ExecutionSelection } from './setupClient.js';
import type { ResearchAgreement } from '../types.js';
import { projectDraftKey, useProjectDraft } from './projectDraft.js';

const pinKey = (pin: { id: string; version: number; sha256: string }) => `${pin.id}:${pin.version}:${pin.sha256}`;
const localDateTime = (seconds: number) => { const date = new Date(seconds * 1000); return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16); };
export function ExecutionEditor({ ownerId, projectId, goalVersion, agreement, disabled, onSave, onApplications, onResources, selection }: { ownerId: string; projectId: string; goalVersion: number; agreement: ResearchAgreement; disabled: boolean; onSave: (agreement: ResearchAgreement) => void; onApplications: () => void; onResources: () => void; selection?: ExecutionSelection }) {
  const initial = agreement.execution;
  const [applications, setApplications] = useState<FactoryApplication[]>([]);
  const [connections, setConnections] = useState<UserConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const draft = useProjectDraft(projectDraftKey(ownerId, projectId, goalVersion, `execution:${selection ? pinKey(selection.applicationRef) : 'current'}`), {
    applicationKey: selection ? pinKey(selection.applicationRef) : initial ? pinKey(initial.applicationRef) : '',
    mode: selection?.mode ?? initial?.mode ?? '',
    choices: selection ? {} : initial?.materialChoices ?? {},
    refs: selection?.connectionRefs ?? initial?.connectionRefs ?? {},
    deadline: initial ? localDateTime(initial.deadline) : '',
    calls: initial ? String(initial.perRoundCaps.toolCalls) : '',
    tokens: initial?.perRoundCaps.tokenLimit?.toString() ?? '',
    amount: initial?.perRoundCaps.amountMicros == null ? '' : String(initial.perRoundCaps.amountMicros / 1_000_000),
  });
  const { applicationKey, mode, choices, refs, deadline, calls, tokens, amount } = draft.value;
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError('');
    void Promise.all([api.applications(controller.signal), api.userConnections(controller.signal), setupApi.candidates(ownerId, controller.signal)]).then(([apps, resources, { workflowPin }]) => {
      if (controller.signal.aborted) return;
      setApplications(apps.map(item => ({ ...item, modes: Object.fromEntries(Object.entries(item.modes).filter(([, value]) => {
        const pin = value.nativeComponent;
        return pin?.kind === workflowPin.kind && pin.id === workflowPin.id && pin.revision === workflowPin.revision && pin.sha256 === workflowPin.sha256;
      })) })).filter(item => Object.keys(item.modes).length > 0));
      setConnections(resources);
    }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '执行配置读取失败'); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [ownerId, reload]);
  const application = applications.find(item => pinKey(item) === applicationKey);
  const selectedMode = application?.modes[mode];
  const originalRef = selection?.applicationRef ?? initial?.applicationRef;
  return <form className="rw-form" aria-label="执行配置" onSubmit={event => {
    event.preventDefault();
    if (disabled || loading || error || !application || !selectedMode) return;
    onSave({ ...agreement, execution: { applicationRef: { id: application.id, version: application.version, sha256: application.sha256 }, mode, materialChoices: choices, connectionRefs: refs, deadline: new Date(deadline).getTime() / 1000, perRoundCaps: { rounds: 1, toolCalls: Number(calls), tokenLimit: agreement.budget.tokenLimit === null ? null : Number(tokens), amountMicros: agreement.budget.tokenLimit === null ? null : Math.round(Number(amount) * 1_000_000), currency: agreement.budget.currency } } });
  }}><h3>研究执行配置</h3><p>选择兼容当前研究组件的已发布应用与已有连接。保存会形成新的待确认约定，不立即运行。通用应用可在应用工作区使用。</p>
    <div className="rw-actions"><button type="button" onClick={onResources}>配置模型与资源</button><button type="button" onClick={onApplications}>管理与发布应用</button><button type="button" onClick={() => setReload(value => value + 1)}>重新读取可用配置</button></div>
    {!draft.saved && <p role="alert">浏览器未能保留本地输入，离开或刷新前请先保留内容。</p>}
    {loading && <p role="status">正在读取可用应用与连接…</p>}{error && <p role="alert">{error}</p>}
    {!loading && !error && !applications.length && <p>没有兼容当前研究组件的已发布应用。请先准备并发布研究执行配置。</p>}
    {!loading && !error && applicationKey && (!application || (mode && !selectedMode)) && <p role="status">原执行配置不兼容当前研究组件或已不在可用目录中；保留原配置供核对，新研究需明确选择兼容版本。原运行仍可在实验页查看。</p>}
    <fieldset disabled={disabled || loading || !!error}><label>执行应用<select required value={applicationKey} onChange={event => { draft.change({ ...draft.value, applicationKey: event.target.value, mode: '', choices: {}, refs: {} }); }}><option value="">请选择已发布版本</option>{originalRef && applicationKey && !application && <option disabled value={applicationKey}>原版本不兼容或不在当前目录：{originalRef.id} v{originalRef.version}</option>}{applications.map(item => <option key={pinKey(item)} value={pinKey(item)}>{item.name} · v{item.version}</option>)}</select></label>
      <label>执行方式<select required value={mode} onChange={event => { draft.change({ ...draft.value, mode: event.target.value, choices: {}, refs: {} }); }}><option value="">请选择执行方式</option>{mode && !selectedMode && <option disabled value={mode}>原执行方式不兼容：{mode}</option>}{Object.keys(application?.modes ?? {}).map(name => <option key={name} value={name}>{name}</option>)}</select></label>
      {Object.entries(selectedMode?.materialChoices ?? {}).map(([slot, choice]) => <label key={slot}>材料选择 · {slot}<select value={choices[slot] ? pinKey(choices[slot]) : ''} onChange={event => { const pin = choice.allowedRefs.find(item => pinKey(item) === event.target.value); const next = { ...choices }; if (pin) next[slot] = pin; else delete next[slot]; draft.change({ ...draft.value, choices: next }); }}><option value="">使用已发布默认版本：{choice.defaultRef.id} v{choice.defaultRef.version}</option>{choice.allowedRefs.map(pin => <option key={pinKey(pin)} value={pinKey(pin)}>{pin.id} · v{pin.version}</option>)}</select></label>)}
      {selectedMode?.connectionRequirements.map(requirement => <label key={requirement.name}>资源连接 · {requirement.name}<select required={requirement.required} value={refs[requirement.name] ?? ''} onChange={event => { const next = { ...refs }; if (event.target.value) next[requirement.name] = event.target.value; else delete next[requirement.name]; draft.change({ ...draft.value, refs: next }); }}><option value="">未选择{requirement.required ? '（必需）' : '（可选）'}</option>{connections.filter(item => item.available && !item.taskId && item.kind === requirement.kind && requirement.requiredCapabilities.every(capability => item.capabilities.includes(capability))).map(item => <option key={item.ref} value={item.ref}>{item.registrationRef} · {item.ref.slice(0, 8)}</option>)}</select></label>)}
      <label>研究截止时间（本地时间）<input type="datetime-local" required value={deadline} onChange={event => draft.change({ ...draft.value, deadline: event.target.value })}/></label>
      <label>每轮工具调用上限<input type="number" min="1" max={agreement.budget.toolCalls} step="1" required value={calls} onChange={event => draft.change({ ...draft.value, calls: event.target.value })}/></label>
      {agreement.budget.tokenLimit !== null && <><label>每轮 Token 上限<input type="number" min="0" max={agreement.budget.tokenLimit} step="1" required value={tokens} onChange={event => draft.change({ ...draft.value, tokens: event.target.value })}/></label><label>每轮金额上限（{agreement.budget.currency}）<input type="number" min="0" max={agreement.budget.amountMicros! / 1_000_000} step="0.000001" required value={amount} onChange={event => draft.change({ ...draft.value, amount: event.target.value })}/></label></>}
      <button className="rw-primary" disabled={!application || !selectedMode}>保存配置并生成待确认版本</button>
    </fieldset>
  </form>;
}
