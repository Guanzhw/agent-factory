/** Reviewed Chat Completions destinations. Other provider prefixes stay denied. */
export function modelEndpoint(input: string): string {
  const value = input.trim();
  const url = new URL(value);
  const go = url.origin === 'https://opencode.ai' && url.pathname === '/zen/go/v1';
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.port
      || (!go && url.pathname !== '/v1') || !url.hostname.includes('.') || url.hostname.endsWith('.localhost')
      || /^[\d.]+$/.test(url.hostname) || url.hostname.includes(':') || go && value !== 'https://opencode.ai/zen/go/v1') {
    throw new Error('请输入 HTTPS /v1 端点，或官方 Go 端点 https://opencode.ai/zen/go/v1。');
  }
  return `${url.origin}${url.pathname}`;
}
