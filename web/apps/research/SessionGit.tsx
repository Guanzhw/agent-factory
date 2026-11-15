import { useEffect, useRef, useState } from 'react';
import { parseGitDiff, sessionGitApi, type GitComment, type GitState } from './sessionGitClient.js';
import './SessionGit.css';

type Anchor = { reviewId: string; path: string; side: 'left' | 'right'; line: number };
export function SessionGit({ ownerId, sessionId, open, revision, running, model, onUpdated, onSend }: {
  ownerId: string; sessionId: string; open: boolean; revision: string; running: boolean;
  model: { modelConnectionRef: string; reasoningEffort?: string }; onUpdated: () => void; onSend: (text: string) => Promise<boolean>;
}) {
  const [git, setGit] = useState<GitState | null>(null);
  const [comments, setComments] = useState<GitComment[]>([]);
  const [repository, setRepository] = useState('');
  const [anchor, setAnchor] = useState<Anchor | null>(null);
  const [text, setText] = useState('');
  const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false); const [refresh, setRefresh] = useState(0);
  const reviewRequest = useRef<{ reviewId: string; requestId: string } | null>(null);
  const commentRequest = useRef<string | null>(null);
  const lock = useRef(false);
  const diffView = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    void Promise.all([sessionGitApi.read(ownerId, sessionId, controller.signal), sessionGitApi.comments(ownerId, sessionId, controller.signal)])
      .then(([value, saved]) => { if (!controller.signal.aborted) { setGit(value); setComments(saved.items); } })
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '读取 Git 变更失败。'); });
    return () => controller.abort();
  }, [ownerId, sessionId, open, revision, refresh]);
  async function run(work: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(''); setNotice('');
    try { await work(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '操作未确认，请刷新核对。'); }
    finally { lock.current = false; setBusy(false); }
  }
  const diffLines = git?.configured ? parseGitDiff(git.diff, git.files) : [];
  const current = git?.configured ? comments.filter(comment => comment.reviewId === git.reviewId) : [];
  return <div className="rs-git">
    {error && <p role="alert" className="rw-error">{error}</p>}{notice && <p role="status">{notice}</p>}
    <div className="rs-git-toolbar"><button type="button" disabled={busy} onClick={() => { setError(''); setRefresh(value => value + 1); }}>刷新 Git 变更</button></div>
    {!git ? <p role="status">正在读取 Git 工作区…</p> : !git.configured ? <form onSubmit={event => { event.preventDefault(); void run(async () => { setGit(await sessionGitApi.attach(ownerId, sessionId, repository.trim())); setNotice('会话工作树已创建，后续工作将在此进行。'); onUpdated(); }); }}>
      <p>为代码任务连接本机 Git 仓库，助手将在独立的会话工作树中工作。</p>
      <label>Git 仓库路径<input value={repository} onChange={event => setRepository(event.target.value)} placeholder="本机仓库的绝对路径" disabled={busy || running}/></label>
      <button disabled={busy || running || !repository.trim()}>创建会话工作树</button>
      {running && <p>当前轮次结束后可连接仓库。</p>}
    </form> : <>
      <details><summary>{git.repositoryPath.split(/[\\/]/).at(-1)} · 工作区信息</summary><dl className="rs-git-paths"><dt>原仓库</dt><dd>{git.repositoryPath}</dd><dt>会话工作树</dt><dd>{git.workspacePath}</dd><dt>基准提交</dt><dd><code>{git.baseCommit}</code></dd></dl></details>
      <div className="rs-git-toolbar"><button disabled={busy || running || !git.diff} onClick={() => void run(async () => {
        if (reviewRequest.current?.reviewId !== git.reviewId) reviewRequest.current = { reviewId: git.reviewId, requestId: crypto.randomUUID() };
        await sessionGitApi.review(ownerId, sessionId, git.reviewId, reviewRequest.current.requestId, model);
        reviewRequest.current = null;
        setNotice('模型审查已提交，请在对话中查看进度和结果。'); onUpdated();
      })}>模型审查</button><button disabled={busy || running || !git.diff || git.applied || git.applicationState === 'unknown'} onClick={() => void run(async () => {
        setGit(await sessionGitApi.apply(ownerId, sessionId, git.reviewId)); setNotice('变更已应用到原仓库。');
      })}>应用到原仓库</button></div>
      {git.applicationState === 'unknown' && <p role="alert" className="rw-error">应用操作曾被中断，原仓库的写入结果尚未确认。请先核对原仓库文件。</p>}
      {git.applied && <p role="status">此版本的变更已应用。</p>}
      <section aria-label="代码差异"><h4>代码差异 · {git.files.length} 个文件</h4>
        <ul>{git.files.map(file => <li key={file.path}><code>{file.status} {file.path}</code></li>)}</ul>
        {!git.diff ? <p>当前工作树没有变更。</p> : <div ref={diffView} className="rs-git-diff" tabIndex={0} aria-label="可滚动代码差异">{diffLines.map((line, index) => {
          const number = line.newLine ?? line.oldLine; const side = line.newLine === undefined ? 'left' : 'right';
          return <div className={`rs-git-line rs-git-${line.kind}`} key={index} tabIndex={-1}>{number !== undefined ? <button type="button" disabled={busy} aria-label={`评论 ${line.path}:${number} ${side}`} onClick={() => { setAnchor({ reviewId: git.reviewId, path: line.path, line: number, side }); commentRequest.current = null; setText(''); }}><span>{line.oldLine ?? ''}</span><span>{line.newLine ?? ''}</span></button> : <span className="rs-git-numbers"/>}<code>{line.text}</code></div>;
        })}</div>}
      </section>
      {anchor && <form className="rs-git-comment-form" onSubmit={event => { event.preventDefault(); void run(async () => {
        commentRequest.current ??= crypto.randomUUID();
        const saved = await sessionGitApi.comment(ownerId, sessionId, { ...anchor, text: text.trim(), requestId: commentRequest.current });
        setComments(previous => [...previous.filter(item => item.id !== saved.id), saved]); setAnchor(null); setText(''); commentRequest.current = null;
      }); }}><p><code>{anchor.path}:{anchor.line}</code> · {anchor.side === 'left' ? '原文件' : '新文件'}</p><label>行审查意见<textarea autoFocus rows={3} value={text} onChange={event => { setText(event.target.value); commentRequest.current = null; }} disabled={busy}/></label><button disabled={busy || !text.trim()}>保存行评论</button><button type="button" disabled={busy} onClick={() => setAnchor(null)}>取消评论</button></form>}
      <section aria-label="审查意见"><h4>审查意见</h4>{!comments.length && <p>点击差异左侧的行号添加评论。</p>}{comments.map(comment => <article className="rs-git-comment" key={comment.id}><strong>{comment.path}:{comment.line} · {comment.side === 'left' ? '原文件' : '新文件'}</strong>{comment.reviewId !== git.reviewId && <span> · 历史版本</span>}<small> · {comment.turnId ? '模型评论' : '我的评论'}</small>{comment.reviewId === git.reviewId && <button type="button" aria-label={`查看位置 ${comment.path}:${comment.line}`} onClick={() => { const index = diffLines.findIndex(line => line.path === comment.path && (comment.side === 'left' ? line.oldLine : line.newLine) === comment.line); const row = diffView.current?.children[index] as HTMLElement | undefined; row?.focus({ preventScroll: true }); row?.scrollIntoView({ block: 'center' }); }}>查看位置</button>}<p>{comment.text}</p></article>)}
        <button disabled={busy || running || !current.length} onClick={() => void run(async () => {
          if (await onSend(`请根据以下行审查意见检查并修改当前会话工作树。意见对应 Git 版本 ${git.reviewId}：\n\n${current.map(comment => `${comment.path}:${comment.line} (${comment.side === 'left' ? '原文件' : '新文件'})\n${comment.text}`).join('\n\n')}`)) setNotice('审查意见已发送，请在对话中查看进度。'); else setError('审查意见未能确认发送，请关闭面板核对对话中的原请求。');
        })}>发送审查意见</button>
      </section>
    </>}
  </div>;
}
