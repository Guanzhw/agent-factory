/** URL pointers are navigation only. Every record still needs server authorization. */
export const workspaceTabs = {
  catalog: '应用目录', openresearch: 'OpenResearch', models: '我的模型/API', developer: '开发者装配', research: '任务与证据', autoresearch: '受控 Auto-Research 实验',
  connections: '我的凭据与连接', comparison: '结果比较', schedules: '计划任务',
  storage: '存储与回收', materials: '共享材料管理', applications: '应用管理', reviews: '方案审查',
} as const;
export type WorkspaceTab = keyof typeof workspaceTabs;
export type WorkspaceRoute = { tab: WorkspaceTab; task: string; run: string; project?: string; mode?: 'personal' | 'managed' };
const managerTabs = new Set<WorkspaceTab>(['materials', 'applications', 'reviews']);
const pointer = (value: string | null) => value && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/.test(value) && !value.includes('..') ? value : '';
export function readWorkspaceRoute(url: URL, manager: boolean): WorkspaceRoute {
  const requested = url.searchParams.get('tab');
  const tab = requested && Object.hasOwn(workspaceTabs, requested) ? requested as WorkspaceTab : 'catalog';
  const mode = url.searchParams.get('mode');
  return { tab: !manager && managerTabs.has(tab) ? 'catalog' : tab, task: pointer(url.searchParams.get('task')), run: pointer(url.searchParams.get('run')), ...(pointer(url.searchParams.get('project')) ? { project: pointer(url.searchParams.get('project')) } : {}), ...(mode === 'personal' || mode === 'managed' ? { mode } : {}) };
}
export function workspaceUrl(current: URL, route: WorkspaceRoute): string {
  const url = new URL(current);
  url.searchParams.set('tab', route.tab);
  for (const key of ['task', 'run', 'project'] as const) {
    if (route[key]) url.searchParams.set(key, route[key]!); else url.searchParams.delete(key);
  }
  if (route.mode) url.searchParams.set('mode', route.mode); else url.searchParams.delete('mode');
  return `${url.pathname}${url.search}${url.hash}`;
}
export function sameWorkspaceRoute(left: WorkspaceRoute, right: WorkspaceRoute) {
  return left.tab === right.tab && left.task === right.task && left.run === right.run && (left.project ?? '') === (right.project ?? '') && left.mode === right.mode;
}
