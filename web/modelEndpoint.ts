/** Normalize a member-configured HTTP(S) model API base. */
export function modelEndpoint(input: string): string {
  const value = input.trim();
  if (/[\s\\?#]/.test(value) || value.split('/').some(part => part === '.' || part === '..')) throw new Error('请输入有效的 HTTP(S) 模型 API 地址。');
  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) throw new Error('请输入有效的 HTTP(S) 模型 API 地址。');
  return `${url.origin}${url.pathname.replace(/\/+$/, '')}`;
}
