/** Generic workspace views; unknown retired application URLs return to the catalog. */
export const workspaceTabs = {
  catalog: '应用', resources: '我的资源', models: '我的模型/API', developer: '开发者装配', tasks: '我的任务',
  connections: '我的凭据与连接', schedules: '计划任务', storage: '存储与回收',
  materials: '共享材料管理', applications: '应用管理', reviews: '历史方案审查', accounts: '账号管理',
} as const;
export type WorkspaceTab = string;
export type ResourceSection = 'servers' | 'credentials' | 'tools' | 'remotes' | 'advanced';
export const resourceSection = (value: string | null | undefined): ResourceSection =>
  ['servers', 'credentials', 'tools', 'remotes', 'advanced'].includes(value ?? '') ? value as ResourceSection : 'servers';
export type WorkspaceRoute = { tab: WorkspaceTab; task: string; modelReturn?: string; resource?: ResourceSection; [key: string]: string | undefined };
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
  return { ...navigation.readQuery?.(url), tab,
    task: routePointer(url.searchParams.get('task')),
    ...(tab === 'connections' || url.searchParams.has('resource') ? { resource: resourceSection(url.searchParams.get('resource')) } : {}),
    ...(modelReturn && modelReturns.includes(modelReturn) ? { modelReturn } : {}) };
}
export function workspaceUrl(current: URL, route: WorkspaceRoute, navigation = defaultNavigation): string {
  const url = new URL(current);
  url.searchParams.set('tab', route.tab);
  for (const key of ['task', 'modelReturn', 'resource', ...navigation.queryKeys ?? []]) {
    if (route[key]) url.searchParams.set(key, route[key]); else url.searchParams.delete(key);
  }
  return `${url.pathname}${url.search}${url.hash}`;
}
/** An application source is display/navigation metadata, never execution authority. */
export function applicationReturn(route: WorkspaceRoute, navigation: WorkspaceNavigation) {
  const tab = route.modelReturn;
  return tab && navigation.modelReturns?.includes(tab) && navigation.applicationTabs?.includes(tab) && navigation.tabs[tab]
    ? { tab, label: navigation.tabs[tab] } : undefined;
}
export function clearApplicationContext(navigation: WorkspaceNavigation): Partial<WorkspaceRoute> {
  return { modelReturn: undefined, resource: undefined, ...Object.fromEntries((navigation.queryKeys ?? []).map(key => [key, ''])) };
}
export function sameWorkspaceRoute(left: WorkspaceRoute, right: WorkspaceRoute) {
  return [...new Set([...Object.keys(left), ...Object.keys(right)])].every(key => (left[key] ?? '') === (right[key] ?? ''));
}
