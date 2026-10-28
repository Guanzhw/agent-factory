// @vitest-environment happy-dom
import { act, createElement, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError } from '../../api.js';
import { ResearchSessions } from './ResearchSessions.js';
import { researchSessionsApi as api, type ResearchSession, type SessionOptions } from './researchSessionsClient.js';
import { clearSessionDrafts, draftKey, requestKey } from './researchSessionStorage.js';

const options: SessionOptions = { available: true, unavailableCode: null, models: [{ connectionRef: 'model-a', provider: 'configured', model: 'research-model', available: true }], limits: { maxTurns: { min: 1, max: 20, default: 8 }, toolCallsPerTurn: { min: 1, max: 12, default: 8 }, operationSeconds: { min: 1, max: 120, default: 60 }, contextCharacters: 12000 }, workspace: { configured: true, hostCommands: true, isolation: 'host-user-not-os-sandbox' }, accounting: { tokenMetered: false, costMetered: false } };
const session: ResearchSession = { id: 'session-a', assistantId: 'assistant-a', title: '保留研究目标', goal: '检查测试程序', boundaries: '测试通过后停止', createdAt: '2026-10-28T08:00:00Z', updatedAt: '2026-10-28T08:00:00Z', state: 'idle', model: { connectionRef: 'model-a', provider: 'configured', model: 'research-model' }, limits: { maxTurns: 8, toolCallsPerTurn: 8, operationSeconds: 60 }, context: { characters: 15, maximumCharacters: 12000 }, allowedActions: ['start'], blockReason: null, sharedSourceIds: [], turns: [] };
let host: HTMLDivElement; let root: Root; let current: ResearchSession;
const models = vi.fn(); const task = vi.fn();
function Harness({ owner = 'alice', initial = '' }: { owner?: string; initial?: string }) {
  const [selected, setSelected] = useState(initial);
  return createElement(ResearchSessions, { ownerId: owner, selectedId: selected, onSelect: setSelected, onModels: models, onTask: task });
}
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); window.sessionStorage.clear(); current = structuredClone(session);
  host = document.createElement('div'); document.body.append(host); root = createRoot(host); models.mockReset(); task.mockReset();
  vi.spyOn(api, 'options').mockResolvedValue(options); vi.spyOn(api, 'list').mockResolvedValue({ items: [], nextCursor: null });
  vi.spyOn(api, 'get').mockImplementation(async () => current);
  vi.spyOn(api, 'create').mockImplementation(async () => current);
  vi.spyOn(api, 'turn').mockImplementation(async () => current);
  vi.spyOn(api, 'correct').mockImplementation(async () => current);
  vi.spyOn(api, 'stop').mockImplementation(async () => current);
  vi.spyOn(api, 'request').mockImplementation(async (_owner, requestId) => ({ requestId, action: 'turn', sessionId: current.id, turnId: 'turn-a', session: current, createsExecution: false, automaticReplay: false }));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
async function mount(initial = '', owner = 'alice') { await act(async () => root.render(createElement(Harness, { key: owner, owner, initial }))); }
const button = (label: string) => [...host.querySelectorAll('button')].find(item => item.textContent === label)!;
async function field(label: string, value: string) {
  const wrapper = [...host.querySelectorAll('label')].find(item => item.firstChild?.textContent === label)!;
  const input = wrapper.querySelector('input,textarea,select')!;
  const prototype = input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : input.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  await act(async () => { Object.getOwnPropertyDescriptor(prototype, 'value')!.set!.call(input, value); input.dispatchEvent(new Event(input.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true })); });
}
async function validDraft() { await field('会话名称', '保留研究目标'); await field('研究目标', '检查测试程序'); await field('停止边界', '测试通过后停止'); }

it('validates beside fields and keeps drafts through resource navigation and remount without creating a session', async () => {
  await mount(); await act(async () => button('创建并开始研究').click());
  expect(host.querySelectorAll('label [role="alert"]')).toHaveLength(3); expect(api.create).not.toHaveBeenCalled();
  await validDraft(); await act(async () => button('配置我的模型').click()); expect(models).toHaveBeenCalledOnce();
  await act(async () => root.unmount()); root = createRoot(host); await mount();
  expect((host.querySelector('textarea') as HTMLTextAreaElement).value).toBe('检查测试程序'); expect(api.turn).not.toHaveBeenCalled();
  await mount('', 'bob'); expect((host.querySelector('textarea') as HTMLTextAreaElement).value).toBe('');
});

it('creates once on double click and retains the created session when the first turn reply is lost', async () => {
  let resolveCreate!: (value: ResearchSession) => void;
  vi.mocked(api.create).mockReturnValue(new Promise(resolve => { resolveCreate = resolve; }));
  vi.mocked(api.turn).mockRejectedValue(new ApiError('首轮响应丢失', 408));
  await mount(); await validDraft();
  await act(async () => { button('创建并开始研究').click(); button('创建并开始研究')?.click(); });
  expect(api.create).toHaveBeenCalledOnce();
  await act(async () => resolveCreate(current));
  expect(api.turn).toHaveBeenCalledOnce(); expect(host.textContent).toContain('会话已创建，第一轮未确认'); expect(host.textContent).toContain('首轮响应丢失');
  expect(host.textContent).toContain('会话已创建，尚无执行轮次'); expect(button('开始这一轮').closest('fieldset')?.disabled).toBe(true);
  const createId = vi.mocked(api.create).mock.calls[0][1].requestId;
  const turnId = vi.mocked(api.turn).mock.calls[0][2].requestId; expect(turnId).not.toBe(createId);
  await act(async () => button('查询原请求').click());
  expect(api.request).toHaveBeenCalledWith('alice', turnId); expect(api.turn).toHaveBeenCalledOnce();
  expect(host.textContent).toContain('没有重新发送，也没有自动开始下一轮'); expect(button('开始这一轮').closest('fieldset')?.disabled).toBe(false);
});

