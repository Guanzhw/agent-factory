import type { MaterialReference } from './models.js';
export interface ComparisonInputManifest {
  schema: 1; evidenceKind: 'synthetic_comparison_input'; choice: string;
  dataset: { path: string; sha256: string; origin: 'synthetic'; license: string; sampleSetSha256: string; sampleCount: number };
  evaluator: { path: string; sha256: string; protocolRevision: string };
  baselineFiles: Record<string, string>; candidateFiles: Record<string, string>; allowedChanges: string[];
  metric: { id: string; unit: string; direction: 'minimize' | 'maximize'; minimumImprovement: number }; seed: number;
  resourceLimits: { cpu: number; memoryMb: number; wallSeconds: number; outputBytes: number };
}
export interface ComparisonSeed { applicationRef: MaterialReference; mode: string; goal: string; input: ComparisonInputManifest }
export interface ComparisonItem extends ComparisonSeed { name: string }
export interface ComparisonObservation { schema: 1; contractSha256: string; variantSha256: string; datasetSha256: string; evaluatorSha256: string; sampleSetSha256: string; sampleCount: number; seed: number; metricId: string; unit: string; status: 'completed' | 'failed' | 'cancelled' | 'unknown'; value: number | null; resultSha256: string }
export interface ComparisonAssessment { schema: 1; evidenceKind: 'offline_comparison_assessment'; contractSha256: string; candidateSha256: string; status: 'inconclusive' | 'improved' | 'regressed' | 'unchanged'; improvement: number | null; metric: ComparisonInputManifest['metric']; reasons: string[]; executionVerified: false; scientificConclusionVerified: false }
export interface ComparisonEvidence { schema: 1; evidenceKind: 'controlled_comparison'; ownerId: string; taskId: string; planId: string; nativeRunId: string | null; choice: string | null; status: 'pending' | 'ready' | 'failed' | 'cancelled' | 'unknown' | 'invalid'; executionVerified: boolean; scientificConclusionVerified: false; contractSha256: string | null; candidateSha256: string | null; input: ComparisonInputManifest | null; baseline: ComparisonObservation | null; candidate: ComparisonObservation | null; assessment: ComparisonAssessment | null; artifactIds: { raw: string; report: string } | null; artifactHashes: { raw: string; report: string } | null; process: { leaseId: string; providerJobId: string; executionStatus: string; exitCode: number | null; allStopped: boolean; capacityHeld: boolean } | null }
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const id = (v: unknown): v is string => typeof v === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$/.test(v);
const hash = (v: unknown): v is string => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v);
const text = (v: unknown, max: number): v is string => typeof v === 'string' && !!v.trim() && [...v].length <= max;
const path = (v: unknown): v is string => typeof v === 'string' && v.length <= 160 && v.split('/').every(p => /^[A-Za-z0-9_.-]+$/.test(p) && p !== '.' && p !== '..');
const integer = (v: unknown, min: number, max: number) => Number.isSafeInteger(v) && Number(v) >= min && Number(v) <= max;
const number = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && Math.abs(v) <= 1e12;
const exact = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k));
const fail = () => new Error('比较输入、任务身份或评估依据无法核对。');
function files(v: unknown): v is Record<string, string> { return record(v) && Object.keys(v).length >= 1 && Object.keys(v).length <= 30 && Object.entries(v).every(([p, h]) => path(p) && hash(h)); }
function metric(v: unknown): v is ComparisonInputManifest['metric'] { return record(v) && exact(v, ['id', 'unit', 'direction', 'minimumImprovement']) && id(v.id) && id(v.unit) && ['minimize', 'maximize'].includes(String(v.direction)) && number(v.minimumImprovement) && v.minimumImprovement >= 0; }
export function comparisonInput(v: unknown): ComparisonInputManifest {
  if (!record(v) || !exact(v, ['schema', 'evidenceKind', 'choice', 'dataset', 'evaluator', 'baselineFiles', 'candidateFiles', 'allowedChanges', 'metric', 'seed', 'resourceLimits'])
      || v.schema !== 1 || v.evidenceKind !== 'synthetic_comparison_input' || !id(v.choice) || !record(v.dataset) || !record(v.evaluator)
      || !exact(v.dataset, ['path', 'sha256', 'origin', 'license', 'sampleSetSha256', 'sampleCount']) || !exact(v.evaluator, ['path', 'sha256', 'protocolRevision'])
      || !path(v.dataset.path) || !hash(v.dataset.sha256) || v.dataset.origin !== 'synthetic' || !id(v.dataset.license) || !hash(v.dataset.sampleSetSha256) || !integer(v.dataset.sampleCount, 1, 10000)
      || !path(v.evaluator.path) || !hash(v.evaluator.sha256) || !id(v.evaluator.protocolRevision) || v.dataset.path === v.evaluator.path
      || !files(v.baselineFiles) || !files(v.candidateFiles) || !Array.isArray(v.allowedChanges) || v.allowedChanges.length < 1 || v.allowedChanges.length > 20 || !v.allowedChanges.every(path)
      || new Set(v.allowedChanges).size !== v.allowedChanges.length || !metric(v.metric) || !integer(v.seed, 0, 2 ** 31 - 1) || !record(v.resourceLimits)
      || !exact(v.resourceLimits, ['cpu', 'memoryMb', 'wallSeconds', 'outputBytes']) || !integer(v.resourceLimits.cpu, 1, 64) || !integer(v.resourceLimits.memoryMb, 1, 196608)
      || !integer(v.resourceLimits.wallSeconds, 1, 3600) || !integer(v.resourceLimits.outputBytes, 1, 10485760)) throw fail();
  const baseline = v.baselineFiles, candidate = v.candidateFiles, changes = v.allowedChanges, dataset = v.dataset, evaluator = v.evaluator;
  if (Object.keys(baseline).length !== Object.keys(candidate).length || Object.keys(baseline).some(p => !Object.hasOwn(candidate, p) || baseline[p] !== candidate[p] && !changes.includes(p))
      || changes.some(p => !Object.hasOwn(baseline, p) || p === dataset.path || p === evaluator.path)
      || baseline[v.dataset.path] !== v.dataset.sha256 || baseline[v.evaluator.path] !== v.evaluator.sha256) throw fail();
  return v as unknown as ComparisonInputManifest;
}
export function comparisonCatalog(v: unknown, ownerId: string): ComparisonItem[] {
  if (!record(v) || v.schema !== 1 || v.ownerId !== ownerId || v.evidenceKind !== 'controlled_comparison' || v.scientificConclusionVerified !== false || !Array.isArray(v.items) || v.items.length > 100) throw fail();
  const items = v.items.map(item => {
    if (!record(item) || !record(item.applicationRef) || !id(item.applicationRef.id) || !integer(item.applicationRef.version, 1, 2 ** 31 - 1) || !hash(item.applicationRef.sha256)
        || !id(item.mode) || !text(item.name, 120) || !text(item.goal, 2000)) throw fail();
    const input = comparisonInput(item.input);
    if (item.mode !== input.choice) throw fail();
    return { applicationRef: item.applicationRef, mode: item.mode, name: item.name, goal: item.goal, input } as unknown as ComparisonItem;
  });
  if (new Set(items.map(item => `${item.applicationRef.id}@${item.applicationRef.version}:${item.mode}`)).size !== items.length) throw fail();
  return items;
}
function observation(v: unknown, input: ComparisonInputManifest, contract: string): v is ComparisonObservation {
  if (!record(v) || !exact(v, ['schema', 'contractSha256', 'variantSha256', 'datasetSha256', 'evaluatorSha256', 'sampleSetSha256', 'sampleCount', 'seed', 'metricId', 'unit', 'status', 'value', 'resultSha256'])
      || v.schema !== 1 || v.contractSha256 !== contract || !hash(v.variantSha256) || v.datasetSha256 !== input.dataset.sha256 || v.evaluatorSha256 !== input.evaluator.sha256
      || v.sampleSetSha256 !== input.dataset.sampleSetSha256 || !integer(v.sampleCount, 0, input.dataset.sampleCount) || v.seed !== input.seed || v.metricId !== input.metric.id || v.unit !== input.metric.unit
      || !['completed', 'failed', 'cancelled', 'unknown'].includes(String(v.status)) || !hash(v.resultSha256)) return false;
  return v.status === 'completed' ? v.sampleCount === input.dataset.sampleCount && number(v.value) : v.value === null;
}
export function comparisonEvidence(v: unknown, scope: { ownerId: string; taskId: string; planId: string; artifacts: { id: string; sha256?: string; size?: number }[] }): { kind: 'missing' } | { kind: 'invalid' } | { kind: 'verified'; evidence: ComparisonEvidence; ranked: boolean } {
  if (v === undefined || v === null) return { kind: 'missing' };
  try {
    if (!record(v) || v.schema !== 1 || v.evidenceKind !== 'controlled_comparison' || v.ownerId !== scope.ownerId || v.taskId !== scope.taskId || v.planId !== scope.planId || v.scientificConclusionVerified !== false
        || !['pending', 'ready', 'failed', 'cancelled', 'unknown', 'invalid'].includes(String(v.status)) || typeof v.executionVerified !== 'boolean'
        || !(v.nativeRunId === null || id(v.nativeRunId)) || !(v.contractSha256 === null || hash(v.contractSha256)) || !(v.candidateSha256 === null || hash(v.candidateSha256))) throw fail();
    const input = v.input === null ? null : comparisonInput(v.input);
    if (input && v.choice !== input.choice || !input && v.choice !== null && !id(v.choice)) throw fail();
    if (v.process !== null && (!record(v.process) || !id(v.process.leaseId) || !id(v.process.providerJobId)
        || !['PREPARED', 'DISPATCHING', 'RUNNING', 'UNKNOWN', 'COMPLETED', 'FAILED', 'CANCELLED', 'LIMIT_STOPPED'].includes(String(v.process.executionStatus))
        || !(v.process.exitCode === null || integer(v.process.exitCode, -255, 255)) || typeof v.process.allStopped !== 'boolean' || typeof v.process.capacityHeld !== 'boolean' || v.process.allStopped && !['COMPLETED', 'FAILED', 'CANCELLED', 'LIMIT_STOPPED'].includes(String(v.process.executionStatus)) || v.process.capacityHeld === false && v.process.allStopped !== true)) throw fail();
    if (v.artifactIds !== null && (!record(v.artifactIds) || !exact(v.artifactIds, ['raw', 'report']) || !id(v.artifactIds.raw) || !id(v.artifactIds.report))) throw fail();
    if (v.artifactHashes !== null && (!record(v.artifactHashes) || !exact(v.artifactHashes, ['raw', 'report']) || !hash(v.artifactHashes.raw) || !hash(v.artifactHashes.report))) throw fail();
    if ((v.artifactIds === null) !== (v.artifactHashes === null)) throw fail();
    if (v.status !== 'ready') {
      for (const result of [v.baseline, v.candidate]) if (result !== null && (!input || !hash(v.contractSha256) || !observation(result, input, v.contractSha256))) throw fail();
      if (v.assessment !== null || v.executionVerified === true) throw fail();
      return { kind: v.status === 'invalid' ? 'invalid' : 'verified', evidence: v as unknown as ComparisonEvidence, ranked: false };
    }
    if (!input || !hash(v.contractSha256) || !hash(v.candidateSha256) || !id(v.nativeRunId) || v.executionVerified !== true
        || !observation(v.baseline, input, v.contractSha256) || !observation(v.candidate, input, v.contractSha256)
        || !record(v.artifactIds) || !record(v.artifactHashes) || !record(v.assessment)) throw fail();
    if (!record(v.process) || v.process.executionStatus !== 'COMPLETED' || v.process.exitCode !== 0 || v.process.allStopped !== true || v.process.capacityHeld !== false) throw fail();
    const artifactIds = v.artifactIds, artifactHashes = v.artifactHashes;
    for (const kind of ['raw', 'report']) if (!id(v.artifactIds[kind]) || !hash(v.artifactHashes[kind]) || scope.artifacts.filter(a => a.id === artifactIds[kind] && a.sha256 === artifactHashes[kind]).length !== 1) throw fail();
    if (v.artifactIds.raw === v.artifactIds.report || v.baseline.resultSha256 !== v.artifactHashes.raw || v.candidate.resultSha256 !== v.artifactHashes.raw) throw fail();
    const a = v.assessment;
    if (!exact(a, ['schema', 'evidenceKind', 'contractSha256', 'candidateSha256', 'status', 'improvement', 'metric', 'reasons', 'executionVerified', 'scientificConclusionVerified'])
        || a.schema !== 1 || a.evidenceKind !== 'offline_comparison_assessment' || a.contractSha256 !== v.contractSha256 || a.candidateSha256 !== v.candidateSha256
        || a.executionVerified !== false || a.scientificConclusionVerified !== false || !metric(a.metric) || Object.keys(input.metric).some(k => (a.metric as unknown as Record<string, unknown>)[k] !== (input.metric as unknown as Record<string, unknown>)[k])
        || !Array.isArray(a.reasons)) throw fail();
    const reasons = [v.baseline.status !== 'completed' ? `BASELINE_${v.baseline.status.toUpperCase()}` : null, v.candidate.status !== 'completed' ? `CANDIDATE_${v.candidate.status.toUpperCase()}` : null].filter(x => x !== null);
    if (a.reasons.length !== reasons.length || a.reasons.some((reason, i) => reason !== reasons[i])) throw fail();
    if (reasons.length) { if (a.status !== 'inconclusive' || a.improvement !== null) throw fail(); }
    else {
      const improvement = (Number(v.candidate.value) - Number(v.baseline.value)) * (input.metric.direction === 'minimize' ? -1 : 1);
      const status = improvement > input.metric.minimumImprovement ? 'improved' : improvement < -input.metric.minimumImprovement ? 'regressed' : 'unchanged';
      if (typeof a.improvement !== 'number' || !Number.isFinite(a.improvement) || a.improvement !== improvement || a.status !== status) throw fail();
    }
    return { kind: 'verified', evidence: v as unknown as ComparisonEvidence, ranked: reasons.length === 0 };
  } catch { return { kind: 'invalid' }; }
}
