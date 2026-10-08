import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../web/api.js';
import { pendingApproval, type JobDetail } from '../web/models.js';
import { RemoteHandoffPanel } from '../web/RemoteHandoff.js';
import { nativeInteractionAvailable, remoteHandoffState } from '../web/remoteHandoffState.js';

afterEach(() => vi.unstubAllGlobals());

const originTask = '11111111-1111-4111-8111-111111111111';
const sourcePlan = '22222222-2222-4222-8222-222222222222';
const receiverPlan = '33333333-3333-4333-8333-333333333333';
const receiverTask = '44444444-4444-4444-8444-444444444444';
const receiverRun = '55555555-5555-4555-8555-555555555555';
const receiptId = '66666666-6666-4666-8666-666666666666';

function fixture(): JobDetail {
  const entries = ['model', 'environment'].map(kind => {
    const materialRef = { id: `${kind}-fixture`, version: 1, sha256: 'a'.repeat(64) };
    const sourceSpec = { materialRef, adapterId: `source-${kind}`, revision: 'source-v1', config: { privateOperatorConfig: 'do-not-render-config' }, connection: { ref: 'do-not-export-connection' } };
    const effectiveSpec = { ...sourceSpec, materialRef: { ...materialRef }, adapterId: `receiver-${kind}`, revision: 'receiver-v2' };
    return { kind, sourceSpec, effectiveSpec, mappingReference: `mapping-${kind}`, mappingRevision: 'mapping-v1', mappingSha256: 'b'.repeat(64) };
  });
  const proof = { schema: 1, originRef: 'trusted-origin', receiptId, originTaskId: originTask, originOwner: 'fixture-origin-user', receiverOwner: 'fixture-receiver-user', receiverPlanId: receiverPlan,
    manifestHash: 'c'.repeat(64), sourceConfiguration: { revision: 'source-config-v1', sha256: 'd'.repeat(64) }, receiverConfiguration: { revision: 'receiver-config-v2', sha256: 'e'.repeat(64) }, entries, sha256: 'f'.repeat(64) };
  return {
    job: { id: originTask, ownerId: 'fixture-origin-user', planId: sourcePlan, definitionId: 'fixture', definitionVersion: 1,
      definition: { id: 'fixture', version: 1, name: 'Controlled fixture', description: '', instructions: '', skills: [], tools: [], knowledge: [], modelPolicy: { providerId: 'controlled', modelId: 'controlled', maxSteps: 8 }, runtimePolicy: { timeoutSeconds: 10, allowExperiment: true }, published: true, createdAt: '2026-10-02T00:00:00Z' },
      binding: {}, input: { topic: 'Controlled remote experiment', mode: 'paused', scenario: 'normal' }, status: 'waiting_approval', runtime: 'live', attempt: 0, createdAt: '2026-10-02T00:00:00Z', updatedAt: '2026-10-02T00:00:00Z',
      executionPlacement: { kind: 'remote-factory', targetRef: 'trusted-receiver', originTaskId: originTask, state: 'PREPARING' }, allowedActions: ['inspect', 'reconcile', 'cancel', 'resume_remote'],
      approvalDetail: { id: 'unrelated-native-tool', version: 1, scope: 'Must not be mistaken for receiver-plan review' } },
    events: [], artifacts: [], snapshot: { receiverReviewRequired: true, remoteHandoff: { id: receiptId, originRef: 'trusted-origin', originOwnerId: 'fixture-origin-user', originTaskId: originTask, remoteOwnerId: 'fixture-receiver-user', requestId: 'original-source-admission', manifestHash: 'c'.repeat(64), remotePlanId: receiverPlan, remoteTaskId: null, remoteRunId: null, state: 'PREPARING', receiverBindingProof: proof } },
  };
}

