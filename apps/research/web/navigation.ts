import { workspaceTabs, routePointer, type WorkspaceNavigation } from '../../../web/workspaceNavigation.js';

/** One research application preserves both native and controlled historical entries. */
export const researchNavigation: WorkspaceNavigation = {
  tabs: { ...workspaceTabs, openresearch: 'OpenResearch', autoresearch: '受控 Auto-Research 实验', comparison: '结果比较' },
  applicationTabs: ['openresearch'], advancedTabs: ['comparison', 'schedules', 'storage'],
  modelReturns: ['catalog', 'resources', 'connections', 'openresearch'],
  queryKeys: ['run', 'project', 'mode'],
  readQuery(url) {
    const project = routePointer(url.searchParams.get('project'));
    const mode = url.searchParams.get('mode');
    return { run: routePointer(url.searchParams.get('run')), ...(project ? { project } : {}),
      ...(mode === 'personal' || mode === 'managed' ? { mode } : {}) };
  },
};
