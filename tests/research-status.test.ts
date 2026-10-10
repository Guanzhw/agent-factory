import { expect, it } from 'vitest';
import { researchStatus, type ResearchStatusInput } from '../web/researchStatus.js';
import type { PersonalSession, PersonalMessage } from '../web/personalAgentApi.js';

const reply: PersonalMessage = { id: 'old-reply', role: 'assistant', completed: true, events: [{ type: 'text', text: 'Earlier reply' }], usageProvenance: 'unavailable' };
const session = (state: string, messages = [reply], activeRequestId?: string) => ({ state, activeRequestId, observation: { messages } } as PersonalSession);
const input: ResearchStatusInput = { ready: true, submitting: false, commandPending: false, attachmentPending: false, connectionUnavailable: false, canRun: true };
it('keeps an unknown request above its active pointer and an earlier completed reply', () => {
  const result = researchStatus({ ...input, session: session('ack_unknown', [reply], 'current-request') });
  expect(result.title).toBe('研究请求待核对'); expect(result.tone).toBe('unknown');
  expect(researchStatus({ ...input, commandPending: true, session: session('result_observed') }).tone).toBe('unknown');
});
it('retains creation uncertainty above retained replies and connection recovery', () => {
  const result = researchStatus({ ...input, session: session('create_ack_unknown'), connectionUnavailable: true });
  expect(result.title).toBe('研究会话创建待核对'); expect(result.tone).toBe('unknown');
  expect(result.explanation).toContain('不会重建会话或发送目标');
});
it('does not count a tool record or an unfinished message as a completed readable reply', () => {
  const tools: PersonalMessage = { ...reply, events: [{ type: 'tool', tool: 'python', status: 'completed', output: 'synthetic' }] };
  expect(researchStatus({ ...input, session: session('result_observed', [tools]) }).title).toBe('已观察到工具记录');
  expect(researchStatus({ ...input, session: session('result_observed', [{ ...reply, events: [] }]) }).title).toBe('等待远端回复');
  expect(researchStatus({ ...input, session: session('result_observed', [{ ...reply, completed: false }]) }).title).toBe('回复正在更新');
  expect(researchStatus({ ...input, session: session('result_observed') }).title).toBe('已观察到回复');
});
it('keeps a connection failure and an active round above a retained completed reply', () => {
  expect(researchStatus({ ...input, session: session('result_observed'), connectionUnavailable: true }).tone).toBe('unavailable');
  expect(researchStatus({ ...input, session: session('pending', [reply], 'current-request') }).title).toBe('等待远端回复');
});
it('distinguishes attachment recovery and first setup from research submission', () => {
  expect(researchStatus({ ...input, attachmentPending: true }).title).toBe('会话关联待核对');
  expect(researchStatus({ ...input, canRun: false }).title).toBe('首次设置待完成');
  expect(researchStatus({ ...input, submitting: true, commandPending: true }).title).toBe('正在提交研究目标');
});
it('surfaces a completed native tool error without exposing its output or claiming process stop', () => {
  const failed: PersonalMessage = { ...reply, events: [{ type: 'tool', tool: 'error', status: 'completed', output: 'private-provider-token STOPPED' }] };
  const result = researchStatus({ ...input, session: session('ready', [failed], 'current-request') });
  expect(result.title).toBe('原生研究回复出现错误'); expect(result.tone).toBe('failed');
  expect(result.explanation).toContain('请刷新核对原会话'); expect(result.explanation).toContain('不能据此认定远端进程已停止'); expect(result.explanation).not.toContain('private-provider-token');
  expect(researchStatus({ ...input, session: session('ready', [{ ...failed, completed: false }], 'current-request') }).tone).toBe('waiting');
  expect(researchStatus({ ...input, session: session('ready', [failed, { ...reply, role: 'user' }], 'new-request') }).tone).toBe('waiting');
  expect(researchStatus({ ...input, commandPending: true, session: session('ready', [failed], 'current-request') }).tone).toBe('unknown');
});
