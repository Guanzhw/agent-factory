// @vitest-environment happy-dom
import { act, createElement, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError } from '../../api.js';
import { SessionQuestions } from './SessionQuestions.js';
import { researchSessionsApi as api } from './researchSessionsClient.js';
import { assistantApi, type ResearchQuestion } from './live/assistantClient.js';
import { clearSessionDrafts, draftKey, requestKey } from './researchSessionStorage.js';

const question: ResearchQuestion = { id: 'question-a', senderId: 'alice', recipientId: 'bob', endpointId: 'qa-bob', text: '这个实验有哪些边界？', createdAt: '2026-10-28T10:00:00Z', delivery: { state: 'accepted', taskId: 'task-bob', runId: 'run-bob' }, reply: null, allowedActions: [], recoveryCode: 'ASSISTANT_RECIPIENT_REQUIRED', sessionId: 'session-a', assistantId: 'assistant-bob', requestId: 'request-a' };
let host: HTMLDivElement; let root: Root;
const useReply = vi.fn();
function Harness({ owner = 'alice', session = 'session-a' }: { owner?: string; session?: string }) {
  const [questionId, onQuestion] = useState('');
  return createElement(SessionQuestions, { ownerId: owner, sessionId: session, questionId, onQuestion, onUse: useReply });
}
const button = (text: string) => [...host.querySelectorAll('button')].find(item => item.textContent === text)!;
async function mount(owner = 'alice', session = 'session-a') { await act(async () => root.render(createElement(Harness, { key: owner + session, owner, session }))); }
async function input(text: string) { await act(async () => { const field = host.querySelector('textarea')!; Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, text); field.dispatchEvent(new Event('input', { bubbles: true })); }); }
async function draft() { await act(async () => button('向同事助手提问').click()); await act(async () => button('向 Bob 的助手提问').click()); await input(question.text); }
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); sessionStorage.clear(); useReply.mockReset();
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  vi.spyOn(api, 'questions').mockResolvedValue({ items: [], nextCursor: null });
  vi.spyOn(api, 'ask').mockImplementation(async (_owner, _session, body) => ({ ...question, requestId: body.requestId }));
  vi.spyOn(assistantApi, 'directory').mockResolvedValue({ items: [{ id: 'assistant-bob', ownerId: 'bob', displayName: 'Bob', qaAvailable: true }], nextCursor: null });
  vi.spyOn(assistantApi, 'question').mockResolvedValue(question);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('sends only the confirmed text and assistant with one original request on double click', async () => {
  let finish!: (value: ResearchQuestion) => void;
  vi.mocked(api.ask).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  await mount(); await draft(); const send = button('确认发送问题');
  await act(async () => { send.click(); send.click(); });
  expect(api.ask).toHaveBeenCalledOnce(); const body = vi.mocked(api.ask).mock.calls[0][2];
  expect(Object.keys(body).sort()).toEqual(['assistantId', 'requestId', 'text']); expect(body.text).toBe(question.text);
  expect(api.ask).toHaveBeenCalledWith('alice', 'session-a', body);
  await act(async () => finish({ ...question, requestId: body.requestId }));
  expect(host.textContent).toContain('原问题已保存'); expect(host.textContent).toContain('尚未取得回答');
  expect(button('查看我的原任务')).toBeUndefined(); expect(button('接续原问题')).toBeUndefined();
});

it('recovers a committed unknown admission with GET only after remount', async () => {
  vi.mocked(api.ask).mockRejectedValue(new ApiError('问题已保存，尚未确认执行', 409, 'RESEARCH_QUESTION_ADMISSION_UNCONFIRMED'));
  await mount(); await draft(); await act(async () => button('确认发送问题').click());
  const original = JSON.parse(sessionStorage.getItem(`${requestKey('alice')}:question:session-a`)!);
  expect(original).toEqual({ requestId: expect.any(String), assistantId: 'assistant-bob' });
  await mount('bob'); expect(host.textContent).not.toContain(question.text);
  vi.mocked(api.questions).mockResolvedValue({ items: [{ ...question, requestId: original.requestId }], nextCursor: null });
  await mount(); await act(async () => button('查询原问题请求').click());
  expect(api.questions).toHaveBeenCalledWith('alice', 'session-a', '', original.requestId);
  expect(api.ask).toHaveBeenCalledOnce(); expect(host.textContent).toContain('原问题已保存');
});

