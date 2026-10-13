import { defineConfig } from 'vitest/config';
export default defineConfig({ test: { include: ['tests/**/*.test.ts', 'apps/*/tests/web/**/*.test.ts'], testTimeout: 20000, pool: 'forks' } });
