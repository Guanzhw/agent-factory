import { ResearchReply } from './ResearchReply.js';
import type { SessionEvent, SessionTurn } from './researchSessionsClient.js';

const tools: Record<string, string> = {
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
  if (turn.status === 'finalizing') return '正在核对最终结果';
  if (turn.status === 'completed') return '本轮已完成';
  if (['cancelled', 'canceled'].includes(turn.status)) return '本轮已停止';
  if (turn.failure || ['failed', 'unknown', 'blocked'].includes(turn.status)) return '本轮需要核对，请查看下方结果或原任务';
  if (turn.status === 'waiting_approval') return turn.children?.some(child => !['completed', 'failed', 'cancelled'].includes(child.status))
    ? '等待子助手返回结果' : '有待处理事项，请查看原任务';
  const last = [...turn.events].sort((a, b) => a.id - b.id).at(-1);
  if (!last) return '请求已提交，等待执行记录';
  if (['research_tool_started', 'tool_started'].includes(last.type)) return `已开始${activityName(last)}`;
  if (['research_tool_finished', 'tool_finished'].includes(last.type)) return last.data.outcome === 'completed'
    ? `${activityName(last)}已返回结果，等待后续记录` : `${activityName(last)}结果需要核对`;
  if (last.type === 'research_reconciliation_required') return '原操作结果尚未确认，请核对原任务';
  if (last.type === 'model_content_delta') return '正在生成回复';
  if (last.type === 'model_binding_selected') return '已选定模型，等待回复或工具记录';
  if (['native_accepted', 'admission_reserved'].includes(last.type)) return '任务已提交，等待开始执行';
  return '任务执行中，等待新的行动记录';
}
export function hasUnconfirmedOperation(turn: SessionTurn): boolean {
  const unconfirmed = turn.toolResults.some(item => item.status.toUpperCase() === 'UNKNOWN');
  if (!['queued', 'running', 'waiting_approval', 'finalizing'].includes(turn.status)) return unconfirmed;
  return turn.events.some(event => (event.data.outcome === 'unknown' || event.type === 'research_reconciliation_required') &&
    !turn.toolResults.some(item => ['DONE', 'CANCELLED'].includes(item.status.toUpperCase()) && typeof event.data.callId === 'string' && item.effectKey.endsWith(':' + event.data.callId)) &&
    !turn.events.some(later => later.id > event.id && later.data.callId === event.data.callId && ['completed', 'cancelled'].includes(String(later.data.outcome))));
}
function ActionRecord({ event }: { event: SessionEvent }) {
      const result = output(event);
      const finished = ['research_tool_finished', 'tool_finished'].includes(event.type);
      const outcome = event.data.outcome;
      const relativePath = event.data.relativePath;
      const failed = outcome === 'failed' || typeof result.exitCode === 'number' && result.exitCode !== 0;
      const state = (!finished ? '已开始，尚无结束记录' : outcome === 'unknown' ? '结果未确认' : failed ? '未成功' : outcome === 'cancelled' ? '已停止' : outcome === 'completed' ? '已返回结果' : '需核对结果');
      const path = typeof result.path === 'string' ? result.path : typeof relativePath === 'string' ? relativePath : '';
      return <li><strong>{activityName(event)}</strong><span>{state}</span>
        {path && <code>{path}</code>}
        {typeof result.exitCode === 'number' && <p>命令退出码：{result.exitCode}{result.exitCode === 0 ? '（执行成功）' : '（请查看输出）'}</p>}
        {finished && outcome === 'completed' && typeof result.afterSha256 === 'string' && path && <p>已保存文件，可在会话工作目录中查看；校验信息见执行详情。</p>}
        {result.truncated === true && <p>输出较长，当前显示预览。完整输出：{[result.stdoutPath, result.stderrPath].filter(value => typeof value === 'string').map(path => <code key={String(path)}>{String(path)} </code>)}</p>}
        {typeof result.stdout === 'string'  && result.stdout && <details><summary>查看命令输出</summary><pre>{result.stdout}</pre></details>}
        {typeof result.stderr === 'string' && result.stderr && <details open={failed}><summary>查看错误输出</summary><pre>{result.stderr}</pre></details>}
      </li>;
}
export function SessionActivity({ turn }: { turn: SessionTurn }) {
  const events = [...turn.events].sort((a, b) => a.id - b.id);
  const actions = events.filter(event => ['research_tool_started', 'research_tool_finished', 'tool_started', 'tool_finished'].includes(event.type));
  const recent = actions.filter(event => !['research_tool_started', 'tool_started'].includes(event.type) || !actions.some(other =>
    ['research_tool_finished', 'tool_finished'].includes(other.type) && other.id > event.id && typeof event.data.callId === 'string' && other.data.callId === event.data.callId));
  const children = turn.children ?? [];
  const latest = events.at(-1);
  const responses = new Map<string, string>();
  for (const event of events) if (event.type === 'model_content_delta' && typeof event.data.text === 'string' && typeof event.data.responseId === 'string') {
    responses.set(event.data.responseId, (responses.get(event.data.responseId) ?? '') + event.data.text);
  }
  const liveText = turn.result === null ? [...responses.values()].at(-1) : undefined;
  return <section className="rs-activity" aria-label={`第 ${turn.sequence} 轮行动与结果`}>
    <p className="rs-activity-current" role="status">{activitySummary(turn)}</p>
    {latest && <small>最近记录于 {new Date(latest.createdAt).toLocaleTimeString('zh-CN')} · 实际执行记录</small>}
    {liveText && <div className="rs-streaming-reply"><ResearchReply text={liveText}/><small>{turn.status === 'running' && latest?.type === 'model_content_delta' ? '回复生成中…' : '本次收到的部分回复'}</small></div>}
    {recent.length > 3 && <details className="rs-earlier-actions"><summary>查看此前 {recent.length - 3} 项操作</summary><ol>{recent.slice(0, -3).map(event => <ActionRecord key={event.id} event={event}/>)}</ol></details>}
    {recent.length > 0 && <ol>{recent.slice(-3).map(event => <ActionRecord key={event.id} event={event}/>)}</ol>}
    {!!children.length && <div className="rs-active-children"><strong>子助手</strong>{children.map(child => <div key={child.childTaskId}><p role="status">{({ running: '执行中', queued: '排队中', completed: '已完成', failed: '未完成', cancelled: '已停止' } as Record<string, string>)[child.status] ?? '等待结果'}</p><p className="rs-child-preview">{child.goal}</p><details><summary>查看委托内容</summary><p>{child.goal}</p></details></div>)}</div>}
    {children.some(child => ['failed', 'unknown', 'blocked'].includes(child.status)) && <p role="alert">子助手有未完成或未确认的结果，请展开执行详情核对。</p>}
    {hasUnconfirmedOperation(turn) && <p role="alert">原工具操作结果未知，需核对原任务，不要重发同一操作。</p>}
  </section>;
}
