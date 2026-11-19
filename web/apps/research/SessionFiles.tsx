import { useEffect, useRef, useState } from 'react';
import { authEpoch, assertAuthEpoch, expireBrowserSession } from '../../browserAuth.js';
import { ApiError, factoryRequest } from '../../api.js';
import { draftKey, readStored, removeStored, writeStored } from './researchSessionStorage.js';
import './SessionFiles.css';

const textFile = /\.(?:md|markdown|txt|text|json|jsonl|ya?ml|toml|ini|csv|tsv|py|js|jsx|ts|tsx|css|html|xml|svg|sh|sql|log)$/i;

export async function uploadFile(owner: string, session: string, file: File) {
  const data = new FormData();
  data.append('file', file);
  const key = `${draftKey(owner, session)}:upload:${JSON.stringify([file.name, file.size])}`;
  const pending = readStored<string | null>(key, null);
  async function send(requestId: string) {
    writeStored(key, requestId);
    return factoryRequest<{ path: string; size: number }>(`/research/sessions/${encodeURIComponent(session)}/files?requestId=${requestId}`,
      'POST', data, undefined, owner);
  }
  let result;
  try { result = await send(pending ?? crypto.randomUUID()); }
  catch (error) {
    if (error instanceof ApiError && (error.status === 0 || error.code === 'INVALID_RESPONSE')) {
      throw new Error('上传结果未确认。请重新选择同一个文件重试。');
    }
    // Different bytes can have the same name and size.
    if (!pending || !(error instanceof ApiError && error.status === 409)) throw error;
    removeStored(key);
    if (!error.message.startsWith('IDEMPOTENCY_CONFLICT')) throw error;
    result = await send(crypto.randomUUID());
  }
  removeStored(key);
  return result;
}

