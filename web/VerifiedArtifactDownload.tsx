import { useRef, useState } from 'react';
import { safeDownloadName, verifiedArtifact } from './artifactDownload.js';
import type { Artifact } from './models.js';

export function ArtifactDownload({ jobId, artifact }: { jobId: string; artifact: Artifact }) {
  const lock = useRef(false); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [verified, setVerified] = useState(false);
  async function download() {
    if (lock.current) return; lock.current = true; setBusy(true); setError(''); setVerified(false);
    try {
      const blob = await verifiedArtifact(jobId, artifact); const url = URL.createObjectURL(blob);
      try { const link = document.createElement('a'); link.href = url; link.download = safeDownloadName(artifact.name); document.body.append(link); link.click(); link.remove(); setVerified(true); }
      finally { setTimeout(() => URL.revokeObjectURL(url), 1000); }
    } catch (failure) { setError(failure instanceof Error ? failure.message : '下载完整性未确认。'); }
    finally { lock.current = false; setBusy(false); }
  }
  return <><div className="artifact-download"><span className="file-glyph" aria-hidden="true">▤</span><div><strong>{artifact.name}</strong><small>{artifact.mediaType} · {artifact.size.toLocaleString()} 字节</small></div><button className="text-button" disabled={busy} onClick={() => void download()} aria-label={`校验并下载 ${artifact.name}`}>{busy ? '正在校验…' : '校验并下载'}</button></div>{verified && <p className="artifact-integrity" role="status">字节数与 SHA-256 已核对，已交给浏览器下载。</p>}{error && <div className="error-message" role="alert">{error}</div>}</>;
}
