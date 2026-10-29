// @vitest-environment happy-dom
import { act, createElement, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError } from '../../api.js';
import { ResearchSessions } from './ResearchSessions.js';
import { researchSessionsApi as api, type ResearchSession, type SessionOptions, type SessionTurn } from './researchSessionsClient.js';
import { clearSessionDrafts, draftKey, requestKey } from './researchSessionStorage.js';
import { assistantApi, type ResearchQuestion } from './live/assistantClient.js';

const options: SessionOptions = { available: true, unavailableCode: null, models: [{ connectionRef: 'model-a', provider: 'configured', model: 'research-model', available: true }], limits: { maxTurns: { min: 1, max: 20, default: 8 }, toolCallsPerTurn: { min: 1, max: 12, default: 8 }, operationSeconds: { min: 1, max: 120, default: 60 }, contextCharacters: 12000 }, workspace: { configured: true, hostCommands: true, isolation: 'host-user-not-os-sandbox' }, accounting: { tokenMetered: false, costMetered: false } };
const session: ResearchSession = { id: 'session-a', assistantId: 'assistant-a', title: '保留研究目标', goal: '检查测试程序', boundaries: '测试通过后停止', createdAt: '2026-10-28T08:00:00Z', updatedAt: '2026-10-28T08:00:00Z', state: 'idle', model: { connectionRef: 'model-a', provider: 'configured', model: 'research-model' }, limits: { maxTurns: 8, toolCallsPerTurn: 8, operationSeconds: 60 }, context: { characters: 15, maximumCharacters: 12000 }, allowedActions: ['start'], blockReason: null, sharedSourceIds: [], turns: [] };
const completedTurn: SessionTurn = { id: 'turn-a', sequence: 1, requestId: 'start-id', taskId: 'task-a', runId: 'run-a', status: 'completed', createdAt: session.createdAt, completedAt: session.updatedAt, result: '原始回复和证据仍可查。', failure: null, messages: [], events: [], toolResults: [] };
let host: HTMLDivElement; let root: Root; let current: ResearchSession;
const models = vi.fn(); const task = vi.fn();
function Harness({ owner = 'alice', initial = '' }: { owner?: string; initial?: string }) {
  const [selected, setSelected] = useState(initial);
  const [questionId, setQuestionId] = useState('');
  return createElement(ResearchSessions, { ownerId: owner, selectedId: selected, questionId, onQuestion: setQuestionId, onSelect: setSelected, onModels: models, onTask: task });
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
  vi.spyOn(api, 'questions').mockResolvedValue({ items: [], nextCursor: null });
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

it('keeps a temporary child result distinct from the main reply and opens only its original task', async () => {
  const child = { childTaskId: 'child-task-a', runId: 'child-run-a', goal: '检查解析器并报告回归测试', status: 'completed', result: 'parser.ts:24 的测试通过。' };
  current = { ...current, turns: [{ ...completedTurn, children: [child], events: [{ id: 1, jobId: 'task-a', type: 'research_tool_finished', message: '临时子助手返回结果', data: { toolName: 'research_wait_child', outcome: 'completed', output: child }, createdAt: session.updatedAt }] }] };
  await mount(session.id);
  const section = host.querySelector('[aria-label="第 1 轮临时子助手"]')!;
  expect(section.textContent).toContain(child.goal); expect(section.textContent).toContain('已完成');
  expect(section.textContent).toContain(child.result); expect(section.textContent).not.toContain(completedTurn.result);
  expect(section.querySelector('details')?.open).toBe(false);
  expect(host.querySelector('.rs-events > ol > li > strong')?.textContent).toBe('等待子助手结果');
  expect(host.querySelector('.rs-events > ol > li > p')?.textContent).toBe('临时子助手返回结果');
  expect(host.querySelector<HTMLDetailsElement>('.rs-events > ol > li > details')?.open).toBe(false);
  await act(async () => button('查看原子任务记录').click());
  expect(task).toHaveBeenCalledExactlyOnceWith('child-task-a');
  await act(async () => button('刷新会话').click());
  expect(api.turn).not.toHaveBeenCalled(); expect(api.create).not.toHaveBeenCalled(); expect(api.stop).not.toHaveBeenCalled();
});

it.each([
  ['pending', '待执行'], ['queued', '排队中'], ['running', '执行中'], ['paused', '已暂停，等待继续'],
  ['failed', '执行失败'], ['cancelled', '已停止'], ['canceled', '已停止'], ['canceling', '停止请求已接收，尚未确认停止'],
  ['unknown', '结果未知，请核对原子任务'], ['unrecognized', '结果未知，请核对原子任务'],
])('shows child state %s without treating an unconfirmed result as success', async (status, label) => {
  current = { ...current, turns: [{ ...completedTurn, result: null, children: [{ childTaskId: 'child-task-a', runId: null, goal: '检查原操作', status, result: '不能当作已确认结果' }] }] };
  await mount(session.id);
  const section = host.querySelector('[aria-label="第 1 轮临时子助手"]')!;
  expect(section.querySelector('[role="status"]')?.textContent).toBe(label);
  expect(section.textContent).not.toContain('不能当作已确认结果'); expect(section.textContent).not.toContain('已完成');
  expect(section.querySelectorAll('button')).toHaveLength(1);
  expect(api.turn).not.toHaveBeenCalled(); expect(api.stop).not.toHaveBeenCalled();
});

it('explains native child waiting without asking for approval and keeps the existing parent stop action', async () => {
  current = { ...current, state: 'running', allowedActions: ['correct', 'stop'], turns: [{ ...completedTurn, status: 'waiting_approval', result: null, children: [{ childTaskId: 'child-task-a', runId: 'child-run-a', goal: '运行完整测试', status: 'running', result: null }] }] };
  await mount(session.id);
  expect(host.querySelector('.rs-turn > header')?.textContent).toContain('等待子助手结果');
  expect(host.querySelector('.rs-turn > header')?.textContent).not.toContain('waiting_approval');
  expect(host.textContent).toContain('停止本会话也会请求停止子任务');
  await act(async () => button('请求停止').click());
  expect(api.stop).toHaveBeenCalledOnce(); expect(vi.mocked(api.stop).mock.calls[0].slice(0, 2)).toEqual(['alice', session.id]);
  expect(api.turn).not.toHaveBeenCalled();
});

it('does not invent children for existing turns or invent a result body for a completed child', async () => {
  current = { ...current, turns: [completedTurn] };
  await mount(session.id);
  expect(host.querySelector('[aria-label="第 1 轮临时子助手"]')).toBeNull();
  current = { ...current, turns: [{ ...completedTurn, children: [{ childTaskId: 'child-task-a', runId: 'child-run-a', goal: '核对测试', status: 'completed', result: null }] }] };
  await act(async () => button('刷新会话').click());
  const section = host.querySelector('[aria-label="第 1 轮临时子助手"]')!;
  expect(section.textContent).toContain('尚无已确认的结果正文'); expect(section.querySelector('.rs-child-result')).toBeNull();
});

it('renders main and child Markdown while preserving code and avoiding active HTML or remote images', async () => {
  const code = 'def result():\n    return "ok"\n';
  const result = '**修复完成**\n\n- 读过源码\n- 跑过测试\n\n```python\n' + code + '```\n\n![测试图片](https://example.invalid/tracker.png)\n\n<script>alert(1)</script>\n\n[危险链接](javascript:alert(1))';
  const goal = '检查测试并报告来源。\n保留所有原始文件。';
  current = { ...current, turns: [{ ...completedTurn, result, children: [{ childTaskId: 'child-task-a', runId: 'child-run-a', goal, status: 'completed', result: '### 子助手结论\n\n`result()` 返回正确。' }] }] };
  await mount(session.id);
  const main = host.querySelector('.rs-turn > .rs-reply .rs-markdown')!;
  expect(main.querySelector('strong')?.textContent).toBe('修复完成'); expect(main.querySelectorAll('li')).toHaveLength(2);
  expect(main.querySelector('pre code')?.textContent).toBe(code);
  expect(main.querySelector('img,script')).toBeNull(); expect(main.textContent).toContain('测试图片');
  expect(main.querySelector('a')?.getAttribute('href')).toBe('');
  const childGoal = host.querySelector<HTMLDetailsElement>('.rs-child-goal')!;
  const childResult = host.querySelector<HTMLDetailsElement>('.rs-child-result')!;
  expect(childGoal.open).toBe(false); expect(childGoal.querySelector('p')?.textContent).toBe(goal);
  expect(childResult.open).toBe(false); expect(childResult.querySelector('h3')?.textContent).toBe('子助手结论');
  await act(async () => { childGoal.open = true; childResult.open = true; button('查看原子任务记录').click(); });
  expect(task).toHaveBeenCalledExactlyOnceWith('child-task-a');
  expect(api.turn).not.toHaveBeenCalled(); expect(api.create).not.toHaveBeenCalled(); expect(api.stop).not.toHaveBeenCalled();
});

it('keeps command failure and unknown receipts visible despite a successful-looking assistant reply', async () => {
  const stdout = '  first\n    second\n';
  current = { ...current, turns: [{ ...completedTurn, result: '**一切成功**', toolResults: [
    { effectKey: 'failed-command', status: 'DONE', result: { outcome: 'completed', output: { argv: ['python', '-m', 'pytest'], cwd: 'project', exitCode: 1, stdout, stderr: 'AssertionError\n' } } },
    { effectKey: 'failed-tool', status: 'DONE', result: { outcome: 'failed', stopped: true, code: 'RESEARCH_COMMAND_UNAVAILABLE' } },
    { effectKey: 'unknown-command', status: 'UNKNOWN', result: null },
    { effectKey: 'completed-command', status: 'DONE', result: { outcome: 'completed', output: { argv: ['python', '-V'], cwd: '.', exitCode: 0, stdout: 'Python\n', stderr: '' } } },
  ] }] };
  await mount(session.id);
  const records = [...host.querySelectorAll<HTMLDetailsElement>('.rs-tool-results > details')];
  expect(records.map(record => record.open)).toEqual([true, true, true, false]);
  expect(records[0].querySelector('summary')?.textContent).toContain('操作失败 · 退出码 1');
  expect(records[1].querySelector('summary')?.textContent).toContain('操作失败');
  expect(records[2].querySelector('summary')?.textContent).toContain('结果未知，需核对原操作');
  expect(records[3].querySelector('summary')?.textContent).toContain('回执已确认 · 退出码 0');
  expect(records[0].querySelector('summary')?.textContent).not.toContain('failed-command');
  expect(records[0].querySelector('.rs-command-output pre')?.textContent).toBe(stdout);
  expect(records[0].textContent).toContain('failed-command');
  await act(async () => button('查看原任务记录').click()); expect(task).toHaveBeenCalledWith('task-a');
  expect(api.turn).not.toHaveBeenCalled();
});

it.each([
  ['research_remember', { operation: 'remember', memory: { id: 'memory-a', text: '测试使用 pytest', updatedAt: session.updatedAt } }, ['记住个人偏好', '已记住', '测试使用 pytest']],
  ['research_find_memories', { operation: 'find', memories: [{ id: 'memory-a', text: '测试使用 pytest', updatedAt: session.updatedAt }], page: 1, total: 2, nextPage: 2 }, ['查找个人记忆', '第 1 页 · 共 2 条匹配 · 还有第 2 页', '是否采用请结合助手回复和后续执行记录核对']],
  ['research_update_memory', { operation: 'update', memory: { id: 'memory-a', text: '测试使用 python -m pytest -q', updatedAt: session.updatedAt }, previousText: '测试使用 pytest' }, ['纠正个人记忆', '已修改', '修改前', '测试使用 pytest', '修改后', '测试使用 python -m pytest -q']],
  ['research_forget_memory', { operation: 'forget', memory: { id: 'memory-a', text: '测试使用 python -m pytest -q', updatedAt: session.updatedAt }, notice: '仅移除个人记忆；旧会话和摘要保留。' }, ['忘记个人记忆', '已忘记', '测试使用 python -m pytest -q', '旧会话和摘要保留']],
] as const)('shows the real %s memory result inside existing expanded tool events without executing on refresh', async (toolName, output, expected) => {
  current = { ...current, capabilities: { memory: true }, turns: [{ ...completedTurn, events: [{ id: 1, jobId: 'task-a', type: 'research_tool_finished', message: '研究工具返回结果', data: { toolName, outcome: 'completed', output }, createdAt: session.updatedAt }] }] };
  await mount(session.id);
  const events = host.querySelector<HTMLDetailsElement>('.rs-events')!;
  expect(events.open).toBe(true);
  for (const text of expected) expect(events.textContent).toContain(text);
  expect(events.textContent).toContain('记忆条目：memory-a');
  expect(events.querySelector('details')?.open).toBe(false);
  await act(async () => button('刷新会话').click());
  expect(api.create).not.toHaveBeenCalled(); expect(api.turn).not.toHaveBeenCalled(); expect(api.correct).not.toHaveBeenCalled(); expect(api.stop).not.toHaveBeenCalled();
});

it.each([
  ['failed', 'RESEARCH_MEMORY_UNAVAILABLE', '本次操作未完成'],
  ['unknown', 'RESEARCH_TOOL_RECEIPT_UNCONFIRMED', '本次操作结果尚未确认'],
] as const)('does not present a %s memory write as saved or offer replay', async (outcome, code, expected) => {
  current = { ...current, turns: [{ ...completedTurn, events: [{ id: 1, jobId: 'task-a', type: 'research_tool_finished', message: '原操作需核对', data: { toolName: 'research_remember', outcome, code }, createdAt: session.updatedAt }] }] };
  await mount(session.id);
  const events = host.querySelector<HTMLDetailsElement>('.rs-events')!;
  expect(events.open).toBe(true); expect(events.querySelector('[role="alert"]')?.textContent).toContain(expected);
  expect(events.textContent).toContain(code); expect(events.textContent).not.toContain('已记住');
  expect(events.querySelector('button')).toBeNull(); expect(api.turn).not.toHaveBeenCalled();
});

it('distinguishes a later memory receipt reconciliation from another write and explains oversized searches', async () => {
  current = { ...current, turns: [{ ...completedTurn, events: [
    { id: 1, jobId: 'task-a', type: 'research_tool_finished', message: '已核对原记忆操作，未重新执行', data: { toolName: 'research_remember', outcome: 'completed', reconciled: true, output: { operation: 'remember', memory: { id: 'memory-a', text: '回答先给结论' } } }, createdAt: session.updatedAt },
    { id: 2, jobId: 'task-a', type: 'research_tool_finished', message: '结果过大', data: { toolName: 'research_find_memories', outcome: 'failed', code: 'RESEARCH_TOOL_OUTPUT_TOO_LARGE' }, createdAt: session.updatedAt },
  ] }] };
  await mount(session.id);
  const events = host.querySelector('.rs-events')!;
  expect(events.textContent).toContain('已核对原操作，未重新执行');
  expect(events.textContent).toContain('结果超过当前输出范围，可在下一条指令中缩小查找范围');
  expect(api.turn).not.toHaveBeenCalled();
});

it('does not invent a confirmed memory body from a malformed success and explains an old fixed binding', async () => {
  current = { ...current, capabilities: { memory: false }, turns: [{ ...completedTurn, events: [{ id: 1, jobId: 'task-a', type: 'research_tool_finished', message: '研究工具返回结果', data: { toolName: 'research_remember', outcome: 'completed', output: { operation: 'remember', memory: { id: 'memory-a' } } }, createdAt: session.updatedAt }] }] };
  await mount(session.id);
  const events = host.querySelector('.rs-events')!;
  expect(events.textContent).toContain('本次操作结果尚未确认'); expect(events.textContent).not.toContain('已记住');
  expect(host.textContent).toContain('此会话的原工具配置不包含个人记忆');
  expect(button('新建会话')).toBeDefined(); expect(api.create).not.toHaveBeenCalled();
});

it('does not turn a memory search response without paging evidence into an empty result', async () => {
  current = { ...current, turns: [{ ...completedTurn, events: [{ id: 1, jobId: 'task-a', type: 'research_tool_finished', message: '研究工具返回结果', data: { toolName: 'research_find_memories', outcome: 'completed', output: { operation: 'find', memories: [] } }, createdAt: session.updatedAt }] }] };
  await mount(session.id);
  const events = host.querySelector('.rs-events')!;
  expect(events.textContent).toContain('本次操作结果尚未确认'); expect(events.textContent).not.toContain('本页没有匹配的个人记忆');
});

it('validates beside fields and keeps drafts through resource navigation and remount without creating a session', async () => {
  await mount(); await act(async () => button('创建并开始研究').click());
  expect(host.querySelectorAll('label [role="alert"]')).toHaveLength(3); expect(api.create).not.toHaveBeenCalled();
  await validDraft(); await act(async () => button('配置我的模型').click()); expect(models).toHaveBeenCalledOnce();
  await act(async () => root.unmount()); root = createRoot(host); await mount();
  expect((host.querySelector('textarea') as HTMLTextAreaElement).value).toBe('检查测试程序'); expect(api.turn).not.toHaveBeenCalled();
  await mount('', 'bob'); expect((host.querySelector('textarea') as HTMLTextAreaElement).value).toBe('');
});

it('focuses and scrolls the first invalid field and opens collapsed invalid limits', async () => {
  const scroll = vi.spyOn(HTMLElement.prototype, 'scrollIntoView').mockImplementation(() => {});
  await mount(); await field('会话名称', '保留研究目标'); await field('停止边界', '测试通过后停止');
  await act(async () => button('创建并开始研究').click());
  const goal = host.querySelector('textarea')!;
  expect(document.activeElement).toBe(goal); expect(goal.getAttribute('aria-invalid')).toBe('true');
  expect(scroll.mock.contexts.at(-1)).toBe(goal.closest('label')); expect(scroll).toHaveBeenLastCalledWith({ block: 'center' });
  await field('研究目标', '检查测试程序'); await field('会话最多轮次', '99');
  const limits = host.querySelector<HTMLDetailsElement>('.rs-limits')!; limits.open = false;
  await act(async () => button('创建并开始研究').click());
  const input = limits.querySelector('input')!;
  expect(limits.open).toBe(true); expect(document.activeElement).toBe(input);
  expect(scroll.mock.contexts.at(-1)).toBe(input.closest('label')); expect(api.create).not.toHaveBeenCalled();
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
  expect(host.textContent).toContain('本次查询没有重新发送或启动研究'); expect(button('开始这一轮').closest('fieldset')?.disabled).toBe(false);
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
  expect(host.textContent).toContain('待纳入研究请求'); expect(host.textContent).not.toContain('已纳入研究请求');
  current = { ...current, turns: [{ ...current.turns[0], messages: [{ ...current.turns[0].messages[0], state: 'included', includedAt: session.createdAt }] }] };
  await act(async () => button('刷新会话').click()); expect(host.textContent).toContain('已纳入研究请求'); expect(host.textContent).not.toContain('模型已遵守');
});

it('keeps older payloads readable without inventing raw size or a summary', async () => {
  await mount(session.id);
  expect(host.querySelector('.rs-context-status')).toBeNull();
  expect(host.querySelector('.rs-agreement')?.textContent).toContain('当前会话上下文 15 / 12000');
  expect(host.textContent).not.toContain('当前模型上下文');
  expect(host.textContent).not.toContain('undefined'); expect(host.textContent).not.toContain('原始上下文');
  expect(api.turn).not.toHaveBeenCalled();
});

it('continues an over-limit history only on explicit submission and retains all original records', async () => {
  current = { ...current, turns: [completedTurn], context: { characters: 14000, rawCharacters: 14000, maximumCharacters: 12000, compaction: { status: 'needed', throughSequence: 0 } } };
  let resolveTurn!: (value: ResearchSession) => void;
  vi.mocked(api.turn).mockImplementation(() => new Promise(resolve => { resolveTurn = resolve; }));
  await mount(session.id); await act(async () => button('刷新会话').click());
  expect(host.textContent).toContain('继续前需要整理上下文'); expect(host.textContent).toContain('尚无已确认的摘要');
  expect(host.textContent).toContain(completedTurn.result); expect(button('开始这一轮').closest('fieldset')?.disabled).toBe(false);
  expect(api.turn).not.toHaveBeenCalled();
  await field('下一轮指令', '沿用目标和边界继续');
  const start = button('开始这一轮'); await act(async () => { start.click(); start.click(); });
  expect(api.turn).toHaveBeenCalledOnce(); expect(api.turn).toHaveBeenCalledWith('alice', session.id, expect.objectContaining({ text: '沿用目标和边界继续' }));
  current = { ...current, state: 'running', allowedActions: ['correct', 'stop'], context: { ...current.context, compaction: { status: 'preparing', throughSequence: 0 } } };
  await act(async () => resolveTurn(current));
  expect(host.textContent).toContain('正在整理上下文'); expect(host.textContent).toContain(completedTurn.result);
});

it('keeps corrections pending through summary preparation and completion until a research request includes them', async () => {
  current = { ...current, state: 'running', allowedActions: ['correct', 'stop'], turns: [{ ...completedTurn, status: 'running', completedAt: null, result: null, messages: [{ id: 'correction-a', kind: 'correction', text: '保留原始数据', state: 'pending', createdAt: session.createdAt, includedAt: null }] }], context: { characters: 4000, rawCharacters: 14000, maximumCharacters: 12000, compaction: { status: 'preparing', throughSequence: 0 } } };
  await mount(session.id);
  expect(host.querySelector('.rs-context-status')?.getAttribute('aria-live')).toBe('polite');
  expect(host.textContent).toContain('待纳入研究请求'); expect(host.textContent).not.toContain('已纳入研究请求');
  current = { ...current, context: { ...current.context, compaction: { status: 'ready', throughSequence: 1 } } };
  await act(async () => button('刷新会话').click());
  expect(host.textContent).toContain('已确认的摘要覆盖至第 1 轮'); expect(host.textContent).toContain('待纳入研究请求');
  expect(host.textContent).not.toContain('已纳入研究请求'); expect(host.textContent).not.toContain('研究成功');
  current = { ...current, turns: [{ ...current.turns[0], messages: [{ ...current.turns[0].messages[0], state: 'included', includedAt: session.updatedAt }] }] };
  await act(async () => button('刷新会话').click());
  expect(host.textContent).toContain('已纳入研究请求'); expect(api.turn).not.toHaveBeenCalled();
});

it.each(['failed', 'unknown'] as const)('preserves the last confirmed range after %s and explains explicit continuation', async status => {
  current = { ...current, turns: [completedTurn], context: { characters: 4000, rawCharacters: 14000, maximumCharacters: 12000, compaction: { status, throughSequence: 1, code: 'RESEARCH_SUMMARY_UNCONFIRMED' } } };
  await mount(session.id);
  expect(host.textContent).toContain('上次已确认的摘要覆盖至第 1 轮'); expect(host.textContent).toContain(completedTurn.result);
  expect(host.textContent).toContain(status === 'unknown' ? '可能新增一次用于整理的模型请求' : '再尝试整理');
  expect(button('开始这一轮')).toBeDefined(); expect(api.turn).not.toHaveBeenCalled();
  await act(async () => button('查看原任务记录').click()); expect(task).toHaveBeenCalledWith('task-a');
});

it.each(['needed', 'unknown'] as const)('does not offer a retry for %s when the original business effect is blocked', async status => {
  current = { ...current, state: 'blocked', blockReason: 'RESEARCH_EFFECT_UNCONFIRMED', allowedActions: ['stop'], turns: [{ ...completedTurn, status: 'unknown', completedAt: null, toolResults: [{ effectKey: 'original-operation', status: 'UNKNOWN', result: null }] }], context: { characters: 14000, rawCharacters: 14000, maximumCharacters: 12000, compaction: { status, throughSequence: 1 } } };
  await mount(session.id); await act(async () => button('刷新会话').click());
  expect(button('开始这一轮')).toBeUndefined(); expect(host.textContent).toContain('结果未知，需核对原操作');
  expect(host.textContent).not.toContain('可能新增一次'); expect(host.textContent).toContain('当前不能开始新一轮');
  expect(api.turn).not.toHaveBeenCalled();
});

it('does not suggest another summary request while a previous submission still needs reconciliation', async () => {
  current = { ...current, context: { ...current.context, compaction: { status: 'unknown', throughSequence: 0 } } };
  window.sessionStorage.setItem(requestKey('alice'), JSON.stringify([{ requestId: 'original-id', action: 'turn', sessionId: session.id }]));
  await mount(session.id);
  expect(button('开始这一轮').closest('fieldset')?.disabled).toBe(true); expect(host.textContent).not.toContain('可能新增一次');
  expect(host.textContent).toContain('原请求仍需核对'); expect(api.turn).not.toHaveBeenCalled();
});

it('explains the summary input capacity refusal without inventing an unknown business operation', async () => {
  current = { ...current, state: 'blocked', blockReason: 'RESEARCH_SUMMARY_INPUT_LIMIT', allowedActions: ['stop'], turns: [completedTurn], context: { characters: 50000, rawCharacters: 50000, maximumCharacters: 12000 } };
  await mount(session.id);
  expect(host.textContent).toContain('待整理的回复超过单次整理容量'); expect(host.textContent).toContain(completedTurn.result);
  expect(host.textContent).not.toContain('原操作需要核对'); expect(button('开始这一轮')).toBeUndefined();
  await act(async () => button('查看原任务记录').click()); expect(task).toHaveBeenCalledWith('task-a');
  expect(api.turn).not.toHaveBeenCalled(); expect(api.stop).not.toHaveBeenCalled();
});

it('starts a new turn after completion even when the service also permits stored corrections', async () => {
  current = { ...current, allowedActions: ['start', 'correct', 'stop'] };
  await mount(session.id); expect(button('保存纠正')).toBeUndefined();
  await field('下一轮指令', '沿用原边界，检查另一组结果'); await act(async () => button('开始这一轮').click());
  expect(api.turn).toHaveBeenCalledWith('alice', session.id, expect.objectContaining({ text: '沿用原边界，检查另一组结果' }));
  expect(api.correct).not.toHaveBeenCalled();
});

it('uses server stop permission even while the session is idle', async () => {
  current = { ...current, allowedActions: ['start', 'stop'] };
  await mount(session.id);
  expect(host.querySelector('.rs-detail-heading .rs-state')?.textContent).toBe('待开始');
  expect(button('请求停止')).toBeDefined(); expect(button('开始这一轮')).toBeDefined();
  expect(api.stop).not.toHaveBeenCalled(); expect(api.turn).not.toHaveBeenCalled();
});

it('shows finalizing during detail polling before presenting a completed session as ready to continue', async () => {
  vi.useFakeTimers();
  try {
    current = { ...current, state: 'running', allowedActions: ['correct', 'stop'], turns: [{ id: 'turn-a', sequence: 1, requestId: 'start-id', taskId: 'task-a', runId: null, status: 'running', createdAt: session.createdAt, completedAt: null, result: null, failure: null, messages: [], events: [], toolResults: [] }] };
    vi.mocked(api.list).mockResolvedValue({ items: [current], nextCursor: null });
    await mount(session.id); expect(host.querySelector('.rs-session-list')?.textContent).toContain('执行中');
    current = { ...current, turns: [{ ...current.turns[0], status: 'finalizing' }] };
    await act(async () => vi.advanceTimersByTimeAsync(4000));
    expect(host.querySelector('.rs-turn > header')?.textContent).toContain('正在核对最终结果');
    expect(host.querySelector('.rs-turn > header')?.textContent).not.toContain('本轮已完成');
    expect(button('开始这一轮')).toBeUndefined();
    current = { ...current, state: 'idle', updatedAt: '2026-10-28T08:01:00Z', allowedActions: ['start', 'correct', 'stop'], turns: [{ ...current.turns[0], status: 'completed', completedAt: '2026-10-28T08:01:00Z', result: '本轮已完成。' }] };
    await act(async () => vi.advanceTimersByTimeAsync(4000));
    expect(api.list).toHaveBeenCalledOnce();
    expect(host.querySelector('.rs-session-list')?.textContent).toContain('就绪');
    expect(host.querySelector('.rs-session-list')?.textContent).not.toContain('执行中');
    expect(host.querySelector('.rs-session-list')?.textContent).toContain(new Date(current.updatedAt).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }));
    expect(host.querySelector('.rs-detail-heading .rs-state')?.textContent).toBe('可继续');
    expect(button('请求停止')).toBeDefined(); expect(button('开始这一轮')).toBeDefined(); expect(api.turn).not.toHaveBeenCalled();
  } finally { vi.useRealTimers(); }
});

