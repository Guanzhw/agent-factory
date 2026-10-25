/* Offline delivery fixture only. No production authentication or API forwarding. */
(() => {
  const key = 'factory:offline-demo-persona';
  let persona = sessionStorage.getItem(key) ?? 'alice';
  const response = (body, status = 200) => new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  const users = { alice: { id: 'alice', name: '张予阳', role: 'user' }, bob: { id: 'bob', name: '演示 Bob', role: 'user' } };
  const data = {
    '/auth/config': { enabled: false, loginPath: '/api/factory/auth/login', logoutPath: '/api/factory/auth/logout' },
    '/status': { mode: 'demo', maxWorkers: 1, activeWorkers: 0, queuedJobs: 0, integration: 'Synthetic UI fixture', liveEnabled: false },
    '/materials': [], '/jobs': { items: [], nextCursor: null }, '/execution-targets': [],
    '/personal-models/capabilities': { enabled: false, providers: [], liveCompatibilityVerified: false },
    '/personal-models': [], '/user-connections': [], '/user-connections/registrations': [],
    '/resources/leases': { leases: [], nextCursor: null },
    '/personal-credentials/capabilities': { enabled: false, providerIds: [] },
    '/personal-ssh/capabilities': { enabled: false }, '/personal-tools/descriptors': [],
    '/personal-tools': [], '/personal-remotes/providers': [], '/personal-remotes': []
  };
  window.fetch = async (input, init = {}) => {
    const url = new URL(input instanceof Request ? input.url : input, location.href);
    const method = (init.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (url.origin !== location.origin || !url.pathname.startsWith('/api/factory/')) throw new TypeError('离线演示拒绝网络请求');
    const path = url.pathname.slice('/api/factory'.length);
    if (method === 'POST' && path === '/logout') {
      persona = 'signed-out'; sessionStorage.setItem(key, persona); return response(null, 204);
    }
    if (method === 'POST' && path === '/demo/login') {
      const body = JSON.parse(init.body ?? await input.text());
      if (!Object.hasOwn(users, body.persona)) return response({ detail: '离线演示仅提供 Alice 和 Bob；无管理员操作。' }, 403);
      persona = body.persona; sessionStorage.setItem(key, persona); return response(users[persona]);
    }
    if (method === 'GET' && path === '/session') return users[persona] ? response(users[persona]) : response({ detail: 'SIGN_IN_REQUIRED' }, 401);
    if (method === 'GET' && Object.hasOwn(data, path)) return response(data[path]);
    return response({ detail: 'OFFLINE_DEMO_UNSUPPORTED_REQUEST' }, 404);
  };
})();
