import { useEffect, useState } from 'react';
import { ApiError } from '../../../api.js';
import { useResearchCommand } from '../useProjectCommand.js';
import { setupApi, type SetupCandidates } from './setupClient.js';
import { assistantApi, type AssistantConfiguration, type QASetup, type QuestionBudget, type ResearchAssistant } from './assistantClient.js';
const errorText = (error: unknown) => error instanceof Error ? error.message : '读取助手配置失败。';
export const accountingNotice = '操作额度受限，token/费用未计量';
type Props = { ownerId: string; assistant: ResearchAssistant | null; setupId?: string; onSetup: (id: string) => void; onSaved: (value: ResearchAssistant) => void; onReload: () => void; onResources: () => void };
type ConfigureCommand = { action: 'configure'; body: AssistantConfiguration & { requestId: string; expectedRevision: number } };
type EnableCommand = { action: 'enable'; body: { requestId: string; expectedRevision: number; createIdentity: boolean; modelConnectionRef: string; setupId?: string; budget: QuestionBudget; associations: { enabled: boolean; maxRecipients: number } } };
type PreviousCommand = { action: 'create'; body: { requestId: string } } | { action: 'draft'; body: Parameters<typeof assistantApi.draft>[1] } | { action: 'publish'; body: { requestId: string } };

function PreviousRequest({ ownerId, storageKey, onSaved, onSetup, onRecovered }: Pick<Props, 'ownerId' | 'onSaved' | 'onSetup'> & { storageKey: string; onRecovered: () => void }) {
  const setupId = storageKey.slice(`factory:research-qa-setup:${encodeURIComponent(ownerId)}:`.length);
  const actions = storageKey === `factory:research-assistant-create:${encodeURIComponent(ownerId)}` ? ['create'] : ['draft', 'publish'];
  const command = useResearchCommand<PreviousCommand, ResearchAssistant | QASetup>(storageKey, actions, value => value.action === 'create' ? assistantApi.create(ownerId, value.body) : value.action === 'draft' ? assistantApi.draft(ownerId, value.body) : assistantApi.publish(ownerId, setupId, value.body), value => {
    if ('qa' in value) onSaved(value); else onSetup(value.id);
    onRecovered();
  });
  return command.feedback;
}

export function AssistantSettings(props: Props) { return <Settings key={props.ownerId} {...props}/>; }