it.each(['2026-10-28T08:01:00Z', session.updatedAt])('keeps a freshly read running list when detail refresh fails, even with unchanged updatedAt (%s)', async updatedAt => {
  vi.mocked(api.list).mockResolvedValue({ items: [current], nextCursor: null });
  await mount(session.id); expect(host.querySelector('.rs-session-list')?.textContent).toContain('就绪');
  const newer = { ...current, state: 'running' as const, updatedAt };
  vi.mocked(api.list).mockResolvedValue({ items: [newer], nextCursor: null });
  let rejectDetail!: (reason: unknown) => void;
  vi.mocked(api.get).mockImplementation(() => new Promise((_resolve, reject) => { rejectDetail = reject; }));
  await act(async () => button('刷新会话').click());
  expect(host.querySelector('.rs-session-list')?.textContent).toContain('执行中');
  await act(async () => rejectDetail(new ApiError('详情暂时不可读取', 503)));
  expect(host.textContent).toContain('详情暂时不可读取'); expect(api.list).toHaveBeenCalledTimes(2);
  expect(host.querySelector('.rs-session-list')?.textContent).toContain('执行中');
  expect(host.querySelector('.rs-session-list')?.textContent).toContain(new Date(updatedAt).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }));
  expect(api.turn).not.toHaveBeenCalled();
});

