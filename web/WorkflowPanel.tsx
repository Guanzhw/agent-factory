import { useEffect, useRef, useState } from 'react';
import { useCommandKeys } from './commandKeys.js';
import { ApiError } from './api.js';
import { currentWorkflowAfterReceipt, sameWorkflowLineage, workflowCommandReceipt, workflowCommandSettled, workflowPointer, workflowStateLabel, workflowView, WorkflowResponses, type WorkflowApi, type WorkflowCommand, type WorkflowSnapshot, type WorkflowView } from './workflowState.js';

export function WorkflowStages({ workflow }: { workflow: WorkflowSnapshot }) {
  return <section aria-label="工作流阶段"><h3>工作流阶段</h3>
    <p>{({ ACTIVE: '工作流尚未结束', COMPLETED: '工作流执行结束', CANCELLED: '工作流已取消' })[workflow.status]}</p>
    {workflow.cancelRequested && <p role="status">已记录取消请求。各阶段是否停止，以服务器返回的停止证据为准。</p>}
    <ol>{workflow.definition.stages.map(stage => {
      const entry = workflow.stages[stage.id]; const failure = entry.observation?.failure;
      return <li key={stage.id}><h4>{stage.id}</h4><p>{workflowStateLabel[entry.state]}</p>
        {entry.state === 'UNKNOWN' && <p>原执行结果尚未确认。请核对原操作；是否继续由服务器按原审批范围决定。</p>}
        {entry.state === 'WAITING' && <p>等待原执行的外部状态更新。</p>}
        {entry.state === 'HUMAN_WAIT' && <p>本阶段需要人工决定，尚未获得执行同意。</p>}
        {stage.dependencies.length > 0 && <p>依赖阶段：{stage.dependencies.join('、')}</p>}
        {failure && <div role="status"><p>失败代码：{failure.code}</p><p>原因代码：{failure.messageCode}</p></div>}
        {Object.keys(stage.failureRoutes).length > 0 && <details><summary>已配置的失败处理路径</summary><ul>{Object.entries(stage.failureRoutes).map(([code, target]) => <li key={code}>{code} → {target}{entry.state === 'FAILED' && failure?.code === code ? '（匹配本次失败；目标阶段状态见记录）' : ''}</li>)}</ul></details>}
        {entry.observation?.allStopped === true && <p>本阶段执行已确认停止。</p>}
      </li>;
    })}</ol>
  </section>;
}
export function WorkflowPanel({ ownerId, taskId, api, disabled = false }: { ownerId: string; taskId: string; api: WorkflowApi; disabled?: boolean }) {
  return <WorkflowSession key={`${ownerId}:${taskId}`} ownerId={ownerId} taskId={taskId} api={api} disabled={disabled}/>;
}
function WorkflowSession({ ownerId, taskId, api, disabled }: { ownerId: string; taskId: string; api: WorkflowApi; disabled: boolean }) {
  const storageKey = `factory-workflow-command-v1:${encodeURIComponent(ownerId)}:${encodeURIComponent(taskId)}`;
  const [pending, setPending] = useState<WorkflowCommand | undefined>(() => { try { return workflowPointer(window.sessionStorage.getItem(storageKey)); } catch { return undefined; } });
  const [view, setView] = useState<WorkflowView>(); const current = useRef<WorkflowView | undefined>(undefined);
  const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [ready, setReady] = useState(false); const [busy, setBusy] = useState(false); const [refresh, setRefresh] = useState(0);
  const [notRecorded, setNotRecorded] = useState(false);
  const mutation = useRef(false); const alive = useRef(true); const responses = useRef(new WorkflowResponses());
  const keys = useCommandKeys(ownerId);
  function remember(value?: WorkflowCommand) {
    setPending(value); setNotRecorded(false);
    try { if (value) window.sessionStorage.setItem(storageKey, JSON.stringify(value)); else window.sessionStorage.removeItem(storageKey); } catch { /* Preserve in-page original command when storage is unavailable. */ }
  }
  function accept(next: WorkflowView) {
    const previous = current.current;
    if (previous?.available && (!next.available || !sameWorkflowLineage(previous.workflow, next.workflow))) throw new Error('工作流身份或版本发生变化。');
    current.current = next; setView(next);
  }
  function acceptReceipt(snapshot: WorkflowSnapshot) {
    const before = current.current?.available ? current.current.workflow : undefined;
    accept({ available: true, workflow: currentWorkflowAfterReceipt(before, snapshot), allowedActions: [] });
  }
  useEffect(() => { alive.current = true; return () => { alive.current = false; responses.current.invalidate(); }; }, []);
  useEffect(() => {
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function read() {
      try {
        if (!mutation.current) {
          const raw = await responses.current.read(() => api.get(taskId, controller.signal), controller.signal);
          if (!controller.signal.aborted && raw !== undefined) { accept(workflowView(raw, ownerId, taskId)); setReady(true); setError(''); }
        }
      } catch { if (!controller.signal.aborted) { setReady(false); setError('工作流更新失败，已保留最后确认的记录。请重新读取。'); } }
      if (!controller.signal.aborted) timer = setTimeout(() => void read(), 5000);
    }
    void read(); return () => { controller.abort(); clearTimeout(timer); };
  }, [api, ownerId, taskId, refresh]);
  const intent = (value: Omit<WorkflowCommand, 'commandId'>) => ({ action: value.action, ...(value.stageId === undefined ? {} : { stageId: value.stageId }), ...(value.version === undefined ? {} : { version: value.version }), ...(value.approved === undefined ? {} : { approved: value.approved }) });
  async function lookup() {
    if (!pending || mutation.current || disabled) return;
    mutation.current = true; responses.current.invalidate(); setBusy(true); setError(''); setNotRecorded(false);
    try {
      const receipt = workflowCommandReceipt(await api.commandStatus(taskId, pending.commandId), ownerId, taskId, pending);
      if (!alive.current) return;
      if (receipt.workflow) acceptReceipt(receipt.workflow);
      if (workflowCommandSettled(receipt.status)) {
        const key = await keys('workflow-command', { taskId, ...intent(pending) });
        if (!alive.current) return;
        if (key.requestId === pending.commandId) key.acknowledged(); remember();
      }
      setNotice(receipt.status === 'rejected' ? '服务器已明确拒绝原命令。请读取最新状态后重新决定。' : receipt.status === 'completed' ? '原命令已完成核对，执行结果以阶段记录为准。' : '原命令仍待确认。可核对原执行的状态，不会自动重放原决定。');
    } catch (error) {
      if (alive.current) {
        if (error instanceof ApiError && error.status === 404) { setNotRecorded(true); setNotice('服务器未找到这条原命令。可显式提交同一命令，内容和标识保持不变。'); }
        else setError('原命令记录暂时无法读取，已保留原命令。');
      }
    } finally { mutation.current = false; if (alive.current) { setReady(false); setBusy(false); setRefresh(value => value + 1); } }
  }
  async function submit(decision: Omit<WorkflowCommand, 'commandId'>, retry = false) {
    if (disabled || mutation.current || !ready || !view?.available || pending && !retry && !['reconcile', 'cancel'].includes(decision.action) || retry && (!pending || !notRecorded)) return;
    if (!retry && !view.allowedActions.some(item => item.action === decision.action && item.stageId === decision.stageId)) return;
    mutation.current = true; responses.current.invalidate(); setBusy(true); setError(''); setNotice('');
    try {
      const payload = intent(decision);
      const key = await keys('workflow-command', { taskId, ...payload });
      if (!alive.current) return;
      const command = retry ? pending! : { ...payload, commandId: key.requestId };
      const preserveEarlier = !!pending && !retry;
      if (!preserveEarlier) remember(command);
      let raw: unknown;
      try { raw = await api.command(taskId, command); }
      finally { if (command.action === 'reconcile') key.acknowledged(); }
      const result = workflowCommandReceipt(raw, ownerId, taskId, command);
      if (!alive.current) return;
      if (result.workflow) acceptReceipt(result.workflow);
      if (workflowCommandSettled(result.status)) { if (!preserveEarlier) remember(); if (key.requestId === command.commandId) key.acknowledged(); }
      setReady(false); setNotice(result.status === 'rejected' ? '服务器已明确拒绝此命令。请读取最新状态后重新决定。' : result.status === 'unknown' || result.status === 'recorded' ? '命令仍待核对，已保留原命令。可继续核对原执行状态。' : '已收到命令完成回执。执行和停止结果以阶段记录为准。');
    } catch { if (alive.current) { setReady(false); setError('原命令结果尚未确认。请先读取状态，再核对同一命令；不会自动提交新决定。'); } }
    finally { mutation.current = false; if (alive.current) { setBusy(false); setRefresh(value => value + 1); } }
  }
  if (view?.available === false && !pending && !error) return null;
  const blocked = disabled || busy || !ready || !!pending;
  return <section className="workflow-panel" aria-label="工作流记录">
    {error && <p role="alert" className="error-message">{error}</p>}{notice && <p role="status">{notice}</p>}
    {!view && !error && <p>正在读取工作流记录…</p>}
    {view?.available && <><WorkflowStages workflow={view.workflow}/>
      {view.allowedActions.some(item => item.action === 'reconcile') && <p className="quiet">核对原执行会查询原操作；等待条件满足时，可继续原已授权任务。</p>}
      <div className="button-row">{view.allowedActions.map(item => {
        const version = view.workflow.version; const scope = item.stageId ? ` ${item.stageId}` : '';
        return item.action === 'decide' ? <div key={`decide:${item.stageId}`}><p>决定阶段{scope}</p><button className="primary" disabled={blocked} onClick={() => void submit({ ...item, approved: true, version })}>同意本阶段</button><button className="secondary" disabled={blocked} onClick={() => void submit({ ...item, approved: false, version })}>不同意本阶段</button></div>
          : <button key={`${item.action}:${item.stageId ?? ''}`} className={item.action === 'cancel' ? 'secondary danger' : 'secondary'} disabled={['reconcile', 'cancel'].includes(item.action) ? disabled || busy || !ready : blocked} onClick={() => void submit({ ...item, ...(['resume', 'reconcile'].includes(item.action) ? { version } : {}) })}>{item.action === 'resume' ? `继续阶段${scope}` : item.action === 'cancel' ? '请求取消工作流' : `核对原执行${scope}`}</button>;
      })}</div></>}
    {pending && <div className="state-note"><p>保留了一条待核对的原命令。在确认前不能提交新的人工决定或继续阶段；仍可核对原执行。</p><button className="secondary" disabled={disabled || busy} onClick={() => void lookup()}>读取原命令回执</button>{notRecorded && <button className="secondary" disabled={disabled || busy || !ready || !view?.available} onClick={() => void submit(pending, true)}>提交同一原命令</button>}</div>}
    <button className="text-button" disabled={busy} onClick={() => setRefresh(value => value + 1)}>读取工作流最新记录</button>
  </section>;
}
