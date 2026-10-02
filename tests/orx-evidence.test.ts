import { describe, expect, it } from 'vitest';
import { orxExperimentState, reviewedOrxBinarySha256, reviewedOrxCommit, reviewedLinuxOrxBinarySha256, reviewedLinuxRuntimeImage, type OrxExperiment } from '../web/orxExperimentState.js';
import type { JobDetail } from '../web/models.js';
const hash = 'a'.repeat(64);
function experiment(): OrxExperiment { return {
  schema: 1, evidenceKind: 'toy_local_evaluation', taskId: 'task', planId: 'plan', nativeRunId: 'native-run', effectFingerprint: hash,
  projectId: 'owned-project', experimentId: 'owned-experiment', orxRunId: 'orx-run', status: 'done', launchIntent: { state: 'done', acknowledgement: 'observed_native_run', previousRunId: null },
  provenance: { taskId: 'task', projectId: 'owned-project', experimentId: 'owned-experiment', evidenceKind: 'actual_orx_local_toy_evaluation', zeroModelCalls: true, githubSyncEnabled: false, fileSha256: { 'baseline.py': hash, 'candidate.py': hash, 'evaluator.py': hash, 'dataset.json': hash }, upstreamSourceCommit: reviewedOrxCommit, upstreamArchiveSha256: hash, binarySha256: reviewedOrxBinarySha256, recipeSourceCommit: 'b'.repeat(40), recipeArchiveSha256: hash, commandSha256: hash, evaluatorSha256: hash, datasetSha256: hash, resultSha256: hash },
  evaluation: { schemaVersion: 1, evidenceKind: 'actual_orx_local_toy_evaluation', taskId: 'task', status: 'done', zeroModelCalls: true, sampleCount: 8, metric: 'mean_squared_error', baseline: { value: 16 }, candidate: { value: 0 }, improvement: 16, fileSha256: { 'baseline.py': hash, 'candidate.py': hash, 'evaluator.py': hash, 'dataset.json': hash } },
  stopEvidence: { allStopped: true, kind: 'windows_task_job', activeProcesses: 0, enforced: ['active_processes'] }, observationSource: 'durable_factory_effect', liveObservation: false,
}; }
function detail(value?: unknown): JobDetail { return { job: { id: 'task', planId: 'plan', ownerId: 'alice' }, artifacts: [], events: [{ type: 'native_accepted', data: { runId: 'native-run' } }], ...(value === undefined ? {} : { orxExperiment: value }) } as unknown as JobDetail; }
describe('actual ORX persisted evidence projection', () => {
  it('accepts identity-bound real CLI/evaluator facts and separately requires positive stopping evidence', () => {
    const state = orxExperimentState(detail(experiment())); expect(state.kind).toBe('verified');
    if (state.kind === 'verified') { expect(state.sourceVerified).toBe(true); expect(state.evaluationVerified).toBe(true); expect(state.stopped).toBe(true); }
    const value = experiment(); value.status = 'cancelled'; value.evaluation = null; value.stopEvidence = null;
    const canceled = orxExperimentState(detail(value)); expect(canceled.kind).toBe('verified');
    if (canceled.kind === 'verified') expect(canceled.stopped).toBe(false);
    value.stopEvidence = { allStopped: true }; const absentProof = orxExperimentState(detail(value)); if (absentProof.kind === 'verified') expect(absentProof.stopped).toBe(false);
  });
  it('requires Linux runtime identity and actual container stopping evidence', () => {
    const value = experiment();
    Object.assign(value.provenance!, { runtimePlatform: 'linux', binarySha256: reviewedLinuxOrxBinarySha256, runtimeImage: reviewedLinuxRuntimeImage });
    value.stopEvidence = { allStopped: true, kind: 'linux_task_container', containerId: hash, specSha256: hash,
      activeProcesses: 0, network: 'none', pidLimitIncludesThreads: true, enforced: ['kernel_tasks'] };
    const state = orxExperimentState(detail(value));
    if (state.kind === 'verified') { expect(state.sourceVerified).toBe(true); expect(state.stopped).toBe(true); }
    else expect.fail('Expected verified Linux evidence');
    value.stopEvidence.kind = 'windows_task_job';
    const wrongPlatform = orxExperimentState(detail(value));
    if (wrongPlatform.kind === 'verified') expect(wrongPlatform.stopped).toBe(false);
    value.provenance!.runtimeImage = 'unreviewed';
    const drift = orxExperimentState(detail(value));
    if (drift.kind === 'verified') expect(drift.sourceVerified).toBe(false);
  });
  it('keeps unresolved original launch observable without inventing a run or score', () => {
    const value = { schema: 1, evidenceKind: 'toy_local_evaluation', taskId: 'task', status: 'UNKNOWN', nativeRunId: 'native-run', orxRunId: null, launchIntent: { state: 'UNKNOWN', acknowledgement: 'unknown' }, observationSource: 'durable_factory_intent', liveObservation: false };
    const state = orxExperimentState(detail(value)); expect(state.kind).toBe('verified');
    if (state.kind === 'verified') { expect(state.evaluationVerified).toBe(false); expect(state.stopped).toBe(false); }
    expect(orxExperimentState(detail()).kind).toBe('missing');
  });
  it('rejects foreign task/plan/native run and unsupported observation or launch authority', () => {
    const values = [experiment(), experiment(), experiment(), experiment(), experiment()];
    values[0].taskId = 'other'; values[1].planId = 'other'; values[2].nativeRunId = 'other'; values[3].liveObservation = true as false; values[4].orxRunId = null;
    for (const value of values) expect(orxExperimentState(detail(value)).kind).toBe('invalid');
  });
  it('does not present a score if upstream binary, evaluator, dataset, or result provenance drifts', () => {
    for (const key of ['upstreamSourceCommit', 'binarySha256', 'evaluatorSha256', 'datasetSha256', 'resultSha256']) {
      const value = experiment(); value.provenance![key] = 'changed'; const state = orxExperimentState(detail(value));
      expect(state.kind).toBe('verified'); if (state.kind === 'verified') expect(state.evaluationVerified).toBe(false);
    }
    const value = experiment(); value.evaluation!.taskId = 'other'; const state = orxExperimentState(detail(value));
    expect(state.kind).toBe('verified'); if (state.kind === 'verified') expect(state.evaluationVerified).toBe(false);
  });
  it('links saved results to an exact owned artifact checksum', () => {
    const value = experiment(); value.artifactId = 'result'; value.artifactSha256 = hash;
    const d = detail(value); expect(orxExperimentState(d).kind).toBe('invalid');
    d.artifacts.push({ id: 'result', jobId: 'task', sha256: hash, name: 'result.json', size: 10, mediaType: 'application/json', createdAt: '2026-10-02T00:00:00Z' });
    expect(orxExperimentState(d).kind).toBe('verified');
    d.artifacts[0].jobId = 'other'; expect(orxExperimentState(d).kind).toBe('invalid');
  });
});
