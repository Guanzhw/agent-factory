import { ApiError, factoryRequest } from './api.js';
import type { UserConnection } from './models.js';

export interface PersonalToolDescriptor {
  adapterId: string; revision: string; toolName: string; description: string;
  inputSchema: Record<string, unknown>; transport: 'cli' | 'mcp';
  credentialProviderId: string; credentialDestination: string; capabilities: string[];
  permission: string; readOnly: boolean; timeoutSeconds?: number; maxOutputBytes?: number;
}
export interface PersonalToolConnection {
  ownerId: string; registrationRef: string; adapterId: string; revision: string; descriptorRevision: string;
  visibility: 'personal' | 'team'; isOwner: boolean;
  kind: 'tool'; toolName: string; transport: 'cli' | 'mcp'; credentialRef?: string | null; credentialRevision?: string | null;
  runtimeBinding?: { adapterId: string; revision: string; config: Record<string, unknown> };
  status: 'configured' | 'revoked' | 'credential_unavailable' | 'adapter_changed' | 'unavailable';
  available: boolean; capabilities: string[]; createdAt: string; expiresAt: null;
  allowedActions: ('inspect' | 'revoke' | 'bind' | 'sharing')[];
}
export interface ToolConfiguration {
  adapterId: string; credentialRef: string; credentialRevision: string; requestId: string;
}
export interface ToolConnectionReceipt {
  requestId: string; action: 'tool.configure' | 'tool.revoke' | 'tool.sharing'; tool: PersonalToolConnection;
}
export interface ToolBindingReceipt { requestId: string; action: 'bind'; connection: UserConnection }
export interface DiscoveredTool { name: string; description: string; inputSchema: Record<string, unknown>; readOnly: boolean }
export interface MemberToolConfiguration {
  transport: 'cli' | 'mcp'; toolName: string; description: string; inputSchema: Record<string, unknown>;
  requestId: string; credentialRef?: string | null; credentialRevision?: string | null;
  url?: string; remoteToolName?: string; executable?: string; arguments?: string[];
  workingDirectory?: string; environment?: Record<string, string>; argumentOptions?: Record<string, string>;
  stdinJson?: boolean; credentialEnvironmentVariable?: string; outputFormat?: 'json' | 'text'; readOnly?: boolean;
}

export class ToolConnectionError extends Error {
  constructor(public readonly status: number, public readonly code?: string) {
    super(status === 401 ? '登录已过期，请重新登录后核对原工具连接请求。'
      : status === 403 ? '当前账号没有此工具连接的操作权限。'
        : status === 422 ? '工具连接配置未被接受，请检查工具与凭据引用。'
          : '工具连接操作尚未确认，请核对原请求。');
  }
}

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const identifier = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_.:@-]{1,200}$/.test(value);
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(identifier) && new Set(value).size === value.length;
const date = (value: unknown): value is string => typeof value === 'string' && Number.isFinite(Date.parse(value));
const transport = (value: unknown): value is 'cli' | 'mcp' => value === 'cli' || value === 'mcp';
const invalid = () => new ToolConnectionError(200, 'INVALID_RESPONSE');
const ref = encodeURIComponent;

