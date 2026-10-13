import { factoryRequest, ApiError } from '../../../web/api.js';
import type { Artifact, JobDetail } from '../../../web/models.js';
import type { PersonalSession } from './personalAgentApi.js';

export async function captureNativeArtifacts(detail: JobDetail, session: PersonalSession, commandRequestId: string, signal?: AbortSignal): Promise<{ artifacts: Artifact[]; skipped: number }> {
  if (!session.connectionPin || !session.nativeSessionId) throw new ApiError('原生会话绑定尚未确认。', 409, 'NATIVE_SESSION_UNCONFIRMED');
  const value = await factoryRequest<Record<string, unknown>>(`/personal-agent/tasks/${encodeURIComponent(detail.job.id)}/artifacts`, 'POST',
    { commandRequestId, expectedFingerprint: session.connectionPin.fingerprint }, signal, detail.job.ownerId);
  const fields = ['taskId', 'ownerId', 'commandRequestId', 'nativeProjectId', 'nativeSessionId', 'artifacts', 'skipped', 'scientificConclusionVerified'];
  const invalid = () => new ApiError('产物回执无法核对，请保留原任务后重试。', 200, 'INVALID_RESPONSE');
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(k => !fields.includes(k))
      || value.taskId !== detail.job.id || value.ownerId !== detail.job.ownerId || value.commandRequestId !== commandRequestId
      || value.nativeProjectId !== session.nativeProjectId || value.nativeSessionId !== session.nativeSessionId
      || value.scientificConclusionVerified !== false || !Array.isArray(value.artifacts) || value.artifacts.length > 16
      || !Array.isArray(value.skipped) || value.skipped.length > 2000) throw invalid();
  const artifacts = value.artifacts as Artifact[];
  for (const item of artifacts) {
    const a = item as Artifact & { provenance?: Record<string, unknown> };
    if (!a || typeof a !== 'object' || Object.keys(a).some(k => !['id', 'jobId', 'name', 'mediaType', 'size', 'sha256', 'createdAt', 'provenance'].includes(k))
        || a.jobId !== detail.job.id || typeof a.id !== 'string' || !/^[A-Za-z0-9_.:-]{1,200}$/.test(a.id)
        || typeof a.name !== 'string' || !a.name || a.name.length > 120 || /[/\\\r\n]/.test(a.name)
        || typeof a.mediaType !== 'string' || !['text/plain', 'text/csv', 'text/markdown', 'application/json'].includes(a.mediaType)
        || !Number.isSafeInteger(a.size) || a.size < 0 || a.size > 32 * 1024 * 1024 || !/^[a-f0-9]{64}$/.test(a.sha256)
        || typeof a.createdAt !== 'string' || !a.provenance || a.provenance.source !== 'native-orx-file-api'
        || a.provenance.nativeProjectId !== session.nativeProjectId || a.provenance.nativeSessionId !== session.nativeSessionId
        || a.provenance.commandRequestId !== commandRequestId || a.provenance.scientificConclusionVerified !== false) throw invalid();
  }
  if (new Set(artifacts.map(a => a.id)).size !== artifacts.length) throw invalid();
  for (const item of value.skipped) {
    if (!item || typeof item !== 'object' || Object.keys(item).some(k => !['path', 'reason'].includes(k))
        || typeof item.path !== 'string' || !item.path || item.path.length > 512
        || !['FILE_COUNT_LIMIT', 'FILE_UNAVAILABLE_OR_INCOMPLETE', 'OUTPUT_BYTE_LIMIT', 'TASK_OUTPUT_LIMIT'].includes(item.reason)) throw invalid();
  }
  return { artifacts, skipped: value.skipped.length };
}
