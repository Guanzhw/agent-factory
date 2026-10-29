import { describe, expect, it } from 'vitest';
import { researchNavigation } from '../web/research-composition.js';
import { readWorkspaceRoute, workspaceUrl } from '../web/workspaceNavigation.js';

describe('explicit research navigation', () => {
  const navigation = researchNavigation;
  it('keeps the platform as the default and ignores application routes in core-only composition', () => {
    const url = new URL('https://factory.example/?tab=research&project=inference');
    expect(readWorkspaceRoute(url, false).tab).toBe('catalog');
    expect(readWorkspaceRoute(new URL('https://factory.example/'), false, navigation).tab).toBe('catalog');
    expect(readWorkspaceRoute(url, false, navigation)).toMatchObject({ tab: 'research', project: 'inference' });
  });
  it('preserves project and evidence deep links without accepting arbitrary view state', () => {
    const url = new URL('https://factory.example/?tab=research&project=inference&researchTab=evidence#observation');
    const route = readWorkspaceRoute(url, false, navigation);
    expect(workspaceUrl(url, route, navigation)).toBe('/?tab=research&project=inference&researchTab=evidence#observation');
    expect(readWorkspaceRoute(new URL('https://factory.example/?tab=research&project=../alice&researchTab=unknown&researchView=admin'), false, navigation)).toMatchObject({ project: '', researchTab: '', researchView: '' });
  });
  it('can clear project and app view pointers when returning to the platform', () => {
    const url = new URL('https://factory.example/?tab=research&project=inference&researchTab=evidence&researchView=team');
    expect(workspaceUrl(url, { tab: 'catalog', task: '', project: '', researchTab: '', researchView: '' }, navigation)).toBe('/?tab=catalog');
  });
});

it('preserves live assistant setup and original-question context through resources without sharing it with core', () => {
  const url = new URL('https://factory.example/?tab=research&researchView=assistant&researchQASetup=qa-1&researchPeer=peer-1&researchQuestion=question-1');
  const route = readWorkspaceRoute(url, false, researchNavigation);
  expect(route).toMatchObject({ researchView: 'assistant', researchQASetup: 'qa-1', researchPeer: 'peer-1', researchQuestion: 'question-1' });
  const resourceURL = workspaceUrl(url, { ...route, tab: 'resources', modelReturn: 'research' }, researchNavigation);
  expect(readWorkspaceRoute(new URL(resourceURL, url), false, researchNavigation)).toMatchObject({ researchQuestion: 'question-1', researchQASetup: 'qa-1' });
  expect(readWorkspaceRoute(url, false).researchQuestion).toBeUndefined();
  expect(readWorkspaceRoute(new URL('https://factory.example/?tab=research&researchQuestion=../other&researchQASetup=https://wrong'), false, researchNavigation)).toMatchObject({ researchQuestion: '', researchQASetup: '' });
});

it('preserves a research session across model configuration and rejects unsafe session pointers', () => {
  const url = new URL('https://factory.example/?tab=research&researchView=sessions&researchSession=session-1');
  const route = readWorkspaceRoute(url, false, researchNavigation);
  const modelUrl = workspaceUrl(url, { ...route, tab: 'models', modelReturn: 'research' }, researchNavigation);
  expect(readWorkspaceRoute(new URL(modelUrl, url), false, researchNavigation)).toMatchObject({ researchView: 'sessions', researchSession: 'session-1', modelReturn: 'research' });
  expect(readWorkspaceRoute(new URL('https://factory.example/?tab=research&researchView=sessions&researchSession=../alice'), false, researchNavigation).researchSession).toBe('');
  expect(readWorkspaceRoute(url, false).researchSession).toBeUndefined();
});

it('keeps the research origin while choosing a concrete resource category', () => {
  const url = new URL('https://factory.example/?tab=research&project=project-1&researchSetup=setup-2');
  const original = readWorkspaceRoute(url, false, researchNavigation);
  const resources = { ...original, tab: 'connections', resource: 'credentials', modelReturn: 'research' };
  const restored = readWorkspaceRoute(new URL(workspaceUrl(url, resources, researchNavigation), url), false, researchNavigation);
  expect(restored).toMatchObject({ tab: 'connections', resource: 'credentials', project: 'project-1', researchSetup: 'setup-2', modelReturn: 'research' });
  const returned = readWorkspaceRoute(new URL(workspaceUrl(url, { ...restored, tab: 'research', modelReturn: '' }, researchNavigation), url), false, researchNavigation);
  expect(returned).toMatchObject({ tab: 'research', project: 'project-1', researchSetup: 'setup-2' });
});
