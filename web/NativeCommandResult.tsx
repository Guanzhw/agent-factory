import { useEffect, useRef, useState } from 'react';
import { checkPersonalRecovery, personalAgentApi, type PersonalSession } from './personalAgentApi.js';
import type { Artifact, JobDetail } from './models.js';
import { researchReplyFailed } from './researchStatus.js';
import { captureNativeArtifacts } from './nativeResearchArtifacts.js';

/** A command receipt identifies the Factory command, never a research verdict. */
export function personalCommandRequest(detail: JobDetail): string {
  try {
    const receipt = typeof detail.snapshot?.content === 'string' ? JSON.parse(detail.snapshot.content) : detail.snapshot?.content;
    if (receipt && receipt.executionContract === 'personal-external-v1' && receipt.factoryIdentity?.taskId === detail.job.id && receipt.factoryIdentity?.planId === detail.job.planId && typeof receipt.requestId === 'string' && /^[A-Za-z0-9_.:-]{8,100}$/.test(receipt.requestId) && ['create', 'prompt', 'interrupt'].includes(receipt.action)) return receipt.requestId;
  } catch { /* Native content is not necessarily a personal command receipt. */ }
  return '';
}

function isPrompt(detail: JobDetail): boolean {
  try {
    const receipt = typeof detail.snapshot?.content === 'string' ? JSON.parse(detail.snapshot.content) : detail.snapshot?.content;
    return !!personalCommandRequest(detail) && receipt?.action === 'prompt';
  } catch { return false; }
}

export function taskResultSource(detail: JobDetail): string {
  if (detail.orxExperiment) return 'ORX 本地 toy 实验 · 实际执行与研究结论分别验证';
  if (personalCommandRequest(detail)) return detail.job.runtime === 'demo'
    ? '原生会话命令 · 命令记录为演示执行，远端回复单独列示'
    : '原生会话命令 · 远端回复单独列示';
  return detail.job.runtime === 'demo' ? '确定性演示 · 结果为合成数据' : '真实运行 · 证据需要单独验证';
}

/** Read the original command and session. No submit, fallback, or new task. */
export function NativeCommandResult({ detail, onArtifacts }: { detail: JobDetail; onArtifacts?: (artifacts: Artifact[]) => void }) {
  const [session, setSession] = useState<PersonalSession>(); const [error, setError] = useState('');
  const [capturing, setCapturing] = useState(false); const [captureNotice, setCaptureNotice] = useState('');
  const captureLock = useRef(false); const captureAbort = useRef<AbortController | undefined>(undefined);
  const job = detail.job;
  const requestId = personalCommandRequest(detail);
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
    void read(); return () => { ctrl.abort(); captureAbort.current?.abort(); clearTimeout(timer); };
  }, [job.id, job.planId, job.ownerId, requestId]);
  if (!requestId) return null;
  async function capture() {
    if (captureLock.current || !session) return;
    captureLock.current = true; setCapturing(true); setCaptureNotice('');
    const ctrl = new AbortController(); captureAbort.current = ctrl;
    try {
      const result = await captureNativeArtifacts(detail, session, requestId, ctrl.signal);
      if (!ctrl.signal.aborted) {
        onArtifacts?.(result.artifacts);
        setCaptureNotice(result.artifacts.length ? `已收集 ${result.artifacts.length} 份真实文本产物，可在下方校验并下载。${result.skipped ? `另有 ${result.skipped} 项未收集：文件不完整、格式暂不支持或达到输出限额。` : ''}` : result.skipped ? '文件暂不能收集：需要完整文本且在输出限额内。已有记录保留。' : '原生工作树尚无可收集的文本产物。已有记录保留。');
      }
    } catch { if (!ctrl.signal.aborted) setCaptureNotice('暂不能确认研究产物。请核对平台环境、已结束会话及当前连接后重试；没有重发研究。'); }
    finally { captureLock.current = false; if (!ctrl.signal.aborted) setCapturing(false); }
  }
  return <section aria-label="原生会话回复与结果"><h3>原生会话回复与结果</h3>{isPrompt(detail) && session?.namespace === 'native-openresearch' && detail.job.status === 'completed' && <div><button disabled={capturing || !!session.activeRequestId || session.latestFactoryIdentity?.taskId !== detail.job.id} onClick={() => void capture()}>{capturing ? '正在收集产物…' : '收集平台研究文本产物'}</button><p className="quiet">保存原生工作树中的完整文本文件，核对字节与哈希后下载；不代表研究结论已验证。</p>{captureNotice && <p role="status">{captureNotice}</p>}</div>}{error && <p role="status">{error}</p>}{session ? <><p>项目 {session.nativeProjectId} · 会话 {session.nativeSessionId ?? '待确认'}</p><p>{session.activeRequestId ? '原请求仍待核对；命令任务完成不等于研究已完成。' : '以下为原会话记录，研究结论仍需核实。'}</p>{session.observation?.messages.length ? session.observation.messages.map(message => <article key={message.id}><h4>{message.role === 'assistant' ? '远程回复' : '你的研究目标'} · {researchReplyFailed(message) ? '远端执行失败' : message.completed ? '远端报告完成' : '进行中'}</h4>{researchReplyFailed(message) && <p role="status">未取得最终回复。可刷新原会话核对错误记录。</p>}{message.events.map((event, i) => event.type === 'text' ? <p className="native-result-text" key={i}>{event.text}</p> : <details key={i}><summary>工具 {event.tool} · {event.status}</summary><pre className="native-result-text">{event.output}</pre></details>)}</article>) : <p>尚未观察到远程回复，正在读取原会话。</p>}</> : !error && <p role="status">正在读取原生会话…</p>}</section>;
}
