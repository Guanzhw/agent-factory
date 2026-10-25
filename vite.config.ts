import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig(({ mode }) => ({ plugins: [react(), ...(mode === 'research' ? [{ name: 'research-entry', transformIndexHtml: { order: 'pre' as const, handler: (html: string) => html.replace('/main.tsx', '/research-main.tsx') } }] : [])], root: 'web', build: { outDir: '../dist', emptyOutDir: true }, server: { host: '127.0.0.1', proxy: { '^/api/': 'http://127.0.0.1:3100' } } }));
