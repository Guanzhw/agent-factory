import { useEffect, useState } from 'react';
import { authEpoch, assertAuthEpoch, expireBrowserSession } from '../../browserAuth.js';
import { factoryRequest } from '../../api.js';
import './SessionFiles.css';

const textFile = /\.(?:md|markdown|txt|text|json|jsonl|ya?ml|toml|ini|csv|tsv|py|js|jsx|ts|tsx|css|html|xml|svg|sh|sql|log)$/i;

export function SessionFiles({ ownerId, sessionId, revision, onAttention }: { ownerId: string; sessionId: string; revision: string; onAttention?: (value: boolean) => void }) {
  const [files, setFiles] = useState<{ path: string; size: number }[]>([]);
  const [error, setError] = useState('');
  const [errors, setErrors] = useState<{ path: string; message: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [previewPath, setPreviewPath] = useState('');
  const [preview, setPreview] = useState<{ key: string; text?: string; error?: string; loading?: boolean }>({ key: '' });
  const base = `/research/sessions/${encodeURIComponent(sessionId)}/files`;
  const previewKey = `${ownerId}\0${base}\0${revision}\0${refresh}\0${previewPath}`;
  useEffect(() => { onAttention?.(!!error || errors.length > 0); }, [error, errors, onAttention]);
  useEffect(() => {
    const abort = new AbortController();
    setError('');
    setLoading(true);
    setFiles([]);
    setErrors([]);
    setPreviewPath('');
    void factoryRequest<{ files: typeof files; errors: typeof errors }>(base, 'GET', undefined, abort.signal, ownerId).then(result => {
      if (abort.signal.aborted) return;
      setFiles(result.files);
      setErrors(result.errors);
      setLoading(false);
    }).catch((reason: unknown) => {
      if (!abort.signal.aborted) {
        setError(reason instanceof Error ? reason.message : '文件列表暂时不可用。');
        setLoading(false);
      }
    });
    return () => abort.abort();
  }, [base, ownerId, revision, refresh]);
  useEffect(() => {
    if (!previewPath) return;
    const abort = new AbortController();
    const epoch = authEpoch();
    const url = `/api/factory${base}/download?path=${encodeURIComponent(previewPath)}`;
    setPreview({ key: previewKey, loading: true });
    void (async () => {
      try {
        const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: abort.signal,
          headers: { 'X-Factory-Expected-Owner': ownerId } });
        assertAuthEpoch(epoch);
        if (response.status === 401) expireBrowserSession();
        if (!response.ok) throw new Error(`文件读取失败（${response.status}），请刷新文件列表后重试。`);
        let text: string;
        try { text = new TextDecoder('utf-8', { fatal: true }).decode(await response.arrayBuffer()); }
        catch { throw new Error('该文件不是有效的 UTF-8 文本，无法预览。'); }
        assertAuthEpoch(epoch);
        if (!abort.signal.aborted) setPreview({ key: previewKey, text });
      } catch (reason) {
        if (!abort.signal.aborted) setPreview({ key: previewKey, error: reason instanceof Error ? reason.message : '文件预览暂时不可用。' });
      }
    })();
    return () => abort.abort();
  }, [base, ownerId, previewKey, previewPath]);
  return <section className="rs-files" aria-label="会话文件">
    <p>会话文件（{files.length}）</p>
    <p>下载工作目录中的当前文件。<button type="button" onClick={() => setRefresh(value => value + 1)}>刷新文件列表</button></p>
    {loading && <p role="status">正在读取文件…</p>}
    {error && <p role="alert">{error}</p>}
    {errors.length > 0 && <div role="alert"><p>部分路径无法读取，以下仅列出可访问的文件：</p>
      <ul>{errors.map(issue => <li key={issue.path}>{issue.path}：{issue.message}</li>)}</ul>
    </div>}
    {!loading && !error && errors.length === 0 && files.length === 0 && <p>还没有生成文件。</p>}
    <ul>{files.map(file => <li key={file.path}>
      <a href={`/api/factory${base}/download?path=${encodeURIComponent(file.path)}`} download>{file.path}</a> <small>（{file.size.toLocaleString()} 字节）</small>
      {textFile.test(file.path) && <button type="button" aria-expanded={previewPath === file.path} onClick={() => setPreviewPath(previewPath === file.path ? '' : file.path)}>{previewPath === file.path ? '关闭预览' : '预览'}</button>}
      {previewPath === file.path && preview.key === previewKey && <div className="rs-file-preview" aria-label={`${file.path}预览`}>
        {preview.loading && <p role="status">正在读取预览…</p>}
        {preview.error && <p role="alert">{preview.error}</p>}
        {preview.text !== undefined && <pre>{preview.text}</pre>}
      </div>}
    </li>)}</ul>
  </section>;
}