export function SessionFiles({ ownerId, sessionId, revision, onAttention }: { ownerId: string; sessionId: string; revision: string; onAttention?: (value: boolean) => void }) {
  const [files, setFiles] = useState<{ path: string; size: number }[]>([]);
  const [error, setError] = useState('');
  const [errors, setErrors] = useState<{ path: string; message: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [directory, setDirectory] = useState('.');
  const [directories, setDirectories] = useState<string[]>([]);
  const [offset, setOffset] = useState(0);
  const passage = useRef({ decoder: new TextDecoder('utf-8', { fatal: true }), text: '', end: 0, tag: '' });
  const [refresh, setRefresh] = useState(0);
  const [previewPath, setPreviewPath] = useState('');
  const [preview, setPreview] = useState<{ key: string; text?: string; more?: boolean; error?: string; loading?: boolean }>({ key: '' });
  const base = `/research/sessions/${encodeURIComponent(sessionId)}/files`;
  const previewKey = `${ownerId}\0${base}\0${revision}\0${refresh}\0${previewPath}`;
  useEffect(() => { onAttention?.(!!error || errors.length > 0); }, [error, errors, onAttention]);
  useEffect(() => {
    const abort = new AbortController();
    setError('');
    setLoading(true);
    setFiles([]); setDirectories([]);
    setErrors([]);
    setPreviewPath('');
    void factoryRequest<{ files: typeof files; errors: typeof errors; directories?: string[] }>(`${base}?directory=${encodeURIComponent(directory)}`, 'GET', undefined, abort.signal, ownerId).then(result => {
      if (abort.signal.aborted) return;
      setFiles(result.files); setDirectories(result.directories ?? []);
      setErrors(result.errors);
      setLoading(false);
    }).catch((reason: unknown) => {
      if (!abort.signal.aborted) {
        setError(reason instanceof Error ? reason.message : '文件列表暂时不可用。');
        setLoading(false);
      }
    });
    return () => abort.abort();
  }, [base, ownerId, revision, refresh, directory]);
  useEffect(() => {
    if (!previewPath) return;
    const abort = new AbortController();
    const epoch = authEpoch();
    const url = `/api/factory${base}/download?path=${encodeURIComponent(previewPath)}`;
    if (offset === 0) passage.current = { decoder: new TextDecoder('utf-8', { fatal: true }), text: '', end: 0, tag: '' };
    const current = passage.current;
    setPreview({ key: previewKey, loading: true, text: current.text });
    void (async () => {
      try {
        const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: abort.signal,
          headers: { 'X-Factory-Expected-Owner': ownerId, Range: `bytes=${offset}-${offset + 65535}`, ...(offset && current.tag ? { 'If-Match': current.tag } : {}) } });
        assertAuthEpoch(epoch);
        if (response.status === 401) expireBrowserSession();
        if (response.status === 412) throw new Error('文件已变化，请刷新后重新读取。');
        if (response.status === 416 && offset === 0 && response.headers.get('Content-Range') === 'bytes */0') {
          if (!abort.signal.aborted) setPreview({ key: previewKey, text: '' });
          return;
        }
        if (response.status !== 206) throw new Error(`文件读取失败（${response.status}），请刷新文件列表后重试。`);
        const total = Number(response.headers.get('Content-Range')?.split('/')[1]);
        const bytes = await response.arrayBuffer();
        if (abort.signal.aborted) return;
        current.end = offset + bytes.byteLength;
        current.tag = response.headers.get('ETag') ?? '';
        const more = total > current.end;
        try { current.text += current.decoder.decode(bytes, { stream: more }); }
        catch { throw new Error('该文件不是有效的 UTF-8 文本，无法预览。'); }
        assertAuthEpoch(epoch);
        if (!abort.signal.aborted) setPreview({ key: previewKey, text: current.text, more });
      } catch (reason) {
        if (!abort.signal.aborted) setPreview({ key: previewKey, error: reason instanceof Error ? reason.message : '文件预览暂时不可用。' });
      }
    })();
    return () => abort.abort();
  }, [base, ownerId, previewKey, previewPath, offset]);
  return <section className="rs-files" aria-label="会话文件">
    <p>会话文件（{files.length}）</p>
    <p>下载工作目录中的当前文件。<button type="button" onClick={() => setRefresh(value => value + 1)}>刷新文件列表</button></p>
    {directory !== '.' && <button type="button" onClick={() => setDirectory(directory.split('/').slice(0, -1).join('/') || '.')}>上一级目录</button>}
    {directories.map(path => <button key={path} type="button" onClick={() => setDirectory(path)}>打开目录 {path}</button>)}
    {loading && <p role="status">正在读取文件…</p>}
    {error && <p role="alert">{error}</p>}
    {errors.length > 0 && <div role="alert"><p>部分路径无法读取，以下仅列出可访问的文件：</p>
      <ul>{errors.map(issue => <li key={issue.path}>{issue.path}：{issue.message}</li>)}</ul>
    </div>}
    {!loading && !error && errors.length === 0 && directories.length === 0 && files.length === 0 && <p>还没有生成文件。</p>}
    <ul>{files.map(file => <li key={file.path}>
      <a href={`/api/factory${base}/download?path=${encodeURIComponent(file.path)}`} download>{file.path}</a> <small>（{file.size.toLocaleString()} 字节）</small>
      {textFile.test(file.path) && <button type="button" aria-expanded={previewPath === file.path} onClick={() => { setOffset(0); setPreviewPath(previewPath === file.path ? '' : file.path); }}>{previewPath === file.path ? '关闭预览' : '预览'}</button>}
      {previewPath === file.path && preview.key === previewKey && <div className="rs-file-preview" aria-label={`${file.path}预览`}>
        {preview.loading && <p role="status">正在读取预览…</p>}
        {preview.error && <p role="alert">{preview.error}</p>}
        {preview.text !== undefined && <pre>{preview.text}</pre>}{preview.more && <button type="button" onClick={() => setOffset(passage.current.end)}>继续读取</button>}
      </div>}
    </li>)}</ul>
  </section>;
}
