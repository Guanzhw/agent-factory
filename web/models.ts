import type { Artifact, Connection, Job, JobEvent, Material, MaterialReference, PlatformInfo, User } from '../shared/types.js';

export type { Artifact, Connection, JobEvent, MaterialReference, User };
export type FactoryMaterial = Material & {
  published: boolean;
  governance?: { state: 'draft' | 'published' | 'withdrawn' | 'archived'; authorId?: string; reason?: string | null; reviewId?: string | null };
  provenance?: { kind: 'original' | 'upstream'; source?: string | null; revision?: string | null; notice: string };
};
export interface MaterialGovernancePolicy {
  review_mode: 'separate-admin' | 'demo-self-review'; revision: string; fingerprint: string;
  demoCompatibility: boolean; taskApprovalSeparate: boolean; importExecutesCode: boolean;
}
export interface MaterialReview {
  id: string; materialId: string; version: number; authorId: string; sha256: string;
  immutableDigest: string; policyRevision: string; currentPolicy: boolean;
  decision: 'pending' | 'approved' | 'denied'; reviewerId?: string | null; requestedBy: string;
  createdAt: string; decidedAt?: string | null; state: 'draft' | 'published' | 'withdrawn' | 'archived';
  material: FactoryMaterial; demoCompatibility: boolean; taskApprovalSeparate: boolean;
}
export type FactoryStatus = PlatformInfo;
export interface Plan {
  id: string;
  fingerprint: string;
  normalizedGoal: string;
  materialRefs: MaterialReference[];
  capabilities: string[];
  missing: string[];
  status: 'ready' | 'blocked';
  createdAt: string;
  authorization?: PlanAuthorization;
}
export interface PendingQuestion { id: string; version: number; text: string }
export interface PendingApproval { id: string; version: number; scope: string }
export type FactoryJob = Job & {
  planId?: string;
  executionPlacement?: { kind: string; targetRef: string; originTaskId: string; remoteTaskId?: string; state: string };
  allowedActions?: string[];
  validationStatus?: string;
  evidenceKind?: string;
  questionId?: string;
  questionVersion?: number;
  requirementId?: string;
  approvalVersion?: number;
  questionDetail?: PendingQuestion & { fields?: { name: string; type: string; description?: string; value?: unknown }[] };
  approvalDetail?: PendingApproval & { toolName?: string; arguments?: Record<string, unknown> };
};
export interface JobDetail { job: FactoryJob; events: JobEvent[]; artifacts: Artifact[]; snapshot?: Record<string, unknown> }
export interface DelegationFact {
  taskId: string | null; nativeStatus: string | null; unknown: boolean;
  failed: boolean; pending: boolean; stopped: boolean;
  link?: { parent_id: string; root_id: string; depth: number; request_id: string };
}
export interface DelegationGroup { parent: DelegationFact; children: DelegationFact[]; pending: boolean; unknown: boolean; allStopped: boolean }
export interface DelegationScope {
  allowed: boolean; parentTaskId: string; rootTaskId: string; depth: number;
  capabilities: string[]; tools: string[]; budget: Record<string, unknown>;
  sharedBudget: { toolCallsUsed: number; toolCallsLimit: number; childrenUsed: number; childrenLimit: number; maxDepth: number };
  reason?: string;
}
export interface ChildReceipt { job: FactoryJob; childTask: Record<string, unknown>; link: Record<string, unknown>; duplicate: boolean }
export function eventCopy(event: JobEvent): { title: string; message: string } {
  const known: Record<string, [string, string]> = {
    admission_reserved: ['任务已登记', '任务范围已保留，正在等待运行服务确认。'],
    native_accepted: ['运行服务已接收', '原生持久化队列已接收任务。'],
    admission_unknown: ['接收结果待核对', '尚未收到运行确认，需要核对原请求。'],
    admission_rejected: ['运行请求被拒绝', '运行服务拒绝了本次请求，原因见记录详情。'],
    plan_bound: ['方案已绑定', '执行已绑定到持久化的不可变方案。'],
    delegation_bound: ['子任务范围已绑定', '子任务已在提交运行前绑定不可变的父任务与根任务范围。'],
    cascade_cancel_pending: ['后代取消待确认', '后代任务的原生取消结果仍未确认。'],
    protected_denied: ['操作权限检查未通过', '当前授权或取消状态阻止了工具操作。'],
    tool_failed: ['工具执行未成功', '工具没有建立有效结果，原因见记录详情。'],
    question_answered: ['回答已提交', '已向运行服务提交本次问题的回答。'],
    approval_decided: ['审批决定已提交', '已提交本次工具调用的审批决定。'],
    scope_answered: ['任务范围已确认', '已接收用户提供的任务范围。'],
    reconciliation: ['状态已核对', '已查询运行服务；未确认的操作仍保留为待核对。'],
    cancel_requested: ['已请求取消', '正在等待原生执行与任务计算停止。'],
    compute_started: ['合成计算已启动', '有资源上限的合成评估子进程已启动。'],
    compute_stopped: ['任务计算已清理', '后端记录了任务计算及其子进程的清理结果。'],
    compute_cancelled: ['计算取消已确认', '任务计算清理确认后，后端记录了取消结果。'],
    literature_fixture: ['合成文献记录已生成', '记录来自测试样本，不能作为真实文献证据。'],
    checksum_completed: ['输入校验完成', '已记录输入校验结果。'],
    experiment_completed: ['合成评估完成', '评估记录已生成；这些数值不证明真实研究改进。'],
    effect_unknown: ['计算结果待核对', '计算确认尚不明确，需要核对原操作。'],
    artifact: ['产物已保存', '已保存产物，并记录内容哈希。'],
  };
  if (event.type === 'lifecycle') {
    const status = String(event.data?.status ?? event.message).toLowerCase();
    const native: Record<string, string> = { pending: '等待运行', paused: '等待继续', cancelled: '已取消', error: '执行失败' };
    return { title: '执行状态记录', message: `运行服务报告：${statusNames[status] ?? native[status] ?? '状态详见记录详情'}。` };
  }
  const copy = known[event.type];
  return copy ? { title: copy[0], message: copy[1] } : { title: '执行记录', message: '后端记录了一条事件，详情可展开查看。' };
}
export function evaluationEvidence(detail: JobDetail): Record<string, unknown> | undefined {
  const value = detail.snapshot?.evaluation;
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}
export interface MaterialDraft {
  id?: string;
  name: string;
  kind: Material['kind'];
  description: string;
  content: string;
  dependencies: MaterialReference[];
  permissions: string[];
}
export const kindNames: Record<Material['kind'], string> = {
  skill: '技能', tool: '工具', prompt: '提示词', knowledge: '知识', model: '模型', environment: '环境',
};
export const statusNames: Record<string, string> = {
  queued: '排队中', running: '运行中', waiting_input: '等待回答', waiting_approval: '等待审批',
  canceling: '正在请求取消', canceled: '已取消', completed: '执行完成', failed: '执行失败',
  unknown: '状态待确认', reconciling: '正在核对状态', waiting_children: '等待子任务',
};
export const materialKey = (m: { id: string; version: number }) => `${m.id}@${m.version}`;
export function pendingQuestion(detail: JobDetail): PendingQuestion | undefined {
  const { job, snapshot } = detail;
  if (job.questionDetail) return job.questionDetail;
  const raw = snapshot?.question;
  if (raw && typeof raw === 'object') {
    const q = raw as Record<string, unknown>;
    const id = q.id ?? q.questionId;
    if (typeof id === 'string' && typeof q.version === 'number' && typeof (q.text ?? q.question) === 'string') {
      return { id, version: q.version, text: String(q.text ?? q.question) };
    }
  }
  if (job.question && job.questionId && typeof job.questionVersion === 'number') {
    return { id: job.questionId, version: job.questionVersion, text: job.question };
  }
}
export function pendingApproval(detail: JobDetail): PendingApproval | undefined {
  const { job, snapshot } = detail;
  if (job.approvalDetail) return job.approvalDetail;
  const raw = snapshot?.approval;
  if (raw && typeof raw === 'object') {
    const a = raw as Record<string, unknown>;
    const id = a.id ?? a.requirementId;
    if (typeof id === 'string' && typeof a.version === 'number' && typeof a.scope === 'string') {
      return { id, version: a.version, scope: a.scope };
    }
  }
  if (job.approval && job.requirementId && typeof job.approvalVersion === 'number') {
    return { id: job.requirementId, version: job.approvalVersion, scope: job.approval.scope };
  }
}

