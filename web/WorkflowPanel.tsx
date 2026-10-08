import { useEffect, useRef, useState } from 'react';
import { useCommandKeys } from './commandKeys.js';
import { ApiError } from './api.js';
import { currentWorkflowAfterReceipt, sameWorkflowLineage, workflowCommand, workflowCommandReceipt, workflowCommandSettled, workflowStateLabel, workflowView, WorkflowResponses, type WorkflowApi, type WorkflowCommand, type WorkflowRequirement, type WorkflowSnapshot, type WorkflowView } from './workflowState.js';

export function WorkflowStages({ workflow }: { workflow: WorkflowSnapshot }) {
  return <section aria-label="原生工作流记录"><h3>原生工作流</h3>
    <p>运行状态：{workflowStateLabel(workflow.status)}</p>
    <ol>{workflow.steps.map((step, index) => <li key={`${step.id}:${index}`}><strong>{step.name}</strong>：{workflowStateLabel(step.status)}</li>)}</ol>
    {workflow.requirements.length > 0 && <section aria-label="待处理要求"><h4>待处理要求</h4><ul>{workflow.requirements.map(requirement => <li key={requirement.id}>{requirement.stepName}：{requirement.kind === 'confirmation' ? '等待确认' : requirement.kind === 'input' ? '等待填写输入' : '等待外部结果'}</li>)}</ul></section>}
    {workflow.operations.length > 0 && <section aria-label="外部操作停止证据"><h4>外部操作</h4><p>原生运行结束不代表外部操作已停止。</p><ul>{workflow.operations.map(operation => <li key={operation.id}>{operation.stepId}：{workflowStateLabel(operation.state)}；{operation.allStopped ? '已确认停止' : '尚未确认停止'}</li>)}</ul></section>}
  </section>;
}
function RequirementDecision({ requirement, disabled, decide }: { requirement: WorkflowRequirement; disabled: boolean; decide: (decision: Pick<WorkflowCommand, 'approved' | 'values'>) => void }) {
  const [text, setText] = useState('{}'); const [error, setError] = useState('');
  if (requirement.kind === 'confirmation') return <div><p>确认：{requirement.stepName}</p><button className="primary" disabled={disabled} onClick={() => decide({ approved: true })}>同意</button><button className="secondary" disabled={disabled} onClick={() => decide({ approved: false })}>不同意</button></div>;
  function submit() {
    try {
      const values: unknown = JSON.parse(text);
      if (!values || typeof values !== 'object' || Array.isArray(values)) throw new Error();
      setError(''); decide({ values: values as Record<string, unknown> });
    } catch { setError('请填写 JSON 对象，字段类型由服务器核对。'); }
  }
  return <div><label>{requirement.stepName} 输入（JSON）<textarea aria-label={`${requirement.stepName} 输入（JSON）`} disabled={disabled} rows={4} maxLength={32768} value={text} onChange={event => setText(event.target.value)}/></label>
    {requirement.fields?.length ? <ul>{requirement.fields.map(field => <li key={field.name}>{field.name}（{field.type}，{field.required ? '必需' : '可选'}）</li>)}</ul> : null}
    {error && <p role="alert">{error}</p>}<button className="primary" disabled={disabled} onClick={submit}>提交原要求的输入</button></div>;
}
export function WorkflowPanel({ ownerId, taskId, api, disabled = false }: { ownerId: string; taskId: string; api: WorkflowApi; disabled?: boolean }) {
  return <WorkflowSession key={`${ownerId}:${taskId}`} ownerId={ownerId} taskId={taskId} api={api} disabled={disabled}/>;
}
function WorkflowSession({ ownerId, taskId, api, disabled }: { ownerId: string; taskId: string; api: WorkflowApi; disabled: boolean }) {
  const storageKey = `factory-workflow-commands-v2:${encodeURIComponent(ownerId)}:${encodeURIComponent(taskId)}`;
  const [pending, setPending] = useState<WorkflowCommand[]>(() => {
    try { const saved = window.sessionStorage.getItem(storageKey) ?? '[]'; if (saved.length > 640000) return []; const raw: unknown = JSON.parse(saved); return Array.isArray(raw) && raw.length <= 16 ? raw.map(workflowCommand) : []; } catch { return []; }
  });
  const pendingRef = useRef(pending);
  const [view, setView] = useState<WorkflowView>(); const current = useRef<WorkflowView | undefined>(undefined);
  const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [ready, setReady] = useState(false); const [busy, setBusy] = useState(false); const [refresh, setRefresh] = useState(0);
  const [notRecorded, setNotRecorded] = useState<string[]>([]);
  const mutation = useRef(false); const alive = useRef(true); const responses = useRef(new WorkflowResponses());
  const keys = useCommandKeys(ownerId);
  function remember(command: WorkflowCommand, remove = false) {
    const next = pendingRef.current.filter(item => item.commandId !== command.commandId);
    if (!remove) next.push(command);
    pendingRef.current = next; setPending(next); setNotRecorded(ids => ids.filter(id => id !== command.commandId));
    try { if (next.length) window.sessionStorage.setItem(storageKey, JSON.stringify(next)); else window.sessionStorage.removeItem(storageKey); } catch { /* Keep exact unresolved commands in memory. */ }
  }
  function accept(next: WorkflowView) {
    const previous = current.current;
    if (previous?.available && (!next.available || !sameWorkflowLineage(previous.workflow, next.workflow))) throw new Error('原工作流身份发生变化。');
    current.current = next; setView(next);
  }
  function acceptReceipt(snapshot: WorkflowSnapshot) {
    const before = current.current?.available ? current.current.workflow : undefined;
    const next = currentWorkflowAfterReceipt(before, snapshot);
    if (!before) accept({ available: true, workflow: next, allowedActions: [] });
  }
  const intent = (value: Omit<WorkflowCommand, 'commandId'>) => {
    const { action, version, requirementId, operationId, approved, values } = value;
    return { action, ...(version === undefined ? {} : { version }), ...(requirementId === undefined ? {} : { requirementId }), ...(operationId === undefined ? {} : { operationId }), ...(approved === undefined ? {} : { approved }), ...(values === undefined ? {} : { values }) };
  };
  useEffect(() => { alive.current = true; return () => { alive.current = false; responses.current.invalidate(); }; }, []);
  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function read() {
      try {
        if (!mutation.current) {
          const raw = await responses.current.read(() => api.get(taskId, controller.signal), controller.signal);
          if (!controller.signal.aborted && raw !== undefined) { accept(workflowView(raw, ownerId, taskId)); setReady(true); setError(''); }
        }
      } catch { if (!controller.signal.aborted) { setReady(false); setError('工作流更新失败，已保留最后确认的记录。'); } }
      if (!controller.signal.aborted) timer = setTimeout(() => void read(), 5000);
    }
    void read(); return () => { controller.abort(); clearTimeout(timer); };
  }, [api, ownerId, taskId, refresh]);
  async function lookup(command: WorkflowCommand) {
    if (mutation.current || disabled) return;
    mutation.current = true; responses.current.invalidate(); setBusy(true); setError('');
    try {
      const receipt = workflowCommandReceipt(await api.commandStatus(taskId, command.commandId), ownerId, taskId, command);
      if (!alive.current) return;
      if (receipt.workflow) acceptReceipt(receipt.workflow);
      if (workflowCommandSettled(receipt.status)) {
        const key = await keys('workflow-command', { taskId, ...intent(command) });
        if (!alive.current) return;
        if (key.requestId === command.commandId) key.acknowledged(); remember(command, true);
      }
      setNotice(workflowCommandSettled(receipt.status) ? '原命令已核对，请查看最新原生记录。' : '原命令仍待确认，不会自动重放。');
    } catch (error) {
      if (alive.current) {
        if (error instanceof ApiError && error.status === 404) { setNotRecorded(ids => [...new Set([...ids, command.commandId])]); setNotice('服务器未找到原命令。可显式提交同一标识与内容。'); }
        else setError('原命令回执暂不可读，已保留原命令。');
      }
    } finally { mutation.current = false; if (alive.current) { setReady(false); setBusy(false); setRefresh(value => value + 1); } }
  }
  async function submit(decision: Omit<WorkflowCommand, 'commandId'>, retry?: WorkflowCommand) {
    if (disabled || mutation.current || !ready || !view?.available || (!retry && pending.length >= (decision.action === 'cancel' ? 16 : 15))
      || (!retry && pending.length > 0 && decision.action === 'decide') || (retry && !notRecorded.includes(retry.commandId))) return;
    if (!retry && !view.allowedActions.some(item => item.action === decision.action && item.requirementId === decision.requirementId && item.operationId === decision.operationId)) return;
    mutation.current = true; responses.current.invalidate(); setBusy(true); setError(''); setNotice('');
    try {
      const payload = intent(decision); const key = await keys('workflow-command', { taskId, ...payload });
      if (!alive.current) return;
      const command = workflowCommand(retry ?? { ...payload, commandId: key.requestId });
      remember(command);
      const result = workflowCommandReceipt(await api.command(taskId, command), ownerId, taskId, command);
      if (!alive.current) return;
      if (result.workflow) acceptReceipt(result.workflow);
      if (workflowCommandSettled(result.status)) { remember(command, true); if (key.requestId === command.commandId) key.acknowledged(); }
      setNotice(workflowCommandSettled(result.status) ? '已收到原命令回执，请查看最新记录。' : '命令仍待核对，已保留原标识与内容。');
    } catch { if (alive.current) setError('命令结果尚未确认。请读取原回执，不会自动重试。'); }
    finally { mutation.current = false; if (alive.current) { setReady(false); setBusy(false); setRefresh(value => value + 1); } }
  }
  if (view?.available === false && !pending.length && !error) return null;
  const blocked = disabled || busy || !ready;
  return <section className="workflow-panel" aria-label="工作流记录">
    {error && <p role="alert" className="error-message">{error}</p>}{notice && <p role="status">{notice}</p>}
    {!view && !error && <p>正在读取工作流记录…</p>}
    {view?.available && <><WorkflowStages workflow={view.workflow}/><div className="button-row">{view.allowedActions.map(item => {
      const version = view.workflow.version;
      if (item.action === 'decide') {
        const requirement = view.workflow.requirements.find(entry => entry.id === item.requirementId)!;
        return <RequirementDecision key={`${requirement.id}:${version}`} requirement={requirement} disabled={blocked || pending.length > 0} decide={decision => void submit({ ...item, ...decision, version })}/>;
      }
      return <button key={`${item.action}:${item.operationId ?? ''}`} className={item.action === 'cancel' ? 'secondary danger' : 'secondary'} disabled={blocked || pending.length >= (item.action === 'cancel' ? 16 : 15)} onClick={() => void submit({ ...item, ...(item.action === 'reconcile' ? { version } : {}) })}>{item.action === 'cancel' ? '请求取消原工作流' : `核对原操作 ${item.operationId}`}</button>;
    })}</div></>}
    {pending.map(command => <div className="state-note" key={command.commandId}><p>原命令 {command.commandId} 待核对；未确认前不提交新的人工决定。</p><button className="secondary" disabled={disabled || busy} onClick={() => void lookup(command)}>读取原命令回执</button>{notRecorded.includes(command.commandId) && <button className="secondary" disabled={blocked || !view?.available} onClick={() => void submit(command, command)}>提交同一原命令</button>}</div>)}
    <button className="text-button" disabled={busy} onClick={() => setRefresh(value => value + 1)}>读取工作流最新记录</button>
  </section>;
}
