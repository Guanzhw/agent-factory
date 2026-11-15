import { factoryRequest } from '../../api.js';

export type TriggerSource = 'external' | 'cron' | 'research';
export const triggerSourceLabels: Record<TriggerSource, string> = {
  research: '团队研究发布', external: '外部事件', cron: '定时',
};
export interface TriggerOrigin {
  kind: 'trigger'; triggerId: string; triggerTitle: string; eventId: string; source: TriggerSource; eventType: string; contentId?: string;
}
export interface SessionTrigger {
  id: string; sessionId: string; title: string; instruction: string; source: TriggerSource;
  eventType: string | null; cron: string | null; timezone: string; keyword: string;
  enabled: boolean; createdAt: string; nextRunAt: number | null;
}
export interface TriggerDelivery { id: string; triggerId: string; eventId: string; state: string; error: string | null; turnId: string | null; createdAt: string }
export interface TriggerPage { items: SessionTrigger[]; deliveries: TriggerDelivery[] }
export interface CreateTrigger {
  requestId: string; title: string; instruction: string; source: TriggerSource;
  eventType?: string; cron?: string; timezone?: string; keyword?: string;
}
const path = (sessionId: string) => `/research/sessions/${encodeURIComponent(sessionId)}/triggers`;
export const sessionTriggersApi = {
  list: (owner: string, sessionId: string, signal?: AbortSignal) => factoryRequest<TriggerPage>(path(sessionId), 'GET', undefined, signal, owner),
  create: (owner: string, sessionId: string, body: CreateTrigger) => factoryRequest<SessionTrigger>(path(sessionId), 'POST', body, undefined, owner),
  remove: (owner: string, sessionId: string, id: string, requestId: string) => factoryRequest<{ id: string; enabled: false }>(`${path(sessionId)}/${encodeURIComponent(id)}?requestId=${encodeURIComponent(requestId)}`, 'DELETE', undefined, undefined, owner),
};
