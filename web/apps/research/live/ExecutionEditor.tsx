import { useEffect, useState } from 'react';
import { api } from '../../../api.js';
import type { FactoryApplication, UserConnection } from '../../../models.js';
import type { ExecutionSelection } from './setupClient.js';
import type { ResearchAgreement } from '../types.js';

const pinKey = (pin: { id: string; version: number; sha256: string }) => `${pin.id}:${pin.version}:${pin.sha256}`;
const localDateTime = (seconds: number) => { const date = new Date(seconds * 1000); return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16); };
export function ExecutionEditor({ agreement, disabled, onSave, onApplications, onResources, selection }: { agreement: ResearchAgreement; disabled: boolean; onSave: (agreement: ResearchAgreement) => void; onApplications: () => void; onResources: () => void; selection?: ExecutionSelection }) {
  const initial = agreement.execution;
  const [applications, setApplications] = useState<FactoryApplication[]>([]);
  const [connections, setConnections] = useState<UserConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [applicationKey, setApplicationKey] = useState(selection ? pinKey(selection.applicationRef) : initial ? pinKey(initial.applicationRef) : '');
  const [mode, setMode] = useState(selection?.mode ?? initial?.mode ?? '');
  const [choices, setChoices] = useState(selection ? {} : initial?.materialChoices ?? {});
  const [refs, setRefs] = useState(selection?.connectionRefs ?? initial?.connectionRefs ?? {});
  const [deadline, setDeadline] = useState(initial ? localDateTime(initial.deadline) : '');
  const [calls, setCalls] = useState(initial ? String(initial.perRoundCaps.toolCalls) : '');
  const [tokens, setTokens] = useState(initial?.perRoundCaps.tokenLimit?.toString() ?? '');
  const [amount, setAmount] = useState(initial?.perRoundCaps.amountMicros == null ? '' : String(initial.perRoundCaps.amountMicros / 1_000_000));
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError('');
    void Promise.all([api.applications(controller.signal), api.userConnections(controller.signal)]).then(([apps, resources]) => { if (!controller.signal.aborted) { setApplications(apps); setConnections(resources); } }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '执行配置读取失败'); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [reload]);
  const application = applications.find(item => pinKey(item) === applicationKey);
  const selectedMode = application?.modes[mode];
  return <form className="rw-form" aria-label="执行配置" onSubmit={event => {
    event.preventDefault();
    if (!application || !selectedMode) return;
    onSave({ ...agreement, execution: { applicationRef: { id: application.id, version: application.version, sha256: application.sha256 }, mode, materialChoices: choices, connectionRefs: refs, deadline: new Date(deadline).getTime() / 1000, perRoundCaps: { rounds: 1, toolCalls: Number(calls), tokenLimit: agreement.budget.tokenLimit === null ? null : Number(tokens), amountMicros: agreement.budget.tokenLimit === null ? null : Math.round(Number(amount) * 1_000_000), currency: agreement.budget.currency } } });
  }}><h3>研究执行配置</h3><p>选择已发布的执行应用与已有连接。保存会形成新的待确认约定，不立即运行。自主研究资格与原预算由服务端核对。</p>
    <div className="rw-actions"><button type="button" onClick={onResources}>配置模型与资源</button><button type="button" onClick={onApplications}>管理与发布应用</button><button type="button" onClick={() => setReload(value => value + 1)}>重新读取可用配置</button></div>
    {loading && <p role="status">正在读取可用应用与连接…</p>}{error && <p role="alert">{error}</p>}
    {!loading && !error && !applications.length && <p>尚无可选的已发布应用。请先在应用管理中保存并发布适用的研究执行定义。</p>}
    <fieldset disabled={disabled || loading || !!error}><label>执行应用<select required value={applicationKey} onChange={event => { setApplicationKey(event.target.value); setMode(''); setChoices({}); setRefs({}); }}><option value="">请选择已发布版本</option>{initial && !application && <option value={pinKey(initial.applicationRef)}>原版本不在当前目录：{initial.applicationRef.id} v{initial.applicationRef.version}</option>}{applications.map(item => <option key={pinKey(item)} value={pinKey(item)}>{item.name} · v{item.version}</option>)}</select></label>
      <label>执行方式<select required value={mode} onChange={event => { setMode(event.target.value); setChoices({}); setRefs({}); }}><option value="">请选择执行方式</option>{Object.keys(application?.modes ?? {}).map(name => <option key={name} value={name}>{name}</option>)}</select></label>
      {Object.entries(selectedMode?.materialChoices ?? {}).map(([slot, choice]) => <label key={slot}>材料选择 · {slot}<select value={choices[slot] ? pinKey(choices[slot]) : ''} onChange={event => { const pin = choice.allowedRefs.find(item => pinKey(item) === event.target.value); setChoices(previous => { const next = { ...previous }; if (pin) next[slot] = pin; else delete next[slot]; return next; }); }}><option value="">使用已发布默认版本：{choice.defaultRef.id} v{choice.defaultRef.version}</option>{choice.allowedRefs.map(pin => <option key={pinKey(pin)} value={pinKey(pin)}>{pin.id} · v{pin.version}</option>)}</select></label>)}
      {selectedMode?.connectionRequirements.map(requirement => <label key={requirement.name}>资源连接 · {requirement.name}<select required={requirement.required} value={refs[requirement.name] ?? ''} onChange={event => setRefs(previous => { const next = { ...previous }; if (event.target.value) next[requirement.name] = event.target.value; else delete next[requirement.name]; return next; })}><option value="">未选择{requirement.required ? '（必需）' : '（可选）'}</option>{connections.filter(item => item.available && !item.taskId && item.kind === requirement.kind && requirement.requiredCapabilities.every(capability => item.capabilities.includes(capability))).map(item => <option key={item.ref} value={item.ref}>{item.registrationRef} · {item.ref.slice(0, 8)}</option>)}</select></label>)}
      <label>研究截止时间（本地时间）<input type="datetime-local" required value={deadline} onChange={event => setDeadline(event.target.value)}/></label>
      <label>每轮工具调用上限<input type="number" min="1" max={agreement.budget.toolCalls} step="1" required value={calls} onChange={event => setCalls(event.target.value)}/></label>
      {agreement.budget.tokenLimit !== null && <><label>每轮 Token 上限<input type="number" min="0" max={agreement.budget.tokenLimit} step="1" required value={tokens} onChange={event => setTokens(event.target.value)}/></label><label>每轮金额上限（{agreement.budget.currency}）<input type="number" min="0" max={agreement.budget.amountMicros! / 1_000_000} step="0.000001" required value={amount} onChange={event => setAmount(event.target.value)}/></label></>}
      <button className="rw-primary" disabled={!application || !selectedMode}>保存配置并生成待确认版本</button>
    </fieldset>
  </form>;
}
