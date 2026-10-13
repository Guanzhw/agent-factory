import { validThinkingMetadata, type OwnerModel } from './ownerModelApi.js';
import type { PersonalCredential } from './personalRemoteApi.js';
import { modelEndpoint } from './modelEndpoint.js';
export { modelEndpoint } from './modelEndpoint.js';

export interface ModelSetup {
  owner: string; provider: OwnerModel['provider']; baseURL: string; model: string;
  thinkingMode?: OwnerModel['thinkingMode'];
  credentialRequest: string; modelRequest: string; defaultRequest: string;
  stage: 'credential' | 'model' | 'default'; reference?: string;
  credential?: PersonalCredential; rotating?: { credentialRef: string; credentialRevision: string };
  chooseDefault: boolean;
}
export function setupCredential(value: PersonalCredential, setup: ModelSetup): PersonalCredential {
  if (!value || value.status !== 'active' || value.providerId !== 'byok-chat-v1'
      || value.destination !== new URL(setup.baseURL).origin || !value.credentialRef || !value.credentialRevision) throw new Error('密钥保存回执无法核对，请保留原请求。');
  return { credentialRef: value.credentialRef, credentialRevision: value.credentialRevision,
    providerId: value.providerId, destination: value.destination, status: value.status };
}
/** This is deliberately a whitelist: no key, secret value or secret hash is stored. */
export function setupMetadata(setup: ModelSetup): ModelSetup {
  if (!validThinkingMetadata(setup)) throw new Error('Invalid thinking metadata');
  return { owner: setup.owner, provider: setup.provider, baseURL: setup.baseURL, model: setup.model,
    credentialRequest: setup.credentialRequest, modelRequest: setup.modelRequest, defaultRequest: setup.defaultRequest,
    stage: setup.stage, chooseDefault: setup.chooseDefault, ...(setup.reference ? { reference: setup.reference } : {}),
    ...(setup.thinkingMode ? { thinkingMode: setup.thinkingMode } : {}),
    ...(setup.credential ? { credential: setupCredential(setup.credential, setup) } : {}),
    ...(setup.rotating ? { rotating: { credentialRef: setup.rotating.credentialRef, credentialRevision: setup.rotating.credentialRevision } } : {}) };
}
export function readModelSetup(raw: string | null, owner: string): ModelSetup | null {
  if (!raw) return null;
  try {
    const s = JSON.parse(raw) as ModelSetup;
    if (s.owner !== owner || !['openai', 'openai-compatible'].includes(s.provider)
        || !['credential', 'model', 'default'].includes(s.stage) || typeof s.chooseDefault !== 'boolean'
        || !['credentialRequest', 'modelRequest', 'defaultRequest'].every(key => /^[a-zA-Z0-9_.:-]{8,100}$/.test(String(s[key as keyof ModelSetup])))
        || typeof s.model !== 'string' || !s.model || s.model.length > 120 || modelEndpoint(s.baseURL) !== s.baseURL) return null;
    return setupMetadata(s);
  } catch { return null; }
}
