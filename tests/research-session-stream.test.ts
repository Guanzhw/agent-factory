import { afterEach, expect, it, vi } from 'vitest';
import { researchSessionsApi } from '../web/apps/research/researchSessionsClient.js';

const session = { id: 's', state: 'running', turns: [], allowedActions: ['stop'], sharedSourceIds: [] };
afterEach(() => vi.unstubAllGlobals());
function source(text: string) {
  const bytes = new TextEncoder().encode(text);
  return new Response(new ReadableStream({ start(controller) {
    // Byte-sized chunks cross UTF-8, CRLF and JSON boundaries.
    for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
    controller.close();
  } }), { headers: { 'Content-Type': 'text/event-stream' } });
}
it('reads fragmented SSE snapshots in order with owner association and no mutation', async () => {
  const changed = { ...session, title: '实际进度', state: 'stopped' };
  const fetch = vi.fn().mockResolvedValue(source(`: heartbeat\r\n\r\nevent: session\r\ndata: ${JSON.stringify(session)}\r\n\r\nevent: session\r\ndata: ${JSON.stringify(changed)}\r\n\r\n`));
  vi.stubGlobal('fetch', fetch); const receive = vi.fn();
  await expect(researchSessionsApi.watch('alice', 's', new AbortController().signal, receive)).rejects.toThrow('实时连接已断开');
  expect(receive.mock.calls.map(call => call[0].state)).toEqual(['running', 'stopped']);
  expect(receive.mock.calls[1][0].title).toBe('实际进度');
  expect(fetch).toHaveBeenCalledWith('/api/factory/research/sessions/s/events', expect.objectContaining({ headers: { Accept: 'text/event-stream', 'X-Factory-Expected-Owner': 'alice' } }));
});
it('rejects another session snapshot instead of displaying its content', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(source(`event: session\ndata: ${JSON.stringify({ ...session, id: 'another-session' })}\n\n`)));
  const receive = vi.fn();
  await expect(researchSessionsApi.watch('alice', 's', new AbortController().signal, receive)).rejects.toThrow('会话回执无法核对');
  expect(receive).not.toHaveBeenCalled();
});