it.each([['RESEARCH_ASSISTANT_UNCONFIGURED', 409], ['LOCAL_BUDGET_EXHAUSTED', 429], ['LOCAL_BUDGET_CLOSED_OR_EXPIRED', 409]] as const)('keeps editable drafts after a confirmed pre-admission %s refusal', async (code, status) => {
  vi.mocked(api.ask).mockRejectedValue(new ApiError('接收方配置或额度不可用，请对方核对助手设置。', status, code));
  await mount(); await draft(); await act(async () => button('确认发送问题').click());
  expect((host.querySelector('textarea') as HTMLTextAreaElement).value).toBe(question.text);
  expect(button('确认发送问题').closest('fieldset')?.disabled).toBe(false);
  expect(button('查询原问题请求')).toBeUndefined(); expect(host.textContent).toContain('请对方核对助手设置');
  expect(sessionStorage.getItem(`${draftKey('alice', 'session-a')}:question:request`)).toBeNull();
});

it('keeps unsent text on navigation, isolates owners and clears private drafts on logout', async () => {
  await mount(); await draft(); expect(host.textContent).toContain('未发送内容保存在本浏览器');
  await mount('alice', 'session-b'); expect(host.textContent).not.toContain(question.text);
  await mount(); expect((host.querySelector('textarea') as HTMLTextAreaElement).value).toBe(question.text);
  expect(api.ask).not.toHaveBeenCalled(); clearSessionDrafts('alice');
  expect(sessionStorage.getItem(`${draftKey('alice', 'session-a')}:question`)).toBeNull();
});

it('shows field errors near the draft and does not send on reads, refresh or selecting a reply', async () => {
  await mount(); await act(async () => button('向同事助手提问').click()); await act(async () => button('向 Bob 的助手提问').click());
  await act(async () => button('确认发送问题').click());
  expect(document.activeElement).toBe(host.querySelector('textarea')); expect(host.querySelector('textarea')?.getAttribute('aria-invalid')).toBe('true');
  expect(host.querySelector('#rs-question-error')?.textContent).toContain('至少 2 个字'); expect(api.ask).not.toHaveBeenCalled();
  const answered: ResearchQuestion = { ...question, reply: { state: 'available', text: '先验证数据边界', contentIds: [], createdAt: question.createdAt } };
  vi.mocked(api.questions).mockResolvedValue({ items: [answered], nextCursor: null }); vi.mocked(assistantApi.question).mockResolvedValue(answered);
  await act(async () => button('刷新已发问题').click()); await act(async () => button(question.text).click()); await act(async () => button('用于下一轮').click());
  expect(useReply).toHaveBeenCalledWith(question.id); expect(api.ask).not.toHaveBeenCalled();
  expect(host.textContent).toContain('无可用团队依据');
});

it('drops a late original-session list after switching owner', async () => {
  let finish!: (value: { items: ResearchQuestion[]; nextCursor: null }) => void;
  vi.mocked(api.questions).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  await mount(); await mount('bob'); await act(async () => finish({ items: [question], nextCursor: null }));
  expect(host.textContent).not.toContain(question.text); expect(api.ask).not.toHaveBeenCalled();
});

it('retains the original recovery pointer when an acknowledgement arrives after leaving the session', async () => {
  let finish!: (value: ResearchQuestion) => void;
  vi.mocked(api.ask).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  await mount(); await draft(); await act(async () => button('确认发送问题').click());
  const key = `${requestKey('alice')}:question:session-a`; const saved = sessionStorage.getItem(key)!;
  await mount('bob'); await act(async () => finish({ ...question, requestId: JSON.parse(saved).requestId }));
  expect(sessionStorage.getItem(key)).toBe(saved); expect(host.textContent).not.toContain(question.text);
  await mount(); expect(button('查询原问题请求')).toBeDefined(); expect(api.ask).toHaveBeenCalledOnce();
});

