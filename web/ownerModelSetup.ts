import type { OwnerModel } from './ownerModelApi.js';
import type { PersonalCredential } from './personalRemoteApi.js';

export interface ModelSetup {
  owner: string; provider: OwnerModel['provider']; baseURL: string; model: string;
  credentialRequest: string; modelRequest: string; defaultRequest: string;
  stage: 'credential' | 'model' | 'default'; reference?: string;
  credential?: PersonalCredential; rotating?: { credentialRef: string; credentialRevision: string };
  chooseDefault: boolean;
}
export function modelEndpoint(input: string): string {
  const url = new URL(input.trim());
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.port
      || url.pathname !== '/v1' || !url.hostname.includes('.') || url.hostname.endsWith('.localhost') || /^[\d.]+$/.test(url.hostname) || url.hostname.includes(':')) throw new Error('请输入 HTTPS 模型端点，路径为 /v1。');
  return `${url.origin}/v1`;
}
export function setupCredential(value: PersonalCredential, setup: ModelSetup): PersonalCredential {
  if (!value || value.status !== 'active' || value.providerId !== 'byok-chat-v1'
      || value.destination !== new URL(setup.baseURL).origin || !value.credentialRef || !value.credentialRevision) throw new Error('密钥保存回执无法核对，请保留原请求。');
  return { credentialRef: value.credentialRef, credentialRevision: value.credentialRevision,
    providerId: value.providerId, destination: value.destination, status: value.status };
}
/** This is deliberately a whitelist: no key, secret value or secret hash is stored. */
export function setupMetadata(setup: ModelSetup): ModelSetup {
  return { owner: setup.owner, provider: setup.provider, baseURL: setup.baseURL, model: setup.model,
    credentialRequest: setup.credentialRequest, modelRequest: setup.modelRequest, defaultRequest: setup.defaultRequest,
    stage: setup.stage, chooseDefault: setup.chooseDefault, ...(setup.reference ? { reference: setup.reference } : {}),
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
