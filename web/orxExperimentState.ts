import type { JobDetail } from './models.js';
export const reviewedOrxCommit = 'f336b121525d99364e2dee4fe90b2784894a54e6';
export const reviewedOrxBinarySha256 = 'd602b1b184589b72d9ce68a119b8959ee595f46869e951f63309781e60b173e7';
export interface OrxExperiment {
  schema: 1; evidenceKind: 'toy_local_evaluation'; taskId: string; planId?: string | null; nativeRunId?: string | null;
  effectFingerprint?: string | null; projectId?: string | null; experimentId?: string | null; orxRunId?: string | null;
  status: 'NOT_STARTED' | 'UNKNOWN' | 'starting' | 'running' | 'done' | 'failed' | 'cancelled';
  launchIntent: { state: string; acknowledgement: 'unknown' | 'observed_native_run'; previousRunId?: string | null };
  provenance?: Record<string, unknown>; evaluation?: Record<string, unknown> | null; stopEvidence?: Record<string, unknown> | null;
  artifactId?: string; artifactSha256?: string; observationSource: string; liveObservation: false;
}
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const identifier = (value: unknown): value is string => typeof value === 'string' && value.length > 0 && value.length <= 256 && !Array.from(value).some(character => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127);
const hash = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const commit = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{40}$/.test(value);
export type OrxExperimentState = { kind: 'missing' } | { kind: 'invalid' } | { kind: 'verified'; experiment: OrxExperiment; sourceVerified: boolean; evaluationVerified: boolean; stopped: boolean };
export function orxExperimentState(detail: JobDetail): OrxExperimentState {
  const value = detail.orxExperiment;
  if (value === undefined || value === null) return { kind: 'missing' };
  if (!record(value) || value.schema !== 1 || value.evidenceKind !== 'toy_local_evaluation' || value.taskId !== detail.job.id
      || !['NOT_STARTED', 'UNKNOWN', 'starting', 'running', 'done', 'failed', 'cancelled'].includes(String(value.status))
      || !record(value.launchIntent) || !identifier(value.launchIntent.state) || !['unknown', 'observed_native_run'].includes(String(value.launchIntent.acknowledgement))
      || !['durable_factory_intent', 'durable_factory_effect', 'durable_factory_observation'].includes(String(value.observationSource)) || value.liveObservation !== false) return { kind: 'invalid' };
  if (value.planId !== undefined && value.planId !== null && value.planId !== detail.job.planId) return { kind: 'invalid' };
  for (const key of ['nativeRunId', 'projectId', 'experimentId', 'orxRunId']) if (value[key] !== undefined && value[key] !== null && !identifier(value[key])) return { kind: 'invalid' };
  if (value.effectFingerprint !== undefined && value.effectFingerprint !== null && !hash(value.effectFingerprint)) return { kind: 'invalid' };
  const nativeRunIds = detail.events.filter(event => event.type === 'native_accepted').map(event => event.data?.runId).filter(identifier);
  if (value.nativeRunId && nativeRunIds.length && !nativeRunIds.includes(String(value.nativeRunId))) return { kind: 'invalid' };
  if (value.launchIntent.acknowledgement === 'observed_native_run' && (!value.orxRunId || !value.nativeRunId || !value.projectId || !value.experimentId || !value.effectFingerprint)) return { kind: 'invalid' };
  if (!['NOT_STARTED', 'UNKNOWN'].includes(String(value.status)) && value.launchIntent.acknowledgement !== 'observed_native_run') return { kind: 'invalid' };
  const p = value.provenance;
  const sourceVerified = record(p) && p.taskId === detail.job.id && p.projectId === value.projectId && p.experimentId === value.experimentId
    && p.evidenceKind === 'actual_orx_local_toy_evaluation' && p.zeroModelCalls === true && p.githubSyncEnabled === false
    && record(p.fileSha256) && ['baseline.py', 'candidate.py', 'evaluator.py', 'dataset.json'].every(key => hash(p.fileSha256 && (p.fileSha256 as Record<string, unknown>)[key]))
    && p.upstreamSourceCommit === reviewedOrxCommit && p.binarySha256 === reviewedOrxBinarySha256
    && commit(p.recipeSourceCommit) && ['upstreamArchiveSha256', 'recipeArchiveSha256', 'commandSha256', 'evaluatorSha256', 'datasetSha256'].every(key => hash(p[key]));
  const e = value.evaluation;
  if (!(e === undefined || e === null || record(e)) || !(value.stopEvidence === undefined || value.stopEvidence === null || record(value.stopEvidence))) return { kind: 'invalid' };
  let evaluationVerified = false;
  if (record(e)) {
    const files = e.fileSha256;
    evaluationVerified = !!sourceVerified && record(p) && hash(p.resultSha256) && e.schemaVersion === 1
      && e.evidenceKind === 'actual_orx_local_toy_evaluation' && e.taskId === detail.job.id && e.status === value.status && e.zeroModelCalls === true
      && Number.isSafeInteger(e.sampleCount) && Number(e.sampleCount) > 0 && e.metric === 'mean_squared_error'
      && record(e.baseline) && typeof e.baseline.value === 'number' && Number.isFinite(e.baseline.value)
      && record(e.candidate) && typeof e.candidate.value === 'number' && Number.isFinite(e.candidate.value)
      && typeof e.improvement === 'number' && Number.isFinite(e.improvement) && record(files)
      && ['baseline.py', 'candidate.py', 'evaluator.py', 'dataset.json'].every(key => hash(files[key]))
      && files['evaluator.py'] === p.evaluatorSha256 && files['dataset.json'] === p.datasetSha256
      && record(p.fileSha256) && ['baseline.py', 'candidate.py', 'evaluator.py', 'dataset.json'].every(key => files[key] === (p.fileSha256 as Record<string, unknown>)[key]);
  }
  if (value.artifactId !== undefined || value.artifactSha256 !== undefined) {
    if (!identifier(value.artifactId) || !hash(value.artifactSha256) || !detail.artifacts.some(artifact => artifact.id === value.artifactId && artifact.jobId === detail.job.id && artifact.sha256 === value.artifactSha256)) return { kind: 'invalid' };
  }
  return { kind: 'verified', experiment: value as unknown as OrxExperiment, sourceVerified: !!sourceVerified, evaluationVerified,
    stopped: record(value.stopEvidence) && value.stopEvidence.allStopped === true && value.stopEvidence.kind === 'windows_task_job'
      && value.stopEvidence.activeProcesses === 0 && Array.isArray(value.stopEvidence.enforced) && value.stopEvidence.enforced.includes('active_processes') };
}
