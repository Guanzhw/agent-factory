import { factoryRequest as request } from '../../../web/api.js';
import type { Plan } from '../../../web/models.js';
import type { SynthesisCreate } from './synthesisJourneyState.js';
import type { IterationStart } from './iterationState.js';
const segment = encodeURIComponent;

/** Research endpoints retain their existing URLs and request/receipt contracts. */
export const researchApi = {
  iterations: {
    presets: (owner: string, signal?: AbortSignal) => request<unknown>('/research-iterations/presets', 'GET', undefined, signal, owner),
    list: (owner: string, signal?: AbortSignal) => request<unknown>('/research-iterations', 'GET', undefined, signal, owner),
    start: (owner: string, input: IterationStart) => request<unknown>('/research-iterations', 'POST', input, undefined, owner),
    get: (owner: string, id: string, signal?: AbortSignal) => request<unknown>(`/research-iterations/${segment(id)}`, 'GET', undefined, signal, owner),
    recover: (owner: string, id: string) => request<unknown>(`/research-iterations/requests/${segment(id)}`, 'GET', undefined, undefined, owner),
    advance: (owner: string, id: string, input: { previousRoundId: string; requestId: string }) => request<unknown>(`/research-iterations/${segment(id)}/advance`, 'POST', input, undefined, owner),
    reconcile: (owner: string, id: string) => request<unknown>(`/research-iterations/${segment(id)}/reconcile`, 'POST', {}, undefined, owner),
    cancel: (owner: string, id: string) => request<unknown>(`/research-iterations/${segment(id)}/cancel`, 'POST', {}, undefined, owner),
  },
  autoresearch: {
    presets: (signal?: AbortSignal) => request<unknown>('/autoresearch/presets', 'GET', undefined, signal),
    start: (input: { presetId: string; goal?: string; requestId: string }, signal?: AbortSignal) => request<unknown>('/autoresearch/runs', 'POST', input, signal),
    get: (id: string, signal?: AbortSignal) => request<unknown>(`/autoresearch/runs/${segment(id)}`, 'GET', undefined, signal),
    recover: (id: string, signal?: AbortSignal) => request<unknown>(`/autoresearch/requests/${segment(id)}`, 'GET', undefined, signal),
    cancel: (id: string, input: { requestId: string }, signal?: AbortSignal) => request<unknown>(`/autoresearch/runs/${segment(id)}/cancel`, 'POST', input, signal),
  },
  comparisons: { catalog: (signal?: AbortSignal) => request<unknown>('/comparisons/catalog', 'GET', undefined, signal) },
  synthesis: {
    preview: (taskId: string, signal?: AbortSignal) => request<unknown>(`/synthesis/sources/${segment(taskId)}`, 'GET', undefined, signal),
    list: (taskId: string, after?: string, signal?: AbortSignal) => request<unknown>(`/synthesis/snapshots?${new URLSearchParams({ sourceTaskId: taskId, limit: '20', ...(after ? { after } : {}) })}`, 'GET', undefined, signal),
    inspect: (id: string, signal?: AbortSignal) => request<unknown>(`/synthesis/snapshots/${segment(id)}`, 'GET', undefined, signal),
    current: (id: string, signal?: AbortSignal) => request<unknown>(`/synthesis/snapshots/${segment(id)}/current`, 'GET', undefined, signal),
    create: (input: SynthesisCreate) => request<unknown>('/synthesis/snapshots', 'POST', input),
  },
  plan: (topic: string, mode: 'literature' | 'experiment', requestId: string) => request<Plan>('/plans', 'POST', { topic, mode, requestId }),
};
