import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clearBrowserSession, configureBrowserAuth } from '../../../../web/browserAuth.js';
import { personalAgentApi } from '../../web/personalAgentApi.js';
import { personalOrxProjectApi } from '../../web/personalOrxProjectApi.js';

// Synthetic HTTP responses only. Changing an integration-verification label must
// not make an otherwise identical historical record unreadable or upgrade its
// separate stop, metering, permission, or side-effect guarantees.
const ownerId = 'synthetic-owner';
const requestId = 'synthetic-original-request';
const identity = {
  planId: 'synthetic-plan', taskId: 'synthetic-task', nativeRunId: 'synthetic-run',
  executionContract: 'personal-external-v1',
};
const connection = {
  ref: 'synthetic-binding', registrationRef: 'synthetic-remote', ownerId,
  kind: 'orx', status: 'active', available: true, taskId: null,
  capabilities: ['project:read', 'session:read', 'session:prompt'],
  fingerprint: 'a'.repeat(64), revision: 'synthetic-r1', version: 1,
};

function session(liveEndToEndVerified: boolean) {
  return {
    id: 'synthetic-session', namespace: 'native-openresearch',
    executionContract: 'personal-external-v1', connectionRef: connection.ref,
    connectionPin: { ...connection }, bindingStatus: 'active', bindingHistory: [],
    nativeProjectId: 'synthetic-project', upstreamOrxProjectId: 'synthetic-project',
    nativeSessionId: 'synthetic-native-session', activeRequestId: null,
    state: 'result_observed', factoryIdentity: { ...identity },
    modelCredentialCustody: 'remote', budgetEnforcement: 'advisory',
    stopVerified: false, liveEndToEndVerified,
    observation: {
      sessionId: 'synthetic-native-session', projectId: 'synthetic-project',
      observedAt: '2026-10-13T00:00:00Z', provenance: 'remote-reported',
      trustedMetering: false, exactTurnVerified: false, messages: [],
    },
  };
}

function sessionRecovery(liveEndToEndVerified: boolean) {
  const original = session(liveEndToEndVerified);
  return {
    requestId,
    plan: {
      id: identity.planId, fingerprint: 'b'.repeat(64),
      inputValues: {
        executionContract: 'personal-external-v1', action: 'prompt',
        connectionPin: JSON.stringify(connection), nativeProjectId: original.nativeProjectId,
        factorySessionId: original.id, nativeSessionId: original.nativeSessionId,
      },
    },
    authorization: {},
    job: { id: identity.taskId, planId: identity.planId, ownerId, status: 'completed' },
    nativeRunId: identity.nativeRunId,
    receipt: {
      requestId, action: 'prompt', state: 'result_observed',
      session: original, factoryIdentity: { ...identity },
    },
  };
}

function projectReceipt(liveEndToEndVerified: boolean, resultVerified = liveEndToEndVerified) {
  const request = {
    name: 'Synthetic project', path: '/synthetic/project', createFolder: true,
    requireNewFolder: true, initializeGit: true, cloneUrl: null, paperId: null,
    locale: 'zh', github_sync_enabled: false, githubSyncEnabled: false,
  };
  return {
    requestId, action: 'project_create', planId: identity.planId,
    consentState: 'dispatch_started', state: 'acknowledged',
    preview: {
      previewHash: 'c'.repeat(64), connectionPin: { ...connection }, request,
      disclosure: {
        version: 'native-orx-create-consent-v2', remotePath: request.path,
        repository: null, paperId: null, remoteWrites: 'create-new-folder-and-project',
        clone: false, paperDownload: false, gitInitialization: true,
        githubSyncEnabled: false, pathResolution: 'upstream-canonical-path-and-enclosing-git-root',
        starterSuggestions: 'may-request-four-project-chat-suggestions',
        modelInput: ['README', 'selected-code', 'file-list', 'paper-summary'],
        modelSelection: 'remote-preferred-or-ready-harness',
        billing: 'owner-remote-account-possible-cost', hardBudgetEnforced: false,
        automaticExperiment: false, emptyCacheHitOrNoHarness: 'may-skip-model-request',
        unknownResponse: 'read-only-reconcile-never-resend',
      },
    },
    result: {
      nativeProjectId: 'synthetic-project', name: request.name, path: request.path,
      namespace: 'native-openresearch', githubSyncRequested: false,
      correlationSource: 'native-create-response', liveEndToEndVerified: resultVerified,
    },
    factoryIdentity: { ...identity }, candidates: [],
    candidateCorrelation: 'unproven-does-not-settle-original-request', liveEndToEndVerified,
  };
}

function projectRecovery(liveEndToEndVerified: boolean) {
  const receipt = projectReceipt(liveEndToEndVerified);
  return {
    requestId,
    plan: {
      id: identity.planId, fingerprint: 'b'.repeat(64),
      applicationRef: { id: 'personal-orx-project-create-v1', version: 1, sha256: 'd'.repeat(64) },
      inputValues: { requestId, action: 'project_create', text: JSON.stringify(receipt.preview) },
    },
    authorization: {}, receipt,
    job: { id: identity.taskId, planId: identity.planId, ownerId, status: 'completed' },
    nativeRunId: identity.nativeRunId,
  };
}

