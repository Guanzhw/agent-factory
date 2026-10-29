// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiError } from '../../../api.js';
import { assistantApi, type ResearchQuestion, type ResearchSource } from './assistantClient.js';
import { AskAssistant, AssistantDirectory, OriginalQuestion } from './AssistantQuestions.js';
let host: HTMLDivElement; let root: Root;
const question: ResearchQuestion = { id: 'q-original', senderId: 'alice', recipientId: 'bob', endpointId: 'endpoint-old', text: '哪些条件不适用？', createdAt: '2026-10-25T12:00:00Z', delivery: { state: 'accepted', taskId: 'original-task', runId: 'original-run' }, reply: { state: 'available', text: '仅对已记录条件适用。', contentIds: ['source-a', 'source-b'], createdAt: '2026-10-25T12:01:00Z' } };
const pendingKey = 'factory:research-question:alice:bob-assistant';
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(yes => { resolve = yes; }); return { promise, resolve }; }
beforeEach(() => { vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); host = document.createElement('div'); document.body.append(host); root = createRoot(host); window.sessionStorage.clear(); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const button = (text: string) => [...host.querySelectorAll('button')].find(item => item.textContent === text)!;
async function askMount(owner = 'alice', onQuestion = vi.fn()) { await act(async () => root.render(createElement(AskAssistant, { key: owner, ownerId: owner, peerId: 'bob-assistant', onQuestion }))); return onQuestion; }
async function send() { await act(async () => { const area = host.querySelector('textarea')!; Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(area, question.text); area.dispatchEvent(new Event('input', { bubbles: true })); }); await act(async () => host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))); }
async function readMount(id = 'q-original', owner = 'alice') { await act(async () => root.render(createElement(OriginalQuestion, { key: owner + id, ownerId: owner, questionId: id }))); }

it('shows actual peers and directs a question only to the selected available identity', async () => {
  vi.spyOn(assistantApi, 'directory').mockResolvedValue({ items: [{ id: 'peer', ownerId: 'bob', displayName: 'Bob', qaAvailable: true }, { id: 'disabled', ownerId: 'carol', displayName: 'Carol', qaAvailable: false }], nextCursor: null });
  const onAsk = vi.fn(); await act(async () => root.render(createElement(AssistantDirectory, { ownerId: 'alice', onAsk })));
  expect(button('向 Carol 的助手提问').disabled).toBe(true);
  await act(async () => button('向 Bob 的助手提问').click()); expect(onAsk).toHaveBeenCalledExactlyOnceWith('peer', 'Bob');
});
it('recovers a 408 with the original key and body after remount, never admitting a replacement', async () => {
  const ask = vi.spyOn(assistantApi, 'ask').mockRejectedValueOnce(new ApiError('未知应答', 408, 'TIMEOUT')).mockResolvedValue(question);
  await askMount(); await send(); const original = JSON.parse(window.sessionStorage.getItem(pendingKey)!);
  await askMount('bob'); expect(host.textContent).not.toContain('重试原操作');
  const onQuestion = await askMount(); expect(button('发送私密问题').disabled).toBe(true);
  await act(async () => button('重试原操作').click());
  expect(ask.mock.calls[1]).toEqual(['alice', 'bob-assistant', original.body]); expect(onQuestion).toHaveBeenCalledWith('q-original');
});
it('retains an acknowledgement arriving after sender navigation for same-key recovery', async () => {
  const late = deferred<ResearchQuestion>(); const ask = vi.spyOn(assistantApi, 'ask').mockReturnValueOnce(late.promise).mockResolvedValue(question);
  const oldRoute = await askMount(); await send(); const saved = window.sessionStorage.getItem(pendingKey);
  const otherRoute = await askMount('bob'); await act(async () => late.resolve(question));
  expect(oldRoute).not.toHaveBeenCalled(); expect(otherRoute).not.toHaveBeenCalled(); expect(window.sessionStorage.getItem(pendingKey)).toBe(saved);
  const restored = await askMount(); await act(async () => button('重试原操作').click());
  expect(ask.mock.calls[1]).toEqual(ask.mock.calls[0]); expect(restored).toHaveBeenCalledWith('q-original');
});
it('keeps an acknowledged original question when later reading fails without sending again', async () => {
  const ask = vi.spyOn(assistantApi, 'ask').mockResolvedValue(question); vi.spyOn(assistantApi, 'question').mockRejectedValue(new ApiError('读取被拒绝', 404, 'NOT_FOUND'));
  const onQuestion = await askMount(); await send(); expect(onQuestion).toHaveBeenCalledWith(question.id);
  await readMount(); expect(host.textContent).toContain('读取被拒绝'); expect(host.textContent).toContain(question.id); expect(ask).toHaveBeenCalledOnce();
});
it('removes the entire derived answer when any input dependency becomes unavailable', async () => {
  vi.spyOn(assistantApi, 'question').mockResolvedValueOnce(question).mockResolvedValue({ ...question, reply: { state: 'source_unavailable' } });
  await readMount(); expect(host.textContent).toContain('输入依据'); expect(host.textContent).toContain('source-b');
  await act(async () => button('核对原问题').click()); expect(host.textContent).not.toContain('仅对已记录条件适用。'); expect(host.textContent).not.toContain('source-a'); expect(host.textContent).toContain('整个派生回答与依据已隐藏');
  expect(window.sessionStorage.length).toBe(0);
});
it('discards late reads after switching question or owner', async () => {
  const late = deferred<ResearchQuestion>(); vi.spyOn(assistantApi, 'question').mockReturnValueOnce(late.promise).mockResolvedValue({ ...question, id: 'other', text: '新成员问题', reply: null });
  await readMount(); await readMount('other', 'carol'); await act(async () => late.resolve(question));
  expect(host.textContent).toContain('新成员问题'); expect(host.textContent).not.toContain(question.text); expect(host.textContent).not.toContain('仅对已记录条件适用。');
});
it('aborts a late source when a newer authority check hides the answer', async () => {
  vi.spyOn(assistantApi, 'question').mockResolvedValueOnce(question).mockResolvedValueOnce(question).mockResolvedValue({ ...question, reply: { state: 'source_unavailable' } });
  const late = deferred<ResearchSource>(); vi.spyOn(assistantApi, 'source').mockReturnValue(late.promise);
  await readMount(); await act(async () => button('source-a').click());
  expect(host.textContent).not.toContain('仅对已记录条件适用。'); await act(async () => button('核对原问题').click());
  await act(async () => late.resolve({ id: 'source-a', ownerId: 'bob', source: {}, content: { text: '撤回来源旧正文' }, verificationStatus: 'unverified', createdAt: '' }));
  expect(host.textContent).not.toContain('撤回来源旧正文'); expect(host.textContent).toContain('整个派生回答与依据已隐藏');
});
it('clears cached text on focus revalidation and a denied source read', async () => {
  vi.spyOn(assistantApi, 'question').mockResolvedValue(question); vi.spyOn(assistantApi, 'source').mockRejectedValue(new ApiError('来源不可读', 403, 'FORBIDDEN'));
  await readMount(); await act(async () => button('source-a').click()); expect(host.textContent).not.toContain('仅对已记录条件适用。'); expect(host.textContent).toContain('来源不可读');
  await act(async () => window.dispatchEvent(new Event('focus'))); expect(assistantApi.question).toHaveBeenCalledTimes(3);
});

