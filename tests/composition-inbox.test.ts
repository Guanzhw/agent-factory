import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { CompositionInbox, CompositionInboxList } from '../web/CompositionInbox.js';
import { compositionInboxPage, CompositionInboxRequests } from '../web/compositionInboxState.js';

const proposalId = '11111111-1111-4111-8111-111111111111';
const planId = '22222222-2222-4222-8222-222222222222';
function fixture(owner = 'alice') {
  return { schema: 1, ownerId: owner, snapshot: false, nextCursor: null, items: [{
    id: proposalId, ownerId: owner, createdAt: '2026-10-04T12:00:00.123456+00:00', state: 'accepted',
    fingerprint: 'a'.repeat(64), parentId: null, planId: planId as string | null,
    applicationRef: { id: 'public-fixture', version: 1, sha256: 'b'.repeat(64) },
    mode: 'literature', goalPreview: '公开材料核对', preflightStatus: 'ready',
  }] };
}

describe('composition inbox read boundary', () => {
  it('checks original owner, immutable references and accepted plan link', () => {
    const value = fixture();
    const checked = compositionInboxPage(value, 'alice');
    expect(checked.items[0].planId).toBe(planId);
    value.items[0].goalPreview = 'changed';
    expect(checked.items[0].goalPreview).toBe('公开材料核对');
    expect(() => compositionInboxPage(fixture(), 'bob')).toThrow();
    const invalid = fixture(); invalid.items[0].planId = '';
    expect(() => compositionInboxPage(invalid, 'alice')).toThrow();
  });
  it('rejects malformed pages, owner mixing, duplicates and unbounded cursor/summary', () => {
    const base = fixture();
    for (const change of [{ schema: true }, { snapshot: true }, { nextCursor: '../foreign' }, { nextCursor: 'a'.repeat(2049) }, { items: [base.items[0], base.items[0]] }]) {
      expect(() => compositionInboxPage({ ...base, ...change }, 'alice')).toThrow();
    }
    for (const change of [{ ownerId: 'bob' }, { goalPreview: 'x'.repeat(161) }, { state: 'executed' },
      { createdAt: 'bad' }, { applicationRef: { ...base.items[0].applicationRef, version: 0 } }, { fingerprint: 'invalid' }]) {
      expect(() => compositionInboxPage({ ...base, items: [{ ...base.items[0], ...change }] }, 'alice')).toThrow();
    }
  });
  it('ignores late old-owner replies even if transport ignores cancellation', async () => {
    const requests = new CompositionInboxRequests();
    let resolve!: (value: unknown) => void;
    const old = requests.load('alice', undefined, () => new Promise(result => { resolve = result; }));
    const current = await requests.load('bob', undefined, async () => fixture('bob'));
    resolve(fixture());
    expect(await old).toBeUndefined();
    expect(current?.ownerId).toBe('bob');
  });
  it('aborted reads and stale failures cannot overwrite the last confirmed page', async () => {
    const requests = new CompositionInboxRequests();
    const controller = new AbortController();
    let reject!: (error: Error) => void;
    const stale = requests.load('alice', undefined, () => new Promise((_, fail) => { reject = fail; }), controller.signal);
    controller.abort(); requests.invalidate(); reject(new Error('synthetic old failure'));
    expect(await stale).toBeUndefined();
    const checked = await requests.load('alice', undefined, async () => fixture());
    await expect(requests.load('alice', undefined, async () => { throw new Error('offline'); })).rejects.toThrow('offline');
    expect(checked?.items[0].id).toBe(proposalId);
  });
  it('rejects a looping cursor and makes no extra read or mutation', async () => {
    const load = vi.fn().mockResolvedValue({ ...fixture(), nextCursor: 'same' });
    await expect(new CompositionInboxRequests().load('alice', 'same', load)).rejects.toThrow();
    expect(load).toHaveBeenCalledTimes(1);
  });
  it('renders historical recovery rather than accept/execute controls and escapes source text', () => {
    const value = fixture(); value.items[0].goalPreview = '<script>untrusted</script>';
    const select = vi.fn();
    const html = renderToStaticMarkup(createElement(CompositionInboxList, { page: compositionInboxPage(value, 'alice'), onSelect: select }));
    expect(html).toContain('查看原方案'); expect(html).toContain('已固定方案');
    expect(html).toContain('&lt;script&gt;'); expect(html).not.toContain('<script>');
    expect(html).not.toContain('确认方案并创建任务'); expect(select).not.toHaveBeenCalled();
    value.items[0].state = 'rejected'; value.items[0].planId = null;
    const rejected = renderToStaticMarkup(createElement(CompositionInboxList, { page: compositionInboxPage(value, 'alice'), onSelect: select }));
    expect(rejected).toContain('恢复此提案'); expect(rejected).toContain('已拒绝');
  });
  it('initial panel states its read-only scope and never loads or selects during server render', () => {
    const load = vi.fn(), select = vi.fn();
    const html = renderToStaticMarkup(createElement(CompositionInbox, { ownerId: 'alice', loadPage: load, onSelect: select }));
    expect(html).toContain('我的装配提案'); expect(html).toContain('查看记录不会接受提案、开始任务');
    expect(load).not.toHaveBeenCalled(); expect(select).not.toHaveBeenCalled();
  });
});
