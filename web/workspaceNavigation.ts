export const workspaceTabs = { resources: '设置', models: '模型', connections: '连接', accounts: '成员管理' } as const;
export const connectionResources = ['servers', 'tools', 'credentials'] as const;
export type ConnectionResource = typeof connectionResources[number];
export type WorkspaceTab = string;
export type WorkspaceRoute = { tab: WorkspaceTab; [key: string]: string | undefined };
export interface WorkspaceNavigation {
  tabs: Readonly<Record<string, string>>;
  homeTab?: string;
  queryKeys?: readonly string[];
  readQuery?: (url: URL) => Record<string, string>;
}
export const defaultNavigation: WorkspaceNavigation = { tabs: workspaceTabs, homeTab: 'resources' };
export const routePointer = (value: string | null) => value && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/.test(value) && !value.includes('..') ? value : '';
export function readWorkspaceRoute(url: URL, administrator: boolean, navigation = defaultNavigation): WorkspaceRoute {
  const requested = url.searchParams.get('tab');
  const tab = requested && Object.hasOwn(navigation.tabs, requested) && (requested !== 'accounts' || administrator) ? requested : navigation.homeTab ?? 'resources';
  const resource = url.searchParams.get('resource') as ConnectionResource;
  return { ...navigation.readQuery?.(url), tab, ...(connectionResources.includes(resource) ? { resource } : {}) };
}
export function workspaceUrl(current: URL, route: WorkspaceRoute, navigation = defaultNavigation): string {
  const url = new URL(current);
  url.search = '';
  url.searchParams.set('tab', route.tab);
  for (const key of ['resource', ...navigation.queryKeys ?? []]) if (route[key]) url.searchParams.set(key, route[key]);
  return `${url.pathname}${url.search}${url.hash}`;
}
export function sameWorkspaceRoute(left: WorkspaceRoute, right: WorkspaceRoute) {
  return [...new Set([...Object.keys(left), ...Object.keys(right)])].every(key => (left[key] ?? '') === (right[key] ?? ''));
}
