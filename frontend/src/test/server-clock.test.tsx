import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ServerClock } from '../games/serverClock';
import { useServerTime } from '../games/useRanked';
const epoch = Date.parse('2026-10-12T12:00:00Z');
const stamp = (ms: number) => new Date(epoch + ms).toISOString();
afterEach(() => vi.useRealTimers());
it('compensates symmetric latency without depending on the browser wall clock', () => {
  const a = new ServerClock(),
    b = new ServerClock();
  a.sample(stamp(100), 0, 200);
  b.sample(stamp(300), 200, 400);
  expect(a.now(500)).toBe(epoch + 500);
  expect(b.now(500)).toBe(epoch + 500);
});
it('rejects bad samples, favors low RTT, and slews a changed reconnect estimate monotonically', () => {
  const clock = new ServerClock();
  clock.sample(stamp(50), 0, 100);
  clock.sample(stamp(5000), 100, 1100); // queued/high-latency sample
  clock.sample('invalid', 0, 200);
  expect(clock.now(1100)).toBe(epoch + 1100);
  clock.sample(stamp(31300), 31100, 31200); // expired selection, different path
  const before = clock.now(31200);
  expect(clock.now(32200) - before).toBeGreaterThanOrEqual(900);
  expect(clock.now(32200) - before).toBeLessThanOrEqual(1100);
});
it('keeps the 45-second countdown and five-second results clock stable across delayed snapshots', () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'performance'] });
  const clock = new ServerClock();
  clock.sample(stamp(100), 0, 200);
  const view = renderHook(({ server }) => useServerTime(server, clock), {
    initialProps: { server: stamp(0) },
  });
  act(() => vi.advanceTimersByTime(1000));
  expect(view.result.current).toBe(epoch + 1000);
  view.rerender({ server: stamp(300) }); // late snapshot must not rewind/reset
  act(() => vi.advanceTimersByTime(1000));
  expect(view.result.current).toBe(epoch + 2000);
  expect(Math.ceil((epoch + 45000 - view.result.current) / 1000)).toBe(43);
  act(() => vi.advanceTimersByTime(3000));
  expect(Math.ceil((epoch + 5000 - view.result.current) / 1000)).toBe(0);
});
