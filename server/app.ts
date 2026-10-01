import express from 'express';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createOpencodeClient } from '@opencode-ai/sdk/v2';

export const integrationPins = {
  opencodeSdk: '1.18.34',
  opencodeImport: '@opencode-ai/sdk/v2',
  openResearchRevision: 'f336b121525d99364e2dee4fe90b2784894a54e6',
};

export function createApp() {
  const app = express();
  app.disable('x-powered-by');
  app.use((_req, res, next) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'");
    next();
  });
  app.get('/api/health', (_req, res) => res.json({ status: 'ok', stage: 'M1', modelCalls: 'disabled' }));
  app.get('/api/status', (_req, res) => res.json({
    name: 'Agent Factory', stage: 'M1', runtime: process.version,
    integrationPins, liveResearchVerified: false,
    features: [
      { phase: 'M1', title: 'Foundation', state: 'implemented', detail: 'TypeScript, React, local API, pinned dependencies and CI checks' },
      { phase: 'M2', title: 'Factory core', state: 'planned', detail: 'Roles, versioned definitions, bindings, durable jobs, scheduling and audit' },
      { phase: 'M3', title: 'Auto-Research', state: 'planned', detail: 'Literature and experiments, SDK sessions, scoped approvals and evidence' },
      { phase: 'M4', title: 'Acceptance', state: 'planned', detail: 'Recovery, isolation, browser workflows and deployment readiness' },
    ],
  }));
  app.use('/api', (_req, res) => res.status(404).json({ error: 'API route does not exist' }));
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  app.use(express.static(path.join(root, 'dist')));
  app.get('/{*path}', (_req, res) => res.sendFile(path.join(root, 'dist', 'index.html')));
  return app;
}

// Creating the client configures the intended network-v2 integration only.
// It sends no request, starts no OpenCode server and invokes no model.
export function createRuntimeClient(baseUrl = 'http://127.0.0.1:4096') {
  const url = new URL(baseUrl);
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) {
    throw new Error('The initial integration requires a loopback OpenCode endpoint');
  }
  return createOpencodeClient({ baseUrl, throwOnError: true });
}
