import { describe, expect, it } from 'vitest';
import { currencyMicros, usageLedgerState, type UsageLedger } from '../web/usageLedgerState.js';
import type { JobDetail } from '../web/models.js';
const hash = 'a'.repeat(64);
function ledger(): UsageLedger {
  return { schema: 1, ownerId: 'alice', taskId: 'task', rootTaskId: 'root', currency: 'USD', commitment: {
    schema: 1, currency: 'USD', amountMicros: 100, tokenLimit: 1000, provider: 'controlled', model: 'controlled-no-fee', adapterId: 'controlled-v1', adapterRevision: '1', pricingRevision: 'synthetic-zero-1', pricingSha256: hash, bindingSha256: hash, sha256: hash, perAttemptInputTokens: 10, perAttemptOutputTokens: 20,
  }, scopes: ['task', 'root', 'user'].map((scope, index) => ({ scope: scope as 'task' | 'root' | 'user', id: ['task', 'root', 'alice'][index], tokenLimit: 1000, amountMicrosLimit: 100, settledTokens: 30, settledAmountMicros: 0, heldTokens: 30, heldAmountMicros: 0 })), attempts: [{ id: 'attempt-1', runId: 'run-1', state: 'UNKNOWN', streaming: true, provider: 'controlled', model: 'controlled-no-fee', pricingRevision: 'synthetic-zero-1', commitmentSha256: hash, reservedTokens: 30, reservedAmountMicros: 0, createdAt: '2026-10-02T00:00:00Z', updatedAt: '2026-10-02T00:00:00Z' }], zeroTariff: true, hasUnknown: true, migration: null };
}
function detail(value?: unknown): JobDetail { return { job: { id: 'task', ownerId: 'alice' }, events: [], artifacts: [], ...(value === undefined ? {} : { usageLedger: value }) } as unknown as JobDetail; }
describe('durable usage ledger projection', () => {
  it('keeps unknown reservations as actual held facts instead of treating zero tariff as zero tokens', () => {
    const state = usageLedgerState(detail(ledger())); expect(state.kind).toBe('verified');
    if (state.kind === 'verified') { expect(state.ledger.hasUnknown).toBe(true); expect(state.ledger.scopes[0].heldTokens).toBe(30); }
    expect(usageLedgerState(detail()).kind).toBe('missing');
    const root = ledger(); root.rootTaskId = root.taskId; root.scopes = root.scopes.filter(scope => scope.scope !== 'root'); root.attempts[0].state = 'RESERVED'; expect(usageLedgerState(detail(root)).kind).toBe('verified');
  });
  it('rejects foreign scope, changed approved pricing/model, missing commitment', () => {
    const fixtures: UsageLedger[] = [ledger(), ledger(), ledger(), ledger()];
    fixtures[0].ownerId = 'bob'; fixtures[1].attempts[0].model = 'new-model'; fixtures[2].attempts[0].pricingRevision = 'new-rate'; fixtures[3].attempts[0].commitmentSha256 = 'b'.repeat(64);
    for (const value of fixtures) expect(usageLedgerState(detail(value)).kind).toBe('invalid');
  });
  it('retains authoritative charged overage instead of hiding actual billing facts', () => {
    const value = ledger(); value.scopes[0].settledTokens = 1001; value.scopes[0].settledAmountMicros = 101;
    expect(usageLedgerState(detail(value)).kind).toBe('verified');
  });
  it('requires authoritative settlement and retains every repeated or streaming attempt independently', () => {
    const value = ledger(); value.hasUnknown = false; value.attempts[0].state = 'SETTLED';
    expect(usageLedgerState(detail(value)).kind).toBe('invalid');
    Object.assign(value.attempts[0], { inputTokens: 5, outputTokens: 10, chargedAmountMicros: 0, usageEvidenceSha256: hash });
    value.attempts.push({ ...value.attempts[0], id: 'attempt-2', streaming: false });
    expect(usageLedgerState(detail(value)).kind).toBe('verified');
    value.attempts[1].id = 'attempt-1'; expect(usageLedgerState(detail(value)).kind).toBe('invalid');
  });
  it('does not erase unknown usage by a false projection flag or accept duplicate shared scopes', () => {
    const value = ledger(); value.hasUnknown = false; expect(usageLedgerState(detail(value)).kind).toBe('invalid');
    value.hasUnknown = true; value.scopes.push({ ...value.scopes[0] }); expect(usageLedgerState(detail(value)).kind).toBe('invalid');
  });
  it('formats micros without rounding away small reservations or inventing currency', () => {
    expect(currencyMicros(1, 'USD')).toBe('USD 0.000001'); expect(currencyMicros(1000001, 'USD')).toBe('USD 1.000001');
    expect(currencyMicros(-1, 'USD')).toBe('未提供'); expect(currencyMicros(0, 'unknown')).toBe('未提供');
  });
});