it.each([[403, 'MEMBER_REQUIRED'], [409, 'LOCAL_BUDGET_CLOSED_OR_EXPIRED']] as const)('does not erase a new request pointer when the old instance receives a late %s/%s rejection', async (status, code) => {
  let rejectOld!: (error: Error) => void;
  vi.mocked(api.ask).mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectOld = reject; }));
  await mount(); await draft(); await act(async () => button('确认发送问题').click());
  const key = `${requestKey('alice')}:question:session-a`; const original = JSON.parse(sessionStorage.getItem(key)!);
  await mount('bob');
  vi.mocked(api.questions).mockImplementation(async (_owner, _session, _after, requestId) => ({ items: requestId === original.requestId ? [{ ...question, requestId: original.requestId }] : [], nextCursor: null }));
  await mount(); await act(async () => button('查询原问题请求').click());
  await act(async () => button('向同事助手提问').click()); await input('第二个不同问题');
  vi.mocked(api.ask).mockImplementationOnce(() => new Promise(() => {})); await act(async () => button('确认发送问题').click());
  const newer = sessionStorage.getItem(key)!; expect(JSON.parse(newer).requestId).not.toBe(original.requestId);
  await act(async () => rejectOld(new ApiError('原请求已被拒绝', status, code)));
  expect(sessionStorage.getItem(key)).toBe(newer); expect(api.ask).toHaveBeenCalledTimes(2);
});

it('retains an explicitly unconfirmed committed request regardless of its error status', async () => {
  vi.mocked(api.ask).mockRejectedValue(new ApiError('问题已保存，读取权限已变化', 403, 'RESEARCH_QUESTION_ADMISSION_UNCONFIRMED'));
  await mount(); await draft(); await act(async () => button('确认发送问题').click());
  expect(button('查询原问题请求')).toBeDefined(); expect(button('确认发送问题').closest('fieldset')?.disabled).toBe(true);
  expect(JSON.parse(sessionStorage.getItem(`${requestKey('alice')}:question:session-a`)!).requestId).toBe(vi.mocked(api.ask).mock.calls[0][2].requestId);
});

it('re-sends only after an exact not-found lookup and explicit click, preserving the original payload through remount', async () => {
  vi.mocked(api.ask).mockRejectedValueOnce(new ApiError('网络未连接', 0, 'OFFLINE'));
  await mount(); await draft(); await act(async () => button('确认发送问题').click());
  const original = structuredClone(vi.mocked(api.ask).mock.calls[0][2]);
  vi.mocked(api.questions).mockImplementation(async (_owner, _session, _after, requestId) => {
    if (requestId) throw new ApiError('未找到本会话的原问题。', 404, 'RESEARCH_QUESTION_NOT_FOUND');
    return { items: [], nextCursor: null };
  });
  expect(button('按原请求再次发送')).toBeUndefined(); await act(async () => button('查询原问题请求').click());
  expect(button('按原请求再次发送')).toBeDefined(); expect(api.ask).toHaveBeenCalledOnce();
  await mount('bob');
  sessionStorage.setItem(`${draftKey('alice', 'session-a')}:question`, JSON.stringify({ assistantId: 'someone-else', name: '其他助手', text: '不能替代原文的新草稿' }));
  await mount(); expect(button('按原请求再次发送')).toBeUndefined();
  await act(async () => button('查询原问题请求').click()); await act(async () => button('按原请求再次发送').click());
  expect(api.ask).toHaveBeenCalledTimes(2); expect(vi.mocked(api.ask).mock.calls[1]).toEqual(['alice', 'session-a', original]);
});

it.each([[404, undefined], [403, 'RESEARCH_QUESTION_NOT_FOUND'], [500, 'SERVER_ERROR']] as const)('does not offer re-send after an inconclusive %s/%s lookup', async (status, code) => {
  vi.mocked(api.ask).mockRejectedValue(new ApiError('响应丢失', 0));
  await mount(); await draft(); await act(async () => button('确认发送问题').click());
  vi.mocked(api.questions).mockRejectedValue(new ApiError('读取未确认', status, code));
  await act(async () => button('查询原问题请求').click());
  expect(button('按原请求再次发送')).toBeUndefined(); expect(api.ask).toHaveBeenCalledOnce();
});

