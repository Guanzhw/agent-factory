import type { Plan, PlanAuthorization } from './models.js';
import { checkedAuthorization } from './planReviewState.js';
import { factoryRequest as request, ApiError } from './api.js';

export interface NativeProject { id: string; name: string; projectIdentityHash: string; evidenceKind: string; verificationStatus: string }
export interface ResearchProject { id: string; name: string; description: string; kind: 'factory-workspace' | 'native-openresearch'; connectionRefs: Record<string, string>; upstreamProjectId: string | null; nativeProject?: NativeProject; sessionExecutionAvailable?: boolean; sessionBlocker?: string }
export interface ResearchSession { id: string; projectId: string; goal: string; state: string; taskId: string | null; executionContract: string; contextSource: string; verificationStatus: string; workloadPresetId?: string; managedProfileId?: string; nativeProfileId?: string; upstreamSessionId?: string; planId?: string; plan?: Plan; authorization?: PlanAuthorization }
export interface ManagedResearchSession extends ResearchSession { executionContract: 'managed-native-attachment-v1'; managedProfileId: string; nativeProfileId: string; upstreamSessionId: string; planId: string; plan: Plan; authorization: PlanAuthorization }
export interface ManagedProfile { kind: 'managed-connection-probe'; modelRequests: 1; nativeTools: 'disabled'; nativeResearchAvailable: false; id: string; name: string; nativeProfileId: string; upstreamSessionId: string; profile: { harness: string; model: string }; executionContract: 'managed-native-attachment-v1'; liveEndToEndVerified: false }
export interface ResearchCapabilities { contractVersion: number; nativeProjectAttachment: boolean; upstreamProjectCreation: boolean; liveEndToEndVerified: boolean; workloads: { id: string; name: string; ready: boolean; blockers: string[]; limits: Record<string, unknown> }[] }
const rec = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const str = (v: unknown): v is string => typeof v === 'string';
const bad = () => new ApiError('响应身份或能力无法核对。保留原请求，仅刷新读取。', 200, 'INVALID_RESPONSE');
export function researchProject(v: unknown, id?: string): ResearchProject {
  if (!rec(v) || !str(v.id) || id !== undefined && v.id !== id || !str(v.name) || !str(v.description) || !['factory-workspace', 'native-openresearch'].includes(String(v.kind)) || !rec(v.connectionRefs) || !Object.values(v.connectionRefs).every(str)) throw bad();
  if (v.kind === 'native-openresearch' && (!str(v.upstreamProjectId) || !rec(v.nativeProject) || v.nativeProject.id !== v.upstreamProjectId || v.nativeProject.evidenceKind !== 'native-project-metadata' || v.nativeProject.verificationStatus !== 'metadata-observed' || !str(v.nativeProject.projectIdentityHash) || !/^[a-f0-9]{64}$/.test(v.nativeProject.projectIdentityHash))) throw bad();
  if (v.kind === 'factory-workspace' && v.upstreamProjectId !== null) throw bad();
  return v as unknown as ResearchProject;
}
export function isManagedSession(v: ResearchSession): v is ManagedResearchSession { return v.executionContract === 'managed-native-attachment-v1'; }
export function researchSession(v: unknown, project: string, id?: string): ResearchSession {
  if (!rec(v) || !str(v.id) || id !== undefined && v.id !== id || v.projectId !== project || !str(v.goal) || !str(v.state) || !(v.taskId === null || str(v.taskId)) || !str(v.verificationStatus)) throw bad();
  if (v.executionContract === 'managed-native-attachment-v1') {
    const plan = v.plan; const input = rec(plan) && rec(plan.inputValues) ? plan.inputValues.managedAttachment : undefined;
    if (v.contextSource !== 'original-native-project-session' || !str(v.managedProfileId) || !str(v.nativeProfileId) || !str(v.upstreamSessionId) || !str(v.planId) || !rec(plan) || plan.id !== v.planId || !str(plan.fingerprint) || !/^[a-f0-9]{64}$/.test(plan.fingerprint) || !['ready', 'blocked'].includes(String(plan.status)) || !rec(input) || !str(input.ownerId) || !str(input.connectionRef) || !str(input.projectId) || !str(input.projectIdentityHash) || !rec(input.profile) || !str(input.profile.harness) || !str(input.profile.model) || input.sessionId !== v.upstreamSessionId || input.modelRequests !== 1 || input.nativeTools !== 'disabled') throw bad();
    checkedAuthorization(v.authorization as PlanAuthorization);
  } else if (v.executionContract !== 'controlled-workload-v1' || v.contextSource !== 'approved-workload-preset' || !str(v.workloadPresetId)) throw bad();
  return v as unknown as ResearchSession;
}
const list = <T,>(v: unknown, check: (v: unknown) => T): T[] => { if (!Array.isArray(v)) throw bad(); return v.map(check); };
const path = (p: string) => `/openresearch/projects/${encodeURIComponent(p)}`;
export const openresearchApi = {
  recover: async (requestId: string) => {
    const v = await request<unknown>(`/openresearch/requests/${encodeURIComponent(requestId)}`);
    if (!rec(v) || v.requestId !== requestId) throw bad();
    if (['project-create', 'native-project-attach'].includes(String(v.action))) return { project: researchProject(v.project) };
    if (['session-create', 'managed-prepare', 'managed-start'].includes(String(v.action)) && rec(v.session) && str(v.session.projectId)) return { session: researchSession(v.session, v.session.projectId) };
    throw bad();
  },
  managedProfiles: async (p: string, signal?: AbortSignal): Promise<ManagedProfile[]> => {
    const values = await request<unknown>(`${path(p)}/managed-profiles`, 'GET', undefined, signal);
    return list(values, v => {
      if (!rec(v) || v.kind !== 'managed-connection-probe' || v.modelRequests !== 1 || v.nativeTools !== 'disabled' || v.nativeResearchAvailable !== false || !str(v.id) || !str(v.name) || !str(v.nativeProfileId) || !str(v.upstreamSessionId) || !rec(v.profile) || !str(v.profile.harness) || !str(v.profile.model) || v.executionContract !== 'managed-native-attachment-v1' || v.liveEndToEndVerified !== false) throw bad();
      return v as unknown as ManagedProfile;
    });
  },
  prepareManaged: async (p: string, profileId: string, goal: string, requestId: string): Promise<ManagedResearchSession> => {
    const v = researchSession(await request(`${path(p)}/sessions/prepare-managed`, 'POST', { profileId, goal, requestId }), p);
    if (!isManagedSession(v) || v.managedProfileId !== profileId || v.goal !== goal || v.taskId !== null || v.state !== 'prepared') throw bad();
    return v;
  },
  startManaged: async (p: string, session: ManagedResearchSession, requestId: string): Promise<ManagedResearchSession> => {
    const v = researchSession(await request(`${path(p)}/sessions/${encodeURIComponent(session.id)}/start`, 'POST', { requestId }), p, session.id);
    if (!isManagedSession(v) || v.state === 'prepared' && v.taskId === null || v.planId !== session.planId || v.plan.fingerprint !== session.plan.fingerprint || v.managedProfileId !== session.managedProfileId || v.nativeProfileId !== session.nativeProfileId || v.upstreamSessionId !== session.upstreamSessionId) throw bad();
    return v;
  },
  capabilities: async (signal?: AbortSignal): Promise<ResearchCapabilities> => {
    const v = await request<unknown>('/openresearch/capabilities', 'GET', undefined, signal);
    if (!rec(v) || v.contractVersion !== 1 || typeof v.nativeProjectAttachment !== 'boolean' || typeof v.upstreamProjectCreation !== 'boolean' || typeof v.liveEndToEndVerified !== 'boolean' || !Array.isArray(v.workloads) || !v.workloads.every(p => rec(p) && str(p.id) && str(p.name) && typeof p.ready === 'boolean' && Array.isArray(p.blockers) && p.blockers.every(str) && rec(p.limits))) throw bad();
    return v as unknown as ResearchCapabilities;
  },
  projects: async (signal?: AbortSignal) => list(await request('/openresearch/projects', 'GET', undefined, signal), v => researchProject(v)),
  project: async (id: string, signal?: AbortSignal) => researchProject(await request(path(id), 'GET', undefined, signal), id),
  create: async (name: string, requestId: string) => researchProject(await request('/openresearch/projects', 'POST', { name, requestId })),
  native: async (ref: string) => {
    const v = await request<unknown>(`/openresearch/native-projects?${new URLSearchParams({ connectionRef: ref })}`);
    if (!rec(v) || v.connectionRef !== ref || !Array.isArray(v.projects) || !v.projects.every(p => rec(p) && str(p.id) && str(p.name) && str(p.projectIdentityHash) && /^[a-f0-9]{64}$/.test(p.projectIdentityHash) && p.evidenceKind === 'native-project-metadata' && p.verificationStatus === 'metadata-observed')) throw bad();
    return v.projects as NativeProject[];
  },
  attach: async (connectionRef: string, native: NativeProject, requestId: string) => {
    const p = researchProject(await request('/openresearch/projects/attach', 'POST', { connectionRef, nativeProjectId: native.id, projectIdentityHash: native.projectIdentityHash, requestId }));
    if (p.upstreamProjectId !== native.id || p.connectionRefs.workspace !== connectionRef || p.nativeProject?.projectIdentityHash !== native.projectIdentityHash) throw bad();
    return p;
  },
  refresh: async (id: string) => researchProject(await request(`${path(id)}/refresh`, 'POST'), id),
  sessions: async (p: string, signal?: AbortSignal) => list(await request(`${path(p)}/sessions`, 'GET', undefined, signal), v => researchSession(v, p)),
  start: async (p: string, workloadPresetId: string, goal: string, requestId: string) => {
    const value = researchSession(await request(`${path(p)}/sessions`, 'POST', { workloadPresetId, goal, requestId, executionContract: 'controlled-workload-v1' }), p);
    if (value.workloadPresetId !== workloadPresetId || value.goal !== goal) throw bad();
    return value;
  },
  reconcile: async (p: string, s: string) => researchSession(await request(`${path(p)}/sessions/${encodeURIComponent(s)}/reconcile`, 'POST'), p, s),
};