it('keeps a newly read list when an older in-flight detail succeeds later with the same timestamp', async () => {
  vi.mocked(api.list).mockResolvedValue({ items: [current], nextCursor: null });
  await mount(session.id);
  const oldDetail = structuredClone(current);
  vi.mocked(api.list).mockResolvedValue({ items: [{ ...current, state: 'running' }], nextCursor: null });
  let resolveDetail!: (value: ResearchSession) => void;
  vi.mocked(api.get).mockImplementation(() => new Promise(resolve => { resolveDetail = resolve; }));
  await act(async () => button('刷新会话').click());
  expect(host.querySelector('.rs-session-list')?.textContent).toContain('执行中');
  await act(async () => resolveDetail(oldDetail));
  expect(host.querySelector('.rs-session-list')?.textContent).toContain('执行中');
  expect(api.turn).not.toHaveBeenCalled();
});

it('keeps a new detail observation when an older in-flight list succeeds later with the same timestamp', async () => {
  current = { ...current, state: 'running', allowedActions: ['correct', 'stop'] };
  vi.mocked(api.list).mockResolvedValue({ items: [current], nextCursor: null });
  await mount(session.id);
  const oldList = { items: [current], nextCursor: null };
  let resolveList!: (value: typeof oldList) => void;
  vi.mocked(api.list).mockImplementation(() => new Promise(resolve => { resolveList = resolve; }));
  current = { ...current, state: 'idle', allowedActions: ['start'] };
  await act(async () => button('刷新会话').click());
  await act(async () => resolveList(oldList));
  expect(host.querySelector('.rs-session-list')?.textContent).toContain('就绪');
  expect(host.querySelector('.rs-session-list')?.textContent).not.toContain('执行中');
  expect(api.turn).not.toHaveBeenCalled();
});

