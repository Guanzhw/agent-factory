import { validOutputTokens, type OwnerModel } from './ownerModelApi.js';
import { validModelProtocol, validThinkingMetadata, type ModelProtocol } from './modelProviderConfig.js';
import type { PersonalCredential } from './personalRemoteApi.js';
import { modelEndpoint } from './modelEndpoint.js';
export { modelEndpoint } from './modelEndpoint.js';
const identifier = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_.:@-]{1,200}$/.test(value);

export interface ModelSetup {
  owner: string; provider: OwnerModel['provider']; baseURL: string; model: string;
  thinkingMode?: OwnerModel['thinkingMode'];
  maxOutputTokens?: number;
  protocol?: ModelProtocol;
  dispatched?: { model?: true; default?: true };
  credentialRequest: string; modelRequest: string; defaultRequest: string;
  stage: 'credential' | 'model' | 'default'; reference?: string;
  credential?: PersonalCredential; rotating?: { credentialRef: string; credentialRevision: string };
  chooseDefault: boolean;
  noCredentials?: true;
}
export function setupCredential(value: PersonalCredential, setup: ModelSetup): PersonalCredential {
  if (!value || value.status !== 'active' || value.providerId !== 'byok-chat-v1'
      || value.destination !== new URL(setup.baseURL).origin
      || ![value.credentialRef, value.credentialRevision].every(identifier)
      || setup.rotating && (value.credentialRef !== setup.rotating.credentialRef || value.credentialRevision === setup.rotating.credentialRevision)) throw new Error('密钥保存回执无法核对，请保留原请求。');
  return { credentialRef: value.credentialRef, credentialRevision: value.credentialRevision,
    providerId: value.providerId, destination: value.destination, status: value.status };
}
/** This is deliberately a whitelist: no key, secret value or secret hash is stored. */
export function setupMetadata(setup: ModelSetup): ModelSetup {
  if (!validThinkingMetadata(setup)
      || Object.prototype.hasOwnProperty.call(setup, 'maxOutputTokens') && !validOutputTokens(setup.maxOutputTokens)
      || Object.prototype.hasOwnProperty.call(setup, 'protocol') && !validModelProtocol(setup.protocol)
      || setup.reference !== undefined && !identifier(setup.reference)
      || setup.rotating && ![setup.rotating.credentialRef, setup.rotating.credentialRevision].every(identifier)
      || setup.dispatched !== undefined && (!setup.dispatched || typeof setup.dispatched !== 'object' || Array.isArray(setup.dispatched)
        || Object.keys(setup.dispatched).some(key => !['model', 'default'].includes(key))
        || Object.values(setup.dispatched).some(value => value !== true))) throw new Error('Invalid setup metadata');
  return { owner: setup.owner, provider: setup.provider, baseURL: setup.baseURL, model: setup.model,
    credentialRequest: setup.credentialRequest, modelRequest: setup.modelRequest, defaultRequest: setup.defaultRequest,
    stage: setup.stage, chooseDefault: setup.chooseDefault, ...(setup.noCredentials ? { noCredentials: true as const } : {}), ...(setup.reference ? { reference: setup.reference } : {}),
    ...(Object.prototype.hasOwnProperty.call(setup, 'protocol') ? { protocol: setup.protocol } : {}),
    ...(setup.dispatched ? { dispatched: { ...(setup.dispatched.model ? { model: true as const } : {}), ...(setup.dispatched.default ? { default: true as const } : {}) } } : {}),
    ...(setup.thinkingMode ? { thinkingMode: setup.thinkingMode } : {}),
    ...(Object.prototype.hasOwnProperty.call(setup, 'maxOutputTokens') ? { maxOutputTokens: setup.maxOutputTokens } : {}),
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

export function setupDispatched(setup: ModelSetup, phase: 'model' | 'default'): boolean {
  if (setup.dispatched !== undefined) return setup.dispatched[phase] === true;
  return phase === 'model' ? setup.stage === 'model' || setup.stage === 'default'
    : setup.stage === 'default' && setup.chooseDefault;
}

export function readModelSetups(raw: string | null, owner: string): ModelSetup[] {
  if (!raw) return [];
  try {
    const value: unknown = JSON.parse(raw);
    if (!Array.isArray(value) || value.length > 100) return [];
    return value.map(item => readModelSetup(JSON.stringify(item), owner)).filter((item): item is ModelSetup => item !== null);
  } catch { return []; }
}
