import { ApiError, factoryRequest } from '../../api.js';
import type { ResearchQuestion } from './live/assistantClient.js';

export interface SessionLimits { maxTurns: number; toolCallsPerTurn: number; operationSeconds: number }
type Limit = { min: number; max: number; default: number };
export interface SessionOptions {
  available: boolean; unavailableCode: string | null;
  collaboration?: { available: boolean };
  models: { connectionRef: string; provider: string; model: string; available: boolean }[];
  limits: { maxTurns: Limit; toolCallsPerTurn: Limit; operationSeconds: Limit; contextCharacters: number };
  workspace: { configured: boolean; hostCommands: boolean; isolation: 'host-user-not-os-sandbox' };
  accounting: { tokenMetered: boolean; costMetered: boolean };
}
export interface SessionMessage { id: string; kind: 'instruction' | 'correction'; text: string; state: 'pending' | 'included'; createdAt: string; includedAt: string | null }
export interface SessionEvent { id: number; jobId: string; type: string; message: string; data: Record<string, unknown>; createdAt: string }
export type SessionAssistantReply = { questionId: string; state: 'unavailable'; code: string } | {
  questionId: string; state: 'available'; senderId: string; recipientId: string; endpointId: string;
  questionText: string; reply: Extract<ResearchQuestion['reply'], { state: 'available' }>; delivery: ResearchQuestion['delivery'];
};
export interface SessionTurn {
  id: string; sequence: number; requestId: string; taskId: string | null; runId: string | null; status: string;
  createdAt: string; completedAt: string | null; result: string | null; failure: string | null;
  messages: SessionMessage[]; events: SessionEvent[];
  toolResults: { effectKey: string; status: string; result: Record<string, unknown> | null }[];
  assistantReply?: SessionAssistantReply;
  assistantReplies?: SessionAssistantReply[];
  continuation?: { questionIds: string[] };
}
export interface SessionSummary {
  id: string; assistantId: string; title: string; goal: string; boundaries: string; createdAt: string; updatedAt: string;
  state: 'idle' | 'running' | 'stopping' | 'stopped' | 'blocked';
  collaboration?: { enabled: boolean };
  capabilities?: { memory: boolean };
  model: { connectionRef: string; provider: string; model: string }; limits: SessionLimits;
  context: {
    characters: number; maximumCharacters: number; rawCharacters?: number;
    compaction?: { status: 'needed' | 'preparing' | 'ready' | 'failed' | 'unknown'; throughSequence: number; code?: string };
  };
  allowedActions: ('start' | 'correct' | 'stop')[];
  blockReason: string | null; sharedSourceIds: string[];
}
export interface ResearchSession extends SessionSummary { turns: SessionTurn[] }
export type SessionAction = 'create' | 'turn' | 'correct' | 'stop';
export interface SessionRequest {
  requestId: string; action: SessionAction; sessionId: string; turnId: string | null;
  session: ResearchSession; createsExecution: false; automaticReplay: false;
}
export interface CreateSession { requestId: string; title: string; goal: string; boundaries: string; modelConnectionRef: string; limits: SessionLimits }
export interface SessionPage { items: SessionSummary[]; nextCursor: string | null }
const base = '/research/sessions';
const path = (id: string) => `${base}/${encodeURIComponent(id)}`;
function detail(value: ResearchSession, id?: string) {
  if (!value || typeof value.id !== 'string' || id && value.id !== id || !Array.isArray(value.turns)
      || !Array.isArray(value.allowedActions) || !Array.isArray(value.sharedSourceIds)
      || !['idle', 'running', 'stopping', 'stopped', 'blocked'].includes(value.state)) {
    throw new ApiError('会话回执无法核对，请查询原请求。', 200, 'INVALID_RESPONSE');
  }
  return value;
}
export const researchSessionsApi = {
  options: (owner: string, signal?: AbortSignal) => factoryRequest<SessionOptions>(`${base}/options`, 'GET', undefined, signal, owner),
  list: (owner: string, after = '', signal?: AbortSignal) => factoryRequest<SessionPage>(`${base}${after ? `?after=${encodeURIComponent(after)}` : ''}`, 'GET', undefined, signal, owner),
  get: async (owner: string, id: string, signal?: AbortSignal) => detail(await factoryRequest<ResearchSession>(path(id), 'GET', undefined, signal, owner), id),
  create: async (owner: string, body: CreateSession) => detail(await factoryRequest<ResearchSession>(base, 'POST', body, undefined, owner)),
  turn: async (owner: string, id: string, body: { requestId: string; text: string; assistantQuestionId?: string }) => detail(await factoryRequest<ResearchSession>(`${path(id)}/turns`, 'POST', body, undefined, owner), id),
  questions: (owner: string, id: string, after = '', requestId = '', signal?: AbortSignal) => factoryRequest<{ items: ResearchQuestion[]; nextCursor: string | null }>(`${path(id)}/questions?limit=20&after=${encodeURIComponent(after)}${requestId ? `&requestId=${encodeURIComponent(requestId)}` : ''}`, 'GET', undefined, signal, owner),
  ask: (owner: string, id: string, body: { requestId: string; assistantId: string; text: string }) => factoryRequest<ResearchQuestion>(`${path(id)}/questions`, 'POST', body, undefined, owner),
  correct: async (owner: string, id: string, body: { requestId: string; text: string }) => detail(await factoryRequest<ResearchSession>(`${path(id)}/corrections`, 'POST', body, undefined, owner), id),
  stop: async (owner: string, id: string, body: { requestId: string }) => detail(await factoryRequest<ResearchSession>(`${path(id)}/stop`, 'POST', body, undefined, owner), id),
  request: async (owner: string, requestId: string, signal?: AbortSignal): Promise<SessionRequest> => {
    const value = await factoryRequest<SessionRequest>(`${base}/requests/${encodeURIComponent(requestId)}`, 'GET', undefined, signal, owner);
    if (!value || value.requestId !== requestId || value.createsExecution !== false || value.automaticReplay !== false
        || !['create', 'turn', 'correct', 'stop'].includes(value.action)) throw new ApiError('原请求回执不匹配，请继续核对。', 200, 'INVALID_RESPONSE');
    detail(value.session, value.sessionId); return value;
  },
};
