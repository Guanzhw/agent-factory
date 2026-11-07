export type Role = 'manager' | 'user';
export interface User { id: string; name: string; role: Role }
export interface MaterialReference { id: string; version: number; sha256: string }
export type ConnectionKind = 'model' | 'tool' | 'knowledge' | 'environment' | 'orx';
export type ConnectionStatus = 'active' | 'unavailable' | 'expired' | 'revoked' | 'changed' | 'missing' | 'task_ended';
export interface UserConnection {
  ref: string; ownerId: string; version: 1; fingerprint: string; kind: ConnectionKind;
  revision: string; capabilities: string[]; taskId: string | null; registrationRef: string;
  expiresAt: string | null; createdAt: string; revokedAt: string | null;
  status: ConnectionStatus; available: boolean; allowedActions: ('inspect' | 'revoke')[];
}
