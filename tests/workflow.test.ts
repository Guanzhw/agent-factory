import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../web/api.js';
import { WorkflowPanel, WorkflowStages } from '../web/WorkflowPanel.js';
import { currentWorkflowAfterReceipt, sameWorkflowLineage, workflowCommand, workflowCommandReceipt, workflowCommandSettled, workflowPointer, workflowSnapshot, workflowView, WorkflowResponses, type WorkflowSnapshot } from '../web/workflowState.js';

function fixture(): WorkflowSnapshot {
  const handle = { adapterId: 'controlled', revision: 'v1', id: 'original-handle' };
  return { schema: 1, id: 'workflow-one', ownerId: 'alice', taskId: 'task-one', nativeRunId: 'native-one', planId: 'plan-one', planSha256: 'a'.repeat(64), definitionSha256: 'b'.repeat(64), version: 4, status: 'ACTIVE', cancelRequested: false,
    definition: { id: 'controlled-flow', revision: 'v1', stages: [
      { id: 'prepare', adapterId: 'controlled', revision: 'v1', dependencies: [], failureRoutes: { INVALID: 'review' }, humanGate: false },
      { id: 'review', adapterId: 'controlled', revision: 'v1', dependencies: ['prepare'], failureRoutes: {}, humanGate: true },
    ] }, stages: {
      prepare: { state: 'FAILED', operationId: 'original-operation', handle, approved: true, observation: { operationId: 'original-operation', handle, state: 'FAILED', allStopped: true, failure: { code: 'INVALID', messageCode: 'CONTROLLED_FAILURE', retryable: false } } },
      review: { state: 'HUMAN_WAIT', operationId: null, handle: null, observation: null, approved: false },
    } };
}
afterEach(() => vi.unstubAllGlobals());
describe('owner-bound workflow projection and commands', () => {
  it('renders actual waits, structured failure route and stop proof without fabricated progress or raw output', () => {
    const raw = fixture(); const value = workflowSnapshot(raw, 'alice', 'task-one'); raw.stages.prepare.state = 'COMPLETED';
    const html = renderToStaticMarkup(createElement(WorkflowStages, { workflow: value }));
    expect(html).toContain('执行失败'); expect(html).toContain('等待人工决定'); expect(html).toContain('INVALID'); expect(html).toContain('匹配本次失败'); expect(html).toContain('本阶段执行已确认停止');
    expect(html).not.toContain('100%'); expect(html).not.toContain('original-handle'); expect(html).not.toContain('alice');
    expect(value.stages.prepare.state).toBe('FAILED');
  });
  it('rejects foreign owner/task, mismatched operation or handle, invalid proof and unsupported states', () => {
    expect(() => workflowSnapshot(fixture(), 'bob', 'task-one')).toThrow();
    expect(() => workflowSnapshot(fixture(), 'alice', 'other-task')).toThrow();
    for (const edit of [(x: WorkflowSnapshot) => { x.stages.prepare.observation!.operationId = 'other'; }, (x: WorkflowSnapshot) => { x.stages.prepare.observation!.allStopped = false; }, (x: WorkflowSnapshot) => { x.stages.prepare.handle!.adapterId = 'other'; }, (x: WorkflowSnapshot) => { x.version = -1; }]) {
      const raw = fixture(); edit(raw); expect(() => workflowSnapshot(raw, 'alice', 'task-one')).toThrow();
    }
    const raw = fixture(); expect(() => workflowSnapshot({ ...raw, stages: { ...raw.stages, extra: raw.stages.prepare } }, 'alice', 'task-one')).toThrow();
  });
  it('accepts only server-projected stage actions and never grants resume to a failed original stage', () => {
    const raw = { available: true, workflow: fixture(), allowedActions: [{ action: 'decide', stageId: 'review' }, { action: 'reconcile', stageId: 'prepare' }] };
    expect(workflowView(raw, 'alice', 'task-one')).toMatchObject({ allowedActions: raw.allowedActions });
    for (const action of [{ action: 'resume', stageId: 'prepare' }, { action: 'decide', stageId: 'missing' }, { action: 'start' }, { action: 'resume' }]) expect(() => workflowView({ ...raw, allowedActions: [action] }, 'alice', 'task-one')).toThrow();
    expect(workflowView({ available: false }, 'alice', 'task-one')).toEqual({ available: false });
  });
  it('keeps original run/plan/operation identities and rejects stale or replaced snapshots', () => {
    const original = fixture(); const next = fixture(); next.version++;
    expect(sameWorkflowLineage(original, next)).toBe(true);
    for (const edit of [(x: WorkflowSnapshot) => { x.version--; }, (x: WorkflowSnapshot) => { x.nativeRunId = 'other'; }, (x: WorkflowSnapshot) => { x.planSha256 = 'c'.repeat(64); }, (x: WorkflowSnapshot) => { x.stages.prepare.operationId = 'replacement'; }]) {
      const changed = fixture(); edit(changed); expect(sameWorkflowLineage(original, changed)).toBe(false);
    }
  });
  it('preserves exact bounded decision pointer and distinguishes unknown receipt from completion', () => {
    const command = { commandId: 'command-one', action: 'decide' as const, stageId: 'review', version: 4, approved: false };
    expect(workflowPointer(JSON.stringify(command))).toEqual(command);
    expect(workflowPointer(JSON.stringify({ ...command, version: undefined }))).toBeUndefined();
    expect(workflowPointer(JSON.stringify({ ...command, secret: 'not allowed' }))).toBeUndefined();
    expect(() => workflowCommand({ ...command, approved: 'false' })).toThrow();
    expect(workflowCommandReceipt({ commandId: command.commandId, status: 'unknown' }, 'alice', 'task-one', command)).toEqual({ status: 'unknown' });
    expect(workflowCommandReceipt({ commandId: command.commandId, status: 'recorded', workflow: fixture() }, 'alice', 'task-one', command).status).toBe('recorded');
    expect(workflowCommandSettled('recorded')).toBe(false); expect(workflowCommandSettled('unknown')).toBe(false);
    expect(workflowCommandSettled('rejected')).toBe(true); expect(workflowCommandSettled('completed')).toBe(true);
    expect(() => workflowCommand({ commandId: 'reconcile-one', action: 'reconcile' })).toThrow();
    expect(() => workflowCommand({ commandId: 'reconcile-one', action: 'reconcile', version: 4 })).toThrow();
    expect(workflowCommand({ commandId: 'reconcile-one', action: 'reconcile', stageId: 'prepare', version: 4 }).version).toBe(4);
    expect(() => workflowCommandReceipt({ commandId: 'different', status: 'completed', workflow: fixture() }, 'alice', 'task-one', command)).toThrow();
  });
  it('accepts an older same-lineage command receipt without regressing the current snapshot', () => {
    const current = fixture(); current.version = 6;
    expect(currentWorkflowAfterReceipt(current, fixture())).toBe(current);
    const replacement = fixture(); replacement.nativeRunId = 'different';
    expect(() => currentWorkflowAfterReceipt(current, replacement)).toThrow();
  });
  it('drops delayed reads and errors after a command or identity invalidation', async () => {
    const reads = new WorkflowResponses(); let resolve!: (value: string) => void;
    const old = reads.read(() => new Promise<string>(done => { resolve = done; })); reads.invalidate();
    expect(await reads.read(async () => 'new')).toBe('new'); resolve('old'); expect(await old).toBeUndefined();
    let reject!: (value: Error) => void;
    const staleError = reads.read(() => new Promise<never>((_, fail) => { reject = fail; })); reads.invalidate(); reject(new Error('stale')); expect(await staleError).toBeUndefined();
  });
  it('uses encoded authenticated endpoints and never automatically repeats an uncertain POST', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ available: false }))).mockRejectedValueOnce(new TypeError('offline'));
    vi.stubGlobal('fetch', fetch);
    expect(await api.workflows.get('task/one')).toEqual({ available: false });
    await expect(api.workflows.command('task/one', { commandId: 'original-command', action: 'cancel' })).rejects.toThrow();
    expect(fetch.mock.calls.map(call => [call[0], call[1].method])).toEqual([['/api/factory/workflows/task%2Fone', 'GET'], ['/api/factory/workflows/task%2Fone/commands', 'POST']]);
    expect(fetch.mock.calls[1][1]).toMatchObject({ credentials: 'same-origin', cache: 'no-store', redirect: 'error' });
  });
  it('reads an original command without posting, and preserves explicit not-recorded and conflict errors', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'WORKFLOW_COMMAND_NOT_FOUND' }), { status: 404 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'conflict' }), { status: 409 }));
    vi.stubGlobal('fetch', fetch);
    await expect(api.workflows.commandStatus('task/one', 'command:one')).rejects.toMatchObject({ status: 404 });
    await expect(api.workflows.command('task/one', { commandId: 'command:one', action: 'cancel' })).rejects.toMatchObject({ status: 409 });
    expect(fetch.mock.calls.map(call => call[1].method)).toEqual(['GET', 'POST']);
    expect(fetch.mock.calls[0][0]).toBe('/api/factory/workflows/task%2Fone/commands/command%3Aone');
  });
  it('renders no actions or invented progress before the first server projection', () => {
    const unavailable = async () => { throw new Error('not during render'); };
    const html = renderToStaticMarkup(createElement(WorkflowPanel, { ownerId: 'private-owner', taskId: 'private-task', api: { get: unavailable, commandStatus: unavailable, command: unavailable } }));
    expect(html).toContain('正在读取工作流记录'); expect(html).not.toContain('同意本阶段'); expect(html).not.toContain('private-owner'); expect(html).not.toContain('private-task');
  });
});
