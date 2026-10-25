import { useEffect, useState } from 'react';
import { useResearchCommand } from '../useProjectCommand.js';
import { setupApi, type SetupCandidates } from './setupClient.js';
import { assistantApi, type AssistantConfiguration, type QASetup, type ResearchAssistant } from './assistantClient.js';
const errorText = (error: unknown) => error instanceof Error ? error.message : '读取助手配置失败。';
export const accountingNotice = '操作额度受限，token/费用未计量';

function QASetupForm({ ownerId, setupId, onSetup, onPublished, onResources }: { ownerId: string; setupId?: string; onSetup: (id: string) => void; onPublished: (value: QASetup) => void; onResources: () => void }) {
  const [candidates, setCandidates] = useState<SetupCandidates | null>(null); const [setup, setSetup] = useState<QASetup | null>(null);
  const [name, setName] = useState(''); const [model, setModel] = useState(''); const [error, setError] = useState(''); const [refresh, setRefresh] = useState(0);
  type Command = { action: 'draft'; body: Parameters<typeof assistantApi.draft>[1] } | { action: 'publish'; body: { requestId: string } };
  const command = useResearchCommand<Command, QASetup>(`factory:research-qa-setup:${encodeURIComponent(ownerId)}:${setupId ?? 'new'}`, setupId ? ['publish'] : ['draft'], value => value.action === 'draft' ? assistantApi.draft(ownerId, value.body) : assistantApi.publish(ownerId, setupId!, value.body), value => { setSetup(value); onSetup(value.id); });
  useEffect(() => {
    const controller = new AbortController(); setError(''); setSetup(null);
    const work = setupId ? assistantApi.setup(ownerId, setupId, controller.signal).then(value => {
      if (value.preview.mode !== 'qa') throw new Error('此配置不是研究助手问答配置，请返回自己的QA草稿。');
      if (!controller.signal.aborted) setSetup(value);
    }) : setupApi.candidates(ownerId, controller.signal).then(value => { if (!controller.signal.aborted) setCandidates(value); });
    void work.catch(reason => { if (!controller.signal.aborted) setError(errorText(reason)); });
    return () => controller.abort();
  }, [ownerId, setupId, refresh]);
  const connections = candidates?.connections.filter(connection => connection.available && candidates.models.some(model => model.available && (model.connectionRef === connection.ref || model.reference === connection.registrationRef))) ?? [];
  return <section aria-label="助手QA配置"><h3>发布助手问答配置</h3><p>使用已保存的个人模型连接和固定无训练工具的QA模式。保存私人草稿、发布和启用操作额度是三个独立步骤，不自动调用模型。</p><p>{accountingNotice}</p>
    <div className="rw-actions"><button onClick={onResources}>配置我的模型与资源</button><button onClick={() => setRefresh(value => value + 1)}>重新读取QA配置</button></div>{error && <p role="alert">{error}</p>}{command.feedback}
    {setup ? <article className="rw-agreement"><h4>{setup.state === 'published' ? 'QA配置已发布' : '私人QA草稿 · 尚未发布'}</h4><p>{setup.preview.name}</p><p className="rw-id">模型连接：{setup.preview.modelConnectionRef}</p><p>固定本地问答环境，无实验工具；单次执行上限 {setup.preview.budget.toolCalls} 次工具调用 / {setup.preview.budget.operationSeconds} 秒。</p>
      {setup.state === 'draft' ? <button className="rw-primary" disabled={command.disabled} onClick={() => void command.run({ action: 'publish', body: { requestId: crypto.randomUUID() } })}>明确发布QA配置</button> : setup.applicationRef && <><p className="rw-id">{setup.applicationRef.id} v{setup.applicationRef.version} · {setup.applicationRef.sha256}</p><button className="rw-primary" onClick={() => onPublished(setup)}>使用此版本设置操作额度</button></>}
    </article> : !setupId && candidates ? <form className="rw-form" aria-label="私人QA配置草稿" onSubmit={event => { event.preventDefault(); void command.run({ action: 'draft', body: { requestId: crypto.randomUUID(), name: name.trim(), modelConnectionRef: model, budget: { toolCalls: 8, maxDepth: 1, maxChildren: 1, operationSeconds: 30, outputBytes: 65536 } } }); }}><fieldset disabled={command.disabled}>
      {!connections.length && <p>缺少可用模型连接，请先到资源中心保存并绑定自己的模型。</p>}<label>QA配置名称<input required maxLength={120} value={name} onChange={event => setName(event.target.value)}/></label><label>个人模型连接<select required value={model} onChange={event => setModel(event.target.value)}><option value="">请选择自己的模型连接</option>{connections.map(connection => { const candidate = candidates.models.find(item => item.connectionRef === connection.ref || item.reference === connection.registrationRef)!; return <option key={connection.ref} value={connection.ref}>{candidate.provider} · {candidate.model} · {connection.ref.slice(0, 8)}</option>; })}</select></label>
      <p>固定QA单次边界：最多8次操作，每次操作最多30秒。问题次数和整个问答期的操作额度将在下一步确认。</p><button className="rw-primary" disabled={!model || !name.trim()}>保存私人QA草稿</button>
    </fieldset></form> : !error && <p role="status">正在读取QA配置…</p>}
  </section>;
}