it('shows stop pending separately from confirmation and keeps UNKNOWN original operation visible', async () => {
  current = { ...current, state: 'running', allowedActions: ['correct', 'stop'] };
  vi.mocked(api.stop).mockImplementation(async () => { current = { ...current, state: 'stopping', allowedActions: ['stop'] }; return current; });
  await mount(session.id); await act(async () => button('请求停止').click());
  expect(host.textContent).toContain('目前不能确认已停止'); expect(api.stop).toHaveBeenCalledOnce();
  current = { ...current, state: 'blocked', allowedActions: ['stop'], blockReason: 'RESEARCH_EFFECT_UNKNOWN', turns: [{ id: 'turn-a', sequence: 1, requestId: 'start-id', taskId: 'task-a', runId: null, status: 'unknown', createdAt: session.createdAt, completedAt: null, result: null, failure: null, messages: [], events: [], toolResults: [{ effectKey: 'original-operation', status: 'UNKNOWN', result: null }] }] };
  await act(async () => button('刷新会话').click());
  expect(host.textContent).toContain('结果未知，需核对原操作'); expect(host.querySelector('.rs-tool-results details')?.hasAttribute('open')).toBe(true); expect(button('开始这一轮')).toBeUndefined();
  expect(button('请求停止').disabled).toBe(false);
  await act(async () => button('查看原任务记录').click()); expect(task).toHaveBeenCalledWith('task-a'); expect(api.turn).not.toHaveBeenCalled();
});

