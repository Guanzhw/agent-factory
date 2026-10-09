import type { PersonalCredential } from './personalRemoteApi.js';

const identifier = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_.:@-]{1,200}$/.test(value);
export function credentialDestination(value: string): string {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/' || value !== url.origin) throw new Error('Invalid destination');
  return url.origin;
}
// Project only the current public vault receipt. Never render unexpected fields.
export function credentialReceipt(value: unknown): PersonalCredential {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid receipt');
  const row = value as PersonalCredential;
  const fields = ['credentialRef', 'credentialRevision', 'providerId', 'destination', 'status'];
  if (Object.keys(value).length !== fields.length || Object.keys(value).some(key => !fields.includes(key)) ||
      ![row.credentialRef, row.credentialRevision, row.providerId].every(identifier) || !['active', 'revoked'].includes(row.status) || typeof row.destination !== 'string') throw new Error('Invalid receipt');
  credentialDestination(row.destination);
  return { credentialRef: row.credentialRef, credentialRevision: row.credentialRevision, providerId: row.providerId, destination: row.destination, status: row.status };
}
export interface CredentialCommand {
  owner: string; action: 'create' | 'rotate' | 'revoke'; requestId: string;
  providerId: string; destination: string; credentialRef?: string; credentialRevision?: string;
}
export function readCredentialCommand(raw: string | null, owner: string): CredentialCommand | null {
  try {
    const value = JSON.parse(raw ?? 'null') as CredentialCommand;
    if (!value || value.owner !== owner || !identifier(value.requestId) || !identifier(value.providerId) || !['create', 'rotate', 'revoke'].includes(value.action)) return null;
    const fields = ['owner', 'action', 'requestId', 'providerId', 'destination', ...(value.action === 'create' ? [] : ['credentialRef', 'credentialRevision'])];
    if (Object.keys(value).length !== fields.length || Object.keys(value).some(key => !fields.includes(key)) ||
        value.action !== 'create' && (!identifier(value.credentialRef) || !identifier(value.credentialRevision))) return null;
    credentialDestination(value.destination); return value;
  } catch { return null; }
}
export function matchCredentialReceipt(value: unknown, command: CredentialCommand): PersonalCredential {
  const row = credentialReceipt(value);
  if (row.providerId !== command.providerId || row.destination !== command.destination ||
      command.action !== 'create' && row.credentialRef !== command.credentialRef ||
      command.action === 'rotate' && row.credentialRevision === command.credentialRevision ||
      command.action === 'revoke' && (row.status !== 'revoked' || row.credentialRevision !== command.credentialRevision) ||
      command.action !== 'revoke' && row.status !== 'active') throw new Error('Mismatched receipt');
  return row;
}
export function readUnresolvedCommands(raw: string | null, owner: string): CredentialCommand[] {
  try {
    const values: unknown = JSON.parse(raw ?? '[]');
    if (!Array.isArray(values) || values.length > 100) return [];
    return values.map(value => readCredentialCommand(JSON.stringify(value), owner)).filter((value): value is CredentialCommand => value !== null);
  } catch { return []; }
}
