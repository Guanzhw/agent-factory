import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { test } from 'node:test';
import { checkArchitecture } from './check_web_architecture.mjs';

function fixture(t) {
  const root = mkdtempSync(path.join(os.tmpdir(), 'web-boundary-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  function write(files) {
    for (const [name, contents] of Object.entries(files)) {
      const filename = path.join(root, name);
      mkdirSync(path.dirname(filename), { recursive: true });
      writeFileSync(filename, contents + '\n');
    }
  }
  const config = { source_roots: ['src'], core: ['src/web'], apps: {
    alpha: { path: 'src/apps/alpha', public: ['src/apps/alpha/api.ts'] },
    beta: { path: 'src/apps/beta', public: ['src/apps/beta/api.ts'] },
  }, composition_roots: ['src/web/composition.tsx', 'src/web/main.tsx'] };
  write({
    'tsconfig.json': JSON.stringify({ compilerOptions: { module: 'NodeNext', moduleResolution: 'NodeNext', jsx: 'react-jsx',
      baseUrl: '.', paths: { '@alpha/*': ['src/apps/alpha/*'] } }, include: ['src/**/*'] }),
    'package.json': '{"type":"module"}',
    'src/web/runtime.ts': "import { value } from '../shared/helper.js'; export { value };",
    'src/shared/helper.ts': 'export const value = 1;',
    'src/apps/alpha/api.ts': "export { value } from '../beta/api.js';",
    'src/apps/beta/api.ts': "export { value } from './private.js';",
    'src/apps/beta/private.ts': 'export const value = 2;',
    'src/web/composition.tsx': "export { value } from '../apps/alpha/api.js';",
    'src/web/main.tsx': "import './composition.js';",
  });
  return { root, config, write, check: () => checkArchitecture(root, config) };
}

const chains = result => result.violations.map(violation => violation.chain.join(' -> '));

test('legal shared helpers, exact public APIs, and exact composition', t => {
  const f = fixture(t);
  f.write({ 'src/web/runtime.ts': "import { value } from '../shared/helper.js';\nconst label = 'import appPrivate';\n// require('../apps/beta/private.js')\nexport { value, label };" });
  const result = f.check();
  assert.equal(result.accepted, true);
  assert.deepEqual(result.gaps, []);
});

test('bootstrap can load composition but core and apps cannot import bootstrap through helpers', t => {
  const f = fixture(t);
  const legal = f.check();
  assert.equal(legal.accepted, true);
  assert.ok(legal.graph.get('src/web/main.tsx').some(edge => edge.target === 'src/web/composition.tsx'));
  f.write({ 'src/shared/helper.ts': "import '../web/main.js'; export const value = 1;" });
  const core = f.check();
  assert.equal(core.accepted, false);
  assert.ok(chains(core).includes('src/web/runtime.ts -> src/shared/helper.ts -> src/web/main.tsx'));
  assert.deepEqual(core.gaps, []);
  f.write({ 'src/apps/alpha/api.ts': "export { value } from '../../shared/helper.js';" });
  const app = f.check();
  assert.equal(app.accepted, false);
  assert.ok(chains(app).includes('src/apps/alpha/api.ts -> src/shared/helper.ts -> src/web/main.tsx'));
  assert.deepEqual(app.gaps, []);
});

test('direct app dependency resolves a tsconfig alias and CLI explains the import', t => {
  const f = fixture(t);
  f.write({ 'src/web/runtime.ts': "import { value } from '@alpha/api.js'; export { value };", 'map.json': JSON.stringify(f.config) });
  assert.ok(chains(f.check()).includes('src/web/runtime.ts -> src/apps/alpha/api.ts'));
  const run = spawnSync(process.execPath, [fileURLToPath(new URL('./check_web_architecture.mjs', import.meta.url)),
    '--root', f.root, '--config', path.join(f.root, 'map.json')], { encoding: 'utf8' });
  assert.equal(run.error, undefined, `Architecture CLI spawn failed: ${run.error?.code ?? run.error?.name ?? 'unknown'}`);
  assert.equal(run.signal, null, `Architecture CLI terminated by signal: ${run.signal}`);
  assert.equal(run.status, 1, run.stderr);
  assert.match(run.stderr, /src\/web\/runtime\.ts:1 -> src\/apps\/alpha\/api\.ts/);
  assert.match(run.stderr, /Fix: Core reaches application code/);
  assert.equal(JSON.parse(run.stdout).accepted, false);
  f.write({ 'package.json': JSON.stringify({ type: 'module', imports: { '#entry': {
    import: './src/apps/alpha/api.ts', require: './src/shared/helper.ts',
  } } }), 'src/web/runtime.ts': "import '#entry';" });
  assert.ok(chains(f.check()).includes('src/web/runtime.ts -> src/apps/alpha/api.ts'));
  f.write({ 'src/web/runtime.ts': "require('#entry');" });
  assert.equal(f.check().accepted, true);
  f.write({ 'tsconfig.json': JSON.stringify({ compilerOptions: { module: 'NodeNext', moduleResolution: 'NodeNext',
    baseUrl: '.', paths: { fs: ['src/apps/alpha/api.ts'] } }, include: ['src/**/*'] }),
    'src/web/runtime.ts': "import 'fs';" });
  assert.ok(chains(f.check()).includes('src/web/runtime.ts -> src/apps/alpha/api.ts'));
});

test('indirect re-export through an unowned adapter cannot hide application dependency', t => {
  const f = fixture(t);
  f.write({ 'src/shared/helper.ts': "export * from '../adapters/barrel.js';",
    'src/adapters/barrel.ts': "export { value } from '../apps/alpha/api.js';" });
  assert.ok(chains(f.check()).includes('src/web/runtime.ts -> src/shared/helper.ts -> src/adapters/barrel.ts -> src/apps/alpha/api.ts'));
});

test('cross-app private imports fail directly and through shared code; public permission is exact', t => {
  const f = fixture(t);
  f.write({ 'src/apps/alpha/api.ts': "export { value } from '../../shared/bridge.js';",
    'src/shared/bridge.ts': "export * from '../apps/beta/private.js';" });
  assert.ok(chains(f.check()).includes('src/apps/alpha/api.ts -> src/shared/bridge.ts -> src/apps/beta/private.ts'));
  f.write({ 'src/apps/alpha/api.ts': "export { value } from '../beta/private.js';" });
  assert.ok(chains(f.check()).includes('src/apps/alpha/api.ts -> src/apps/beta/private.ts'));
  f.config.apps.beta.public = ['src/apps/beta'];
  assert.throws(() => f.check(), /exact source file/);
});

test('composition can wire app implementations but never exempts callers or sibling files', t => {
  const f = fixture(t);
  f.write({ 'src/web/runtime.ts': "export * from './composition.js';",
    'src/web/composition-extra.tsx': "export * from '../apps/alpha/api.js';",
    'src/web/main-extra.tsx': "export * from '../apps/alpha/api.js';" });
  const result = f.check();
  assert.ok(chains(result).includes('src/web/runtime.ts -> src/web/composition.tsx'));
  assert.ok(chains(result).includes('src/web/composition-extra.tsx -> src/apps/alpha/api.ts'));
  assert.ok(chains(result).includes('src/web/main-extra.tsx -> src/apps/alpha/api.ts'));
  f.write({ 'src/web/composition.tsx': "export * from '../apps/beta/private.js';" });
  assert.ok(!chains(f.check()).includes('src/web/composition.tsx -> src/apps/beta/private.ts'));
  f.config.composition_roots = ['src/web'];
  assert.throws(() => f.check(), /one exact source file/);
});

test('literal dynamic imports, require, import-equals and type dependencies are edges', t => {
  const f = fixture(t);
  for (const code of [
    "import('../apps/alpha/api.js');", "import(`../apps/alpha/api.js`);",
    "require('../apps/alpha/api.js');", "import app = require('../apps/alpha/api.js');",
    "import type { Value } from '../apps/alpha/api.js';", "type App = import('../apps/alpha/api.js');",
  ]) {
    f.write({ 'src/web/runtime.ts': code });
    assert.ok(chains(f.check()).includes('src/web/runtime.ts -> src/apps/alpha/api.ts'), code);
  }
  f.write({ 'src/web/runtime.ts': "function local(require: (value: string) => void) { require('ordinary-data'); }" });
  assert.equal(f.check().accepted, true);
});

test('coverage gaps are limited to protected origins and their reachable helpers', t => {
  const f = fixture(t);
  f.write({ 'src/tests/unrelated.ts': 'import(target);' });
  assert.equal(f.check().accepted, true);
  f.write({ 'src/shared/helper.ts': "import '../tests/unrelated.js'; export const value = 1;" });
  assert.equal(f.check().gaps[0].module, 'src/tests/unrelated.ts');
  f.write({ 'src/tests/unrelated.ts': '', 'src/apps/beta/unused-private.ts': 'require(target);' });
  assert.equal(f.check().gaps[0].module, 'src/apps/beta/unused-private.ts');
  f.write({ 'src/apps/beta/unused-private.ts': '', 'src/web/runtime.ts': "import '@alpha/missing.js';" });
  assert.match(f.check().gaps[0].message, /Cannot resolve dependency/);
  f.write({ 'src/web/runtime.ts': "import '../../outside.js';", 'outside.ts': 'export const value = 1;' });
  assert.match(f.check().gaps[0].message, /outside source_roots/);
});

test('cycles terminate; path ownership is bounded and invalid/empty maps fail', t => {
  const f = fixture(t);
  f.write({ 'src/shared/helper.ts': "import '../web/runtime.js'; export const value = 1;",
    'src/web2/unowned.ts': "import '../apps/beta/private.js';" });
  assert.equal(f.check().accepted, true);
  const original = structuredClone(f.config);
  f.config.apps.alpha = { path: 'src/web', public: ['src/web/runtime.ts'] };
  assert.throws(() => f.check(), /cannot replace core/);
  Object.assign(f.config, original);
  f.config.core = [];
  assert.throws(() => f.check(), /nonempty/);
});

test('bundler glob discovery in composition or reachable code fails explicitly; text and comments are harmless', t => {
  const f = fixture(t);
  f.write({ 'src/web/composition.tsx': `// import.meta.glob('../apps/*/api.ts')
const documentation = "import.meta.glob('../apps/*/api.ts')";
export { value } from '../apps/alpha/api.js';` });
  assert.equal(f.check().accepted, true);
  for (const code of ["import.meta.glob('../apps/*/api.ts')", "import.meta['glob']('../apps/*/api.ts')", "const discover = import.meta.glob; discover(pattern)"]) {
    f.write({ 'src/web/composition.tsx': code });
    const result = f.check();
    assert.equal(result.accepted, false, code);
    assert.match(result.gaps[0].message, /Bundler glob discovery/);
    assert.equal(result.gaps[0].module, 'src/web/composition.tsx');
  }
  f.write({ 'src/web/composition.tsx': "export { value } from '../apps/alpha/api.js';",
    'src/shared/helper.ts': "export const value = import.meta.glob('./*.ts');" });
  assert.equal(f.check().gaps[0].module, 'src/shared/helper.ts');
});


test('standalone core allows no installed applications and still checks composition imports', t => {
  const f = fixture(t);
  f.config.source_roots = ['src/web', 'src/shared'];
  f.config.core = ['src/web', 'src/shared'];
  f.config.apps = {};
  f.write({ 'src/web/composition.tsx': 'export const installed = [];',
    'src/shared/helper.ts': 'export const value = 1;' });
  assert.equal(f.check().accepted, true);
  f.write({ 'src/shared/helper.ts': "import '../web/main.js'; export const value = 1;" });
  assert.equal(f.check().accepted, false);
  f.config.core = [];
  assert.throws(() => f.check(), /nonempty core/);
});
