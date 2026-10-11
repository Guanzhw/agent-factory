import { describe, expect, it } from 'vitest';
import { readWorkspaceRoute, workspaceUrl, sameWorkspaceRoute } from '../web/workspaceNavigation.js';
const read = (query: string, manager = false) => readWorkspaceRoute(new URL(`https://factory.test/${query}`), manager);
describe('Factory application workspace navigation', () => {
  it('opens the application catalog without depending on controlled presets', () => {
    expect(read('')).toEqual({ tab: 'catalog', task: '', run: '' });
    expect(read('?tab=unknown')).toEqual(read(''));
  });
  it('restores task and research deep links on reload', () => {
    for (const query of ['?tab=resources', '?tab=models', '?tab=connections', '?tab=research&task=task-one', '?tab=autoresearch&run=run-one', '?tab=openresearch&project=orp-one']) {
      const route = read(query); const href = workspaceUrl(new URL('https://factory.test/'), route);
      expect(read(href)).toEqual(route);
    }
  });
  it('retains unrelated URL state without exposing goal or approval data', () => {
    expect(workspaceUrl(new URL('https://factory.test/workspace?lang=zh&task=old#details'), { tab: 'research', task: 'new', run: '' })).toBe('/workspace?lang=zh&task=new&tab=research#details');
  });
  it('does not show administrator views to ordinary users', () => {
    for (const tab of ['materials', 'applications', 'reviews']) {
      expect(read(`?tab=${tab}`).tab).toBe('catalog');
      expect(read(`?tab=${tab}`, true).tab).toBe(tab);
    }
  });
  it('rejects malformed pointers and compares navigation without execution state', () => {
    for (const value of ['../secret', 'a/b', 'a b', '<script>', 'a'.repeat(201)]) expect(read(`?task=${encodeURIComponent(value)}&run=${encodeURIComponent(value)}`)).toEqual(read(''));
    expect(sameWorkspaceRoute(read('?task=one'), read('?task=one'))).toBe(true);
    expect(sameWorkspaceRoute(read('?task=one'), read('?task=two'))).toBe(false);
  });
  it('restores the chosen OpenResearch mode and project through navigation', () => {
    const managed = read('?tab=openresearch&mode=managed&project=orp-one');
    expect(read(workspaceUrl(new URL('https://factory.test/'), managed))).toEqual(managed);
    expect(read('?tab=openresearch&mode=personal').mode).toBe('personal');
    expect(read('?tab=openresearch&mode=unknown').mode).toBeUndefined();
    expect(sameWorkspaceRoute(managed, { ...managed, mode: 'personal' })).toBe(false);
    expect(workspaceUrl(new URL('https://factory.test/?mode=managed'), { tab: 'catalog', task: '', run: '' })).not.toContain('mode=');
  });
  it('persists only an allowed model return view alongside the research pointers', () => {
    const models = read('?tab=models&modelReturn=resources&mode=managed&project=orp-one');
    expect(read(workspaceUrl(new URL('https://factory.test/'), models))).toEqual(models);
    expect(models.modelReturn).toBe('resources');
    expect(sameWorkspaceRoute(models, { ...models, modelReturn: 'openresearch' })).toBe(false);
    for (const value of ['https://outside.test/', 'materials', '../secret', 'unknown']) {
      expect(read(`?tab=models&modelReturn=${encodeURIComponent(value)}`).modelReturn).toBeUndefined();
    }
  });
});
