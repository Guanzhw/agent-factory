import { factoryRequest as request } from '../../../web/api.js';
import type { Plan } from '../../../web/models.js';
import type { SynthesisCreate } from './synthesisJourneyState.js';
const segment = encodeURIComponent;

/** Research endpoints retain their existing URLs and request/receipt contracts. */
export const researchApi = {
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
