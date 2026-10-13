import { GO_BASES } from './modelProviderConfig.js';

/** Reviewed model destinations. Other provider prefixes stay denied. */
export function modelEndpoint(input: string): string {
  const value = input.trim();
  const url = new URL(value);
  const go = GO_BASES.includes(url.origin + url.pathname);
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.port
      || (!go && url.pathname !== '/v1') || !url.hostname.includes('.') || url.hostname.endsWith('.localhost')
      || /^[\d.]+$/.test(url.hostname) || url.hostname.includes(':') || go && value !== url.origin + url.pathname) {
    throw new Error('请输入 HTTPS /v1 端点，或官方 Go 端点。');
  }
  return `${url.origin}${url.pathname}`;
}
