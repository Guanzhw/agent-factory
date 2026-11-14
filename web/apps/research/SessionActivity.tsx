import { useEffect, useState } from 'react';
import { IconChevronRight, IconCircleCheck, IconAlertCircle, IconClock } from '@tabler/icons-react';
import { ResearchReply } from './ResearchReply.js';
import type { SessionEvent, SessionTurn } from './researchSessionsClient.js';

const tools: Record<string, string> = {
  read_file: '读取文件', write_file: '写入文件', edit_file: '编辑文件', run_shell: '运行命令',
  grep: '搜索文件内容', find: '查找文件', ls: '列出目录',
  ssh_servers: '查找 SSH 服务器', ssh_run: '执行 SSH 命令',
  get_skill_instructions: '读取技能说明', get_skill_reference: '读取技能参考', get_skill_script: '读取技能脚本',
  research_project: '读取研究目标', research_experiment: '启动实验', research_record_experiment: '记录实验结果',
  research_experiment_result: '查看实验结果', research_assess: '整理实验评估',
  research_read_file: '读取文件', research_search: '搜索工作区内容', research_edit_file: '修改文件',
  research_run: '运行命令', research_read_shared_evidence: '读取共享证据',
  research_assistant_directory: '查找同事助手', research_ask_assistant: '向同事助手提问',
  research_delegate: '分派子助手任务', research_spawn_child: '分派子助手任务', research_wait_child: '等待子任务结果',
  research_find_memories: '查找个人记忆', research_remember: '保存个人记忆',
  research_update_memory: '更新个人记忆', research_forget_memory: '删除个人记忆',
};
export const activityName = (event: SessionEvent) => tools[String(event.data.toolName)] ?? (typeof event.data.toolName === 'string' ? event.data.toolName : '使用工具');
const output = (event: SessionEvent): Record<string, unknown> => {
  const value = event.data.output;
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
};
export function activitySummary(turn: SessionTurn): string {
  if (turn.status === 'canceling') return '本轮正在停止';
  if (turn.status === 'finalizing') return '正在核对最终结果';
  if (turn.status === 'completed') return '本轮已完成';
  if (['cancelled', 'canceled'].includes(turn.status)) return '本轮已停止';
  if (turn.status === 'unknown') return '本轮结果未知，需核对原任务';
  if (turn.status === 'failed') return '本轮未完成，请核对原任务';
  if (turn.failure || turn.status === 'blocked') return '本轮需要核对，请查看下方结果或原任务';
  if (turn.status === 'waiting_approval') return turn.children?.some(child => !['completed', 'failed', 'cancelled'].includes(child.status))
    ? '等待子助手返回结果' : '有待处理事项，请查看原任务';
  const last = [...turn.events].sort((a, b) => a.id - b.id).at(-1);
  if (!last) return '请求已提交，等待执行记录';
  if (['research_tool_started', 'tool_started'].includes(last.type)) return `已开始${activityName(last)}`;
  if (['research_tool_finished', 'tool_finished'].includes(last.type)) return last.data.outcome === 'completed'
    ? `${activityName(last)}已返回结果，等待后续记录` : `${activityName(last)}结果需要核对`;
  if (last.type === 'research_reconciliation_required') return '原操作结果尚未确认，请核对原任务';
  if (last.type === 'model_content_delta') return '已收到部分回复';
  if (last.type === 'model_reasoning_delta') return '正在思考';
  if (last.type === 'model_binding_selected') return '已选定模型，等待回复或工具记录';
  if (['native_accepted', 'admission_reserved'].includes(last.type)) return '任务已提交，等待开始执行';
  return '等待新的执行记录';
}
export function isInFlightOperation(turn: SessionTurn, item: SessionTurn['toolResults'][number]): boolean {
  if (item.status.toUpperCase() !== 'UNKNOWN' || item.result !== null
      || !['reserved', 'queued', 'running', 'waiting_approval', 'finalizing', 'canceling'].includes(turn.status)) return false;
  const events = turn.events.filter(event => typeof event.data.callId === 'string'
    && item.effectKey === `${turn.runId}:${event.type.startsWith('research_') ? 'research-session-tool' : 'personal-tool'}:${event.data.callId}`);
  return ['research_tool_started', 'tool_started'].includes(events.at(-1)?.type ?? '')
    && !events.some(event => ['research_tool_finished', 'tool_finished'].includes(event.type));
}
export function hasUnconfirmedOperation(turn: SessionTurn): boolean {
  const unconfirmed = turn.toolResults.some(item => item.status.toUpperCase() === 'UNKNOWN' && !isInFlightOperation(turn, item));
  const unfinished = !['reserved', 'queued', 'running', 'waiting_approval', 'finalizing', 'canceling'].includes(turn.status)
    && turn.events.some(event => ['research_tool_started', 'tool_started'].includes(event.type) &&
      !turn.events.some(later => later.id > event.id && typeof event.data.callId === 'string' && later.data.callId === event.data.callId && ['research_tool_finished', 'tool_finished'].includes(later.type)));
  return unconfirmed || unfinished || turn.events.some(event => (event.data.outcome === 'unknown' || event.type === 'research_reconciliation_required') &&
    !turn.toolResults.some(item => ['DONE', 'CANCELLED'].includes(item.status.toUpperCase()) && typeof event.data.callId === 'string' && item.effectKey.endsWith(':' + event.data.callId)) &&
    !turn.events.some(later => later.id > event.id && later.data.callId === event.data.callId && ['completed', 'cancelled'].includes(String(later.data.outcome))));
}
function ActionRecord({ event, start, active }: { event: SessionEvent; start?: SessionEvent; active: boolean }) {
      const result = output(event);
      const finished = ['research_tool_finished', 'tool_finished'].includes(event.type);
      const outcome = event.data.outcome;
      const relativePath = event.data.relativePath;
      const nativeFailure = typeof event.data.output === 'string' && /^(Error[: ]|Exit code: (?!0(?:\r?\n|$))-?\d+)/.test(event.data.output);
      const failed = nativeFailure || outcome === 'failed' || outcome === 'completed' && typeof result.exitCode === 'number' && result.exitCode !== 0;
      const unknown = outcome === 'unknown' || !finished && !active;
      const state = (!finished ? active ? '已开始 · 等待结果' : '缺少结束记录 · 结果未知' : outcome === 'unknown' ? '结果未确认' : failed ? '失败' : outcome === 'cancelled' ? '已停止' : outcome === 'completed' ? '已完成' : '需核对结果');
      const path = typeof result.path === 'string' ? result.path : typeof relativePath === 'string' ? relativePath : '';
      const Icon = failed || unknown ? IconAlertCircle : finished ? IconCircleCheck : IconClock;
      const args = event.data.arguments ?? start?.data.arguments;
      const parameters = args && typeof args === 'object' && !Array.isArray(args) ? args as Record<string, unknown> : null;
      const preview = path || (typeof parameters?.file_path === 'string' ? parameters.file_path : typeof parameters?.command === 'string' ? parameters.command : '') || (Array.isArray(parameters?.argv) ? parameters.argv.join(' ') : typeof parameters?.skill_name === 'string' ? parameters.skill_name : '');
      return <li className={failed || unknown ? 'rs-action-warning' : ''}><details className="rs-tool-call">
        <summary><Icon size={16}/><strong>{activityName(event)}</strong>{preview && <code className="rs-tool-preview" title={preview}>{preview}</code>}<span>{state}</span><IconChevronRight className="rs-disclosure" size={14}/></summary>
        <small>{new Date((start ?? event).createdAt).toLocaleTimeString('zh-CN')}{finished && ` → ${new Date(event.createdAt).toLocaleTimeString('zh-CN')}`}</small>
        {args !== undefined ? <details><summary>调用参数</summary><pre>{JSON.stringify(args, null, 2)}</pre></details> : <p className="rw-muted">此记录未保存调用参数。</p>}
        {typeof event.data.code === 'string' && <p role="alert">错误：<code>{event.data.code}</code></p>}
        {event.data.code === 'RESEARCH_COMMAND_UNAVAILABLE' && <p>执行端未找到该命令，未启动进程。</p>}
        {typeof event.data.message === 'string' && <p>{event.data.message}</p>}
        {typeof result.exitCode === 'number' && <p>命令退出码：{result.exitCode}{result.exitCode === 0 ? '（执行成功）' : '（请查看输出）'}</p>}
        {finished && outcome === 'completed' && typeof result.afterSha256 === 'string' && path && <p>已保存文件，可在右上角“会话文件”中下载。</p>}
        {result.truncated === true && <p>输出较长，当前显示预览。完整输出：{[result.stdoutPath, result.stderrPath].filter(value => typeof value === 'string').map(path => <code key={String(path)}>{String(path)} </code>)}</p>}
        {typeof result.text === 'string' && <details open><summary>文件内容</summary><pre>{result.text}</pre></details>}
        {typeof result.stdout === 'string' && result.stdout && <details open><summary>查看命令输出</summary><pre>{result.stdout}</pre></details>}
        {typeof result.stderr === 'string' && result.stderr && <details open={failed || unknown}><summary>查看错误输出</summary><pre>{result.stderr}</pre></details>}
        {finished && event.data.output !== undefined && typeof result.text !== 'string' && typeof result.stdout !== 'string' && typeof result.afterSha256 !== 'string' && <details open><summary>工具结果</summary><pre>{typeof event.data.output === 'string' ? event.data.output : JSON.stringify(event.data.output, null, 2)}</pre></details>}
        {finished ? <details><summary>完整工具结果</summary><pre>{JSON.stringify(event.data, null, 2)}</pre></details> : <p role="status">尚未收到结束事件，无法确认结果。</p>}
      </details></li>;
}
type TextStep = { kind: 'thinking' | 'message'; id: number; responseId: string; text: string; createdAt: string };
type ToolStep = { kind: 'tool'; id: number; event: SessionEvent; start?: SessionEvent };
function orderedSteps(events: SessionEvent[]) {
  const steps: (TextStep | ToolStep)[] = [];
  const calls = new Map<string, ToolStep>();
  for (const event of events) {
    if (['model_content_delta', 'model_reasoning_delta'].includes(event.type) && typeof event.data.text === 'string' && typeof event.data.responseId === 'string' && event.data.text.length > 0) {
      const kind = event.type === 'model_reasoning_delta' ? 'thinking' : 'message';
      const previous = steps.at(-1);
      if (previous?.kind === kind && previous.responseId === event.data.responseId) previous.text += event.data.text;
      else steps.push({ kind, id: event.id, responseId: event.data.responseId, text: event.data.text, createdAt: event.createdAt });
    } else if (['research_tool_started', 'research_tool_finished', 'tool_started', 'tool_finished'].includes(event.type)) {
      const key = typeof event.data.callId === 'string' ? event.data.callId : `event-${event.id}`;
      const existing = calls.get(key);
      if (existing) existing.event = event;
      else {
        const step: ToolStep = { kind: 'tool', id: event.id, event, ...(['research_tool_started', 'tool_started'].includes(event.type) ? { start: event } : {}) };
        calls.set(key, step); steps.push(step);
      }
    }
  }
  return steps;
}
export function SessionActivity({ turn }: { turn: SessionTurn }) {
  const [now, setNow] = useState(Date.now);
  const active = ['reserved', 'queued', 'running', 'waiting_approval', 'finalizing', 'canceling'].includes(turn.status);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  const events = [...turn.events].sort((a, b) => a.id - b.id);
  const steps = orderedSteps(events);
  const last = steps.at(-1);
  // DSH groups one response's reasoning separately from its accumulated answer.
  const responseId = last && last.kind !== 'tool' ? last.responseId : undefined;
  const hasProcess = steps.some(step => step.kind === 'tool' || step.kind === 'thinking' && step.text.trim());
  const reply = steps.filter((step): step is TextStep => step.kind === 'message' && (!hasProcess || step.responseId === responseId));
  const process = hasProcess ? steps.filter(step => step.kind !== 'message' || step.responseId !== responseId) : [];
  const failures = steps.filter(step => step.kind === 'tool' && (step.event.data.outcome === 'failed' || step.event.data.outcome === 'completed' && typeof output(step.event).exitCode === 'number' && output(step.event).exitCode !== 0)).length;
  const children = turn.children ?? [];
  const latest = events.at(-1);
  const updatedAt = typeof latest?.data.updatedAt === 'string' ? latest.data.updatedAt : latest?.createdAt ?? turn.createdAt;
  const seconds = Math.max(0, Math.floor((now - new Date(updatedAt).getTime()) / 1000));
  const elapsed = turn.completedAt ? Math.max(0, Math.round((Date.parse(turn.completedAt) - Date.parse(turn.createdAt)) / 1000)) : null;
  const duration = elapsed === null ? '' : elapsed < 60 ? `${elapsed}秒` : `${Math.floor(elapsed / 60)}分${elapsed % 60}秒`;
  const liveText = turn.result === null ? reply.map(step => step.text).join('') : undefined;
  const descriptions = [...new Set(process.map(step => step.kind === 'tool' ? activityName(step.event) : step.kind === 'thinking' ? '思考' : '阶段性消息'))];
  return <section className="rs-activity" aria-label={`第 ${turn.sequence} 轮行动与结果`}>
    {process.length > 0 ? <details className="rs-process" open={active}>
    <summary><span className="rs-activity-current" role="status">{turn.status === 'completed' ? `已完成${duration ? `，用时 ${duration}` : ''}` : activitySummary(turn)}{failures > 0 && ` · ${failures} 项失败`}</span><IconChevronRight className="rs-disclosure" size={14}/></summary>
    <details className="rs-process-steps" open><summary>{descriptions.join('、')} · {process.length} 个步骤<IconChevronRight className="rs-disclosure" size={14}/></summary>
    <ol>{process.map(step => step.kind === 'tool' ? <ActionRecord key={step.id} event={step.event} start={step.start} active={active}/> : <li key={step.id} className={step.kind === 'thinking' ? 'rs-thinking-step' : 'rs-step-message'}>{step.kind === 'thinking' ? <details className="rs-thinking" open={active && step === last}><summary>思考<time>{new Date(step.createdAt).toLocaleTimeString('zh-CN')}</time><IconChevronRight className="rs-disclosure" size={14}/></summary><ResearchReply text={step.text}/></details> : <><small>阶段性消息 · {new Date(step.createdAt).toLocaleTimeString('zh-CN')}</small><ResearchReply text={step.text}/></>}</li>)}</ol>
    </details></details> : active && <p className="rs-generating" role="status">{liveText ? '正在生成回答…' : activitySummary(turn)}</p>}
    {!process.length && ['cancelled', 'canceled'].includes(turn.status) && <p role="status">{activitySummary(turn)}</p>}
    {!process.length && (turn.status === 'unknown' || !turn.failure && ['failed', 'blocked'].includes(turn.status)) && <p role="alert">{activitySummary(turn)}</p>}
    {active && seconds >= 15 && <p className="rs-waiting" role="status">已有 {seconds} 秒未收到更新，正在等待执行端。</p>}
    {liveText && <div className="rs-streaming-reply"><ResearchReply text={liveText}/><small>本次收到的部分回复</small></div>}
    {children.some(child => ['failed', 'unknown', 'blocked'].includes(child.status)) && <p role="alert">子助手有未完成或未确认的结果，请查看子助手记录。</p>}
    {hasUnconfirmedOperation(turn) && <p role="alert">原工具操作结果未知，需核对原任务，不要重发同一操作。</p>}
    {turn.status === 'completed' && turn.result === null && <p className="rs-warning" role="alert">执行端已标记完成，但没有保存最终回答。</p>}
  </section>;
}