it('prevents repeat stop while pending and replaces feedback when polling confirms the original session stopped', async () => {
  vi.useFakeTimers();
  try {
    current = { ...current, state: 'running', allowedActions: ['correct', 'stop'] };
    vi.mocked(api.stop).mockImplementation(async () => { current = { ...current, state: 'stopping', allowedActions: ['stop'] }; return current; });
    await mount(session.id); await act(async () => button('请求停止').click());
    expect(host.textContent).toContain('目前不能确认已停止');
    expect(button('请求停止').disabled).toBe(true);
    await act(async () => button('请求停止').click());
    expect(api.stop).toHaveBeenCalledOnce();
    current = { ...current, state: 'stopped', allowedActions: ['start'] };
    await act(async () => vi.advanceTimersByTimeAsync(4000));
    expect(host.querySelector('.rs-detail-heading [role="status"]')?.textContent).toBe('已停止');
    expect(host.textContent).not.toContain('停止请求已接收'); expect(host.textContent).not.toContain('目前不能确认已停止');
    expect(button('请求停止')).toBeUndefined(); expect(button('开始这一轮').disabled).toBe(false);
    expect(api.stop).toHaveBeenCalledOnce(); expect(api.turn).not.toHaveBeenCalled();
  } finally { vi.useRealTimers(); }
});