// Never expose a raw provider/transport message or unexpected error metadata.
async function safe(path: string, owner: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<unknown> {
  try { return await factoryRequest<unknown>(path, method, body, signal, owner); }
  catch (error) {
    const code = error instanceof ApiError && typeof error.code === 'string'
      && /^(?:EXPECTED_OWNER_MISMATCH|INVALID_RESPONSE|BROWSER_AUTH|OFFLINE|PERSONAL_TOOL_[A-Z_]+|CONNECTION_[A-Z_]+)$/.test(error.code)
      ? error.code : undefined;
    throw new ToolConnectionError(error instanceof ApiError ? error.status : 0, code);
  }
}

function descriptor(value: unknown): PersonalToolDescriptor {
  if (!record(value) || ![value.adapterId, value.revision, value.toolName, value.credentialProviderId, value.permission].every(identifier)
      || typeof value.description !== 'string' || !record(value.inputSchema) || !transport(value.transport)
      || typeof value.credentialDestination !== 'string' || !value.credentialDestination || !strings(value.capabilities)
      || typeof value.readOnly !== 'boolean'
      || value.timeoutSeconds !== undefined && (typeof value.timeoutSeconds !== 'number' || !Number.isFinite(value.timeoutSeconds) || value.timeoutSeconds <= 0)
      || value.maxOutputBytes !== undefined && (!Number.isSafeInteger(value.maxOutputBytes) || Number(value.maxOutputBytes) <= 0)) throw invalid();
  // Public declarations only. Credentials and constructor/process details are not copied.
  return { adapterId: value.adapterId as string, revision: value.revision as string, toolName: value.toolName as string,
    description: value.description, inputSchema: value.inputSchema, transport: value.transport,
    credentialProviderId: value.credentialProviderId as string, credentialDestination: value.credentialDestination,
    capabilities: [...value.capabilities], permission: value.permission as string, readOnly: value.readOnly,
    ...(value.timeoutSeconds === undefined ? {} : { timeoutSeconds: value.timeoutSeconds as number }),
    ...(value.maxOutputBytes === undefined ? {} : { maxOutputBytes: value.maxOutputBytes as number }) };
}

function connection(value: unknown, owner: string): PersonalToolConnection {
  if (!record(value) || !identifier(value.ownerId) || value.isOwner !== (value.ownerId === owner)
      || !['personal', 'team'].includes(String(value.visibility)) || value.kind !== 'tool'
      || ![value.registrationRef, value.adapterId, value.revision, value.descriptorRevision, value.toolName].every(identifier)
      || !(value.isOwner ? value.credentialRef === null && value.credentialRevision === null
        || identifier(value.credentialRef) && identifier(value.credentialRevision)
        : value.visibility === 'team' && value.credentialRef === undefined && value.credentialRevision === undefined)
      || !transport(value.transport) || !strings(value.capabilities) || !date(value.createdAt) || value.expiresAt !== null
      || !['configured', 'revoked', 'credential_unavailable', 'adapter_changed', 'unavailable'].includes(String(value.status))
      || typeof value.available !== 'boolean' || value.available !== (value.status === 'configured')
      || !strings(value.allowedActions) || !value.allowedActions.every(action => ['inspect', 'revoke', 'bind', 'sharing'].includes(action))
      || !value.isOwner && value.allowedActions.some(action => action === 'revoke' || action === 'sharing')
      || value.allowedActions.includes('bind') && !value.available
      || value.status === 'revoked' && value.allowedActions.some(action => action !== 'inspect')) throw invalid();
  return { ownerId: value.ownerId as string, visibility: value.visibility as 'personal' | 'team', isOwner: value.isOwner as boolean,
    registrationRef: value.registrationRef as string, adapterId: value.adapterId as string,
    revision: value.revision as string, descriptorRevision: value.descriptorRevision as string, kind: 'tool',
    toolName: value.toolName as string, transport: value.transport,
    ...(value.isOwner ? { credentialRef: value.credentialRef as string | null, credentialRevision: value.credentialRevision as string | null } : {}),
    status: value.status as PersonalToolConnection['status'],
    available: value.available, capabilities: [...value.capabilities], createdAt: value.createdAt, expiresAt: null,
    allowedActions: [...value.allowedActions] as PersonalToolConnection['allowedActions'],
    ...(record(value.runtimeBinding) ? { runtimeBinding: { adapterId: value.adapterId as string,
      revision: value.descriptorRevision as string, config: {} } } : {}) };
}

function binding(value: unknown, owner: string): UserConnection {
  if (!record(value) || value.ownerId !== owner || value.kind !== 'tool' || value.version !== 1
      || ![value.ref, value.registrationRef, value.revision].every(identifier) || value.taskId !== null
      || typeof value.fingerprint !== 'string' || !/^[a-f0-9]{64}$/.test(value.fingerprint)
      || !strings(value.capabilities) || !date(value.createdAt)
      || !(value.expiresAt === null || date(value.expiresAt)) || !(value.revokedAt === null || date(value.revokedAt))
      || !['active', 'unavailable', 'expired', 'revoked', 'changed', 'missing', 'task_ended'].includes(String(value.status))
      || typeof value.available !== 'boolean' || value.available !== (value.status === 'active')
      || !strings(value.allowedActions) || !value.allowedActions.every(action => ['inspect', 'revoke'].includes(action))) throw invalid();
  return { ref: value.ref as string, ownerId: owner, version: 1, fingerprint: value.fingerprint, kind: 'tool',
    revision: value.revision as string, capabilities: [...value.capabilities], taskId: null,
    registrationRef: value.registrationRef as string, expiresAt: value.expiresAt as string | null,
    createdAt: value.createdAt, revokedAt: value.revokedAt as string | null, status: value.status as UserConnection['status'],
    available: value.available, allowedActions: [...value.allowedActions] as UserConnection['allowedActions'] };
}

export const personalToolConnectionApi = {
  discover: async (owner: string, url: string, credential?: { credentialRef: string; credentialRevision: string }): Promise<{ url: string; tools: DiscoveredTool[] }> => {
    const result = await safe('/personal-tools/discover', owner, 'POST', { url, ...credential });
    if (!record(result) || typeof result.url !== 'string' || !Array.isArray(result.tools)
        || result.tools.some(tool => !record(tool) || typeof tool.name !== 'string' || typeof tool.description !== 'string'
          || !record(tool.inputSchema) || typeof tool.readOnly !== 'boolean')) throw invalid();
    return { url: result.url, tools: result.tools as DiscoveredTool[] };
  },
  configureResource: async (owner: string, input: MemberToolConfiguration): Promise<PersonalToolConnection> =>
    connection(await safe('/personal-tools/resources', owner, 'POST', input), owner),
  sharing: async (owner: string, registrationRef: string, visibility: 'personal' | 'team', requestId: string): Promise<PersonalToolConnection> =>
    connection(await safe(`/personal-tools/${ref(registrationRef)}/sharing`, owner, 'POST', { visibility, requestId }), owner),
  descriptors: async (owner: string, signal?: AbortSignal): Promise<PersonalToolDescriptor[]> => {
    const values = await safe('/personal-tools/descriptors', owner, 'GET', undefined, signal);
    if (!Array.isArray(values)) throw invalid();
    return values.map(descriptor);
  },
  list: async (owner: string, signal?: AbortSignal): Promise<PersonalToolConnection[]> => {
    const values = await safe('/personal-tools', owner, 'GET', undefined, signal);
    if (!Array.isArray(values)) throw invalid();
    return values.map(value => connection(value, owner));
  },
  configure: async (owner: string, input: ToolConfiguration): Promise<PersonalToolConnection> => {
    const { adapterId, credentialRef, credentialRevision, requestId } = input;
    if (![adapterId, credentialRef, credentialRevision, requestId].every(identifier)) throw new ToolConnectionError(422, 'INVALID_CONFIGURATION');
    const value = connection(await safe('/personal-tools', owner, 'POST', { adapterId, credentialRef, credentialRevision, requestId }), owner);
    if (value.adapterId !== adapterId || value.credentialRef !== credentialRef || value.credentialRevision !== credentialRevision
        || value.status === 'revoked') throw invalid();
    return value;
  },
  recover: async (owner: string, requestId: string): Promise<ToolConnectionReceipt> => {
    const value = await safe(`/personal-tools/requests/${ref(requestId)}`, owner);
    if (!record(value) || value.requestId !== requestId || !['tool.configure', 'tool.revoke', 'tool.sharing'].includes(String(value.action))) throw invalid();
    return { requestId, action: value.action as ToolConnectionReceipt['action'], tool: connection(value.tool, owner) };
  },
  revoke: async (owner: string, registrationRef: string, requestId: string): Promise<PersonalToolConnection> => {
    const value = connection(await safe(`/personal-tools/${ref(registrationRef)}/revoke`, owner, 'POST', { requestId }), owner);
    if (value.registrationRef !== registrationRef || value.status !== 'revoked' || value.available) throw invalid();
    return value;
  },
  bind: async (owner: string, registrationRef: string, requestId: string, capabilities: string[]): Promise<UserConnection> => {
    if (!identifier(registrationRef) || !identifier(requestId) || !strings(capabilities)) throw new ToolConnectionError(422, 'INVALID_CONFIGURATION');
    const value = binding(await safe('/user-connections', owner, 'POST', { registrationRef, requestId, capabilities: [...capabilities] }), owner);
    if (value.registrationRef !== registrationRef || value.status !== 'active' || !value.available
        || value.capabilities.length !== capabilities.length || capabilities.some(capability => !value.capabilities.includes(capability))) throw invalid();
    return value;
  },
  recoverBinding: async (owner: string, requestId: string): Promise<ToolBindingReceipt> => {
    const value = await safe(`/user-connections/requests/${ref(requestId)}`, owner);
    if (!record(value) || value.requestId !== requestId || value.action !== 'bind') throw invalid();
    return { requestId, action: 'bind', connection: binding(value.connection, owner) };
  },
};
