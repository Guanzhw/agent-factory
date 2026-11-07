import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../../api.js';
const message = (error: unknown) => error instanceof Error ? error.message : '研究项目请求失败。';

type SavedCommand = { action: string; body: { requestId: string } };
export function useResearchCommand<Command extends SavedCommand, Result>(storageKey: string, actions: readonly string[], send: (command: Command) => Promise<Result>, onSuccess: (result: Result) => void, knownRejected?: (error: unknown) => boolean) {
  const [recovery] = useState(() => {
    try {
      const raw = window.sessionStorage.getItem(storageKey);
      if (!raw) return { pending: null, error: '' };
      const saved = JSON.parse(raw) as Command;
      if (!saved || !actions.includes(saved.action) || typeof saved.body?.requestId !== 'string' || !saved.body.requestId) throw new Error('invalid command');
      return { pending: saved, error: '' };
    } catch { return { pending: null, error: '无法读取原研究请求；请保留本页存储并排查，暂不提交新请求。' }; }
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(recovery.error);
  const [pending, setPending] = useState<Command | null>(recovery.pending);
  const active = useRef(false);
  const running = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  async function run(command: Command) {
    if (running.current || recovery.error) return;
    try { window.sessionStorage.setItem(storageKey, JSON.stringify(command)); }
    catch { setError('无法保存原请求，尚未提交。请检查浏览器存储后重试。'); return; }
    running.current = true; setBusy(true); setError(''); setPending(command);
    try {
      const result = await send(command);
      if (active.current) { window.sessionStorage.removeItem(storageKey); setPending(null); onSuccess(result); }
    } catch (reason) {
      let uncertain = !knownRejected?.(reason) && (pending !== null || !(reason instanceof ApiError) || reason.status === 0 || reason.status === 408 || reason.status >= 500 || reason.code === 'INVALID_RESPONSE');
      if (!uncertain) {
        try { window.sessionStorage.removeItem(storageKey); }
        catch { uncertain = true; }
      }
      if (active.current) {
        setPending(uncertain ? command : null);
        setError(uncertain ? '未能确认操作结果。' : message(reason));
      }
    } finally { running.current = false; if (active.current) setBusy(false); }
  }
  return { run, disabled: busy || pending !== null || !!recovery.error, feedback: <>{error && <p role="alert">{error}</p>}{pending && !busy && <div>{!error && <p role="status">未能确认操作结果。</p>}<button className="secondary" onClick={() => void run(pending)}>重新获取</button></div>}{busy && <p role="status">正在保存…</p>}</> };
}
