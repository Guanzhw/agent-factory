import { describe, expect, it } from 'vitest';
import { demoNavigation } from '../web/research-demo-composition.js';
import { readWorkspaceRoute, workspaceUrl } from '../web/workspaceNavigation.js';

describe('explicit research demo navigation', () => {
  it('keeps the platform as the default and ignores application routes in core-only composition', () => {
    const url = new URL('https://factory.example/?tab=research&project=inference');
    expect(readWorkspaceRoute(url, false).tab).toBe('catalog');
    expect(readWorkspaceRoute(new URL('https://factory.example/'), false, demoNavigation).tab).toBe('catalog');
    expect(readWorkspaceRoute(url, false, demoNavigation)).toMatchObject({ tab: 'research', project: 'inference' });
  });
  it('preserves project and evidence deep links without accepting arbitrary view state', () => {
    const url = new URL('https://factory.example/?tab=research&project=inference&researchTab=evidence#observation');
    const route = readWorkspaceRoute(url, false, demoNavigation);
    expect(workspaceUrl(url, route, demoNavigation)).toBe('/?tab=research&project=inference&researchTab=evidence#observation');
    expect(readWorkspaceRoute(new URL('https://factory.example/?tab=research&project=../alice&researchTab=unknown&researchView=admin'), false, demoNavigation)).toMatchObject({ project: '', researchTab: '', researchView: '' });
  });
  it('can clear project and app view pointers when returning to the platform', () => {
    const url = new URL('https://factory.example/?tab=research&project=inference&researchTab=evidence&researchView=team');
    expect(workspaceUrl(url, { tab: 'catalog', task: '', project: '', researchTab: '', researchView: '' }, demoNavigation)).toBe('/?tab=catalog');
  });
});
