import { factoryRequest } from './api.js';
import type { FactoryJob, Plan, PlanAuthorization, UserConnection } from './models.js';

export interface OrxProjectInput { name: string; path: string; source: 'empty' | 'existing' | 'clone' | 'paper'; cloneUrl?: string; paperId?: string }
export interface ProjectSelectionStatus {
  requestId: string; ownerId: string; state: 'complete' | 'failed' | 'unknown';
  localConfiguration: 'none' | 'partial'; failureStatus: number | null; connection: UserConnection | null;
}
function checkSelection(value: ProjectSelectionStatus, requestId: string, ownerId: string): ProjectSelectionStatus {
  if (!value || value.requestId !== requestId || value.ownerId !== ownerId || !['complete', 'failed', 'unknown'].includes(value.state)
    || !['none', 'partial'].includes(value.localConfiguration) || (value.state === 'failed' ? !Number.isInteger(value.failureStatus) || value.failureStatus! < 400 || value.failureStatus! > 599 : value.failureStatus !== null)
    || (value.state === 'complete' ? !value.connection || value.connection.ownerId !== ownerId || value.connection.kind !== 'orx' || !value.connection.capabilities.includes('session:read') : value.connection !== null)) invalid();
  return value;
}
export interface ProjectPreview {
  previewHash: string;
  connectionPin: UserConnection;
  request: { name: string; path: string; createFolder: boolean; requireNewFolder: boolean; initializeGit: boolean; cloneUrl: string | null; paperId: string | null; locale: 'zh'; github_sync_enabled: false; githubSyncEnabled: false };
  disclosure: { version: string; remotePath: string; repository: string | null; paperId: string | null; remoteWrites: string; clone: boolean; paperDownload: boolean; gitInitialization: boolean; githubSyncEnabled: false; pathResolution: 'upstream-canonical-path-and-enclosing-git-root' | 'upstream-clone-target-symlinks-followed-no-new-folder-guarantee'; starterSuggestions: string; modelInput: string[]; modelSelection: string; billing: string; hardBudgetEnforced: false; automaticExperiment: false; emptyCacheHitOrNoHarness: string; unknownResponse: string };
}
export interface OrxProjectReceipt {
  requestId: string; action: 'project_create'; planId: string; consentState: 'awaiting' | 'approved' | 'cancelled' | 'dispatch_started'; state: string;
  preview: ProjectPreview; result: { nativeProjectId: string; name: string; path: string; namespace: 'native-openresearch'; githubSyncRequested: false; correlationSource: 'native-create-response'; liveEndToEndVerified: false } | null;
  factoryIdentity: { planId: string; taskId: string; nativeRunId: string; executionContract: 'personal-external-v1' } | null;
  candidates: { nativeProjectId: string; name: string; path: string }[]; candidateCorrelation: 'unproven-does-not-settle-original-request'; liveEndToEndVerified: false;
}
export interface OrxProjectPrepared { plan: Plan; authorization: PlanAuthorization; receipt: OrxProjectReceipt }
const path = '/personal-agent';
function invalid(): never { throw new Error('项目创建回执无法核对。'); }
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(',')}}`;
  return JSON.stringify(value);
}
export function checkOrxProjectReceipt(value: OrxProjectReceipt, requestId: string, ownerId?: string, planId?: string): OrxProjectReceipt {
  const p = value?.preview; const d = p?.disclosure; const r = p?.request;
  if (!value || value.requestId !== requestId || value.action !== 'project_create' || !value.planId || planId && value.planId !== planId || value.liveEndToEndVerified !== false || value.candidateCorrelation !== 'unproven-does-not-settle-original-request' || !Array.isArray(value.candidates) || !p || !/^[a-f0-9]{64}$/.test(p.previewHash) || !p.connectionPin?.ref || ownerId && p.connectionPin.ownerId !== ownerId || !r || r.github_sync_enabled !== false || r.githubSyncEnabled !== false || !d || d.githubSyncEnabled !== false || d.hardBudgetEnforced !== false || d.automaticExperiment !== false || d.version !== 'native-orx-create-consent-v2' || d.remotePath !== r.path || d.repository !== r.cloneUrl || d.paperId !== r.paperId || d.billing !== 'owner-remote-account-possible-cost' || d.unknownResponse !== 'read-only-reconcile-never-resend' || !Array.isArray(d.modelInput) || !['awaiting', 'approved', 'cancelled', 'dispatch_started'].includes(value.consentState)) invalid();
  if (d.clone !== !!r.cloneUrl || d.remoteWrites !== (r.cloneUrl ? 'clone-into-new-or-existing-empty-folder-and-project' : r.createFolder ? 'create-new-folder-and-project' : 'register-existing-folder') || d.pathResolution !== (r.cloneUrl ? 'upstream-clone-target-symlinks-followed-no-new-folder-guarantee' : 'upstream-canonical-path-and-enclosing-git-root')) invalid();
  if (value.result && (value.state !== 'acknowledged' || !value.result.nativeProjectId || value.result.namespace !== 'native-openresearch' || value.result.githubSyncRequested !== false || value.result.liveEndToEndVerified !== false || value.result.correlationSource !== 'native-create-response' || value.result.name !== r.name)) invalid();
  if (value.state === 'acknowledged' && (!value.result || !value.factoryIdentity) || value.factoryIdentity && (value.factoryIdentity.planId !== value.planId || value.factoryIdentity.executionContract !== 'personal-external-v1')) invalid();
  return value;
}
export function checkOrxProjectPrepared(value: OrxProjectPrepared, requestId: string, ownerId?: string): OrxProjectPrepared {
  if (!value?.plan?.id || !value.plan.fingerprint || value.plan.applicationRef?.id !== 'personal-orx-project-create-v1' || value.plan.inputValues?.action !== 'project_create' || value.plan.inputValues.requestId !== requestId) invalid();
  checkOrxProjectReceipt(value.receipt, requestId, ownerId, value.plan.id);
  let planned: ProjectPreview;
  try { planned = JSON.parse(String(value.plan.inputValues.text)); } catch { invalid(); }
  if (canonical(planned) !== canonical(value.receipt.preview)) invalid();
  return value;
}
export const personalOrxProjectApi = {
  existing: (connectionRef: string, signal?: AbortSignal) => factoryRequest<{ nativeProjectId: string; name: string; path: string }[]>(`${path}/project-selection?connectionRef=${encodeURIComponent(connectionRef)}`, 'GET', undefined, signal),
  selectExisting: (connectionRef: string, nativeProjectId: string, requestId: string, ownerId: string) => factoryRequest<UserConnection>(`${path}/project-selection`, 'POST', { connectionRef, nativeProjectId, requestId }, undefined, ownerId),
  recoverSelected: async (requestId: string, ownerId: string) => checkSelection(await factoryRequest<ProjectSelectionStatus>(`${path}/project-selection/requests/${encodeURIComponent(requestId)}/status`, 'GET', undefined, undefined, ownerId), requestId, ownerId),
  prepare: async (input: { requestId: string; connectionRef: string; project: OrxProjectInput }) => checkOrxProjectPrepared(await factoryRequest<OrxProjectPrepared>(`${path}/project-commands/prepare`, 'POST', input), input.requestId),
  decide: async (requestId: string, previewHash: string, approved: boolean) => checkOrxProjectReceipt(await factoryRequest<OrxProjectReceipt>(`${path}/project-commands/${encodeURIComponent(requestId)}/decision`, 'POST', { previewHash, approved }), requestId),
  submit: async (requestId: string, previewHash: string, planId: string) => { const job = await factoryRequest<FactoryJob>(`${path}/project-commands/${encodeURIComponent(requestId)}/submit`, 'POST', { previewHash, approved: true }); if (!job?.id || job.planId !== planId) invalid(); return job; },
  recover: async (requestId: string) => {
    const recovery = await factoryRequest<{ requestId: string; plan: Plan; authorization: PlanAuthorization; receipt: OrxProjectReceipt | null; job: FactoryJob | null; nativeRunId: string | null }>(`${path}/commands/requests/${encodeURIComponent(requestId)}`);
    if (!recovery.receipt || recovery.requestId !== requestId) invalid();
    checkOrxProjectPrepared({ plan: recovery.plan, authorization: recovery.authorization, receipt: recovery.receipt }, requestId);
    if (recovery.job && (recovery.job.planId !== recovery.plan.id || recovery.receipt.factoryIdentity && (recovery.receipt.factoryIdentity.taskId !== recovery.job.id || recovery.receipt.factoryIdentity.nativeRunId !== recovery.nativeRunId))) invalid();
    return recovery;
  },
  reconcile: async (requestId: string) => checkOrxProjectReceipt(await factoryRequest<OrxProjectReceipt>(`${path}/project-commands/${encodeURIComponent(requestId)}?refresh=true`), requestId),
  connect: async (requestId: string, harness: string, model: string) => {
    const result = await factoryRequest<UserConnection>(`${path}/project-commands/${encodeURIComponent(requestId)}/connect`, 'POST', { harness, model });
    if (!result?.ref || result.kind !== 'orx' || !result.capabilities.includes('session:read') || result.capabilities.includes('project:create')) invalid();
    return result;
  },
};
