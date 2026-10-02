import { ApiError, api } from './api.js';
import type { Artifact } from './models.js';

export const maxVerifiedDownloadBytes = 32 * 1024 * 1024;
export async function verifiedArtifact(jobId: string, artifact: Artifact, signal?: AbortSignal): Promise<Blob> {
  if (artifact.jobId !== jobId || !artifact.id || !/^[a-f0-9]{64}$/.test(artifact.sha256)
      || !Number.isSafeInteger(artifact.size) || artifact.size < 0 || artifact.size > maxVerifiedDownloadBytes) {
    throw new ApiError('产物归属或大小无法核对，下载已停止。', 0, 'ARTIFACT_UNVERIFIED');
  }
  let response: Response;
  try { response = await fetch(api.artifactUrl(jobId, artifact.id), { credentials: 'same-origin', redirect: 'error', signal }); }
  catch (error) { if (error instanceof Error && error.name === 'AbortError') throw error; throw new ApiError('无法读取产物；保留原产物引用后重试。', 0, 'OFFLINE'); }
  if (!response.ok) throw new ApiError(`产物服务返回 ${response.status}，没有下载未核对的内容。`, response.status, 'ARTIFACT_UNAVAILABLE');
  const length = response.headers.get('Content-Length');
  if (response.headers.get('X-Content-SHA256') !== artifact.sha256 || length !== null && (!/^\d+$/.test(length) || Number(length) !== artifact.size)) {
    await response.body?.cancel();
    throw new ApiError('产物响应与已保存的哈希或大小不一致，下载已停止。', 200, 'ARTIFACT_UNVERIFIED');
  }
  const reader = response.body?.getReader();
  if (!reader) throw new ApiError('产物响应没有可核对的内容。', 200, 'ARTIFACT_UNVERIFIED');
  const chunks: Uint8Array[] = []; let count = 0;
  try {
    for (;;) {
      const next = await reader.read(); if (next.done) break;
      count += next.value.byteLength;
      if (count > artifact.size || count > maxVerifiedDownloadBytes) { await reader.cancel(); throw new ApiError('产物超过已保存的大小，下载已停止。', 200, 'ARTIFACT_UNVERIFIED'); }
      chunks.push(next.value);
    }
  } finally { reader.releaseLock(); }
  if (count !== artifact.size) throw new ApiError('产物内容不完整，下载已停止。', 200, 'ARTIFACT_UNVERIFIED');
  const bytes = new Uint8Array(count); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), value => value.toString(16).padStart(2, '0')).join('');
  if (hash !== artifact.sha256) throw new ApiError('产物内容 SHA-256 不匹配，下载已停止。', 200, 'ARTIFACT_UNVERIFIED');
  return new Blob([bytes], { type: artifact.mediaType });
}
export function safeDownloadName(name: string): string { return Array.from(name, value => value.charCodeAt(0) < 32 || value.charCodeAt(0) === 127 || value === '/' || value === '\\' ? '_' : value).join('').slice(0, 180) || 'verified-artifact'; }
