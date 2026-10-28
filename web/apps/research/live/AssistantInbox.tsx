import { useEffect, useState } from 'react';
import { assistantApi, type ResearchQuestion } from './assistantClient.js';

export function AssistantInbox({ ownerId, onQuestion, onSettings }: { ownerId: string; onQuestion: (id: string) => void; onSettings: () => void }) {
  const [after, setAfter] = useState(''); const [refresh, setRefresh] = useState(0);
  const [page, setPage] = useState<{ items: ResearchQuestion[]; nextCursor: string | null } | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController(); setPage(null); setError('');
    void assistantApi.inbox(ownerId, after, controller.signal).then(value => { if (!controller.signal.aborted) setPage(value); })
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '收到的问题暂时不可读取。'); });
    return () => controller.abort();
  }, [ownerId, after, refresh]);
  return <section aria-label="收到的问题"><h2>收到的问题</h2><p>查看发给你助手的原问题。已接受的任务可在你离线时回答；尚未启动的原问题需打开核对。</p>
    <div className="rw-actions"><button onClick={() => setRefresh(value => value + 1)}>刷新收到的问题</button><button onClick={onSettings}>设置我的助手</button></div>
    <p className="rw-muted">未配置问答或额度不足时，请在自己的助手设置中调整。</p>
    {error ? <p role="alert">{error}</p> : !page ? <p role="status">正在读取收到的问题…</p> : !page.items.length ? <p>本页尚无收到的问题。</p> : <ul className="rs-question-list">{page.items.map(question => <li key={question.id}><button onClick={() => onQuestion(question.id)}>{question.text.length > 120 ? `${question.text.slice(0, 120)}…` : question.text}</button><span>来自 {question.senderId} · 送达：{question.delivery.state} · {question.reply?.state === 'available' ? '已有回答' : question.reply ? '回答来源不可用' : '尚无回答'}</span></li>)}</ul>}
    <div className="rw-actions">{after && <button onClick={() => setAfter('')}>第一页收件</button>}{page?.nextCursor && <button onClick={() => setAfter(page.nextCursor!)}>下一页收件</button>}</div>
  </section>;
}