function stubGet(path: string, body: unknown) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    expect(url).toBe(`/api/factory${path}`);
    expect(init).toMatchObject({ method: 'GET', credentials: 'same-origin', cache: 'no-store' });
    expect(init?.body).toBeUndefined();
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

beforeEach(() => {
  clearBrowserSession();
  configureBrowserAuth({ enabled: false, loginPath: '/api/factory/auth/login', logoutPath: '/api/factory/auth/logout' });
  vi.stubGlobal('fetch', vi.fn(() => { throw new Error('Unexpected unconfigured synthetic HTTP request'); }));
});
afterEach(() => { clearBrowserSession(); vi.unstubAllGlobals(); });

describe('research records remain readable when only integration-verification metadata changes', () => {
  it.each([false, true])('reads the original session snapshot with liveEndToEndVerified=%s', async verified => {
    const body = session(verified);
    const fetchMock = stubGet(`/personal-agent/sessions/${body.id}`, body);
    await expect(personalAgentApi.snapshot(body.id)).resolves.toEqual(body);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(body.stopVerified).toBe(false);
    expect(body.observation.trustedMetering).toBe(false);
  });

  it.each([false, true])('recovers the original session command with liveEndToEndVerified=%s', async verified => {
    const body = sessionRecovery(verified);
    const fetchMock = stubGet(`/personal-agent/commands/requests/${requestId}`, body);
    await expect(personalAgentApi.recover(requestId)).resolves.toEqual(body);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([
    { receiptVerified: false, resultVerified: false },
    { receiptVerified: true, resultVerified: false },
    { receiptVerified: false, resultVerified: true },
  ])('reads the original project receipt with metadata $receiptVerified/$resultVerified', async ({ receiptVerified, resultVerified }) => {
    const body = projectReceipt(receiptVerified, resultVerified);
    const fetchMock = stubGet(`/personal-agent/project-commands/${requestId}?refresh=true`, body);
    await expect(personalOrxProjectApi.reconcile(requestId)).resolves.toEqual(body);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(body.preview.disclosure.hardBudgetEnforced).toBe(false);
    expect(body.preview.disclosure.automaticExperiment).toBe(false);
  });

  it.each([false, true])('recovers the original project command with liveEndToEndVerified=%s', async verified => {
    const body = projectRecovery(verified);
    const fetchMock = stubGet(`/personal-agent/commands/requests/${requestId}`, body);
    await expect(personalOrxProjectApi.recover(requestId)).resolves.toEqual(body);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe('record identity and actual execution guarantees still reject tampering', () => {
  it.each(['request', 'task', 'pin'] as const)('rejects changed session recovery %s', async field => {
    const body = sessionRecovery(false);
    if (field === 'request') body.requestId = 'different-request';
    if (field === 'task') body.receipt.factoryIdentity.taskId = 'different-task';
    if (field === 'pin') body.receipt.session.connectionPin.fingerprint = 'e'.repeat(64);
    const fetchMock = stubGet(`/personal-agent/commands/requests/${requestId}`, body);
    await expect(personalAgentApi.recover(requestId)).rejects.toThrow('个人会话回执无法核对');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each(['request', 'task', 'pin'] as const)('rejects changed project recovery %s', async field => {
    const body = projectRecovery(false);
    if (field === 'request') body.requestId = 'different-request';
    if (field === 'task') body.receipt.factoryIdentity.taskId = 'different-task';
    if (field === 'pin') body.receipt.preview.connectionPin.fingerprint = 'e'.repeat(64);
    const fetchMock = stubGet(`/personal-agent/commands/requests/${requestId}`, body);
    await expect(personalOrxProjectApi.recover(requestId)).rejects.toThrow('项目创建回执无法核对');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([ownerId, 'different-owner'])('checks the selected project owner %s against the requesting owner', async responseOwner => {
    const body = {
      requestId, ownerId: responseOwner, state: 'complete', localConfiguration: 'none',
      failureStatus: null, connection: { ...connection, ownerId: responseOwner },
    };
    const fetchMock = stubGet(`/personal-agent/project-selection/requests/${requestId}/status`, body);
    const result = personalOrxProjectApi.recoverSelected(requestId, ownerId);
    if (responseOwner === ownerId) await expect(result).resolves.toEqual(body);
    else await expect(result).rejects.toThrow('项目创建回执无法核对');
    expect(fetchMock).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ headers: { 'X-Factory-Expected-Owner': ownerId } }));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('still rejects an unsupported claim of verified remote stop', async () => {
    const body = { ...session(false), stopVerified: true };
    stubGet(`/personal-agent/sessions/${body.id}`, body);
    await expect(personalAgentApi.snapshot(body.id)).rejects.toThrow('个人会话回执无法核对');
  });

  it('still rejects a project receipt that adds automatic experiments', async () => {
    const body = projectReceipt(false);
    body.preview.disclosure.automaticExperiment = true;
    stubGet(`/personal-agent/project-commands/${requestId}?refresh=true`, body);
    await expect(personalOrxProjectApi.reconcile(requestId)).rejects.toThrow('项目创建回执无法核对');
  });
});
