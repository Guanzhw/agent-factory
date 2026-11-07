import { useEffect, useState } from 'react';
import { ApiError } from '../../../api.js';
import { ownerModelApi, type OwnerModel } from '../../../ownerModelApi.js';
import { useResearchCommand } from '../useProjectCommand.js';
import { assistantApi, type ResearchAssistant } from './assistantClient.js';
export const accountingNotice = 'token/费用未计量';
type Props = { ownerId: string; assistant: ResearchAssistant | null; onSaved: (value: ResearchAssistant) => void; onReload: () => void; onResources: () => void };
type Command = { action: 'configure'; body: { requestId: string; expectedRevision: number; createIdentity: boolean; modelConnectionRef: string; associations: boolean } };

export function AssistantSettings(props: Props) { return <Settings key={props.ownerId} {...props}/>; }
function Settings({ ownerId, assistant, onSaved, onReload, onResources }: Props) {
  const [models, setModels] = useState<OwnerModel[]>([]);
  const [model, setModel] = useState(assistant?.qa.state === 'configured' ? assistant.qa.connectionRefs.model : '');
  const [associations, setAssociations] = useState(assistant?.qa.state !== 'configured' || assistant.qa.associations?.enabled === true);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const command = useResearchCommand<Command, ResearchAssistant>(`factory:research-assistant-direct:${encodeURIComponent(ownerId)}`, ['configure'], async ({ body }) => {
    if (body.createIdentity) await assistantApi.create(ownerId, { requestId: body.requestId + ':assistant' });
    return assistantApi.configure(ownerId, { requestId: body.requestId, expectedRevision: body.expectedRevision,
      connectionRefs: { model: body.modelConnectionRef }, associations: { enabled: body.associations, maxRecipients: null } });
  }, onSaved, reason => reason instanceof ApiError && reason.status === 409 && reason.code === 'RESEARCH_ASSISTANT_REVISION_CONFLICT');
  useEffect(() => {
    const controller = new AbortController(); setError('');
    void ownerModelApi.list(ownerId, controller.signal).then(values => {
      if (controller.signal.aborted) return;
      setModels(values);
      setModel(current => current || values.find(item => item.available && item.connectionRef)?.connectionRef || '');
    }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '读取模型失败。'); });
    return () => controller.abort();
  }, [ownerId, refresh]);
  const available = models.filter(item => item.available && item.connectionRef);
  return <section aria-label="离线代答设置"><h2>离线代答</h2><p>其他成员询问团队经验时，使用所选模型回答。日常聊天无需启用。</p>
    {assistant?.qa.state === 'configured' && <p>{assistant.qa.available ? '当前可接收问题。' : `当前不可用：${assistant.qa.unavailableCode}`}</p>}
    {command.feedback}{error && <p role="alert">{error}</p>}
    <div className="rw-actions"><button onClick={onReload}>刷新助手状态</button><button onClick={onResources}>配置模型</button><button onClick={() => setRefresh(value => value + 1)}>刷新模型</button></div>
    <form className="rw-form" onSubmit={event => { event.preventDefault(); void command.run({ action: 'configure', body: {
      requestId: crypto.randomUUID(), expectedRevision: assistant?.configurationRevision ?? 0,
      createIdentity: !assistant, modelConnectionRef: model, associations,
    } }); }}><fieldset disabled={command.disabled}>
      <label>模型<select required value={model} onChange={event => setModel(event.target.value)}><option value="">请选择模型</option>{available.map(item => <option key={item.connectionRef} value={item.connectionRef}>{item.provider} · {item.model}</option>)}</select></label>
      <label><input type="checkbox" checked={associations} onChange={event => setAssociations(event.target.checked)}/>自动关联相关团队研究记录</label>
      <button className="rw-primary" disabled={!available.some(item => item.connectionRef === model)}>保存离线代答配置</button>
    </fieldset></form>
  </section>;
}