it('shows unavailable configuration honestly and clears private drafts on logout while retaining opaque recovery pointers', async () => {
  vi.mocked(api.options).mockResolvedValue({ ...options, available: false, unavailableCode: 'RESEARCH_WORKSPACE_NOT_CONFIGURED', models: [], workspace: { ...options.workspace, configured: false } });
  await mount(); expect(button('创建并开始研究').disabled).toBe(true); expect(host.textContent).toContain('服务尚未配置会话工作目录'); expect(button('配置我的模型')).toBeDefined();
  await field('研究目标', '私人研究输入');
  window.sessionStorage.setItem(requestKey('alice'), JSON.stringify([{ requestId: 'request-a', action: 'create', sessionId: null }]));
  clearSessionDrafts('alice'); expect(window.sessionStorage.getItem(draftKey('alice'))).toBeNull(); expect(window.sessionStorage.getItem(requestKey('alice'))).toContain('request-a');
});

it('uses a selected original reply only when submitting the next turn', async () => {
  const reply: ResearchQuestion = { id: 'question-a', senderId: 'alice', recipientId: 'bob', endpointId: 'qa-bob', text: '原问题', createdAt: session.createdAt, delivery: { state: 'accepted', taskId: 'b-task', runId: 'b-run' }, reply: { state: 'available', text: '同事回答', contentIds: [], createdAt: session.createdAt } };
  vi.mocked(api.questions).mockResolvedValue({ items: [reply], nextCursor: null }); vi.spyOn(assistantApi, 'question').mockResolvedValue(reply);
  await mount(session.id); await act(async () => button('原问题').click()); await act(async () => button('用于下一轮').click());
  expect(api.turn).not.toHaveBeenCalled(); expect(api.correct).not.toHaveBeenCalled(); expect(host.textContent).toContain('已选择下一轮引用');
  await field('下一轮指令', '结合该回复核对边界'); await act(async () => button('开始这一轮').click());
  expect(api.turn).toHaveBeenCalledWith('alice', session.id, expect.objectContaining({ assistantQuestionId: 'question-a', text: '结合该回复核对边界' }));
  expect(host.textContent).not.toContain('已选择下一轮引用');
});

