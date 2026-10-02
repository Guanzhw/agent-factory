import { useRef } from 'react';

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonical(item)]));
  return value;
}

export function useCommandKeys(ownerId: string) {
  const memory = useRef(new Map<string, string>());
  return async (operation: string, payload: unknown) => {
    const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(canonical(payload))));
    const hash = Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, '0')).join('');
    const storage = `factory-command-v2:${encodeURIComponent(ownerId)}:${operation}:${hash}`;
    let requestId = memory.current.get(storage);
    if (!requestId) {
      try { requestId = window.localStorage.getItem(storage) ?? undefined; } catch { /* Keep current-page retries available when storage is disabled. */ }
      if (!requestId || !/^[0-9a-f-]{36}$/.test(requestId)) requestId = crypto.randomUUID();
      memory.current.set(storage, requestId);
      try { window.localStorage.setItem(storage, requestId); } catch { /* Store no material, credential or connection contents. */ }
    }
    return { requestId, acknowledged() { memory.current.delete(storage); try { window.localStorage.removeItem(storage); } catch { /* A later explicit intent can still use a new key. */ } } };
  };
}
