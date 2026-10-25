import type { ClientRequest, IncomingMessage } from 'node:http';
import type { ProxyOptions } from 'vite';

export function developmentProxies(target = 'http://127.0.0.1:8000') {
  const forwardPeer = (outgoing: ClientRequest, incoming: IncomingMessage) => {
    // Replace, never append to, caller-supplied forwarding headers, including WS upgrades.
    outgoing.setHeader('X-Forwarded-For', incoming.socket.remoteAddress ?? '');
    outgoing.removeHeader('X-Forwarded-Host');
    outgoing.removeHeader('X-Forwarded-Proto');
    outgoing.removeHeader('Forwarded');
  };
  const options = (): ProxyOptions => ({
    target,
    // Django trusts ONLY this exact development proxy address when DEBUG=True.
    // Local browser peers remain distinct, so localhost also works with strict IP checks.
    ...(new URL(target).hostname === '127.0.0.1' ? { localAddress: '127.0.0.2' } : {}),
    changeOrigin: false,
    xfwd: false,
    configure(proxy) {
      proxy.on('proxyReq', forwardPeer);
      proxy.on('proxyReqWs', forwardPeer);
    },
  });
  return {
    '/api': options(),
    '/admin': options(),
    '/static': options(),
    '/ws': { ...options(), ws: true },
  };
}
