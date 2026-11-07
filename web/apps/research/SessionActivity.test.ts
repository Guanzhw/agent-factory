import { expect, it } from 'vitest';
import { activitySummary, hasUnconfirmedOperation } from './SessionActivity.js';
import type { SessionTurn } from './researchSessionsClient.js';
const turn: SessionTurn = { id: 't', sequence: 1, requestId: 'r', taskId: 'task', runId: 'run', status: 'running', createdAt: '2026-11-07T00:00:00Z', completedAt: null, result: null, failure: null, messages: [], events: [], toolResults: [] };
it('does not invent an action before events arrive', () => {
  expect(activitySummary(turn)).toBe('请求已提交，等待执行记录');
});
it('describes the latest recorded action, not an invented live model thought', () => {
  const event = { id: 2, jobId: 'task', type: 'research_tool_started', message: '', createdAt: turn.createdAt, data: { toolName: 'research_read_file', callId: 'c' } };
  expect(activitySummary({ ...turn, events: [event] })).toBe('已开始读取文件');
  expect(activitySummary({ ...turn, events: [{ ...event, type: 'research_tool_finished', data: { ...event.data, outcome: 'unknown' } }] })).toContain('需要核对');
});
it('does not describe a stale tool start as active after a turn stops', () => {
  expect(activitySummary({ ...turn, status: 'cancelled', events: [{ id: 1, jobId: 'task', type: 'research_tool_started', message: '', data: { toolName: 'research_run' }, createdAt: turn.createdAt }] })).toBe('本轮已停止');
});

it('does not confuse an active reserved effect with an unconfirmed stopped operation', () => {
  const active = { ...turn, toolResults: [{ effectKey: 'command', status: 'UNKNOWN', result: null }] };
  expect(hasUnconfirmedOperation(active)).toBe(false);
  expect(hasUnconfirmedOperation({ ...active, status: 'unknown' })).toBe(true);
  expect(hasUnconfirmedOperation({ ...active, events: [{ id: 1, jobId: 'task', type: 'research_reconciliation_required', message: '', createdAt: turn.createdAt, data: {} }] })).toBe(true);
});
