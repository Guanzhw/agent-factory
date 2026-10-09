export type Role = 'manager' | 'user';
export interface User { id: string; name: string; role: Role }
export type MaterialKind = 'skill' | 'tool' | 'prompt' | 'knowledge' | 'model' | 'environment';
export interface MaterialReference { id: string; version: number; sha256: string }
export interface Material {
  id: string; version: number; kind: MaterialKind; name: string; description: string;
  content: string; sha256: string; license: string; origin: string;
  dependencies: MaterialReference[]; compatibility: string[]; permissions: string[];
  inputSchema: Record<string, unknown>; outputSchema: Record<string, unknown>;
  archived: boolean; createdAt: string;
}
export interface CompositionDraft { name: string; materials: MaterialReference[]; scenario: string }
export interface CompositionIssue { materialId?: string; code: 'dependency' | 'compatibility' | 'permission' | 'schema'; message: string }
export interface Definition {
  id: string; version: number; name: string; description: string;
  instructions: string; skills: string[]; tools: string[]; knowledge: string[];
  modelPolicy: { providerId: string; modelId: string; maxSteps: number };
  runtimePolicy: { timeoutSeconds: number; allowExperiment: boolean };
  materialRefs?: MaterialReference[]; published: boolean; createdAt: string;
}
export interface Connection { id: string; ownerId: string; name: string; providerId: string; status: 'configured' | 'unavailable' }
export type JobStatus = 'queued' | 'running' | 'waiting_input' | 'waiting_approval' | 'canceling' | 'canceled' | 'completed' | 'failed';
export interface JobInput {
  topic: string; mode: 'literature' | 'experiment'; scenario: 'normal' | 'failure' | 'slow';
  sources?: { title: string; url: string }[]; scheduledAt?: string;
}
export interface Job {
  id: string; ownerId: string; definitionId: string; definitionVersion: number;
  definition: Definition; binding: { connectionId?: string }; input: JobInput;
  status: JobStatus; createdAt: string; updatedAt: string; answer?: string;
  question?: string; approval?: { scope: string; requestedAt: string; decidedAt?: string; approved?: boolean };
  error?: string; runtime: 'demo' | 'live'; attempt: number;
}
export interface JobEvent { id: number; jobId: string; type: string; message: string; data?: Record<string, unknown>; createdAt: string }
export interface Artifact { id: string; jobId: string; name: string; mediaType: string; size: number; sha256: string; createdAt: string }
export interface AuditEntry { id: number; actorId: string; action: string; targetId: string; details: Record<string, unknown>; createdAt: string }
export interface Schedule { id: string; ownerId: string; definitionId: string; input: JobInput; connectionId?: string; everyHours: number; nextRunAt: string; enabled: boolean }
export interface PlatformInfo { mode: 'demo' | 'live'; maxWorkers: number; activeWorkers: number; queuedJobs: number; integration: string; liveEnabled: boolean; feeManagementEnabled?: boolean; platformPaidModelsEnabled?: boolean }

export type ConnectionKind = 'model' | 'tool' | 'knowledge' | 'environment' | 'orx';
export type ConnectionStatus = 'active' | 'unavailable' | 'expired' | 'revoked' | 'changed' | 'missing' | 'task_ended';
export interface UserConnection {
  ref: string; ownerId: string; version: 1; fingerprint: string; kind: ConnectionKind;
  revision: string; capabilities: string[]; taskId: string | null; registrationRef: string;
  expiresAt: string | null; createdAt: string; revokedAt: string | null;
  status: ConnectionStatus; available: boolean; allowedActions: ('inspect' | 'revoke')[];
}
export interface ConnectionRegistration {
  registrationRef: string; kind: ConnectionKind; revision: string; capabilities: string[];
  expiresAt: string | null; status: 'available' | 'unavailable' | 'expired' | 'changed';
  available: boolean; allowedActions: ('inspect' | 'bind')[];
}
