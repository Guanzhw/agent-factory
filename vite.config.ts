import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig(({ mode }) => ({ plugins: [react(), ...(['research', 'research-demo'].includes(mode) ? [{ name: 'research-entry', transformIndexHtml: { order: 'pre' as const, handler: (html: string) => html.replace('/main.tsx', mode === 'research-demo' ? '/research-demo-main.tsx' : '/research-main.tsx') } }] : [])], root: 'web', build: { outDir: '../dist', emptyOutDir: true }, server: { host: '127.0.0.1', proxy: { '^/api/': 'http://127.0.0.1:3100' } } }));
