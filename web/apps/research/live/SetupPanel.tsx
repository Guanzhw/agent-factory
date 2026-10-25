import { useEffect, useState } from 'react';
import { useResearchCommand } from '../useProjectCommand.js';
import { setupApi, type ExecutionSelection, type ResearchSetup, type SetupCandidates, type SetupCommand, type SetupRequirement } from './setupClient.js';
const pinKey = (ref: { id: string; version: number; sha256: string }) => `${ref.id}:${ref.version}:${ref.sha256}`;
const errorText = (error: unknown) => error instanceof Error ? error.message : '研究配置读取失败';

export function SetupPanel({ ownerId, setupId, onSetup, onPublished, onResources, onMaterials }: { ownerId: string; setupId?: string; onSetup: (id: string) => void; onPublished: (selection: ExecutionSelection) => void; onResources: () => void; onMaterials: () => void }) {
  const [candidates, setCandidates] = useState<SetupCandidates | null>(null);
  const [candidateError, setCandidateError] = useState('');
  const [setup, setSetup] = useState<ResearchSetup | null>(null);
  const [readError, setReadError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [name, setName] = useState('');
  const [modelRef, setModelRef] = useState('');
  const [environmentKey, setEnvironmentKey] = useState('');
  const [environmentRef, setEnvironmentRef] = useState('');
  const [toolKeys, setToolKeys] = useState<string[]>([]);
  const [refs, setRefs] = useState<Record<string, string>>({});
  const [budget, setBudget] = useState({ toolCalls: '8', maxDepth: '2', maxChildren: '4', operationSeconds: '8', outputBytes: '65536' });
  const command = useResearchCommand<SetupCommand, ResearchSetup>(`factory:research-setup-command:${encodeURIComponent(ownerId)}:${setupId ? encodeURIComponent(setupId) : 'new'}`, setupId ? ['publish'] : ['draft'], value => value.action === 'draft' ? setupApi.draft(ownerId, value.body) : setupApi.publish(ownerId, setupId!, value.body), result => { setSetup(result); onSetup(result.id); });
  useEffect(() => {
    const controller = new AbortController(); setCandidateError('');
    void setupApi.candidates(ownerId, controller.signal).then(value => { if (!controller.signal.aborted) setCandidates(value); }).catch(reason => { if (!controller.signal.aborted) setCandidateError(errorText(reason)); });
    return () => controller.abort();
  }, [ownerId, refresh]);
  useEffect(() => {
    if (!setupId) return;
    const controller = new AbortController(); setReadError('');
    void setupApi.read(ownerId, setupId, controller.signal).then(value => { if (!controller.signal.aborted) setSetup(value); }).catch(reason => { if (!controller.signal.aborted) setReadError(errorText(reason)); });
    return () => controller.abort();
  }, [ownerId, setupId, refresh]);
  const environment = candidates?.environments.find(item => `${item.adapterId}:${item.revision}` === environmentKey);
  const tools = candidates?.experimentMaterials.filter(item => toolKeys.includes(pinKey(item))) ?? [];
  const requirements = new Map<string, SetupRequirement[]>();
  for (const tool of tools) for (const requirement of tool.connectionRequirements) requirements.set(requirement.name, [...requirements.get(requirement.name) ?? [], requirement]);
  const modelConnections = candidates?.connections.filter(connection => connection.available && candidates.models.some(model => model.available && (model.connectionRef === connection.ref || model.reference === connection.registrationRef))) ?? [];
  return <section className="rw-setup" aria-label="准备研究执行配置"><h3>准备研究执行配置</h3><p>选用已保存的模型、已注册运行环境和实验工具。先保存私人草稿并检查，再明确发布；此过程不会启动研究。</p>
    <div className="rw-actions"><button onClick={onResources}>配置模型与资源</button><button onClick={onMaterials}>管理实验工具材料</button><button onClick={() => setRefresh(value => value + 1)}>重新读取配置</button></div>
    {command.feedback}{candidateError && <p role="alert">{candidateError}</p>}{readError && <p role="alert">{readError}</p>}
    {setupId && !setup && !readError && <p role="status">正在恢复原配置草稿…</p>}
    {setup && <article className="rw-agreement"><h4>{setup.state === 'published' ? '配置已发布' : '私人草稿 · 尚未发布'}</h4><dl><dt>名称</dt><dd>{setup.preview.name}</dd><dt>模型连接</dt><dd>{setup.preview.modelConnectionRef}</dd><dt>运行环境</dt><dd>{setup.preview.environment.adapterId} · {setup.preview.environment.revision}</dd><dt>实验工具版本</dt><dd>{setup.preview.experimentMaterialRefs.map(ref => `${ref.id} v${ref.version}`).join('、')}</dd><dt>单次执行上限</dt><dd>{setup.preview.budget.toolCalls} 次工具调用 · {setup.preview.budget.maxDepth} 层嵌套 · {setup.preview.budget.maxChildren} 个子任务 · {setup.preview.budget.operationSeconds} 秒/操作 · {setup.preview.budget.outputBytes} 字节输出</dd></dl><details><summary>核对固定版本与个人绑定</summary><ul>{setup.preview.experimentMaterialRefs.map(ref => <li className="rw-id" key={pinKey(ref)}>{ref.id} v{ref.version} · {ref.sha256}</li>)}</ul><ul>{Object.entries(setup.connectionRefs).map(([slot, ref]) => <li className="rw-id" key={slot}>{slot}：{ref}</li>)}</ul></details>
      {setup.state === 'draft' ? <><p>发布后团队可读取材料定义；个人连接仍是自己的资源绑定，不随定义公开。</p><button className="rw-primary" disabled={command.disabled} onClick={() => void command.run({ action: 'publish', body: { requestId: crypto.randomUUID() } })}>发布研究执行配置</button></> : setup.applicationRef && <><p className="rw-id">已发布版本：{setup.applicationRef.id} v{setup.applicationRef.version}</p><button className="rw-primary" onClick={() => onPublished({ applicationRef: setup.applicationRef!, mode: 'research', connectionRefs: setup.connectionRefs })}>用于当前研究约定</button></>}
    </article>}
    {!setupId && !setup && <>{!candidates && !candidateError && <p role="status">正在读取模型、运行环境与工具…</p>}{candidates && <form className="rw-form" aria-label="研究执行配置草稿" onSubmit={event => {
      event.preventDefault(); if (!environment) return;
      const selectedRefs = Object.fromEntries([...requirements.keys()].filter(slot => refs[slot]).map(slot => [slot, refs[slot]]));
      void command.run({ action: 'draft', body: { requestId: crypto.randomUUID(), name: name.trim(), modelConnectionRef: modelRef, environment: { adapterId: environment.adapterId, revision: environment.revision, ...(environment.connectionKind ? { connectionRef: environmentRef } : {}) }, experimentMaterialRefs: tools.map(({ id, version, sha256 }) => ({ id, version, sha256 })), connectionRefs: selectedRefs, budget: { toolCalls: Number(budget.toolCalls), maxDepth: Number(budget.maxDepth), maxChildren: Number(budget.maxChildren), operationSeconds: Number(budget.operationSeconds), outputBytes: Number(budget.outputBytes) } } });
    }}><fieldset disabled={command.disabled || !!candidateError}>
      {!modelConnections.length && <p role="status">缺少可用模型连接。请先在资源中心保存模型并建立可用绑定。</p>}{!candidates.environments.length && <p role="status">缺少已注册运行环境。需要先完成实际运行环境注册，不能用演示环境替代。</p>}{!candidates.experimentMaterials.some(item => item.available) && <p role="status">缺少可用的已发布实验工具；请在材料管理中核对发布与依赖。</p>}
      <label>配置名称<input required maxLength={120} value={name} onChange={event => setName(event.target.value)}/></label>
      <label>已保存模型连接<select required value={modelRef} onChange={event => setModelRef(event.target.value)}><option value="">请选择模型连接</option>{modelConnections.map(connection => { const model = candidates.models.find(item => item.connectionRef === connection.ref || item.reference === connection.registrationRef)!; return <option key={connection.ref} value={connection.ref}>{model.provider} · {model.model} · {connection.ref.slice(0, 8)}</option>; })}</select></label>
      <label>运行环境<select required value={environmentKey} onChange={event => { setEnvironmentKey(event.target.value); setEnvironmentRef(''); }}><option value="">请选择实际运行环境</option>{candidates.environments.map(item => <option key={`${item.adapterId}:${item.revision}`} value={`${item.adapterId}:${item.revision}`}>{item.adapterId} · {item.revision}</option>)}</select></label>
      {environment?.connectionKind && <label>环境连接<select required value={environmentRef} onChange={event => setEnvironmentRef(event.target.value)}><option value="">请选择已有环境连接</option>{candidates.connections.filter(item => item.available && item.kind === environment.connectionKind && environment.requiredCapabilities.every(capability => item.capabilities.includes(capability))).map(item => <option key={item.ref} value={item.ref}>{item.registrationRef} · {item.ref.slice(0, 8)}</option>)}</select></label>}
      <fieldset><legend>已发布实验工具</legend>{candidates.experimentMaterials.map(item => <label key={pinKey(item)}><input type="checkbox" disabled={!item.available} checked={toolKeys.includes(pinKey(item))} onChange={event => setToolKeys(previous => event.target.checked ? [...previous, pinKey(item)] : previous.filter(key => key !== pinKey(item)))}/>{item.name} · v{item.version}{!item.available && <small>不可用：{item.unavailableReason}</small>}</label>)}</fieldset>
      {[...requirements.entries()].map(([slot, needs]) => <label key={slot}>工具连接 · {slot}<select required value={refs[slot] ?? ''} onChange={event => setRefs(previous => ({ ...previous, [slot]: event.target.value }))}><option value="">请选择已有连接</option>{candidates.connections.filter(item => item.available && needs.every(need => item.kind === need.kind && need.requiredCapabilities.every(capability => item.capabilities.includes(capability)))).map(item => <option key={item.ref} value={item.ref}>{item.registrationRef} · {item.ref.slice(0, 8)}</option>)}</select></label>)}
      <details><summary>单次执行上限</summary><p>这些是运行边界；整个项目的轮次、用量、金额与截止时间将在研究约定中另行确认。</p>{([['toolCalls', '工具调用次数', 1, 128], ['maxDepth', '最大嵌套层级', 1, 8], ['maxChildren', '最多子任务', 1, 64], ['operationSeconds', '单操作秒数', 1, 600], ['outputBytes', '输出字节数', 1024, 1048576]] as const).map(([key, label, min, max]) => <label key={key}>{label}<input type="number" required min={min} max={max} step="1" value={budget[key]} onChange={event => setBudget(previous => ({ ...previous, [key]: event.target.value }))}/></label>)}</details>
      <button className="rw-primary" disabled={!modelRef || !environment || !tools.length || tools.some(item => !item.available)}>保存私人配置草稿</button>
    </fieldset></form>}</>}
  </section>;
}