export interface PlanAuthorization {
  executionAllowed: boolean; reviewRequired: boolean; code?: string; message?: string;
  policy: { name: string; revision: string; fingerprint: string; review_ttl_seconds: number };
  nativeToolConfirmationSeparate: boolean;
}
export interface PlanReview {
  id: string; ownerId: string; planId: string; planDigest: string; planFingerprint: string;
  policyRevision: string; expiresAt: string; expired: boolean; currentPolicy: boolean;
  planIntegrityMatches?: boolean;
  decision: 'pending' | 'approved' | 'denied'; approvalEffective: boolean; reviewerId: string | null;
  planSummary?: { normalizedGoal?: string; application?: string; mode?: string; tools?: string[];
    capabilities?: string[]; budget?: Record<string, unknown>; materialRefs?: MaterialReference[] };
}

export interface ExecutionTarget { id: string; name: string; kind: "remote-factory"; connectivityVerified: boolean }

export interface EventPage {
  events: (JobEvent & { sequence: number; payloadSha256: string; receiverPayloadSha256?: string })[];
  nextCursor: string; streamId: string; schema: 1; nativeCursor: false;
  source: 'factory-af_events' | 'factory-remote-af_events'; hasMore: boolean;
  highWatermark: number; highWatermarkSequence: number; afterSequence: number;
  startSequence: number | null; endSequence: number | null;
  payloadSha256: string; payloadBytes: number; executionTargetRef?: string;
}
