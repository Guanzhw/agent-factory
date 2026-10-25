import { defineConfig } from 'vitest/config';
export default defineConfig({ test: { include: ['tests/**/*.test.ts', 'web/apps/**/*.test.ts'], testTimeout: 20000, pool: 'forks' } });
