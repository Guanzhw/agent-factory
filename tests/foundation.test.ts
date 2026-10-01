import { describe, expect, it, vi } from 'vitest';
import request from 'supertest';
import { createApp, createRuntimeClient, integrationPins } from '../server/app.js';

describe('foundation boundaries', () => {
  it('reports a healthy foundation without claiming real research ran', async () => {
    const response = await request(createApp()).get('/api/status');
    expect(response.status).toBe(200);
    expect(response.body.stage).toBe('M1');
    expect(response.body.liveResearchVerified).toBe(false);
    expect(response.body.integrationPins.openResearchRevision).toBe(integrationPins.openResearchRevision);
  });
  it('does not fall back from unknown API routes into frontend HTML', async () => {
    const response = await request(createApp()).get('/api/jobs');
    expect(response.status).toBe(404);
    expect(response.type).toBe('application/json');
  });
  it('constructs the actual v2 client without network or model use', () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    const client = createRuntimeClient();
    expect(typeof client.session.create).toBe('function');
    expect(typeof client.session.abort).toBe('function');
    expect(typeof client.event.subscribe).toBe('function');
    expect(fetchMock).not.toHaveBeenCalled();
    fetchMock.mockRestore();
  });
  it('rejects non-loopback and non-http initial endpoints', () => {
    expect(() => createRuntimeClient('http://example.com')).toThrow('loopback');
    expect(() => createRuntimeClient('https://localhost')).toThrow('loopback');
  });
});
