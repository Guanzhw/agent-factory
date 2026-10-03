import { useEffect, useState } from 'react';
import { api, ApiError } from './api.js';
import { adoptCommandPointer, forgetCommandPointer, pendingCommandPointers, type CommandPointer } from './controlCommandStorage.js';
import type { ControlReceipt } from './models.js';

export function commandNotice(receipt: ControlReceipt): string {
  if (receipt.stopConfirmed) return '停止已确认；原命令的任务范围已获得停止证据。';
  if (receipt.executionContinuing) return '决定已记录，执行正在继续；这不代表任务已完成。';
  if (receipt.decisionRecorded) return receipt.action === 'cancel' ? '取消决定已记录，停止尚未确认。' : '决定已记录；后续执行结果以任务记录为准。';
  if (receipt.state === 'INTENT_RECORDED') return '请求已保存，但尚未越过派发边界。可核对后继续原请求。';
  if (receipt.state === 'REJECTED') return '原请求未通过当前状态或权限检查，未派发。';
  return '提交结果未知。已保留原命令；只核对回执，不会自动再次执行。';
}
const actionName = (action: string) => ({ answer: '回答', approve: '审批决定', cancel: '取消', resume_approved: '恢复已记录审批' })[action] ?? '任务操作';

export function ControlRecovery({ ownerId, onSelect, busy, act }: {
  ownerId: string; onSelect: (task: string) => void; busy: string;
  act: (name: string, work: () => Promise<void>) => Promise<void>;
}) {
  const [receipts, setReceipts] = useState<ControlReceipt[]>([]);
  const [missing, setMissing] = useState<CommandPointer[]>([]);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [cursor, setCursor] = useState<string | null>(null);
  const [pages, setPages] = useState(1);
  useEffect(() => {
    const changed = () => setRefresh(n => n + 1);
    window.addEventListener('factory-controls-changed', changed);
    window.addEventListener('storage', changed);
    return () => { window.removeEventListener('factory-controls-changed', changed); window.removeEventListener('storage', changed); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        let next: string | undefined;
        const values = new Map<string, ControlReceipt>();
        let nextCursor: string | null = null;
        for (let page = 0; page < pages; page++) {
          const result = await api.controlCommands(ownerId, undefined, next, controller.signal);
          for (const value of result.items) values.set(value.commandId, value);
          nextCursor = result.nextCursor;
          if (!nextCursor) break;
          next = nextCursor;
        }
        let pointers: CommandPointer[] = [];
        try {
          for (const value of values.values()) adoptCommandPointer(value);
          pointers = pendingCommandPointers(ownerId);
        } catch { /* Server receipts remain recoverable when local storage is unavailable. */ }
        const absent: CommandPointer[] = [];
        for (const pointer of pointers) {
          if (values.has(pointer.commandId)) continue;
          try {
            const value = await api.controlReceipt(ownerId, pointer.taskId, pointer.commandId, controller.signal);
            if (!value.acknowledged) values.set(value.commandId, value);
            else forgetCommandPointer(pointer);
          } catch (error) {
            if (error instanceof ApiError && error.status === 404) absent.push(pointer);
            else throw error;
          }
        }
        if (!controller.signal.aborted) {
          setReceipts([...values.values()].sort((a, b) => b.createdAt.localeCompare(a.createdAt)));
          setMissing(absent); setCursor(nextCursor); setError('');
        }
      } catch (error) { if (!controller.signal.aborted) setError(error instanceof Error ? error.message : '命令回执读取失败。'); }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 4000);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [ownerId, pages, refresh]);
  if (!receipts.length && !missing.length && !error) return null;
  return <section className="control-recovery" aria-label="待核对的任务操作">
    <div className="section-heading"><h2>待核对的任务操作</h2><button className="text-button" disabled={!!busy} onClick={() => setRefresh(n => n + 1)}>核对回执</button></div>
    <p className="quiet">重启浏览器后仍可核对原操作。决定已记录、执行继续和停止确认分别显示；不会因网络中断自动重发。</p>
    {error && <p role="alert">{error}</p>}
    <ul>{receipts.map(receipt => <li key={receipt.commandId} data-command-id={receipt.commandId}>
      <div><strong>{actionName(receipt.action)}{receipt.action === 'approve' ? receipt.approved ? ' · 同意' : ' · 拒绝' : ''}</strong><p role="status">{commandNotice(receipt)}</p></div>
      <div className="button-row"><button className="secondary" onClick={() => onSelect(receipt.taskId)}>查看任务</button>
        {receipt.canDispatch && <button className="secondary" disabled={!!busy} onClick={() => void act('recover-command', async () => { await api.dispatchControl(ownerId, receipt.taskId, receipt.commandId); setRefresh(n => n + 1); })}>继续未派发请求</button>}
        {(receipt.state === 'REJECTED' || receipt.decisionRecorded && (receipt.action !== 'cancel' || receipt.stopConfirmed)) && <button className="text-button" disabled={!!busy} onClick={() => void act('acknowledge-command', async () => { await api.acknowledgeControl(ownerId, receipt.taskId, receipt.commandId); forgetCommandPointer(receipt); setRefresh(n => n + 1); })}>已核对，收起</button>}
      </div><details className="technical-detail"><summary>操作引用</summary><span>{receipt.commandId}</span><span>{receipt.taskId}</span></details>
    </li>)}</ul>
    {missing.map(pointer => <div className="state-note" key={pointer.commandId}><strong>{actionName(pointer.action)} · 尚无服务端回执</strong><p>原请求可能仍在途中。请继续核对；重新明确提交相同决定时会沿用原标识，不会自动提交。</p><button className="secondary" onClick={() => onSelect(pointer.taskId)}>查看原任务</button></div>)}
    {cursor && <button className="secondary" onClick={() => setPages(n => n + 1)}>加载更多待核对操作</button>}
  </section>;
}
