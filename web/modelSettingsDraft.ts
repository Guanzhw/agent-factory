import type { OwnerModel } from './ownerModelApi.js';

export interface ModelSettingsDraft {
  provider: OwnerModel['provider']; protocol?: OwnerModel['protocol']; endpoint: string; model: string;
  credentialSource: 'new' | 'saved' | 'none'; savedReference: string; outputTokens: string;
  editing?: string; outputEditing?: string;
}
const key = (owner: string) => `factory-model-draft:${encodeURIComponent(owner)}`;
export function readModelSettingsDraft(owner: string): ModelSettingsDraft | undefined {
  try {
    const draft = JSON.parse(sessionStorage.getItem(key(owner)) ?? 'null') as ModelSettingsDraft | null;
    if (!draft || !['openai', 'openai-compatible'].includes(draft.provider)
      || !['new', 'saved', 'none'].includes(draft.credentialSource)
      || [draft.endpoint, draft.model, draft.savedReference, draft.outputTokens].some(value => typeof value !== 'string')
      || draft.protocol !== undefined && !['chat-completions', 'responses'].includes(draft.protocol)
      || [draft.editing, draft.outputEditing].some(value => value !== undefined && typeof value !== 'string')) return;
    return draft;
  } catch { return undefined; }
}
export function saveModelSettingsDraft(owner: string, draft: ModelSettingsDraft) {
  try { sessionStorage.setItem(key(owner), JSON.stringify(draft)); } catch { /* The current form remains editable without storage. */ }
}
export function clearModelSettingsDraft(owner: string) {
  try { sessionStorage.removeItem(key(owner)); } catch { /* Storage may be disabled. */ }
}