function Settings({ ownerId, assistant, setupId, onSetup, onSaved, onReload, onResources }: Props) {
  const [editing, setEditing] = useState(!assistant || assistant.qa.state === 'unconfigured' || !!setupId);
  const [candidates, setCandidates] = useState<SetupCandidates | null>(null); const [setup, setSetup] = useState<QASetup | null>(null);
  const [model, setModel] = useState(assistant?.qa.state === 'configured' ? assistant.qa.connectionRefs.model : '');
  const [associations, setAssociations] = useState(assistant?.qa.state !== 'configured' || assistant.qa.associations?.enabled === true);
  const [maxRecipients, setMaxRecipients] = useState(String(assistant?.qa.state === 'configured' ? assistant.qa.associations?.maxRecipients ?? 2 : 2));
  const [rounds, setRounds] = useState(''); const [calls, setCalls] = useState(''); const [perCalls, setPerCalls] = useState(''); const [deadline, setDeadline] = useState('');
  const [error, setError] = useState(''); const [refresh, setRefresh] = useState(0);
  const [previousKeys, setPreviousKeys] = useState(() => {
    try {
      return Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index)!).filter(key => !!sessionStorage.getItem(key) && (key === `factory:research-assistant-create:${encodeURIComponent(ownerId)}` || key.startsWith(`factory:research-qa-setup:${encodeURIComponent(ownerId)}:`)));
    } catch { return []; }
  });
  const command = useResearchCommand<EnableCommand | ConfigureCommand, ResearchAssistant>(`factory:research-assistant-config:${encodeURIComponent(ownerId)}`, ['enable', 'configure'], async value => {
    if (value.action === 'configure') return assistantApi.configure(ownerId, value.body);
    const body = value.body;
    // The saved consent owns every stage's original request ID, including after a lost reply.
    if (body.createIdentity) await assistantApi.create(ownerId, { requestId: body.requestId + ':assistant' });
    const prepared = body.setupId ? await assistantApi.setup(ownerId, body.setupId) : await assistantApi.draft(ownerId, { requestId: body.requestId + ':draft', name: '研究助手问答', modelConnectionRef: body.modelConnectionRef, budget: { toolCalls: body.budget.perQuestionCaps.toolCalls, maxDepth: 1, maxChildren: 1, operationSeconds: 30, outputBytes: 65536 } });
    if (prepared.preview.mode !== 'qa' || prepared.preview.modelConnectionRef !== body.modelConnectionRef) throw new Error('原问答配置与本次选择不一致，请核对原请求。');
    if (prepared.preview.budget.toolCalls < body.budget.perQuestionCaps.toolCalls) throw new Error('原问答版本的操作上限不足，请核对原请求。');
    const published = prepared.state === 'published' ? prepared : await assistantApi.publish(ownerId, prepared.id, { requestId: body.requestId + ':publish' });
    if (!published.applicationRef || published.preview.mode !== 'qa' || published.connectionRefs.model !== body.modelConnectionRef) throw new Error('原问答发布结果与模型绑定不一致，请核对原请求。');
    setSetup(published);
    return assistantApi.configure(ownerId, { requestId: body.requestId + ':configure', expectedRevision: body.expectedRevision, applicationRef: published.applicationRef, connectionRefs: published.connectionRefs, budget: body.budget, associations: body.associations });
  }, value => { onSaved(value); setEditing(false); setSetup(null); onSetup(''); },
  // Configure checks its original receipt before CAS, so this conflict proves no configuration was saved.
  reason => reason instanceof ApiError && reason.status === 409 && reason.code === 'RESEARCH_ASSISTANT_REVISION_CONFLICT');
  useEffect(() => {
    const controller = new AbortController(); setError('');
    void setupApi.candidates(ownerId, controller.signal).then(value => { if (!controller.signal.aborted) setCandidates(value); }).catch(reason => { if (!controller.signal.aborted) setError(errorText(reason)); });
    if (setupId) void assistantApi.setup(ownerId, setupId, controller.signal).then(value => {
      if (value.preview.mode !== 'qa') throw new Error('此配置不是研究助手问答配置，请核对原链接。');
      if (!controller.signal.aborted) { setSetup(value); setModel(previous => previous || value.preview.modelConnectionRef); setEditing(true); }
    }).catch(reason => { if (!controller.signal.aborted) setError(errorText(reason)); });
    return () => controller.abort();
  }, [ownerId, setupId, refresh]);
  const connections = candidates?.connections.filter(connection => connection.available && candidates.models.some(candidate => candidate.available && (candidate.connectionRef === connection.ref || candidate.reference === connection.registrationRef))) ?? [];
  const revision = assistant?.configurationRevision ?? 0;
  const disabled = command.disabled || previousKeys.length > 0;
  const minimumCalls = candidates?.qaMinimumToolCalls;
  const qaAvailable = minimumCalls != null && minimumCalls > 0;
  const exceedsSelected = setup?.preview.modelConnectionRef === model && Number(perCalls) > setup.preview.budget.toolCalls;
  return <section aria-label="我的研究助手设置"><h2>我的研究助手</h2><p>助手在你确认的额度和期限内离线回答经验问题，不授权训练或GPU；设置过程不调用模型。</p><p>{accountingNotice}</p>
    {assistant && <><p className="rw-id">稳定助手：{assistant.id}</p><p>配置修订：{assistant.configurationRevision}</p></>}
    {assistant?.qa.state === 'configured' && <article className="rw-agreement"><h3>已保存问答配置</h3><p>{assistant.qa.available ? '当前可接收问题' : `当前不可用：${assistant.qa.unavailableCode}`}</p><p>{assistant.qa.associations?.enabled ? `主动关联已启用，每事件最多 ${assistant.qa.associations.maxRecipients} 个接收者。` : '主动关联未启用。'}</p><p>总上限 {assistant.qa.budget.caps.rounds} 个问题 / {assistant.qa.budget.caps.toolCalls} 次工具操作；每问 {assistant.qa.budget.perQuestionCaps.toolCalls} 次。</p><p>截止：{new Date(assistant.qa.budget.deadline * 1000).toLocaleString()}</p><p className="rw-id">{assistant.qa.applicationRef.id} v{assistant.qa.applicationRef.version}</p></article>}
    {previousKeys.map(key => <PreviousRequest key={key} ownerId={ownerId} storageKey={key} onSaved={onSaved} onSetup={onSetup} onRecovered={() => setPreviousKeys(keys => keys.filter(item => item !== key))}/>)}
    {command.feedback}
    <div className="rw-actions"><button onClick={onReload}>读取最新助手配置</button><button onClick={onResources}>配置我的模型与资源</button>{!editing && <button onClick={() => setEditing(true)}>修改离线问答设置</button>}</div>
    {editing && <form className="rw-form" aria-label="离线问答授权" onSubmit={event => {
      event.preventDefault();
      if (!qaAvailable) { setError('当前部署未提供离线问答能力，不能启用。'); return; }
      if (Number(calls) < minimumCalls || Number(perCalls) < minimumCalls) { setError(`每次问答至少需要 ${minimumCalls} 次处理额度；总额度和每问额度都不能低于此值。`); return; }
      if (exceedsSelected) { setError('每问额度超过原问答版本上限；请降低额度，或为当前模型生成新配置。'); return; }
      setError('');
      const unmetered = { tokenLimit: null, amountMicros: null, currency: null };
      void command.run({ action: 'enable', body: { requestId: crypto.randomUUID(), expectedRevision: revision, createIdentity: !assistant, modelConnectionRef: model, ...(setup?.preview.modelConnectionRef === model ? { setupId: setup.id } : {}), associations: { enabled: associations, maxRecipients: Number(maxRecipients) }, budget: { caps: { ...unmetered, rounds: Number(rounds), toolCalls: Number(calls) }, perQuestionCaps: { ...unmetered, rounds: 1, toolCalls: Number(perCalls) }, deadline: new Date(deadline).getTime() / 1000 } } });
    }}><h3>启用离线经验问答</h3><p>选择模型并确认有限额度；系统在同一次操作中准备并绑定准确版本。替换配置保留旧问题与原任务。</p>{error && <p role="alert">{error}</p>}
      <button type="button" onClick={() => setRefresh(value => value + 1)}>重新读取模型</button>
      {qaAvailable ? <p>每次问答至少需要 {minimumCalls} 次处理额度，包括读取依据和保存回答；不足时不会自动加额。</p> : <p>{candidates ? '当前部署未提供离线问答能力，不能启用。' : '正在读取离线问答能力，暂不能启用。'}</p>}
      <fieldset disabled={disabled}>
        {!connections.length && <p>缺少可用模型连接，请先到资源中心保存并绑定自己的模型。</p>}
        <label>个人模型连接<select required value={model} onChange={event => setModel(event.target.value)}><option value="">请选择自己的模型连接</option>{connections.map(connection => { const candidate = candidates!.models.find(item => item.connectionRef === connection.ref || item.reference === connection.registrationRef)!; return <option key={connection.ref} value={connection.ref}>{candidate.provider} · {candidate.model} · {connection.ref.slice(0, 8)}</option>; })}</select></label>
        <label>最多回答问题数<input type="number" min="1" step="1" required value={rounds} onChange={event => setRounds(event.target.value)}/></label><label>总工具操作额度<input type="number" min={minimumCalls ?? undefined} step="1" required value={calls} onChange={event => setCalls(event.target.value)}/></label><label>每问工具操作上限<input type="number" min={minimumCalls ?? undefined} max={calls || undefined} step="1" required value={perCalls} onChange={event => setPerCalls(event.target.value)}/></label><label>问答授权截止时间<input type="datetime-local" required value={deadline} onChange={event => setDeadline(event.target.value)}/></label>
        {exceedsSelected && <p>原问答版本每问上限 {setup!.preview.budget.toolCalls} 次操作。<button type="button" onClick={() => { setSetup(null); onSetup(''); setError(''); }}>为当前模型生成新配置</button></p>}
        <label><input type="checkbox" checked={associations} onChange={event => setAssociations(event.target.checked)}/>自动关联相关团队研究记录</label><label>每条事件最多关联接收者<input type="number" min="1" max="20" step="1" required value={maxRecipients} onChange={event => setMaxRecipients(event.target.value)}/></label>
        <button className="rw-primary" disabled={!qaAvailable || !connections.some(connection => connection.ref === model)}>按修订 {revision} 启用离线问答</button>
      </fieldset>
    </form>}
  </section>;
}