function receipt(detail: JobDetail) { return detail.snapshot!.remoteHandoff as Record<string, unknown>; }
function proof(detail: JobDetail) { return receipt(detail).receiverBindingProof as Record<string, unknown>; }
function accepted(): JobDetail {
  const detail = fixture();
  Object.assign(receipt(detail), { state: 'ACCEPTED', remoteTaskId: receiverTask, remoteRunId: receiverRun });
  Object.assign(detail.job.executionPlacement!, { state: 'ACCEPTED', remoteTaskId: receiverTask, remoteRootTaskId: receiverTask, remoteRunId: receiverRun });
  detail.snapshot!.receiverReviewRequired = false;
  detail.job.allowedActions = ['inspect', 'reconcile', 'cancel', 'approve'];
  return detail;
}

describe('receiver-plan review and native task approval are separate', () => {
  it('recognizes the exact pending reservation and suppresses any native approval payload', () => {
    const detail = fixture();
    expect(remoteHandoffState(detail)).toMatchObject({ kind: 'pending', evidence: { receiverPlanId: receiverPlan, requestId: 'original-source-admission', receiverTaskId: null } });
    expect(nativeInteractionAvailable(detail)).toBe(false);
    expect(pendingApproval(detail)).toBeUndefined();
    expect(nativeInteractionAvailable(accepted())).toBe(true);
    expect(pendingApproval(accepted())).toMatchObject({ id: 'unrelated-native-tool' });
  });

  it('fails closed on scope substitution or a contradictory pre-dispatch task', async () => {
    const mutations: ((detail: JobDetail) => void)[] = [
      detail => { receipt(detail).originOwnerId = 'foreign-owner'; },
      detail => { receipt(detail).id = '-'.repeat(36); },
      detail => { receipt(detail).remoteOwnerId = 'invalid\u007fowner'; },
      detail => { proof(detail).receiverPlanId = sourcePlan; },
      detail => { proof(detail).originTaskId = receiverTask; },
      detail => { proof(detail).sha256 = 'not-a-digest'; },
      detail => { proof(detail).receiverConfiguration = { revision: 'v2', sha256: 'e'.repeat(64), endpoint: 'unexpected' }; },
      detail => { receipt(detail).remoteTaskId = receiverTask; },
      detail => { detail.snapshot!.receiverReviewRequired = false; },
      detail => { const entries = proof(detail).entries as { effectiveSpec: { materialRef: { sha256: string } } }[]; entries[0].effectiveSpec.materialRef.sha256 = '9'.repeat(64); },
    ];
    for (const change of mutations) {
      const detail = fixture(); change(detail);
      const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
      expect(remoteHandoffState(detail).kind).toBe('invalid');
      expect(pendingApproval(detail)).toBeUndefined();
      await expect(api.resumeRemote(detail)).rejects.toMatchObject({ code: 'REMOTE_REVIEW_UNVERIFIED' });
      expect(fetch).not.toHaveBeenCalled();
    }
  });

  it('accepts exact bounded federated identities without accepting control characters', () => {
    const detail = fixture();
    const sourceOwner = 'Department user / 研究員@example.org';
    const receiverOwner = 'Receiver team / 研究員@example.org';
    detail.job.ownerId = sourceOwner;
    receipt(detail).originOwnerId = sourceOwner; receipt(detail).remoteOwnerId = receiverOwner;
    proof(detail).originOwner = sourceOwner; proof(detail).receiverOwner = receiverOwner;
    expect(remoteHandoffState(detail)).toMatchObject({ kind: 'pending', evidence: { sourceOwner, receiverOwner } });
  });

  it('preserves fail-closed native interaction when a remote read has no binding evidence', () => {
    const detail = accepted();
    detail.snapshot = { remoteUnavailable: true };
    expect(remoteHandoffState(detail).kind).toBe('invalid');
    expect(nativeInteractionAvailable(detail)).toBe(false);
    expect(pendingApproval(detail)).toBeUndefined();
    const local = fixture(); delete local.job.executionPlacement; local.snapshot = {};
    expect(remoteHandoffState(local).kind).toBe('none');
    expect(pendingApproval(local)).toMatchObject({ id: 'unrelated-native-tool' });
  });

  it('keeps historical evidence after cancellation before dispatch without offering native task controls', () => {
    const detail = fixture();
    detail.job.status = 'canceled'; detail.job.allowedActions = ['inspect', 'reconcile'];
    detail.job.executionPlacement!.state = 'CANCELLED_NO_DISPATCH';
    receipt(detail).state = 'CANCELLED_NO_DISPATCH'; detail.snapshot!.receiverReviewRequired = false; detail.snapshot!.allStopped = true;
    expect(remoteHandoffState(detail)).toMatchObject({ kind: 'execution', evidence: { receiverPlanId: receiverPlan, receiverTaskId: null } });
    expect(nativeInteractionAvailable(detail)).toBe(false);
    expect(pendingApproval(detail)).toBeUndefined();
  });

  it('shows exact plan and safe provenance without rendering connection references or operator config', () => {
    const detail = fixture(); detail.job.allowedActions = ['inspect', 'reconcile'];
    const html = renderToStaticMarkup(createElement(RemoteHandoffPanel, { detail, busy: '', act: async (_name, work) => { await work(); }, onNotice: () => {} }));
    expect(html).toContain(receiverPlan);
    expect(html).toContain('source-model@source-v1');
    expect(html).toContain('receiver-model@receiver-v2');
    expect(html).toContain('receiver-config-v2');
    expect(html).toContain('f'.repeat(64));
    expect(html).toMatch(/<button[^>]+disabled/);
    expect(html).not.toContain('do-not-export-connection');
    expect(html).not.toContain('do-not-render-config');
    expect(html).not.toContain('fixture-origin-user');
    expect(html).not.toContain('unrelated-native-tool');
  });
});

