export interface AggregateEnforcement {
  schema: 2; backend: 'delegated-cgroup-v2'; cpu: 'cgroup-v2-cpu.max'; memory: 'cgroup-v2-memory.max+memory.swap.max';
  pids: 'cgroup-v2-pids.max'; fileSize: 'per-file-RLIMIT_FSIZE'; wall: 'original-delegated-cgroup-guardian';
  aggregateScopes: ['aggregate-cpu', 'aggregate-memory', 'aggregate-pids']; hostileCodeSandbox: false; networkIsolation: false; configurationSha256: string;
}
export interface AggregateEvidence {
  schema: 1; backend: 'delegated-cgroup-v2'; ticketId: string; bindingSha256: string; configSha256: string;
  rootPinSha256: string; groupPinSha256: string | null; state: string; populated: boolean | null;
  limitsReadbackVerified: boolean; releasedProof: boolean; attached: boolean;
}
export interface ProcessLease {
  id: string; ownerId: string; localTaskId: string; planId: string; nativeRunId: string | null;
  executionStatus: string | null; exitCode: number | null;
  state: string; capacityHeld: boolean; providerJobId: string | null;
  processBinding: { taskId: string; nativeRunId: string; planId: string; bindingFingerprint: string } | null;
  enforcement: { cpu: string; memory: string; fileSize: string; wall: string; aggregateQuota: false; hostileCodeSandbox: false; networkIsolation: false } | AggregateEnforcement | null;
  aggregateEvidence?: AggregateEvidence | null;
  stopEvidence: { allStopped: boolean; kind: 'original-root-reaped-and-no-live-process-group-members' | 'never-dispatched' | 'original-delegated-cgroup-empty-and-removed' } | null;
}
export type ProcessLeaseView = { kind: 'invalid' } | { kind: 'verified'; lease: ProcessLease; stopped: boolean; released: boolean };
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);
const identifier = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.:~-]{0,199}$/.test(value);
const optionalId = (value: unknown) => value === undefined || value === null || identifier(value);
const hash = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const exact = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
const terminal = ['COMPLETED', 'FAILED', 'CANCEL_CONFIRMED', 'RECLAIMING', 'RECLAIMED'];
const executionTerminal = ['COMPLETED', 'CANCELLED', 'LIMIT_STOPPED', 'FAILED'];
const executionStates = ['PREPARED', 'DISPATCHING', 'RUNNING', 'UNKNOWN', ...executionTerminal];
const states = ['RESERVED', 'ACCEPTED', 'RUNNING', 'UNKNOWN', 'CANCEL_REQUESTED', ...terminal];
export function processLeaseView(value: unknown, owner: string): ProcessLeaseView {
  if (!record(value) || !identifier(value.id) || value.ownerId !== owner || !identifier(value.localTaskId) || !identifier(value.planId)
      || !optionalId(value.nativeRunId) || !optionalId(value.providerJobId) || typeof value.state !== 'string' || !states.includes(value.state)
      || typeof value.capacityHeld !== 'boolean' || value.capacityHeld !== (value.state !== 'RECLAIMED')) return { kind: 'invalid' };
  if (!(value.executionStatus === undefined || value.executionStatus === null || typeof value.executionStatus === 'string' && executionStates.includes(value.executionStatus))
      || !(value.exitCode === undefined || value.exitCode === null || typeof value.exitCode === 'number' && Number.isInteger(value.exitCode) && value.exitCode >= -255 && value.exitCode <= 255)) return { kind: 'invalid' };
  const binding = value.processBinding ?? null, enforcement = value.enforcement ?? null, stop = value.stopEvidence ?? null;
  if (binding !== null && (!record(binding) || !exact(binding, ['taskId', 'nativeRunId', 'planId', 'bindingFingerprint'])
      || binding.taskId !== value.localTaskId || !identifier(binding.nativeRunId) || binding.nativeRunId !== value.nativeRunId
      || binding.planId !== value.planId || !hash(binding.bindingFingerprint))) return { kind: 'invalid' };
  const aggregate = record(enforcement) && enforcement.schema === 2;
  if (aggregate) {
    if (!exact(enforcement, ['schema', 'backend', 'cpu', 'memory', 'pids', 'fileSize', 'wall', 'aggregateScopes', 'hostileCodeSandbox', 'networkIsolation', 'configurationSha256'])
        || enforcement.backend !== 'delegated-cgroup-v2' || enforcement.cpu !== 'cgroup-v2-cpu.max'
        || enforcement.memory !== 'cgroup-v2-memory.max+memory.swap.max' || enforcement.pids !== 'cgroup-v2-pids.max'
        || enforcement.fileSize !== 'per-file-RLIMIT_FSIZE' || enforcement.wall !== 'original-delegated-cgroup-guardian'
        || !Array.isArray(enforcement.aggregateScopes) || enforcement.aggregateScopes.length !== 3
        || enforcement.aggregateScopes.join('|') !== 'aggregate-cpu|aggregate-memory|aggregate-pids'
        || enforcement.hostileCodeSandbox !== false || enforcement.networkIsolation !== false || !hash(enforcement.configurationSha256)) return { kind: 'invalid' };
  } else if (enforcement !== null && (!record(enforcement) || !exact(enforcement, ['cpu', 'memory', 'fileSize', 'wall', 'aggregateQuota', 'hostileCodeSandbox', 'networkIsolation'])
      || enforcement.cpu !== 'per-process-RLIMIT_CPU' || enforcement.memory !== 'per-process-RLIMIT_AS'
      || enforcement.fileSize !== 'per-file-RLIMIT_FSIZE' || enforcement.wall !== 'cooperative-process-group-guardian'
      || enforcement.aggregateQuota !== false || enforcement.hostileCodeSandbox !== false || enforcement.networkIsolation !== false)) return { kind: 'invalid' };
  const evidence = value.aggregateEvidence ?? null;
  if (evidence !== null) {
    if (!aggregate || !binding || !identifier(value.providerJobId) || !record(evidence)
        || !exact(evidence, ['schema', 'backend', 'ticketId', 'bindingSha256', 'configSha256', 'rootPinSha256', 'groupPinSha256', 'state', 'populated', 'limitsReadbackVerified', 'releasedProof', 'attached'])
        || evidence.schema !== 1 || evidence.backend !== 'delegated-cgroup-v2'
        || typeof evidence.ticketId !== 'string' || !/^[a-f0-9]{32}$/.test(evidence.ticketId)
        || evidence.bindingSha256 !== binding.bindingFingerprint || evidence.configSha256 !== enforcement.configurationSha256
        || !hash(evidence.rootPinSha256) || !(evidence.groupPinSha256 === null || hash(evidence.groupPinSha256))
        || typeof evidence.state !== 'string' || !['NEW', 'CREATE_INTENT', 'CONFIGURE_INTENT', 'READY', 'ATTACH_INTENT', 'ATTACHED', 'KILL_INTENT', 'EMPTY', 'REMOVE_INTENT', 'RELEASED', 'UNKNOWN'].includes(evidence.state)
        || !(evidence.populated === null || typeof evidence.populated === 'boolean')
        || !['limitsReadbackVerified', 'releasedProof', 'attached'].every(key => typeof evidence[key] === 'boolean')
        || evidence.attached && evidence.groupPinSha256 === null
        || evidence.releasedProof !== (evidence.state === 'RELEASED')
        || evidence.releasedProof && (evidence.populated !== false || evidence.groupPinSha256 === null)
        || evidence.state === 'NEW' && (evidence.attached || evidence.limitsReadbackVerified || evidence.groupPinSha256 !== null || evidence.populated !== null)) return { kind: 'invalid' };
  } else if (aggregate && value.providerJobId != null) return { kind: 'invalid' };
  if (stop !== null && (!record(stop) || !exact(stop, ['allStopped', 'kind']) || typeof stop.allStopped !== 'boolean'
      || typeof stop.kind !== 'string' || !['original-root-reaped-and-no-live-process-group-members', 'never-dispatched', 'original-delegated-cgroup-empty-and-removed'].includes(stop.kind))) return { kind: 'invalid' };
  if (stop?.allStopped === true && (!binding || !identifier(value.providerJobId) || !enforcement || !terminal.includes(value.state) || typeof value.executionStatus !== 'string' || !executionTerminal.includes(value.executionStatus))) return { kind: 'invalid' };
  if (stop?.allStopped === true && aggregate && (stop.kind === 'never-dispatched'
      ? evidence?.state !== 'NEW' : stop.kind !== 'original-delegated-cgroup-empty-and-removed' || evidence?.releasedProof !== true)) return { kind: 'invalid' };
  if (stop?.kind === 'original-delegated-cgroup-empty-and-removed' && (!aggregate || evidence?.state !== 'RELEASED' || evidence.releasedProof !== true || evidence.populated !== false || !hash(evidence.groupPinSha256))) return { kind: 'invalid' };
  if (value.state === 'RECLAIMED' && (stop?.allStopped !== true || typeof value.executionStatus !== 'string' || !executionTerminal.includes(value.executionStatus))) return { kind: 'invalid' };
  const lease = { ...value, executionStatus: value.executionStatus ?? null, exitCode: value.exitCode ?? null, nativeRunId: value.nativeRunId ?? null, providerJobId: value.providerJobId ?? null,
    processBinding: binding, enforcement, aggregateEvidence: evidence, stopEvidence: stop } as unknown as ProcessLease;
  return { kind: 'verified', lease, stopped: stop?.allStopped === true, released: value.state === 'RECLAIMED' };
}
export function processLeasePage(value: unknown, owner: string): { leases: ProcessLease[]; nextCursor: string | null } {
  if (!record(value) || !Array.isArray(value.leases) || value.leases.length > 100
      || !(value.nextCursor === null || typeof value.nextCursor === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value.nextCursor))) {
    throw new Error('执行租约分页响应无法核对。');
  }
  const leases = value.leases.map(item => {
    const view = processLeaseView(item, owner);
    if (view.kind !== 'verified') throw new Error('执行租约身份或进程回执无法核对。');
    return view.lease;
  });
  if (new Set(leases.map(lease => lease.id)).size !== leases.length) {
    throw new Error('执行租约分页边界无法核对。');
  }
  return { leases, nextCursor: value.nextCursor };
}
const labels: Record<string, string> = { RESERVED: '已保留，等待启动确认', ACCEPTED: '已接受', RUNNING: '执行中',
  UNKNOWN: 'UNKNOWN · 执行状态待核对', CANCEL_REQUESTED: '已请求停止，等待确认', COMPLETED: '执行已完成', FAILED: '执行失败',
  CANCEL_CONFIRMED: '取消已确认', RECLAIMING: '回收确认待核对', RECLAIMED: '已释放' };
export const processLeaseState = (state: string) => labels[state] ?? '状态待核对';

const executionLabels: Record<string, string> = { PREPARED: '进程启动前准备', DISPATCHING: '进程启动确认待核对', RUNNING: '进程执行中', UNKNOWN: '进程结果 UNKNOWN', COMPLETED: '进程已结束（COMPLETED）', CANCELLED: '进程已取消', LIMIT_STOPPED: '进程触发限额后停止', FAILED: '进程失败' };
export const processExecutionState = (state: string | null) => state ? executionLabels[state] ?? '进程结果尚未确认' : '进程结果尚未确认';
