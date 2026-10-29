import { useState } from 'react';
import { authEpoch } from '../../../browserAuth.js';
import { draftKey, readStored, writeStored } from '../researchSessionStorage.js';

export const projectDraftKey = (ownerId: string, projectId: string, goalVersion: number, target: string) => draftKey(ownerId, `project:${encodeURIComponent(projectId)}:${goalVersion}:${target}`);

export function useProjectDraft<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => readStored(key, initial));
  const [saved, setSaved] = useState(true);
  const [epoch] = useState(authEpoch);
  function change(next: T) {
    if (epoch !== authEpoch()) return;
    setValue(next);
    setSaved(writeStored(key, next));
  }
  return { value, change, saved };
}