function AllowanceForm({ ownerId, assistant, setup, onSaved, onReload }: { ownerId: string; assistant: ResearchAssistant; setup: QASetup; onSaved: (value: ResearchAssistant) => void; onReload: () => void }) {
  const [associations, setAssociations] = useState(assistant.qa.state === 'unconfigured' ? true : assistant.qa.associations?.enabled ?? false);
  const [maxRecipients, setMaxRecipients] = useState(String(assistant.qa.state === 'configured' ? assistant.qa.associations?.maxRecipients ?? 2 : 2));
  const [rounds, setRounds] = useState(''); const [calls, setCalls] = useState(''); const [perCalls, setPerCalls] = useState(''); const [deadline, setDeadline] = useState('');
  type Command = { action: 'configure'; body: AssistantConfiguration & { requestId: string; expectedRevision: number } };
  const command = useResearchCommand<Command, ResearchAssistant>(`factory:research-assistant-config:${encodeURIComponent(ownerId)}`, ['configure'], value => assistantApi.configure(ownerId, value.body), onSaved);
  return <form className="rw-form" aria-label="问答操作额度" onSubmit={event => { event.preventDefault(); if (!setup.applicationRef) return; const unmetered = { tokenLimit: null, amountMicros: null, currency: null }; void command.run({ action: 'configure', body: { requestId: crypto.randomUUID(), expectedRevision: assistant.configurationRevision, associations: { enabled: associations, maxRecipients: Number(maxRecipients) }, applicationRef: setup.applicationRef, connectionRefs: setup.connectionRefs, budget: { caps: { ...unmetered, rounds: Number(rounds), toolCalls: Number(calls) }, perQuestionCaps: { ...unmetered, rounds: 1, toolCalls: Number(perCalls) }, deadline: new Date(deadline).getTime() / 1000 } } }); }}>
    <h3>确认有限问答操作额度</h3><p>{accountingNotice}</p><p>当前配置修订 {assistant.configurationRevision}。确认后同事可在你离线时询问经验；不授权训练。替换配置不迁移旧问题或原任务。</p>{command.feedback}<button type="button" onClick={onReload}>读取最新助手配置</button>
    <fieldset disabled={command.disabled}><label><input type="checkbox" checked={associations} onChange={event => setAssociations(event.target.checked)}/>自动关联相关团队研究记录</label><p>启用后在原操作额度内处理相关事件，不逐条审批，不获得训练权限；旧配置不会自动启用。</p><label>每条事件最多关联接收者<input type="number" min="1" max="20" step="1" required value={maxRecipients} onChange={event => setMaxRecipients(event.target.value)}/></label><label>最多回答问题数<input type="number" min="1" step="1" required value={rounds} onChange={event => setRounds(event.target.value)}/></label><label>总工具操作额度<input type="number" min="1" step="1" required value={calls} onChange={event => setCalls(event.target.value)}/></label><label>每问工具操作上限<input type="number" min="1" max={calls || undefined} step="1" required value={perCalls} onChange={event => setPerCalls(event.target.value)}/></label><label>问答授权截止时间<input type="datetime-local" required value={deadline} onChange={event => setDeadline(event.target.value)}/></label><button className="rw-primary">按修订 {assistant.configurationRevision} 确认问答配置</button></fieldset>
  </form>;
}

export function AssistantSettings({ ownerId, assistant, setupId, onSetup, onSaved, onReload, onResources }: { ownerId: string; assistant: ResearchAssistant | null; setupId?: string; onSetup: (id: string) => void; onSaved: (value: ResearchAssistant) => void; onReload: () => void; onResources: () => void }) {
  const [editing, setEditing] = useState(!!setupId); const [selection, setSelection] = useState<QASetup | null>(null);
  const create = useResearchCommand<{ action: 'create'; body: { requestId: string } }, ResearchAssistant>(`factory:research-assistant-create:${encodeURIComponent(ownerId)}`, ['create'], value => assistantApi.create(ownerId, value.body), onSaved);
  return <section aria-label="我的研究助手设置"><h2>我的研究助手</h2><p>持续身份不代表常驻推理。助手仅在已确认的操作额度和权限内回答原问题。</p><p>{accountingNotice}</p>{create.feedback}
    {!assistant ? <button className="rw-primary" disabled={create.disabled} onClick={() => void create.run({ action: 'create', body: { requestId: crypto.randomUUID() } })}>创建我的研究助手</button> : <><p className="rw-id">稳定助手：{assistant.id}</p><p>配置修订：{assistant.configurationRevision}</p>
      {assistant.qa.state === 'unconfigured' ? <p>尚未配置问答，不能接收新问题。</p> : <article className="rw-agreement"><h3>已保存问答配置</h3><p>{assistant.qa.available ? '当前可接收问题' : `当前不可用：${assistant.qa.unavailableCode}`}</p><p>{assistant.qa.accounting.notice}</p><p>{assistant.qa.associations?.enabled ? `主动关联已启用，每事件最多 ${assistant.qa.associations.maxRecipients} 个接收者。` : "主动关联未启用。"}</p><p>总上限 {assistant.qa.budget.caps.rounds} 个问题 / {assistant.qa.budget.caps.toolCalls} 次工具操作；每问 {assistant.qa.budget.perQuestionCaps.toolCalls} 次。</p><p>截止：{new Date(assistant.qa.budget.deadline * 1000).toLocaleString()}</p><p className="rw-id">{assistant.qa.applicationRef.id} v{assistant.qa.applicationRef.version}</p></article>}
      <div className="rw-actions"><button onClick={onReload}>核对我的助手</button><button onClick={() => { setEditing(true); setSelection(null); onSetup(''); }}>准备新的QA配置</button></div>
      {editing && !selection && <QASetupForm key={`${ownerId}:${setupId ?? 'new'}`} ownerId={ownerId} setupId={setupId} onSetup={onSetup} onPublished={setSelection} onResources={onResources}/>}
      {selection && <AllowanceForm ownerId={ownerId} assistant={assistant} setup={selection} onReload={onReload} onSaved={value => { onSaved(value); setEditing(false); setSelection(null); onSetup(''); }}/>}
    </>}
  </section>;
}
