import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../web/api.js';
import { WorkflowPanel, WorkflowStages } from '../web/WorkflowPanel.js';
import { currentWorkflowAfterReceipt, sameWorkflowLineage, workflowCommand, workflowCommandReceipt, workflowCommandSettled, workflowPointer, workflowSnapshot, workflowView, WorkflowResponses, type WorkflowSnapshot } from '../web/workflowState.js';

function fixture(): WorkflowSnapshot {
  return { schema: 2, id: 'native-workflow', ownerId: 'alice', taskId: 'task-one', nativeRunId: 'native-one',
    planId: 'plan-one', planSha256: 'a'.repeat(64), version: 'b'.repeat(64), status: 'completed',
    steps: [{ id: 'prepare', name: '准备资料', status: 'completed' }, { id: 'review', name: '人工审核', status: 'paused' }],
    requirements: [{ id: 'original-requirement', stepName: '人工审核', kind: 'confirmation' }],
    operations: [{ id: 'original-operation', stepId: 'prepare', state: 'UNKNOWN', allStopped: false }] };
}
afterEach(() => vi.unstubAllGlobals());
describe('native workflow projection and original commands', () => {
  it('shows native completion separately from physical stop without reconstructing a DAG', () => {
    const raw = fixture(); const value = workflowSnapshot(raw, 'alice', 'task-one'); raw.operations[0].allStopped = true;
    const html = renderToStaticMarkup(createElement(WorkflowStages, { workflow: value }));
    expect(html).toContain('已完成'); expect(html).toContain('等待确认'); expect(html).toContain('尚未确认停止');
    expect(html).toContain('原生运行结束不代表外部操作已停止'); expect(html).not.toContain('100%');
    expect(html).not.toContain('失败处理路径'); expect(value.operations[0].allStopped).toBe(false);
  });
  it('rejects foreign identity, invalid digests and duplicate native records', () => {
    expect(() => workflowSnapshot(fixture(), 'bob', 'task-one')).toThrow();
    expect(() => workflowSnapshot(fixture(), 'alice', 'other')).toThrow();
    for (const changed of [{ ...fixture(), schema: 1 }, { ...fixture(), version: 3 },
      { ...fixture(), operations: [{ id: 'op', stepId: 'prepare', state: 'RUNNING', allStopped: 'yes' }] },
      { ...fixture(), operations: [fixture().operations[0], fixture().operations[0]] }])
      expect(() => workflowSnapshot(changed, 'alice', 'task-one')).toThrow();
    expect(workflowSnapshot({ ...fixture(), steps: [fixture().steps[0], fixture().steps[0]] }, 'alice', 'task-one').steps).toHaveLength(2);
    // Native statuses are projections, not an invented finite-state engine.
    expect(workflowSnapshot({ ...fixture(), status: 'future-native-status' }, 'alice', 'task-one').status).toBe('future-native-status');
  });
  it('accepts only server actions bound to projected requirement or operation identities', () => {
    const raw = { available: true, workflow: fixture(), allowedActions: [
      { action: 'decide', requirementId: 'original-requirement' }, { action: 'reconcile', operationId: 'original-operation' }, { action: 'cancel' }] };
    expect(workflowView(raw, 'alice', 'task-one')).toMatchObject({ allowedActions: raw.allowedActions });
    for (const action of [{ action: 'resume', stageId: 'prepare' }, { action: 'decide', requirementId: 'missing' },
      { action: 'reconcile', operationId: 'missing' }, { action: 'cancel', requirementId: 'original-requirement' }])
      expect(() => workflowView({ ...raw, allowedActions: [action] }, 'alice', 'task-one')).toThrow();
  });
  it('keeps opaque snapshot hashes unordered and never overwrites current GET with a receipt', () => {
    const current = fixture(); const receipt = { ...fixture(), version: 'f'.repeat(64), status: 'running' };
    expect(sameWorkflowLineage(current, receipt)).toBe(true);
    expect(currentWorkflowAfterReceipt(current, receipt)).toBe(current);
    expect(() => currentWorkflowAfterReceipt(current, { ...receipt, nativeRunId: 'replacement' })).toThrow();
    expect(currentWorkflowAfterReceipt(undefined, receipt)).toBe(receipt);
  });
  it('preserves exact decision/input pointers and rejects legacy stage/resume commands', () => {
    const command = { commandId: 'command-one', action: 'decide' as const, requirementId: 'original-requirement', version: 'b'.repeat(64), approved: false };
    expect(workflowPointer(JSON.stringify(command))).toEqual(command);
    expect(workflowCommand({ ...command, approved: undefined, values: { answer: false } }).values).toEqual({ answer: false });
    for (const changed of [{ ...command, version: 4 }, { ...command, stageId: 'review' }, { ...command, action: 'resume' },
      { ...command, values: {} }, { ...command, approved: 'false' }, { commandId: 'cancel-one', action: 'cancel', version: command.version }])
      expect(() => workflowCommand(changed)).toThrow();
    expect(workflowPointer(JSON.stringify({ ...command, secret: 'not allowed' }))).toBeUndefined();
    expect(workflowCommandReceipt({ commandId: command.commandId, status: 'unknown' }, 'alice', 'task-one', command)).toEqual({ status: 'unknown' });
    expect(workflowCommandSettled('recorded')).toBe(false); expect(workflowCommandSettled('unknown')).toBe(false);
    expect(workflowCommandSettled('rejected')).toBe(true); expect(workflowCommandSettled('completed')).toBe(true);
    expect(() => workflowCommandReceipt({ commandId: 'different', status: 'completed' }, 'alice', 'task-one', command)).toThrow();
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