it('lets only the recipient recover when explicitly allowed and keeps repeated clicks on the same original message', async () => {
  const awaiting: ResearchQuestion = { ...question, delivery: { state: 'unconfirmed', taskId: null, runId: null }, reply: null, allowedActions: ['recover'], recoveryCode: null };
  vi.spyOn(assistantApi, 'question').mockResolvedValue(awaiting);
  const finish = deferred<ResearchQuestion>(); const recover = vi.spyOn(assistantApi, 'recover').mockReturnValue(finish.promise);
  await readMount(question.id, 'alice'); expect(button('接续原问题')).toBeUndefined();
  const task = vi.fn(); await act(async () => root.render(createElement(OriginalQuestion, { key: 'bob', ownerId: 'bob', questionId: question.id, onTask: task })));
  const resume = button('接续原问题'); await act(async () => { resume.click(); resume.click(); });
  expect(recover).toHaveBeenCalledExactlyOnceWith('bob', question.id);
  vi.mocked(assistantApi.question).mockResolvedValue({ ...question, allowedActions: [], recoveryCode: 'ASSISTANT_ORIGINAL_TASK_EXISTS' });
  await act(async () => finish.resolve(question));
  expect(button('接续原问题')).toBeUndefined(); await act(async () => button('查看我的原任务').click()); expect(task).toHaveBeenCalledWith('original-task');
});

it('does not derive recovery permission from a missing task and keeps an unknown recovery result read-only', async () => {
  vi.spyOn(assistantApi, 'question').mockResolvedValue({ ...question, delivery: { state: 'unconfirmed', taskId: null, runId: null }, allowedActions: [], recoveryCode: 'ASSISTANT_ENDPOINT_DISABLED' });
  const recover = vi.spyOn(assistantApi, 'recover').mockRejectedValue(new ApiError('响应丢失', 408));
  await readMount(question.id, 'bob'); expect(button('接续原问题')).toBeUndefined(); expect(recover).not.toHaveBeenCalled();
  vi.mocked(assistantApi.question).mockResolvedValue({ ...question, allowedActions: ['recover'] });
  await act(async () => button('核对原问题').click()); await act(async () => button('接续原问题').click());
  expect(host.textContent).toContain('接续结果未确认'); expect(button('接续原问题')).toBeUndefined();
  expect(recover).toHaveBeenCalledOnce();
});
