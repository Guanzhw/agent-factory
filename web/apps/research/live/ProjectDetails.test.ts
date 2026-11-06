// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ProjectDetails } from './ProjectDetails.js';
import type { ResearchProject } from '../types.js';
vi.mock('./RunRecords.js', () => ({ RunRecords: ({ projectId, evidence, onTask }: { projectId: string; evidence: boolean; onTask: (id: string) => void }) => createElement('button', { onClick: () => onTask('original-task') }, `${projectId}:${evidence}`) }));
const project: ResearchProject = { id: 'original-project', ownerId: 'alice', title: 'Original history', state: 'ready', assistantId: null, currentGoalVersion: 1, createdAt: '', ending: null, execution: { available: true, reason: null }, goals: [{ version: 1, createdAt: '', confirmedAt: null, agreement: { objective: 'original objective', evaluation: 'measure', stopConditions: 'finish', resourceRefs: {}, budget: { rounds: 2, toolCalls: 4, tokenLimit: null, amountMicros: null, currency: null } } }] };
let host: HTMLDivElement; let root: Root; const onTask = vi.fn(); const onTab = vi.fn();
beforeEach(() => { vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); host = document.createElement('div'); document.body.append(host); root = createRoot(host); onTask.mockReset(); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });
async function mount(tab = 'overview', value = project) { await act(async () => root.render(createElement(ProjectDetails, { project: value, tab, onTab, onTask }))); }
it('retains original goals without an editable or executable workflow', async () => {
  await mount(); expect(host.textContent).toContain('original objective'); expect(host.querySelector('form,input,textarea')).toBeNull();
  expect(host.textContent).not.toContain('配置研究执行'); expect(host.textContent).not.toContain('确认当前约定');
});
it('opens exact historical execution and evidence including retired delivery-tab links', async () => {
  for (const tab of ['experiments', 'evidence', 'delivery']) { await mount(tab); const record = [...host.querySelectorAll('button')].find(item => item.textContent === `original-project:${tab === 'evidence'}`)!; await act(async () => record.click()); expect(onTask).toHaveBeenLastCalledWith('original-task'); }
});
it('hides goal bodies when the project source is unavailable', async () => {
  await mount('overview', { ...project, sourceUnavailable: true }); expect(host.textContent).toContain('来源不可用'); expect(host.textContent).not.toContain('original objective');
});
