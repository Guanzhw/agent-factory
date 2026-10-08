/** URL pointers are navigation only. Every record still needs server authorization. */
export const workspaceTabs = {
  research: '应用与任务', autoresearch: 'Auto-Research 实验',
  connections: '我的资源连接', comparison: '结果比较', schedules: '计划任务',
  storage: '存储与回收', materials: '共享材料管理', applications: '应用管理', reviews: '方案审查',
} as const;
export type WorkspaceTab = keyof typeof workspaceTabs;
export type WorkspaceRoute = { tab: WorkspaceTab; task: string; run: string };
const managerTabs = new Set<WorkspaceTab>(['materials', 'applications', 'reviews']);
const pointer = (value: string | null) => value && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/.test(value) && !value.includes('..') ? value : '';
export function readWorkspaceRoute(url: URL, manager: boolean): WorkspaceRoute {
  const requested = url.searchParams.get('tab');
  const tab = requested && Object.hasOwn(workspaceTabs, requested) ? requested as WorkspaceTab : 'research';
  return { tab: !manager && managerTabs.has(tab) ? 'research' : tab, task: pointer(url.searchParams.get('task')), run: pointer(url.searchParams.get('run')) };
}
export function workspaceUrl(current: URL, route: WorkspaceRoute): string {
  const url = new URL(current);
  url.searchParams.set('tab', route.tab);
  for (const key of ['task', 'run'] as const) {
    if (route[key]) url.searchParams.set(key, route[key]); else url.searchParams.delete(key);
  }
  return `${url.pathname}${url.search}${url.hash}`;
}
export function sameWorkspaceRoute(left: WorkspaceRoute, right: WorkspaceRoute) {
  return left.tab === right.tab && left.task === right.task && left.run === right.run;
}