it('keeps a selected reply out of current corrections and hides an adopted copy on revoked authority', async () => {
  sessionStorage.setItem(`${draftKey('alice', session.id)}:reply`, JSON.stringify('question-a'));
  current = { ...current, state: 'running', allowedActions: ['correct', 'stop'], turns: [{ ...completedTurn, assistantReply: { state: 'available', questionId: 'question-a', senderId: 'alice', recipientId: 'bob', endpointId: 'qa-bob', questionText: '私密原问题', reply: { state: 'available', text: '撤回后不能显示的回复', contentIds: ['source-private'], createdAt: session.createdAt }, delivery: { state: 'accepted', taskId: 'b-task', runId: 'b-run' } } }] };
  await mount(session.id); await field('补充或纠正当前研究', '只检查数据'); await act(async () => button('保存纠正').click());
  expect(vi.mocked(api.correct).mock.calls[0][2]).toEqual({ requestId: expect.any(String), text: '只检查数据' }); expect(api.turn).not.toHaveBeenCalled();
  expect(host.textContent).toContain('撤回后不能显示的回复');
  current = { ...current, turns: [{ ...current.turns[0], assistantReply: { state: 'unavailable', questionId: 'question-a', code: 'RESEARCH_ASSISTANT_REPLY_UNAVAILABLE' } }] };
  await act(async () => button('刷新会话').click());
  expect(host.textContent).not.toContain('撤回后不能显示的回复'); expect(host.textContent).not.toContain('source-private'); expect(host.textContent).not.toContain('私密原问题');
  expect(host.textContent).toContain('正文与来源已隐藏'); expect(host.textContent).toContain('question-a');
});