it('does not retain immutable private text after logout or reconstruct it from a new draft', async () => {
  vi.mocked(api.ask).mockRejectedValue(new ApiError('响应丢失', 0));
  await mount(); await draft(); await act(async () => button('确认发送问题').click());
  clearSessionDrafts('alice');
  const pointer = sessionStorage.getItem(`${requestKey('alice')}:question:session-a`)!;
  expect(Object.keys(JSON.parse(pointer)).sort()).toEqual(['assistantId', 'requestId']); expect(pointer).not.toContain(question.text);
  expect(sessionStorage.getItem(`${draftKey('alice', 'session-a')}:question:request`)).toBeNull();
  await mount('bob'); await mount();
  vi.mocked(api.questions).mockRejectedValue(new ApiError('未找到本会话的原问题。', 404, 'RESEARCH_QUESTION_NOT_FOUND'));
  await act(async () => button('查询原问题请求').click());
  expect(host.textContent).toContain('原发送文本已清除或不可恢复'); expect(button('按原请求再次发送')).toBeUndefined(); expect(api.ask).toHaveBeenCalledOnce();
});

it('uses one identity for explicit re-send while the original POST is still unresolved', async () => {
  let finishOld!: (value: ResearchQuestion) => void;
  vi.mocked(api.ask).mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve; }));
  await mount(); await draft(); await act(async () => button('确认发送问题').click());
  const original = structuredClone(vi.mocked(api.ask).mock.calls[0][2]);
  await mount('bob'); await mount();
  vi.mocked(api.questions).mockRejectedValue(new ApiError('未找到本会话的原问题。', 404, 'RESEARCH_QUESTION_NOT_FOUND'));
  await act(async () => button('查询原问题请求').click()); await act(async () => button('按原请求再次发送').click());
  expect(vi.mocked(api.ask).mock.calls[1]).toEqual(['alice', 'session-a', original]);
  await act(async () => finishOld({ ...question, requestId: original.requestId }));
  expect(api.ask).toHaveBeenCalledTimes(2); expect(sessionStorage.getItem(`${requestKey('alice')}:question:session-a`)).toBeNull();
});

it.each([
  ['waiting', '等待 bob 的助手回答'], ['pending', '待纳入研究请求'], ['included', '已纳入研究请求'],
  ['blocked', '协作受阻'], ['stopped', '已停止自动继续'],
] as const)('shows the server collaboration %s state without creating another question', async (state, label) => {
  const automatic: ResearchQuestion = { ...question, origin: 'agent', collaboration: { originTurnId: 'origin-turn', state, ...(state === 'pending' ? { continuedTurnId: 'reserved-turn' } : {}) }, reply: state === 'waiting' ? null : { state: 'available', text: '同事原回复', contentIds: [], createdAt: question.createdAt } };
  vi.mocked(api.questions).mockResolvedValue({ items: [automatic], nextCursor: null });
  await mount(); expect(host.textContent).toContain('助手自主提问'); expect(host.textContent).toContain(label);
  if (state === 'pending') { expect(host.textContent).toContain('回复已到'); expect(host.textContent).toContain('已保留自动继续轮次，尚未确认纳入'); expect(host.textContent).not.toContain('已纳入研究请求'); }
  await act(async () => button('刷新已发问题').click()); expect(api.ask).not.toHaveBeenCalled();
});

it('keeps an unconfirmed automatic admission pending with its original-operation explanation', async () => {
  vi.mocked(api.questions).mockResolvedValue({ items: [{ ...question, origin: 'agent', collaboration: { originTurnId: 'origin-turn', state: 'pending', code: 'RESEARCH_COLLABORATION_ADMISSION_UNCONFIRMED' } }], nextCursor: null });
  await mount(); expect(host.textContent).toContain('自动继续请求尚未确认'); expect(host.textContent).toContain('待纳入研究请求');
  expect(host.textContent).not.toContain('协作受阻'); expect(button('按原请求再次发送')).toBeUndefined(); expect(api.ask).not.toHaveBeenCalled();
});

it('polls collaboration changes read-only and removes an open answer when its source is revoked', async () => {
  vi.useFakeTimers();
  try {
    let latest: ResearchQuestion = { ...question, origin: 'agent', collaboration: { originTurnId: 'origin-turn', state: 'pending' }, reply: { state: 'available', text: '不能保留的私密回答', contentIds: ['private-source'], createdAt: question.createdAt } };
    vi.mocked(api.questions).mockImplementation(async () => ({ items: [latest], nextCursor: null }));
    vi.mocked(assistantApi.question).mockResolvedValue(latest);
    await mount(); await act(async () => button(question.text).click()); expect(host.textContent).toContain('不能保留的私密回答');
    latest = { ...latest, reply: { state: 'source_unavailable' }, collaboration: { originTurnId: 'origin-turn', state: 'blocked', code: 'RESEARCH_SOURCE_UNAVAILABLE' } };
    await act(async () => vi.advanceTimersByTimeAsync(4000));
    expect(host.textContent).toContain('原共享来源已不可读'); expect(host.textContent).not.toContain('不能保留的私密回答'); expect(host.textContent).not.toContain('private-source');
    expect(button('用于下一轮')).toBeUndefined(); expect(api.ask).not.toHaveBeenCalled();
  } finally { vi.useRealTimers(); }
});