it('treats a missing original receipt as uncertain and never posts on reopen or refresh', async () => {
  window.sessionStorage.setItem(requestKey('alice'), JSON.stringify([{ requestId: 'original-id', action: 'turn', sessionId: session.id }]));
  vi.mocked(api.request).mockRejectedValue(new ApiError('尚未找到原请求回执，请继续核对；不会自动重发。', 404, 'RESEARCH_SESSION_REQUEST_NOT_FOUND'));
  await mount(session.id); expect(api.turn).not.toHaveBeenCalled(); expect(button('开始这一轮').closest('fieldset')?.disabled).toBe(true);
  await act(async () => button('查询原请求').click()); await act(async () => button('刷新会话').click());
  expect(api.turn).not.toHaveBeenCalled(); expect(api.create).not.toHaveBeenCalled(); expect(host.textContent).toContain('尚未找到原请求回执');
  expect(window.sessionStorage.getItem(requestKey('alice'))).toContain('original-id');
});

it('sends a running supplement as a correction and distinguishes stored pending text from inclusion', async () => {
  current = { ...current, state: 'running', allowedActions: ['correct', 'stop'], turns: [{ id: 'turn-a', sequence: 1, requestId: 'start-id', taskId: 'task-a', runId: null, status: 'running', createdAt: session.createdAt, completedAt: null, result: null, failure: null, messages: [], events: [], toolResults: [] }] };
  vi.mocked(api.correct).mockImplementation(async (_owner, _id, body) => {
    current = { ...current, turns: [{ ...current.turns[0], messages: [{ id: 'correction-a', kind: 'correction', text: body.text, state: 'pending', createdAt: session.createdAt, includedAt: null }] }] }; return current;
  });
  await mount(session.id); await field('补充或纠正当前研究', '不要修改原始数据'); await act(async () => button('保存纠正').click());
  expect(api.correct).toHaveBeenCalledWith('alice', session.id, expect.objectContaining({ text: '不要修改原始数据' })); expect(api.turn).not.toHaveBeenCalled();
  expect(host.textContent).toContain('待纳入模型请求'); expect(host.textContent).not.toContain('已纳入模型请求');
  current = { ...current, turns: [{ ...current.turns[0], messages: [{ ...current.turns[0].messages[0], state: 'included', includedAt: session.createdAt }] }] };
  await act(async () => button('刷新会话').click()); expect(host.textContent).toContain('已纳入模型请求'); expect(host.textContent).not.toContain('模型已遵守');
});

it('starts a new turn after completion even when the service also permits stored corrections', async () => {
  current = { ...current, allowedActions: ['start', 'correct', 'stop'] };
  await mount(session.id); expect(button('保存纠正')).toBeUndefined();
  await field('下一轮指令', '沿用原边界，检查另一组结果'); await act(async () => button('开始这一轮').click());
  expect(api.turn).toHaveBeenCalledWith('alice', session.id, expect.objectContaining({ text: '沿用原边界，检查另一组结果' }));
  expect(api.correct).not.toHaveBeenCalled();
});

it('shows stop pending separately from confirmation and keeps UNKNOWN original operation visible', async () => {
  current = { ...current, state: 'running', allowedActions: ['correct', 'stop'] };
  vi.mocked(api.stop).mockImplementation(async () => { current = { ...current, state: 'stopping', allowedActions: [] }; return current; });
  await mount(session.id); await act(async () => button('请求停止').click());
  expect(host.textContent).toContain('目前不能确认已停止'); expect(api.stop).toHaveBeenCalledOnce();
  current = { ...current, state: 'blocked', blockReason: 'RESEARCH_EFFECT_UNKNOWN', turns: [{ id: 'turn-a', sequence: 1, requestId: 'start-id', taskId: 'task-a', runId: null, status: 'unknown', createdAt: session.createdAt, completedAt: null, result: null, failure: null, messages: [], events: [], toolResults: [{ effectKey: 'original-operation', status: 'UNKNOWN', result: null }] }] };
  await act(async () => button('刷新会话').click());
  expect(host.textContent).toContain('结果未知，需核对原操作'); expect(host.querySelector('.rs-tool-results details')?.hasAttribute('open')).toBe(true); expect(button('开始这一轮')).toBeUndefined();
  await act(async () => button('查看原任务记录').click()); expect(task).toHaveBeenCalledWith('task-a'); expect(api.turn).not.toHaveBeenCalled();
});

it('shows unavailable configuration honestly and clears private drafts on logout while retaining opaque recovery pointers', async () => {
  vi.mocked(api.options).mockResolvedValue({ ...options, available: false, unavailableCode: 'RESEARCH_WORKSPACE_NOT_CONFIGURED', models: [], workspace: { ...options.workspace, configured: false } });
  await mount(); expect(button('创建并开始研究').disabled).toBe(true); expect(host.textContent).toContain('服务尚未配置会话工作目录'); expect(button('配置我的模型')).toBeDefined();
  await field('研究目标', '私人研究输入');
  window.sessionStorage.setItem(requestKey('alice'), JSON.stringify([{ requestId: 'request-a', action: 'create', sessionId: null }]));
  clearSessionDrafts('alice'); expect(window.sessionStorage.getItem(draftKey('alice'))).toBeNull(); expect(window.sessionStorage.getItem(requestKey('alice'))).toContain('request-a');
});
