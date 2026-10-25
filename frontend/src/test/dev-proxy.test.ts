import { createServer as httpServer, request, type IncomingHttpHeaders } from 'node:http';
import type { AddressInfo, Socket } from 'node:net';
import { createServer } from 'vite';
import { expect, it } from 'vitest';
import { developmentProxies } from '../../devProxy';

const browserHeaders = {
  host: '192.168.1.50:5173',
  origin: 'http://192.168.1.50:5173',
  cookie: 'sessionid=synthetic; csrftoken=synthetic',
  'x-csrftoken': 'synthetic',
  'x-forwarded-for': '203.0.113.99',
  'x-forwarded-host': 'evil.example',
  'x-forwarded-proto': 'https',
  forwarded: 'for=203.0.113.99',
};

it('proxies HTTP and WebSocket routes with preserved same-origin headers and sanitized IPs', async () => {
  const observed: { path: string; peer?: string; headers: IncomingHttpHeaders }[] = [];
  const sockets = new Set<Socket>();
  const backend = httpServer((req, res) => {
    observed.push({ path: req.url!, peer: req.socket.remoteAddress, headers: req.headers });
    res.setHeader('Set-Cookie', 'sessionid=synthetic; HttpOnly; SameSite=Lax; Path=/');
    res.end('ok');
  });
  backend.on('connection', (socket) => {
    sockets.add(socket);
    socket.on('close', () => sockets.delete(socket));
  });
  backend.on('upgrade', (req, socket) => {
    observed.push({ path: req.url!, peer: req.socket.remoteAddress, headers: req.headers });
    socket.write(
      'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n',
    );
  });
  await new Promise<void>((resolve) => backend.listen(0, '127.0.0.1', resolve));
  const backendPort = (backend.address() as AddressInfo).port;
  const vite = await createServer({
    configFile: false,
    appType: 'custom',
    optimizeDeps: { noDiscovery: true, include: [] },
    server: {
      host: '127.0.0.1',
      port: 0,
      hmr: false,
      proxy: developmentProxies(`http://127.0.0.1:${backendPort}`),
    },
  });
  try {
    await vite.listen();
    const port = (vite.httpServer!.address() as AddressInfo).port;
    for (const path of ['/api/auth/me/', '/admin/', '/static/admin/base.css']) {
      await new Promise<void>((resolve, reject) => {
        const req = request({ host: '127.0.0.1', port, path, headers: browserHeaders }, (res) => {
          expect(res.statusCode).toBe(200);
          expect(res.headers['set-cookie']?.[0]).toContain('sessionid=synthetic');
          res.resume();
          res.on('end', resolve);
        });
        req.on('error', reject);
        req.end();
      });
    }
    for (const path of [
      '/ws/account/',
      '/ws/parties/ABCDEF/',
      '/ws/matches/match-id/',
      '/ws/ranked/queue/ticket-id/',
    ]) {
      await new Promise<void>((resolve, reject) => {
        const req = request({
          host: '127.0.0.1',
          port,
          path,
          headers: { ...browserHeaders, connection: 'Upgrade', upgrade: 'websocket' },
        });
        req.on('upgrade', (res, socket) => {
          expect(res.statusCode).toBe(101);
          socket.destroy();
          resolve();
        });
        req.on('error', reject);
        req.end();
      });
    }
    expect(observed).toHaveLength(7);
    for (const entry of observed) {
      expect(entry.peer).toBe('127.0.0.2');
      expect(entry.headers['x-forwarded-for']).toBe('127.0.0.1');
      expect(entry.headers.host).toBe(browserHeaders.host);
      expect(entry.headers.origin).toBe(browserHeaders.origin);
      expect(entry.headers.cookie).toBe(browserHeaders.cookie);
      expect(entry.headers['x-csrftoken']).toBe(browserHeaders['x-csrftoken']);
      expect(entry.headers['x-forwarded-host']).toBeUndefined();
      expect(entry.headers['x-forwarded-proto']).toBeUndefined();
      expect(entry.headers.forwarded).toBeUndefined();
    }
  } finally {
    for (const socket of sockets) socket.destroy();
    await vite.close();
    await new Promise<void>((resolve) => backend.close(() => resolve()));
  }
}, 15000);