it('hides an open answer if the current session question list can no longer be read', async () => {
  const answered: ResearchQuestion = { ...question, reply: { state: 'available', text: '读取失权后隐藏的旧回答', contentIds: ['restricted-source'], createdAt: question.createdAt } };
  vi.mocked(api.questions).mockResolvedValue({ items: [answered], nextCursor: null }); vi.mocked(assistantApi.question).mockResolvedValue(answered);
  await mount(); await act(async () => button(question.text).click()); expect(host.textContent).toContain('读取失权后隐藏的旧回答');
  vi.mocked(api.questions).mockRejectedValue(new ApiError('当前会话不可读', 403, 'FORBIDDEN'));
  await act(async () => button('刷新已发问题').click());
  expect(host.textContent).not.toContain('读取失权后隐藏的旧回答'); expect(host.textContent).not.toContain('restricted-source');
  expect(host.textContent).toContain('暂时无法核对本会话的问题'); expect(button('用于下一轮')).toBeUndefined(); expect(api.ask).not.toHaveBeenCalled();
});

it('rechecks an open answer outside the current page and removes revoked text, source and adoption', async () => {
  vi.useFakeTimers();
  try {
    let original: ResearchQuestion = { ...question, reply: { state: 'available', text: '翻页后仍须核权的回答', contentIds: ['source-off-page'], createdAt: question.createdAt } };
    vi.mocked(api.questions).mockImplementation(async (_owner, _session, after) => ({ items: after ? [] : [original], nextCursor: after ? null : 'page-two' }));
    vi.mocked(assistantApi.question).mockImplementation(async () => original);
    vi.spyOn(assistantApi, 'source').mockResolvedValue({ id: 'source-off-page', ownerId: 'bob', source: {}, content: { text: '已打开的私密依据' }, verificationStatus: 'unverified', createdAt: question.createdAt });
    await mount(); await act(async () => button(question.text).click()); await act(async () => button('source-off-page').click());
    await act(async () => button('下一页问题').click());
    await act(async () => vi.advanceTimersByTimeAsync(4000));
    expect(host.textContent).toContain('已打开的私密依据');
    original = { ...original, reply: { state: 'source_unavailable' } };
    await act(async () => vi.advanceTimersByTimeAsync(4000));
    expect(host.textContent).not.toContain('翻页后仍须核权的回答'); expect(host.textContent).not.toContain('source-off-page'); expect(host.textContent).not.toContain('已打开的私密依据');
    expect(button('用于下一轮')).toBeUndefined(); expect(api.ask).not.toHaveBeenCalled();
  } finally { vi.useRealTimers(); }
});

it('updates an already open unanswered question when an off-page reply arrives without sending work', async () => {
  vi.useFakeTimers();
  try {
    let original: ResearchQuestion = { ...question, reply: null };
    vi.mocked(api.questions).mockImplementation(async (_owner, _session, after) => ({ items: after ? [] : [original], nextCursor: after ? null : 'page-two' }));
    vi.mocked(assistantApi.question).mockImplementation(async () => original);
    await mount(); await act(async () => button(question.text).click()); await act(async () => button('下一页问题').click());
    expect(host.textContent).toContain('尚未取得回答');
    original = { ...original, reply: { state: 'available', text: '离线助手刚返回的回答', contentIds: [], createdAt: question.createdAt } };
    await act(async () => vi.advanceTimersByTimeAsync(4000));
    expect(host.textContent).toContain('离线助手刚返回的回答'); expect(button('用于下一轮')).toBeDefined();
    expect(api.ask).not.toHaveBeenCalled(); expect(useReply).not.toHaveBeenCalled();
  } finally { vi.useRealTimers(); }
});
