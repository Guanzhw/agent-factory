import { factoryRequest } from './api.js';

export interface Account { id: string; name: string; email: string | null; disabled: boolean; accountAdmin: boolean }
export type AccountChange = Partial<Pick<Account, 'name' | 'disabled' | 'accountAdmin'>> & { email?: string };
export const accountApi = {
  list: (offset = 0, signal?: AbortSignal) => factoryRequest<{ accounts: Account[]; total: number }>(`/accounts?limit=100&offset=${offset}`, 'GET', undefined, signal),
  create: (input: { id: string; name?: string; email?: string; accountAdmin?: boolean }) => factoryRequest<Account>('/accounts', 'POST', input),
  update: (id: string, input: AccountChange) => factoryRequest<Account>(`/accounts/${encodeURIComponent(id)}`, 'PATCH', input),
};
