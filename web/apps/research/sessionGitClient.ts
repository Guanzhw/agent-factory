import { factoryRequest } from '../../api.js';
import type { ResearchSession } from './researchSessionsClient.js';

export type GitState = { configured: false } | {
  configured: true; repositoryPath: string; workspacePath: string; baseCommit: string;
  reviewId: string; files: { path: string; status: string }[]; diff: string; applied: boolean; applicationState: 'ready' | 'unknown';
};
export interface GitComment { id: string; reviewId: string; path: string; side: 'left' | 'right'; line: number; text: string; createdAt: string; turnId?: string | null }
const path = (id: string) => `/research/sessions/${encodeURIComponent(id)}/git`;
export const sessionGitApi = {
  read: (owner: string, id: string, signal?: AbortSignal) => factoryRequest<GitState>(path(id), 'GET', undefined, signal, owner),
  attach: (owner: string, id: string, repositoryPath: string) => factoryRequest<GitState>(path(id), 'POST', { repositoryPath }, undefined, owner),
  apply: (owner: string, id: string, reviewId: string) => factoryRequest<GitState>(`${path(id)}/apply`, 'POST', { reviewId }, undefined, owner),
  comments: (owner: string, id: string, signal?: AbortSignal) => factoryRequest<{ items: GitComment[] }>(`${path(id)}/comments`, 'GET', undefined, signal, owner),
  comment: (owner: string, id: string, input: Omit<GitComment, 'id' | 'createdAt' | 'turnId'> & { requestId: string }) => factoryRequest<GitComment>(`${path(id)}/comments`, 'POST', input, undefined, owner),
  review: (owner: string, id: string, reviewId: string, requestId: string, model: { modelConnectionRef: string; reasoningEffort?: string }) => factoryRequest<ResearchSession>(`${path(id)}/review`, 'POST', { reviewId, requestId, ...model }, undefined, owner),
  fork: (owner: string, id: string, turnId: string, requestId: string) => factoryRequest<ResearchSession>(`/research/sessions/${encodeURIComponent(id)}/fork`, 'POST', { turnId, requestId }, undefined, owner),
};

export interface DiffLine { text: string; kind: 'header' | 'add' | 'remove' | 'context'; path: string; oldLine?: number; newLine?: number }
export function parseGitDiff(diff: string, files: { path: string }[]): DiffLine[] {
  let path = '', fileIndex = 0, oldLine = 0, newLine = 0, inHunk = false;
  return diff.split('\n').filter((text, index, lines) => index < lines.length - 1 || text !== '').map(text => {
    if (text.startsWith('diff --git ')) { inHunk = false; path = files[fileIndex++].path; }
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(text);
    if (hunk) { oldLine = Number(hunk[1]); newLine = Number(hunk[2]); inHunk = true; }
    else if (inHunk && text.startsWith('+')) return { text, kind: 'add', path, newLine: newLine++ };
    else if (inHunk && text.startsWith('-')) return { text, kind: 'remove', path, oldLine: oldLine++ };
    else if (inHunk && text.startsWith(' ')) return { text, kind: 'context', path, oldLine: oldLine++, newLine: newLine++ };
    return { text, kind: 'header', path };
  });
}
