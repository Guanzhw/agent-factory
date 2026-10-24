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
  operationRef?: ToolOperationRef;
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
  timeoutSeconds?: number; maxOutputBytes?: number;
}

export interface ToolOperationRef { id: string; version: number; sha256: string }
export type PublicToolConfiguration = Omit<MemberToolConfiguration, 'requestId' | 'credentialRef' | 'credentialRevision'>;
export interface ToolOperation {
  operationRef: ToolOperationRef; ownerId: string; configuration: PublicToolConfiguration;
  descriptor: PersonalToolDescriptor;
  runtimeBinding: { adapterId: string; revision: string; config: { operationSha256: string } };
}
export interface CreateToolOperation { configuration: PublicToolConfiguration; requestId: string; operationId?: string }
export interface CreateToolAccount {
  version: number; sha256: string; credentialRef?: string; credentialRevision?: string; requestId: string;
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

const hash = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
function operationRef(value: unknown): ToolOperationRef {
  if (!record(value) || !identifier(value.id) || !Number.isSafeInteger(value.version) || Number(value.version) < 1 || !hash(value.sha256)
      || Object.keys(value).some(key => !['id', 'version', 'sha256'].includes(key))) throw invalid();
  return { id: value.id, version: value.version as number, sha256: value.sha256 };
}
/** Public recipes deliberately exclude account identifiers and private credential values. */
export function publicToolConfiguration(value: unknown): PublicToolConfiguration {
  const fields = ['transport', 'toolName', 'description', 'inputSchema', 'readOnly', 'timeoutSeconds', 'maxOutputBytes',
    'url', 'remoteToolName', 'executable', 'arguments', 'workingDirectory', 'environment', 'argumentOptions',
    'stdinJson', 'credentialEnvironmentVariable', 'outputFormat'];
  if (!record(value) || Object.keys(value).some(key => !fields.includes(key)) || !transport(value.transport)
      || !identifier(value.toolName) || typeof value.description !== 'string' || !record(value.inputSchema)) throw invalid();
  for (const key of ['url', 'remoteToolName', 'executable', 'workingDirectory', 'credentialEnvironmentVariable']) {
    if (value[key] !== undefined && value[key] !== null && typeof value[key] !== 'string') throw invalid();
  }
  if (value.transport === 'cli' && !value.executable || value.transport === 'mcp' && (!value.url || !value.remoteToolName)) throw invalid();
  if (value.url) {
    let url: URL; try { url = new URL(String(value.url)); } catch { throw invalid(); }
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw invalid();
  }
  if (value.arguments !== undefined && (!Array.isArray(value.arguments) || value.arguments.some(item => typeof item !== 'string'))
      || ['environment', 'argumentOptions'].some(key => value[key] !== undefined && (!record(value[key]) || Object.values(value[key]).some(item => typeof item !== 'string')))
      || ['readOnly', 'stdinJson'].some(key => value[key] !== undefined && typeof value[key] !== 'boolean')
      || value.outputFormat !== undefined && !['json', 'text'].includes(String(value.outputFormat))
      || value.timeoutSeconds !== undefined && (typeof value.timeoutSeconds !== 'number' || !Number.isFinite(value.timeoutSeconds) || value.timeoutSeconds <= 0)
      || value.maxOutputBytes !== undefined && (!Number.isSafeInteger(value.maxOutputBytes) || Number(value.maxOutputBytes) <= 0)) throw invalid();
  return structuredClone(value) as unknown as PublicToolConfiguration;
}
function operation(value: unknown): ToolOperation {
  if (!record(value) || !identifier(value.ownerId)) throw invalid();
  const pin = operationRef(value.operationRef), declared = descriptor(value.descriptor);
  if (!record(value.configuration)) throw invalid();
  const { credentialProviderId, credentialDestination, permission, capabilities, ...recipe } = value.configuration;
  const configuration = publicToolConfiguration(recipe), runtime = value.runtimeBinding;
  // Canonical public recipes include descriptor semantics in their hash. Keep
  // these visible, while the creation form only accepts resource recipe fields.
  for (const [key, extra] of Object.entries({ credentialProviderId, credentialDestination, permission, capabilities })) {
    if (extra !== undefined && JSON.stringify(extra) !== JSON.stringify(declared[key as keyof PersonalToolDescriptor])) throw invalid();
  }
  const canonical = { ...configuration, ...(credentialProviderId === undefined ? {} : { credentialProviderId }),
    ...(credentialDestination === undefined ? {} : { credentialDestination }), ...(permission === undefined ? {} : { permission }),
    ...(capabilities === undefined ? {} : { capabilities }) };
  if (!record(runtime) || runtime.adapterId !== declared.adapterId || runtime.revision !== declared.revision
      || !record(runtime.config) || Object.keys(runtime.config).length !== 1 || runtime.config.operationSha256 !== pin.sha256
      || configuration.transport !== declared.transport || configuration.toolName !== declared.toolName) throw invalid();
  return { operationRef: pin, ownerId: value.ownerId, configuration: canonical, descriptor: declared,
    runtimeBinding: { adapterId: declared.adapterId, revision: declared.revision, config: { operationSha256: pin.sha256 } } };
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
  const pin = value.operationRef === undefined ? undefined : operationRef(value.operationRef);
  if (pin && (!record(value.runtimeBinding) || value.runtimeBinding.adapterId !== value.adapterId
      || value.runtimeBinding.revision !== value.descriptorRevision || !record(value.runtimeBinding.config)
      || Object.keys(value.runtimeBinding.config).length !== 1 || value.runtimeBinding.config.operationSha256 !== pin.sha256)) throw invalid();
  return { ...(pin ? { operationRef: pin } : {}), ownerId: value.ownerId as string, visibility: value.visibility as 'personal' | 'team', isOwner: value.isOwner as boolean,
    registrationRef: value.registrationRef as string, adapterId: value.adapterId as string,
    revision: value.revision as string, descriptorRevision: value.descriptorRevision as string, kind: 'tool',
    toolName: value.toolName as string, transport: value.transport,
    ...(value.isOwner ? { credentialRef: value.credentialRef as string | null, credentialRevision: value.credentialRevision as string | null } : {}),
    status: value.status as PersonalToolConnection['status'],
    available: value.available, capabilities: [...value.capabilities], createdAt: value.createdAt, expiresAt: null,
    allowedActions: [...value.allowedActions] as PersonalToolConnection['allowedActions'],
    ...(record(value.runtimeBinding) ? { runtimeBinding: { adapterId: value.adapterId as string,
      revision: value.descriptorRevision as string, config: pin ? { operationSha256: pin.sha256 } : {} } } : {}) };
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
  operations: async (owner: string, signal?: AbortSignal): Promise<ToolOperation[]> => {
    const values = await safe('/personal-tools/operations', owner, 'GET', undefined, signal);
    if (!Array.isArray(values)) throw invalid();
    return values.map(operation);
  },
  operation: async (owner: string, id: string, version: number, signal?: AbortSignal): Promise<ToolOperation> => {
    const value = operation(await safe(`/personal-tools/operations/${ref(id)}/versions/${version}`, owner, 'GET', undefined, signal));
    if (value.operationRef.id !== id || value.operationRef.version !== version) throw invalid();
    return value;
  },
  createOperation: async (owner: string, input: CreateToolOperation): Promise<ToolOperation> => {
    if (!identifier(input.requestId) || input.operationId !== undefined && !identifier(input.operationId)) throw invalid();
    const configuration = publicToolConfiguration(input.configuration);
    const value = operation(await safe('/personal-tools/operations', owner, 'POST', {
      configuration, requestId: input.requestId, ...(input.operationId ? { operationId: input.operationId } : {}),
    }));
    if (value.ownerId !== owner || input.operationId !== undefined && value.operationRef.id !== input.operationId) throw invalid();
    return value;
  },
  createOperationAccount: async (owner: string, id: string, input: CreateToolAccount): Promise<PersonalToolConnection> => {
    const pin = operationRef({ id, version: input.version, sha256: input.sha256 });
    if (!identifier(input.requestId) || (input.credentialRef === undefined) !== (input.credentialRevision === undefined)
        || input.credentialRef !== undefined && (!identifier(input.credentialRef) || !identifier(input.credentialRevision))) throw invalid();
    const value = connection(await safe(`/personal-tools/operations/${ref(id)}/accounts`, owner, 'POST', {
      version: pin.version, sha256: pin.sha256, requestId: input.requestId,
      ...(input.credentialRef ? { credentialRef: input.credentialRef, credentialRevision: input.credentialRevision } : {}),
    }), owner);
    if (!value.isOwner || value.ownerId !== owner || !value.operationRef || value.operationRef.id !== id
        || value.operationRef.version !== pin.version || value.operationRef.sha256 !== pin.sha256
        || (value.credentialRef ?? undefined) !== input.credentialRef || (value.credentialRevision ?? undefined) !== input.credentialRevision) throw invalid();
    return value;
  },
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
