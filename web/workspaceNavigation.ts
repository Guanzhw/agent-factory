/** Generic workspace views; unknown retired application URLs return to the catalog. */
export const workspaceTabs = {
  catalog: '应用', resources: '我的资源', models: '我的模型/API', developer: '高级装配', tasks: '我的任务',
  connections: '我的凭据与连接', schedules: '计划任务', storage: '存储与回收',
  materials: '共享材料', applications: '应用模板', reviews: '历史方案记录', accounts: '账号管理',
} as const;
export const connectionResources = ['servers', 'tools', 'remotes', 'credentials', 'records'] as const;
export type ConnectionResource = typeof connectionResources[number];
export type WorkspaceTab = string;
export type WorkspaceRoute = { tab: WorkspaceTab; task: string; modelReturn?: string; taskReturn?: string; taskReturnTask?: string; scheduleId?: string; [key: string]: string | undefined };
export interface WorkspaceNavigation {
  tabs: Readonly<Record<string, string>>;
  applicationTabs?: readonly string[];
  advancedTabs?: readonly string[];
  modelReturns?: readonly string[];
  queryKeys?: readonly string[];
  readQuery?: (url: URL) => Record<string, string>;
}
export const defaultNavigation: WorkspaceNavigation = { tabs: workspaceTabs };
export const routePointer = (value: string | null) => value && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/.test(value) && !value.includes('..') ? value : '';
/** URL pointers are navigation only. Every record still needs server authorization. */
export function readWorkspaceRoute(url: URL, administrator: boolean, navigation = defaultNavigation): WorkspaceRoute {
  const requested = url.searchParams.get('tab');
  const tab = requested && Object.hasOwn(navigation.tabs, requested) && (requested !== 'accounts' || administrator) ? requested : 'catalog';
  const modelReturn = url.searchParams.get('modelReturn');
  const modelReturns = navigation.modelReturns ?? ['catalog', 'resources', 'connections'];
  const task = routePointer(url.searchParams.get('task'));
  const scheduleId = routePointer(url.searchParams.get('scheduleId'));
  const taskReturn = url.searchParams.get('taskReturn');
  const taskReturnTask = routePointer(url.searchParams.get('taskReturnTask'));
  const hasTaskReturn = tab === 'tasks' && !!task && taskReturnTask === task
    && (taskReturn === 'schedules' ? !!scheduleId : !!taskReturn && navigation.applicationTabs?.includes(taskReturn));
  return { ...navigation.readQuery?.(url), tab,
    task, ...(scheduleId ? { scheduleId } : {}),
    ...(hasTaskReturn ? { taskReturn: taskReturn!, taskReturnTask } : {}),
    ...(connectionResources.includes(url.searchParams.get('resource') as ConnectionResource) ? { resource: url.searchParams.get('resource')! } : {}),
    ...(modelReturn && modelReturns.includes(modelReturn) ? { modelReturn } : {}) };
}
export function workspaceUrl(current: URL, route: WorkspaceRoute, navigation = defaultNavigation): string {
  const url = new URL(current);
  url.searchParams.set('tab', route.tab);
  for (const key of ['task', 'modelReturn', 'resource', 'taskReturn', 'taskReturnTask', 'scheduleId', ...navigation.queryKeys ?? []]) {
    if (route[key]) url.searchParams.set(key, route[key]); else url.searchParams.delete(key);
  }
  return `${url.pathname}${url.search}${url.hash}`;
}
export function sameWorkspaceRoute(left: WorkspaceRoute, right: WorkspaceRoute) {
  return [...new Set([...Object.keys(left), ...Object.keys(right)])].every(key => (left[key] ?? '') === (right[key] ?? ''));
}
