import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../../api.js';
import { sendProjectCommand, type ProjectCommand } from './client.js';
import type { ResearchProject } from './types.js';
const message = (error: unknown) => error instanceof Error ? error.message : '研究项目请求失败。';

type SavedCommand = { action: string; body: { requestId: string } };
export function useResearchCommand<Command extends SavedCommand, Result>(storageKey: string, actions: readonly string[], send: (command: Command) => Promise<Result>, onSuccess: (result: Result) => void) {
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
      let uncertain = pending !== null || !(reason instanceof ApiError) || reason.status === 0 || reason.status === 408 || reason.status >= 500 || reason.code === 'INVALID_RESPONSE';
      if (!uncertain) {
        try { window.sessionStorage.removeItem(storageKey); }
        catch { uncertain = true; }
      }
      if (active.current) {
        setPending(uncertain ? command : null);
        setError(uncertain ? `操作结果尚未确认。请重试原请求，避免重复创建。${message(reason)}` : message(reason));
      }
    } finally { running.current = false; if (active.current) setBusy(false); }
  }
  return { run, disabled: busy || pending !== null || !!recovery.error, feedback: <>{error && <p role="alert">{error}</p>}{pending && <div><p>已保留尚未确认的原请求。刷新或返回本页后，可使用原请求核对结果。</p><button disabled={busy} className="secondary" onClick={() => void run(pending)}>重试原操作</button></div>}{busy && <p role="status">正在保存…</p>}</> };
}


export function useProjectCommand(ownerId: string, projectId: string | undefined, onSuccess: (project: ResearchProject) => void) {
  const storageKey = `factory:research-command:${encodeURIComponent(ownerId)}:${projectId ? encodeURIComponent(projectId) : 'new'}`;
  return useResearchCommand<ProjectCommand, ResearchProject>(storageKey, projectId ? ['goal', 'confirm', 'end', 'start'] : ['create'], command => sendProjectCommand(ownerId, projectId, command), onSuccess);
}
