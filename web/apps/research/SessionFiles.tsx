import { useEffect, useState } from 'react';
import { factoryRequest } from '../../api.js';

export function SessionFiles({ ownerId, sessionId, revision, onAttention }: { ownerId: string; sessionId: string; revision: string; onAttention?: (value: boolean) => void }) {
  const [files, setFiles] = useState<{ path: string; size: number }[]>([]);
  const [error, setError] = useState('');
  const [errors, setErrors] = useState<{ path: string; message: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const base = `/research/sessions/${encodeURIComponent(sessionId)}/files`;
  useEffect(() => { onAttention?.(!!error || errors.length > 0); }, [error, errors, onAttention]);
  useEffect(() => {
    const abort = new AbortController();
    setError('');
    setLoading(true);
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
  return <section className="rs-files" aria-label="会话文件">
    <p>会话文件（{files.length}）</p>
    <p>下载工作目录中的当前文件。<button type="button" onClick={() => setRefresh(value => value + 1)}>刷新文件列表</button></p>
    {loading && <p role="status">正在读取文件…</p>}
    {error && <p role="alert">{error}</p>}
    {errors.length > 0 && <div role="alert"><p>部分路径无法读取，以下仅列出可访问的文件：</p>
      <ul>{errors.map(issue => <li key={issue.path}>{issue.path}：{issue.message}</li>)}</ul>
    </div>}
    {!loading && !error && errors.length === 0 && files.length === 0 && <p>还没有生成文件。</p>}
    <ul>{files.map(file => <li key={file.path}><a href={`/api/factory${base}/download?path=${encodeURIComponent(file.path)}`} download>{file.path}</a> <small>（{file.size.toLocaleString()} 字节）</small></li>)}</ul>
  </section>;
}
