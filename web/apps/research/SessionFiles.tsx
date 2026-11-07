import { useEffect, useState } from 'react';
import { factoryRequest } from '../../api.js';

export function SessionFiles({ ownerId, sessionId, revision }: { ownerId: string; sessionId: string; revision: string }) {
  const [files, setFiles] = useState<{ path: string; size: number }[]>([]);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const base = `/research/sessions/${encodeURIComponent(sessionId)}/files`;
  useEffect(() => {
    const abort = new AbortController();
    setError('');
    void factoryRequest<typeof files>(base, 'GET', undefined, abort.signal, ownerId).then(setFiles).catch((reason: unknown) => {
      if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : '文件列表暂时不可用。');
    });
    return () => abort.abort();
  }, [base, ownerId, revision, refresh]);
  return <section className="rs-files" aria-label="会话文件"><details open={files.length > 0 || !!error}>
    <summary>会话文件（{files.length}）</summary>
    <p>下载工作目录中的当前文件。<button type="button" onClick={() => setRefresh(value => value + 1)}>刷新文件列表</button></p>
    {error && <p role="alert">{error}</p>}
    {!error && files.length === 0 && <p>还没有生成文件。</p>}
    <ul>{files.map(file => <li key={file.path}><a href={`/api/factory${base}/download?path=${encodeURIComponent(file.path)}`} download>{file.path}</a> <small>（{file.size.toLocaleString()} 字节）</small></li>)}</ul>
  </details></section>;
}
