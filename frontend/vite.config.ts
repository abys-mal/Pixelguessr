import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';
import { loadEnv } from 'vite';
import { defineConfig } from 'vitest/config';
import { developmentProxies } from './devProxy.ts';

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: {
    port: Number(
      loadEnv(mode, fileURLToPath(new URL('..', import.meta.url)), 'DEV_').DEV_FRONTEND_PORT ||
        5173,
    ),
    strictPort: true,
    proxy: developmentProxies(process.env.API_PROXY_TARGET),
  },
  test: { environment: 'jsdom', setupFiles: ['./src/test/setup.ts'], restoreMocks: true },
}));
