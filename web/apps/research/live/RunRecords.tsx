import { useEffect, useState } from 'react';
import { readResearchRuns, type ResearchRuns } from './runs.js';

export function RunRecords({ ownerId, projectId, evidence, onTask }: { ownerId: string; projectId: string; evidence: boolean; onTask: (id: string) => void }) {
  const [runs, setRuns] = useState<ResearchRuns | null>(null);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setRuns(null); setError('');
    void readResearchRuns(ownerId, projectId, controller.signal).then(value => { if (!controller.signal.aborted) setRuns(value); }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '读取运行记录失败。'); });
    return () => controller.abort();
  }, [ownerId, projectId, refresh]);
  return <section className="rw-run-records" aria-label={evidence ? '研究证据' : '实验与运行'}><div className="rw-actions"><button onClick={() => setRefresh(value => value + 1)}>核对原运行记录</button></div>
    {error && <p className="rw-error" role="alert">{error}</p>}{!runs && !error && <p role="status">正在读取原运行记录…</p>}
    {runs && runs.items.length === 0 && !runs.rounds?.length && <div className="rw-empty"><h3>尚未建立实验或运行</h3><p>先完成执行配置并确认约定；没有指标时不显示推测曲线。</p></div>}
    {runs?.rounds?.map(round => round.sourceUnavailable ? <article className="rw-agreement" key={round.id}><h3>目标版本 {round.goalVersion} · 来源不可用</h3><p className="rw-id">原轮次：{round.id}</p><p>{round.terminal ? '原终态记录存在；这不是新的资源停止证明。' : '原轮次终态尚未确认。'}</p>{round.taskId && <p className="rw-id">原任务：{round.taskId}</p>}<p>派生正文与产物入口已隐藏；不重新派发。</p></article> : <article className="rw-agreement" key={round.id}><h3>研究轮次 · 目标版本 {round.goalVersion}</h3><p className="rw-id">原轮次：{round.id}</p><p>{round.terminal ? '运行已产生终态记录；科学结论仍需验证。' : '尚未取得终态记录；不能据此判断运行已完成。'}</p>
      {round.taskId && <button onClick={() => onTask(round.taskId!)}>查看原任务与产物</button>}
      {round.terminal?.runtime.map(task => <p key={task.taskId}>原任务 {task.taskId}：{task.status}</p>)}
      {round.terminal?.sharing === 'publication_failed' && <p role="status">运行已停止，终稿超过正文发布预算；完整原决定仍保留，尚未发布或交付，也未启动后继。</p>}
      {round.decision ? <div className="rw-analysis"><strong>Agent 分析 · 尚未独立验证</strong><p>{round.decision.reason}</p><p>{round.decision.action === 'continue' ? '建议继续研究' : round.decision.outcome === 'met' ? '助手判断达标' : '助手判断未达标结束'}</p><h4>来源适用性判断</h4>{round.decision.sourceAssessments?.map(item => <p key={item.contentId}><span className="rw-id">{item.contentId}</span> · {item.disposition === "use" ? "采用" : item.disposition === "reproduce" ? "独立复现" : "不适用"}：{item.reason}</p>)}<h4>引用来源</h4><ul>{round.decision.evidenceIds.map(id => <li className="rw-id" key={id}>{id}</li>)}</ul></div> : <p>尚无助手研究决策；运行完成不等于目标达成。</p>}
      {round.terminalRecordId && <p className="rw-id">终态记录来源：{round.terminalRecordId}</p>}{round.terminal?.continuationBlocked && <p role="status">后继受阻：{round.terminal.continuationBlocked}</p>}
    </article>)}
    {runs?.items.map(experiment => experiment.sourceUnavailable ? <article className="rw-agreement" key={experiment.id}><h3>实验来源不可用</h3><p className="rw-id">原实验：{experiment.id} · 目标版本 {experiment.goalVersion}</p>{experiment.attempts.map(attempt => <p className="rw-id" key={attempt.id}>原执行：{attempt.id} · 原操作：{attempt.operationId ?? '尚未确认'}</p>)}<p>假设、条件及操作输出已隐藏；不可据此判断失败或重派。</p></article> : <article className="rw-agreement" key={experiment.id}><h3>{experiment.hypothesis}</h3><p>目标版本 {experiment.goalVersion}</p><dl>{Object.entries(experiment.conditions).map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{typeof value === 'string' ? value : JSON.stringify(value)}</dd></div>)}</dl>
      {'attempts' in experiment ? experiment.attempts.map(attempt => <div key={attempt.id}><p className="rw-id">实验执行：{attempt.id}</p><p>{attempt.operation?.observation ? `原操作状态：${attempt.operation.observation.state}` : '原操作状态：UNKNOWN，观察结果尚未确认；不重新派发。'}</p>{attempt.operationId && <p className="rw-id">原操作：{attempt.operationId}</p>}{attempt.operation && <p>{attempt.operation.closed ? '原操作已关闭' : '原操作尚未确认关闭；UNKNOWN不代表失败或可安全重跑。'}</p>}</div>) : <div><p>原首轮运行记录</p><p className="rw-id">原请求：{experiment.attempt.requestId}</p>{experiment.attempt.execution?.taskId ? <button onClick={() => onTask(experiment.attempt.execution!.taskId!)}>查看原任务与产物</button> : <p>准入尚未确认；请核对原请求，不新建运行。</p>}</div>}
    </article>)}
  </section>;
}
