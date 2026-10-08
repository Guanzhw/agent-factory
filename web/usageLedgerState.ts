import type { JobDetail } from './models.js';
export interface UsageCommitment {
  schema: 1; currency: string; amountMicros: number; tokenLimit: number; provider: string; model: string; adapterId: string; adapterRevision: string;
  pricingRevision: string; pricingSha256: string; perAttemptInputTokens: number; perAttemptOutputTokens: number; bindingSha256: string; sha256: string;
}
export interface UsageScope { scope: 'task' | 'ancestor' | 'root' | 'user'; id: string; tokenLimit: number; amountMicrosLimit: number; settledTokens: number; settledAmountMicros: number; heldTokens: number; heldAmountMicros: number }
export interface UsageAttempt {
  id: string; runId: string; state: 'RESERVED' | 'UNKNOWN' | 'SETTLED'; streaming: boolean; provider: string; model: string; pricingRevision: string; commitmentSha256: string;
  reservedTokens: number; reservedAmountMicros: number; inputTokens?: number | null; outputTokens?: number | null; chargedAmountMicros?: number | null; usageEvidenceSha256?: string | null; createdAt: string; updatedAt: string;
}
export interface UsageLedger {
  schema: 1; ownerId: string; taskId: string; rootTaskId: string; currency: string; commitment: UsageCommitment; scopes: UsageScope[]; attempts: UsageAttempt[];
  pricingBasis?: 'operator-nominal-not-invoice'; invoiceVerified?: false; actualCostStatus?: 'UNKNOWN';
  zeroTariff: boolean; hasUnknown: boolean; migration: Record<string, unknown> | null;
}
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === 'string' && value.length > 0 && value.length <= 256 && !Array.from(value).some(character => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127);
const hash = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const integer = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
export type UsageLedgerState = { kind: 'missing' } | { kind: 'invalid' } | { kind: 'verified'; ledger: UsageLedger };
export function usageCommitment(value: unknown): UsageCommitment | undefined {
  if (!record(value) || value.schema !== 1 || typeof value.currency !== 'string' || !/^[A-Z]{3}$/.test(value.currency)
      || !['provider', 'model', 'adapterId', 'adapterRevision', 'pricingRevision'].every(key => text(value[key]))
      || !['pricingSha256', 'bindingSha256', 'sha256'].every(key => hash(value[key]))
      || !['amountMicros', 'tokenLimit', 'perAttemptInputTokens', 'perAttemptOutputTokens'].every(key => integer(value[key]))) return undefined;
  return value as unknown as UsageCommitment;
}

export function usageLedgerState(detail: JobDetail): UsageLedgerState {
  const value = detail.usageLedger;
  if (value === undefined || value === null) return { kind: 'missing' };
  if (!record(value) || value.schema !== 1 || value.ownerId !== detail.job.ownerId || value.taskId !== detail.job.id || !text(value.rootTaskId)
      || typeof value.currency !== 'string' || !/^[A-Z]{3}$/.test(value.currency) || !record(value.commitment) || !Array.isArray(value.scopes) || !Array.isArray(value.attempts)
      || typeof value.zeroTariff !== 'boolean' || typeof value.hasUnknown !== 'boolean' || !(value.migration === null || record(value.migration))) return { kind: 'invalid' };
  const pricingFields = ['pricingBasis', 'invoiceVerified', 'actualCostStatus'];
  if (pricingFields.some(key => Object.prototype.hasOwnProperty.call(value, key))
      && !(value.pricingBasis === 'operator-nominal-not-invoice' && value.invoiceVerified === false
        && value.actualCostStatus === 'UNKNOWN')) return { kind: 'invalid' };
  const c = value.commitment;
  if (c.schema !== 1 || c.currency !== value.currency || !['provider', 'model', 'adapterId', 'adapterRevision', 'pricingRevision'].every(key => text(c[key]))
      || !['pricingSha256', 'bindingSha256', 'sha256'].every(key => hash(c[key])) || !['amountMicros', 'tokenLimit', 'perAttemptInputTokens', 'perAttemptOutputTokens'].every(key => integer(c[key]))) return { kind: 'invalid' };
  const scopeKeys = new Set<string>();
  for (const s of value.scopes) {
    if (!record(s) || !['task', 'ancestor', 'root', 'user'].includes(String(s.scope)) || !text(s.id)
        || !['tokenLimit', 'amountMicrosLimit', 'settledTokens', 'settledAmountMicros', 'heldTokens', 'heldAmountMicros'].every(key => integer(s[key]))) return { kind: 'invalid' };
    const key = `${s.scope}:${s.id}`; if (scopeKeys.has(key)) return { kind: 'invalid' }; scopeKeys.add(key);
  }
  if (!scopeKeys.has(`task:${value.taskId}`) || !(value.rootTaskId === value.taskId ? scopeKeys.has(`task:${value.rootTaskId}`) : scopeKeys.has(`root:${value.rootTaskId}`)) || !scopeKeys.has(`user:${value.ownerId}`)) return { kind: 'invalid' };
  const attempts = new Set<string>();
  for (const a of value.attempts) {
    if (!record(a) || !text(a.id) || attempts.has(a.id) || !text(a.runId) || !['RESERVED', 'UNKNOWN', 'SETTLED'].includes(String(a.state)) || typeof a.streaming !== 'boolean'
        || a.provider !== c.provider || a.model !== c.model || a.pricingRevision !== c.pricingRevision || a.commitmentSha256 !== c.sha256
        || !integer(a.reservedTokens) || !integer(a.reservedAmountMicros) || !text(a.createdAt) || !text(a.updatedAt)) return { kind: 'invalid' };
    attempts.add(a.id);
    if (a.state === 'SETTLED' && (!integer(a.inputTokens) || !integer(a.outputTokens) || !integer(a.chargedAmountMicros) || !hash(a.usageEvidenceSha256))) return { kind: 'invalid' };
  }
  if (value.hasUnknown !== value.attempts.some(a => record(a) && ['RESERVED', 'UNKNOWN'].includes(String(a.state)))) return { kind: 'invalid' };
  return { kind: 'verified', ledger: value as unknown as UsageLedger };
}
export function currencyMicros(value: number, currency: string): string {
  if (!integer(value) || !/^[A-Z]{3}$/.test(currency)) return '未提供';
  const whole = Math.floor(value / 1_000_000); const fraction = String(value % 1_000_000).padStart(6, '0');
  return `${currency} ${whole.toLocaleString('zh-CN')}.${fraction}`;
}

export function ledgerBudgetAmount(value: number, ledger: UsageLedger): string {
  if (ledger.pricingBasis !== 'operator-nominal-not-invoice') return currencyMicros(value, ledger.currency);
  if (!integer(value)) return '未提供';
  return `名义预算单位 ${Math.floor(value / 1_000_000).toLocaleString('zh-CN')}.${String(value % 1_000_000).padStart(6, '0')}`;
}