it('distinguishes new-session collaboration availability from an old fixed session', async () => {
  vi.mocked(api.options).mockResolvedValue({ ...options, collaboration: { available: true } });
  await mount(); expect(host.textContent).toContain('助手可按研究目标自主询问');
  await act(async () => root.unmount()); root = createRoot(host);
  current = { ...current, collaboration: { enabled: false } };
  await mount(session.id); expect(host.textContent).toContain('此会话沿用原配置，仅支持手动');
  expect(host.textContent).not.toContain('此会话可自主询问');
  expect(api.create).not.toHaveBeenCalled(); expect(api.turn).not.toHaveBeenCalled();
});

it('shows manual and multiple automatic references with continuation provenance, then hides revoked copies', async () => {
  const reference = (id: string, text: string) => ({ state: 'available' as const, questionId: id, senderId: 'alice', recipientId: 'bob', endpointId: 'qa-bob', questionText: `原问题 ${id}`, reply: { state: 'available' as const, text, contentIds: [`source-${id}`], createdAt: session.createdAt }, delivery: { state: 'accepted', taskId: 'b-task', runId: 'b-run' } });
  current = { ...current, collaboration: { enabled: true }, turns: [{ ...completedTurn, continuation: { questionIds: ['auto-a', 'auto-b'] }, assistantReply: reference('manual-a', '手动引用正文'), assistantReplies: [reference('auto-a', '自主回复甲'), reference('auto-b', '自主回复乙')] }] };
  vi.spyOn(assistantApi, 'question').mockResolvedValue({ id: 'auto-b', senderId: 'alice', recipientId: 'bob', endpointId: 'qa-bob', text: '原问题 auto-b', createdAt: session.createdAt, delivery: { state: 'accepted', taskId: 'b-task', runId: 'b-run' }, reply: null });
  await mount(session.id);
  expect(host.textContent).toContain('手动引用正文'); expect(host.textContent).toContain('自主回复甲'); expect(host.textContent).toContain('自主回复乙');
  expect(host.textContent).toContain('创建轮次不代表回复已纳入模型请求');
  await act(async () => button('自动继续的原问题 auto-b').click()); expect(assistantApi.question).toHaveBeenCalledWith('alice', 'auto-b', expect.any(AbortSignal));
  const unavailable = (questionId: string) => ({ state: 'unavailable' as const, questionId, code: 'RESEARCH_ASSISTANT_REPLY_UNAVAILABLE' });
  current = { ...current, turns: [{ ...current.turns[0], assistantReply: unavailable('manual-a'), assistantReplies: [unavailable('auto-a'), unavailable('auto-b')] }] };
  await act(async () => button('刷新会话').click());
  expect(host.textContent).not.toContain('手动引用正文'); expect(host.textContent).not.toContain('自主回复甲'); expect(host.textContent).not.toContain('自主回复乙');
  expect(host.textContent).not.toContain('source-auto'); expect(host.querySelectorAll('.rs-adopted-reply [role="status"]')).toHaveLength(3);
  expect(api.turn).not.toHaveBeenCalled();
});

it('permits stopping an idle collaboration and never posts a new turn for a late reply or refresh', async () => {
  current = { ...current, collaboration: { enabled: true }, turns: [completedTurn], allowedActions: ['stop'] };
  vi.mocked(api.stop).mockImplementation(async () => { current = { ...current, state: 'stopped', allowedActions: ['start'] }; return current; });
  await mount(session.id); expect(button('请求停止')).toBeDefined(); expect(button('开始这一轮')).toBeUndefined();
  await act(async () => button('请求停止').click());
  expect(host.textContent).toContain('之后到达的同事回复不会自动继续研究');
  await act(async () => button('刷新会话').click());
  expect(api.stop).toHaveBeenCalledOnce(); expect(api.turn).not.toHaveBeenCalled(); expect(api.create).not.toHaveBeenCalled();
  expect(button('请求停止')).toBeUndefined(); expect(button('开始这一轮')).toBeDefined();
});
