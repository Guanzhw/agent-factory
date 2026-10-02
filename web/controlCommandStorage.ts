export type ControlAction = 'answer' | 'approve' | 'cancel';
export interface ControlIntent {
  commandId: string;
  action: ControlAction;
  requirementId?: string;
  version?: number;
  answer?: string;
  approved?: boolean;
}
export interface CommandPointer {
  ownerId: string;
  taskId: string;
  commandId: string;
  action: ControlAction;
  requirementId?: string;
  version?: number;
  decisionSha256: string;
  createdAt: string;
}
const prefix = (owner: string) => `factory-control-v1:${encodeURIComponent(owner)}:`;
const key = (owner: string, task: string, action: string, requirement?: string, version?: number) =>
  `${prefix(owner)}${encodeURIComponent(task)}:${action}:${encodeURIComponent(requirement ?? '')}:${version ?? ''}`;
function pointer(value: unknown, owner: string): value is CommandPointer {
  if (!value || typeof value !== 'object') return false;
  const p = value as Partial<CommandPointer>;
  return p.ownerId === owner && typeof p.taskId === 'string' && typeof p.commandId === 'string'
    && /^[a-zA-Z0-9_.:-]{8,100}$/.test(p.commandId) && ['answer', 'approve', 'cancel'].includes(p.action ?? '')
    && typeof p.decisionSha256 === 'string' && /^[a-f0-9]{64}$/.test(p.decisionSha256)
    && typeof p.createdAt === 'string';
}
export function pendingCommandPointers(owner: string, storage: Storage = localStorage): CommandPointer[] {
  const result: CommandPointer[] = [];
  for (let i = 0; i < storage.length; i++) {
    const name = storage.key(i);
    if (!name?.startsWith(prefix(owner))) continue;
    try { const value: unknown = JSON.parse(storage.getItem(name) ?? 'null'); if (pointer(value, owner)) result.push(value); } catch { /* Ignore corrupt references, never interpret them as payloads. */ }
  }
  return result;
}
export async function decisionFingerprint(decision: Omit<ControlIntent, 'commandId'>): Promise<string> {
  const canonical = JSON.stringify(Object.fromEntries(Object.entries(decision).sort(([a], [b]) => a.localeCompare(b))));
  const bytes = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical)));
  return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
}
export async function persistCommandPointer(owner: string, task: string, decision: Omit<ControlIntent, 'commandId'>, storage: Storage = localStorage): Promise<CommandPointer> {
  const decisionSha256 = await decisionFingerprint(decision);
  const name = key(owner, task, decision.action, decision.requirementId, decision.version);
  const raw = storage.getItem(name);
  if (raw) {
    const old: unknown = JSON.parse(raw);
    if (!pointer(old, owner) || old.taskId !== task || old.decisionSha256 !== decisionSha256) {
      throw new Error('该操作已有待核对的决定，不能用新内容覆盖。请先核对原回执。');
    }
    return old;
  }
  // Persist only references and a digest before POST. Never write the answer,
  // approval text, token, cookie or credential to browser storage.
  const value: CommandPointer = { ownerId: owner, taskId: task, commandId: crypto.randomUUID(), action: decision.action,
    ...(decision.requirementId ? { requirementId: decision.requirementId, version: decision.version } : {}), decisionSha256, createdAt: new Date().toISOString() };
  storage.setItem(name, JSON.stringify(value));
  return value;
}
export function forgetCommandPointer(value: Pick<CommandPointer, 'ownerId' | 'taskId' | 'commandId'>, storage: Storage = localStorage) {
  for (const p of pendingCommandPointers(value.ownerId, storage)) {
    if (p.taskId === value.taskId && p.commandId === value.commandId) storage.removeItem(key(p.ownerId, p.taskId, p.action, p.requirementId, p.version));
  }
}

export function adoptCommandPointer(receipt: { ownerId: string; taskId: string; commandId: string; action: ControlAction; requirementId: string | null; version: number | null; decisionSha256: string }, storage: Storage = localStorage) {
  const name = key(receipt.ownerId, receipt.taskId, receipt.action, receipt.requirementId ?? undefined, receipt.version ?? undefined);
  const raw = storage.getItem(name);
  if (!raw) return;
  const value: unknown = JSON.parse(raw);
  if (pointer(value, receipt.ownerId) && value.taskId === receipt.taskId && value.decisionSha256 === receipt.decisionSha256) {
    storage.setItem(name, JSON.stringify({ ...value, commandId: receipt.commandId }));
  }
}