describe('explicit remote continuation retains the original admitted scope', () => {
  it('requires current resume authority instead of treating read/reconcile as a run grant', async () => {
    const detail = fixture(); detail.job.allowedActions = ['inspect', 'reconcile'];
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    await expect(api.resumeRemote(detail)).rejects.toMatchObject({ code: 'REMOTE_REVIEW_UNVERIFIED' });
    expect(fetch).not.toHaveBeenCalled();
  });

  it('uses the original source plan, request key and target on repeated explicit attempts', async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(accepted().job), { status: 202 })));
    vi.stubGlobal('fetch', fetch);
    await api.resumeRemote(fixture()); await api.resumeRemote(fixture());
    expect(fetch.mock.calls.map(call => [call[0], call[1].method, JSON.parse(call[1].body)])).toEqual([
      ['/api/factory/instances', 'POST', { planId: sourcePlan, requestId: 'original-source-admission', executionTargetRef: 'trusted-receiver' }],
      ['/api/factory/instances', 'POST', { planId: sourcePlan, requestId: 'original-source-admission', executionTargetRef: 'trusted-receiver' }],
    ]);
  });

  it('recovers a lost dispatch acknowledgement using reads with no automatic second dispatch', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(new Response('lost ACK', { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ requestId: 'original-source-admission', taskId: originTask, planId: sourcePlan, executionTargetRef: 'trusted-receiver' })))
      .mockResolvedValueOnce(new Response(JSON.stringify(accepted())));
    vi.stubGlobal('fetch', fetch);
    await expect(api.resumeRemote(fixture())).resolves.toMatchObject({ id: originTask });
    expect(fetch.mock.calls.map(call => call[1].method)).toEqual(['POST', 'GET', 'GET']);
    expect(fetch.mock.calls[1][0]).toBe('/api/factory/requests/original-source-admission');
    expect(fetch.mock.calls[2][0]).toBe(`/api/factory/jobs/${originTask}`);
  });

  it('does not acknowledge a substituted task or owner as the original continuation', async () => {
    for (const changed of [{ ...accepted().job, id: receiverTask }, { ...accepted().job, ownerId: 'foreign-owner' }]) {
      const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(changed), { status: 202 }));
      vi.stubGlobal('fetch', fetch);
      await expect(api.resumeRemote(fixture())).rejects.toMatchObject({ code: 'REMOTE_RECEIPT_MISMATCH' });
      expect(fetch).toHaveBeenCalledTimes(1);
    }
  });
});
