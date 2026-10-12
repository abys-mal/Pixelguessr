import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { connectParty, partyApi, type PartyState } from '../games/parties';

class Socket {
  static OPEN = 1;
  static instances: Socket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  send = vi.fn();
  constructor(public url: string) {
    Socket.instances.push(this);
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  message(value: unknown) {
    this.onmessage?.({ data: JSON.stringify(value) });
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
}
const data = { round_id: 'opaque-round', guess: 'beacon', request_id: 'stable-request-id' };
const state = { code: 'K7M2Q9' } as PartyState;
beforeEach(() => {
  vi.useFakeTimers();
  Socket.instances = [];
  vi.stubGlobal('WebSocket', Socket);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
describe('Party WebSocket transport', () => {
  it('scopes the URL to the party, accepts state and private acknowledgements, and heartbeats', async () => {
    const onState = vi.fn(),
      onConnection = vi.fn();
    const connection = connectParty('K7M2Q9', onState, onConnection);
    const socket = Socket.instances[0];
    expect(socket.url).toContain('/ws/parties/K7M2Q9/');
    socket.open();
    socket.message({ type: 'state', state });
    expect(onState).toHaveBeenCalledWith(state);
    const reply = connection.guess(data);
    expect(JSON.parse(socket.send.mock.calls[0][0])).toEqual({ type: 'guess', ...data });
    socket.message({ type: 'guess_result', request_id: data.request_id, result: 'correct', state });
    expect((await reply).result).toBe('correct');
    await vi.advanceTimersByTimeAsync(5000);
    expect(socket.send).toHaveBeenLastCalledWith(JSON.stringify({ type: 'heartbeat' }));
    connection.close();
  });
  it('retries a lost acknowledgement by HTTP with the same request ID', async () => {
    const fallback = vi.spyOn(partyApi, 'guess').mockResolvedValue({ state, result: 'incorrect' });
    const connection = connectParty('K7M2Q9', vi.fn(), vi.fn());
    const socket = Socket.instances[0];
    socket.open();
    const pending = connection.guess(data);
    socket.close();
    expect((await pending).result).toBe('incorrect');
    expect(fallback).toHaveBeenCalledWith('K7M2Q9', data);
    await vi.advanceTimersByTimeAsync(1000);
    expect(Socket.instances).toHaveLength(2);
    connection.close();
    await vi.advanceTimersByTimeAsync(8000);
    expect(Socket.instances).toHaveLength(2);
  });
  it('does not retry authoritative cooldown rejections through HTTP', async () => {
    const fallback = vi.spyOn(partyApi, 'guess');
    const connection = connectParty('K7M2Q9', vi.fn(), vi.fn());
    const socket = Socket.instances[0];
    socket.open();
    const pending = connection.guess(data);
    socket.message({
      type: 'error',
      request_id: data.request_id,
      detail: 'Wait two seconds.',
      code: 'guess_cooldown',
      status: 429,
    });
    await expect(pending).rejects.toThrow('Wait two seconds.');
    expect(fallback).not.toHaveBeenCalled();
    connection.close();
  });
  it('falls back before the socket opens without sending an unscoped guess', async () => {
    const fallback = vi.spyOn(partyApi, 'guess').mockResolvedValue({ state, result: 'correct' });
    const connection = connectParty('K7M2Q9', vi.fn(), vi.fn());
    await connection.guess(data);
    expect(fallback).toHaveBeenCalledWith('K7M2Q9', data);
    expect(Socket.instances[0].send).not.toHaveBeenCalled();
    connection.close();
  });
});
