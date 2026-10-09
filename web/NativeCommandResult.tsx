import { useEffect, useState } from 'react';
import { checkPersonalRecovery, personalAgentApi, type PersonalSession } from './personalAgentApi.js';
import type { JobDetail } from './models.js';

/** Read the original command and session. No submit, fallback, or new task. */
export function NativeCommandResult({ detail }: { detail: JobDetail }) {
  const [session, setSession] = useState<PersonalSession>(); const [error, setError] = useState('');
  const job = detail.job;
  let requestId = '';
  try {
    const receipt = typeof detail.snapshot?.content === 'string' ? JSON.parse(detail.snapshot.content) : detail.snapshot?.content;
    if (receipt && receipt.executionContract === 'personal-external-v1' && receipt.factoryIdentity?.taskId === job.id && receipt.factoryIdentity?.planId === job.planId && typeof receipt.requestId === 'string' && /^[A-Za-z0-9_.:-]{8,100}$/.test(receipt.requestId) && ['create', 'prompt', 'interrupt'].includes(receipt.action)) requestId = receipt.requestId;
  } catch { /* Native content is not necessarily a personal command receipt. */ }
  useEffect(() => {
    setSession(undefined); setError('');
    if (!requestId) return;
    const ctrl = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    async function read() {
      try {
        const recovered = checkPersonalRecovery(await personalAgentApi.recover(requestId, ctrl.signal), requestId, job.planId);
        if (recovered.job?.id !== job.id || recovered.job.ownerId !== job.ownerId || !recovered.receipt) throw new Error('scope');
        const original = recovered.receipt.session;
        const observed = await personalAgentApi.session(original.id, ctrl.signal);
        if (observed.id !== original.id || observed.namespace !== original.namespace || observed.nativeProjectId !== original.nativeProjectId || observed.nativeSessionId !== original.nativeSessionId) throw new Error('scope');
        if (!ctrl.signal.aborted) { setSession(observed); setError(''); }
      } catch { if (!ctrl.signal.aborted) setError('暂时无法读取原生会话结果。原请求保留，正在只读核对。'); }
      if (!ctrl.signal.aborted) timer = setTimeout(() => void read(), 4000);
    }
    void read(); return () => { ctrl.abort(); clearTimeout(timer); };
  }, [job.id, job.planId, job.ownerId, requestId]);
  if (!requestId) return null;
  return <section aria-label="原生会话回复与结果"><h3>原生会话回复与结果</h3>{error && <p role="status">{error}</p>}{session ? <><p>项目 {session.nativeProjectId} · 会话 {session.nativeSessionId ?? '待确认'}</p><p>{session.activeRequestId ? '原请求仍待核对；命令任务完成不等于研究已完成。' : '以下为远程会话记录。科学结论与精确轮次关联未经验证。'}</p>{session.observation?.messages.length ? session.observation.messages.map(message => <article key={message.id}><h4>{message.role === 'assistant' ? '远程回复' : '你的研究目标'} · {message.completed ? '远端报告完成' : '进行中'}</h4>{message.events.map((event, i) => event.type === 'text' ? <p className="native-result-text" key={i}>{event.text}</p> : <details key={i}><summary>工具 {event.tool} · {event.status}</summary><pre className="native-result-text">{event.output}</pre></details>)}</article>) : <p>尚未观察到远程回复，正在读取原会话。</p>}</> : !error && <p role="status">正在读取原生会话…</p>}</section>;
}
