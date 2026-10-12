import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { connectRanked } from '../games/ranked';
class Socket {
  static OPEN = 1;
  static instances: Socket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  send = vi.fn();
  constructor(public url: string) {
    Socket.instances.push(this);
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  message(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
  close(code = 1000) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}
beforeEach(() => {
  vi.useFakeTimers();
  Socket.instances = [];
  vi.stubGlobal('WebSocket', Socket);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
describe('Ranked private transport', () => {
  it('starts Connecting, receives participant state, heartbeats and reconnects', async () => {
    const state = vi.fn(),
      status = vi.fn(),
      error = vi.fn();
    const close = connectRanked('/ws/matches/id/', state, status, error);
    expect(status).toHaveBeenCalledExactlyOnceWith('Connecting');
    const socket = Socket.instances[0];
    expect(socket.url).toContain('/ws/matches/id/');
    socket.open();
    expect(status).toHaveBeenLastCalledWith('Connected');
    socket.message({ type: 'state', state: { revision: 1 } });
    expect(state).toHaveBeenCalledWith({ revision: 1 });
    await vi.advanceTimersByTimeAsync(5000);
    expect(socket.send).toHaveBeenCalledWith(JSON.stringify({ type: 'heartbeat' }));
    socket.close(1006);
    expect(status).toHaveBeenLastCalledWith('Reconnecting');
    await vi.advanceTimersByTimeAsync(2000);
    expect(Socket.instances).toHaveLength(2);
    close();
    await vi.advanceTimersByTimeAsync(10000);
    expect(Socket.instances).toHaveLength(2);
  });
  it('stops retries and ignores late states after access denial', async () => {
    const state = vi.fn(),
      status = vi.fn(),
      error = vi.fn();
    const close = connectRanked('/ws/ranked/queue/ticket/', state, status, error);
    const socket = Socket.instances[0];
    socket.open();
    socket.message({
      type: 'access_denied',
      detail: 'Grace expired.',
      code: 'reconnect_expired',
      status: 403,
    });
    expect(error).toHaveBeenCalledWith(expect.objectContaining({ code: 'reconnect_expired' }));
    expect(status).toHaveBeenLastCalledWith('Disconnected');
    socket.message({ type: 'state', state: { revision: 9 } });
    expect(state).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(20000);
    expect(Socket.instances).toHaveLength(1);
    close();
  });
  it('stops retrying an unauthenticated handshake', async () => {
    const error = vi.fn();
    const close = connectRanked('/ws/matches/id/', vi.fn(), vi.fn(), error);
    Socket.instances[0].close(4403);
    await vi.advanceTimersByTimeAsync(20000);
    expect(Socket.instances).toHaveLength(1);
    expect(error).toHaveBeenCalledOnce();
    close();
  });
});
