import { ApiError, factoryRequest } from './api.js';
import { RemoteRequestError, definitivelyRejected } from './personalRemoteApi.js';

export interface SSHIdentityInput { name: string; address: string; port: number; username: string; hostKey: string; allowedRoot: string; }
export interface SSHIdentity { address: string; port: number; username: string; hostKey: string; hostFingerprint: string; origin: string; }
export interface PersonalSSHServer extends SSHIdentityInput { reference: string; hostFingerprint: string; defaultDirectory: string;
  status: string; enabled: boolean; diagnostic: string | null; lastCheckRequestId: string | null; credentialRef: string; credentialRevision: string; }
export type SSHAction = 'configure' | 'verify' | 'bind' | 'revoke';
export const sshMessages: Record<string, string> = {
  SSH_INPUT_INVALID: '请核对服务器名称、IP、端口、非 root 账户、Ed25519 主机公钥和私有目录。',
  SSH_IDENTITY_INVALID: '服务器身份或目录格式不适用。请使用允许访问的 IP、非 root 账户、完整 Ed25519 主机公钥和较短的私有目录。',
  SSH_LINUX_ARCH_REQUIRED: '服务器需要 Linux x86-64。请选用符合要求的服务器。',
  SSH_NON_ROOT_REQUIRED: '请使用自己的非 root SSH 账户，并为该账户准备 Docker 权限。',
  SSH_PYTHON_MISSING: '未找到 python3。请先在服务器准备 Python 3.12+，再重新检查。',
  SSH_PYTHON_VERSION_REQUIRED: '服务器的 Python 版本需要 3.12 或更新版本。请升级后重新检查。',
  SSH_DOCKER_MISSING: '未找到 Docker。请先在服务器安装并启动 Docker，再重新检查。',
  SSH_DOCKER_PERMISSION: '此 SSH 账户无权使用 Docker。请在服务器为自己的非 root 账户配置 Docker 权限，重新登录后检查。',
  SSH_DOCKER_UNAVAILABLE: 'Docker 服务不可用。请确认它已启动，且此账户可以运行 docker version。',
  SSH_DIRECTORY_UNSAFE: '此目录不是本人私有目录，或包含链接。请选择自己的新子目录；已有私有目录须归本人所有且权限为 700。',
  SSH_DIRECTORY_PARENT_REQUIRED: '请选择自己已存在目录中的新子目录，例如本人 home 下的 .agent-factory。不会修改其他人的目录或权限。',
  SSH_CHECK_UNCONFIRMED: '连接检查未取得可信结果。请核对服务器可达、主机公钥和 SSH 身份；不会放宽主机校验或安装应用。',
  SSH_AGENT_CAPACITY: '当前 SSH 身份使用量已达到限额。请稍后重新检查。',
  SSH_CREDENTIAL_UNAVAILABLE: 'SSH 身份已失效或不可用。请绑定本人当前有效的身份后重新检查。',
};
async function call<T>(owner: string, path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  try { return await factoryRequest<T>(`/personal-ssh${path}`, method, body, signal, owner); }
  catch (e) { throw new RemoteRequestError(e instanceof ApiError && (definitivelyRejected(e.status) || !!e.code && !!sshMessages[e.code]), e instanceof ApiError ? e.code : undefined); }
}
const ref = encodeURIComponent;
export const personalSSHApi = {
  capabilities: (owner: string, signal?: AbortSignal) => call<{ enabled: boolean }>(owner, '/capabilities', 'GET', undefined, signal),
  list: (owner: string, signal?: AbortSignal) => call<PersonalSSHServer[]>(owner, '', 'GET', undefined, signal),
  identity: (owner: string, input: SSHIdentityInput) => call<SSHIdentity>(owner, '/identity', 'POST', input),
  configure: (owner: string, input: SSHIdentityInput & { credentialRef: string; credentialRevision: string; confirmedHostKey: true; requestId: string }, reference?: string) => call<PersonalSSHServer>(owner, reference ? `/${ref(reference)}/configure` : '', 'POST', input),
  inspect: (owner: string, reference: string) => call<PersonalSSHServer>(owner, `/${ref(reference)}`),
  command: (owner: string, server: string, action: Exclude<SSHAction, 'configure'>, requestId: string) => call<PersonalSSHServer>(owner, `/${ref(server)}/${action}`, 'POST', { requestId }),
  recover: (owner: string, requestId: string, action: SSHAction) => call<{ requestId: string; action: SSHAction; server: PersonalSSHServer }>(owner, `/requests/${ref(requestId)}?action=${action}`),
};
