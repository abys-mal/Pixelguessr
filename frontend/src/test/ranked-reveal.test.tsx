import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { RankedReveal } from '../games/RankedReveal';
import type { DuelRound } from '../games/ranked';

const round: DuelRound = {
  id: 'round-a',
  number: 1,
  status: 'active',
  started_at: '2026-10-12T12:00:00Z',
  reveal_finishes_at: '2026-10-12T12:00:45Z',
  next_starts_at: null,
  winner_id: null,
  grid_size: 20,
  revealed_tiles: [17, 306],
  revealed_count: 2,
  total_tiles: 400,
  image_url: '/ranked/round-a/image/?v=2',
  guessed_ids: [],
  completion: null,
};
const decode = vi.fn<() => Promise<void>>();
const create = vi.fn<(blob: Blob) => string>();
const revoke = vi.fn<(url: string) => void>();
const fetchFrame = vi.fn<typeof fetch>();
const response = (count = 2) =>
  new Response(new Blob(['server masked pixels']), {
    headers: { 'X-Revealed-Tiles': String(count) },
  });
const flush = async () => {
  await act(async () => {});
};
const advance = async (ms: number) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};
const tiles = () => document.querySelectorAll('.game-tiles .is-revealed').length;

beforeEach(() => {
  vi.useFakeTimers();
  let serial = 0;
  create.mockReset().mockImplementation(() => `blob:frame-${++serial}`);
  revoke.mockReset();
  decode.mockReset().mockResolvedValue(undefined);
  fetchFrame.mockReset().mockImplementation(async () => response());
  vi.stubGlobal('fetch', fetchFrame);
  const OriginalURL = URL;
  vi.stubGlobal(
    'URL',
    class extends OriginalURL {
      static createObjectURL = create;
      static revokeObjectURL = revoke;
    },
  );
  vi.stubGlobal(
    'Image',
    class {
      src = '';
      decode = decode;
    },
  );
});
afterEach(() => {
  cleanup();
  expect(vi.getTimerCount()).toBe(0);
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it('keeps the decoded image and tiles while automatically recovering a temporary fetch failure', async () => {
  const view = render(<RankedReveal round={round} />);
  await flush();
  expect(tiles()).toBe(2);
  fetchFrame
    .mockRejectedValueOnce(new TypeError('connection lost'))
    .mockImplementation(async () => response(3));
  const next = { ...round, image_url: '/image/?v=3', revealed_tiles: [17, 306, 88] };
  view.rerender(<RankedReveal round={next} />);
  await flush();
  expect(screen.getByRole('alert')).toBeInTheDocument();
  expect(screen.getByRole('img')).toHaveAttribute('src', 'blob:frame-1');
  expect(tiles()).toBe(2);
  await advance(499);
  expect(fetchFrame).toHaveBeenCalledTimes(2);
  await advance(1);
  expect(fetchFrame).toHaveBeenCalledTimes(3);
  expect(tiles()).toBe(3);
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(revoke).toHaveBeenCalledWith('blob:frame-1');
});

it('retries a failed decode without treating that frame as successfully loaded', async () => {
  decode.mockRejectedValueOnce(new Error('decoder interrupted'));
  render(<RankedReveal round={round} />);
  await flush();
  expect(tiles()).toBe(0);
  expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:frame-1');
  await advance(500);
  expect(tiles()).toBe(2);
  expect(screen.getByRole('img')).toHaveAttribute('src', 'blob:frame-2');
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it.each([401, 403, 404, 410])(
  'stops automatic requests after HTTP %s, including newer snapshots, but allows manual reload',
  async (status) => {
    fetchFrame.mockResolvedValueOnce(new Response(null, { status }));
    const view = render(<RankedReveal round={round} />);
    await flush();
    view.rerender(<RankedReveal round={{ ...round, image_url: '/image/?v=3' }} />);
    await advance(60000);
    expect(fetchFrame).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
    fireEvent.click(screen.getByRole('button', { name: 'Reload picture' }));
    await flush();
    expect(fetchFrame).toHaveBeenCalledTimes(2);
    expect(tiles()).toBe(2);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  },
);

it('prioritizes the newest authorized frame without letting snapshot traffic bypass outage backoff', async () => {
  fetchFrame.mockResolvedValueOnce(new Response(null, { status: 503 }));
  const view = render(<RankedReveal round={round} />);
  await flush();
  for (let count = 3; count <= 8; count++) {
    view.rerender(
      <RankedReveal
        round={{
          ...round,
          image_url: `/image/?v=${count}`,
          revealed_tiles: Array.from({ length: count }, (_, i) => i),
        }}
      />,
    );
  }
  expect(fetchFrame).toHaveBeenCalledOnce();
  fetchFrame.mockImplementation(async () => response(8));
  await advance(500);
  expect(fetchFrame).toHaveBeenCalledTimes(2);
  expect(fetchFrame.mock.calls[1][0]).toBe('/image/?v=8');
  expect(tiles()).toBe(8);
});

it('caps repeated transient retries at eight seconds and cancels the timer on unmount', async () => {
  fetchFrame.mockImplementation(async () => new Response(null, { status: 503 }));
  const view = render(<RankedReveal round={round} />);
  await flush();
  for (const delay of [500, 1000, 2000, 4000, 8000, 8000]) await advance(delay);
  expect(fetchFrame).toHaveBeenCalledTimes(7);
  await advance(7999);
  expect(fetchFrame).toHaveBeenCalledTimes(7);
  view.unmount();
  expect(vi.getTimerCount()).toBe(0);
  await advance(60000);
  expect(fetchFrame).toHaveBeenCalledTimes(7);
});

it('deduplicates repeated snapshots during slow decoding', async () => {
  let finish!: () => void;
  decode.mockImplementationOnce(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  const view = render(<RankedReveal round={round} />);
  await flush();
  view.rerender(<RankedReveal round={{ ...round }} />);
  await advance(5000);
  expect(fetchFrame).toHaveBeenCalledOnce();
  expect(tiles()).toBe(0);
  finish();
  await flush();
  view.rerender(<RankedReveal round={{ ...round }} />);
  expect(fetchFrame).toHaveBeenCalledOnce();
  expect(tiles()).toBe(2);
});

it('aborts an old round request and ignores its late response after a new round loads', async () => {
  let resolve!: (response: Response) => void;
  fetchFrame.mockImplementationOnce(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  const view = render(<RankedReveal round={round} />);
  const signal = (fetchFrame.mock.calls[0][1] as RequestInit).signal!;
  view.rerender(
    <RankedReveal round={{ ...round, id: 'round-b', image_url: '/round-b/image/?v=2' }} />,
  );
  await flush();
  expect(signal.aborted).toBe(true);
  expect(screen.getByRole('img')).toHaveAttribute('src', 'blob:frame-1');
  resolve(response());
  await flush();
  expect(create).toHaveBeenCalledOnce();
  expect(screen.getByRole('img')).toHaveAttribute('src', 'blob:frame-1');
  view.unmount();
  expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:frame-1');
});

it('releases an in-flight decode on unmount and cannot commit a late decode', async () => {
  let finish!: () => void;
  decode.mockImplementationOnce(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  const view = render(<RankedReveal round={round} />);
  await flush();
  view.unmount();
  expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:frame-1');
  finish();
  await flush();
  expect(revoke).toHaveBeenCalledOnce();
  expect(fetchFrame).toHaveBeenCalledOnce();
});

it('automatically recovers the static full results frame, without additional snapshot URLs', async () => {
  fetchFrame
    .mockRejectedValueOnce(new TypeError('offline'))
    .mockImplementation(async () => response(400));
  const completed = {
    ...round,
    status: 'results' as const,
    revealed_count: 400,
    revealed_tiles: Array.from({ length: 400 }, (_, i) => i),
    image_url: '/image/?v=400',
    completion: { answer: 'lighthouse', license: 'CC0', attribution: 'Original drawing' },
  };
  render(<RankedReveal round={completed} />);
  await flush();
  expect(tiles()).toBe(0);
  await advance(500);
  expect(tiles()).toBe(400);
  expect(screen.getByRole('img', { name: 'lighthouse' })).toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('cancels an old retry on round change and starts the new round immediately', async () => {
  fetchFrame.mockResolvedValueOnce(new Response(null, { status: 503 }));
  const view = render(<RankedReveal round={round} />);
  await flush();
  expect(vi.getTimerCount()).toBe(1);
  view.rerender(
    <RankedReveal round={{ ...round, id: 'round-b', image_url: '/round-b/image/?v=2' }} />,
  );
  await flush();
  expect(vi.getTimerCount()).toBe(0);
  expect(fetchFrame).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  await advance(8000);
  expect(fetchFrame).toHaveBeenCalledTimes(2);
});

it('aborts an in-flight fetch on unmount without creating resources from a late response', async () => {
  let resolve!: (response: Response) => void;
  fetchFrame.mockImplementationOnce(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  const view = render(<RankedReveal round={round} />);
  const signal = (fetchFrame.mock.calls[0][1] as RequestInit).signal!;
  view.unmount();
  expect(signal.aborted).toBe(true);
  resolve(response());
  await flush();
  expect(create).not.toHaveBeenCalled();
  expect(revoke).not.toHaveBeenCalled();
});

it('manual reload remains single-flight while a retry is decoding', async () => {
  fetchFrame.mockRejectedValueOnce(new TypeError('offline'));
  let finish!: () => void;
  decode.mockImplementationOnce(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  render(<RankedReveal round={round} />);
  await flush();
  await advance(500);
  fireEvent.click(screen.getByRole('button', { name: 'Reload picture' }));
  fireEvent.click(screen.getByRole('button', { name: 'Reload picture' }));
  await advance(5000);
  expect(fetchFrame).toHaveBeenCalledTimes(2);
  finish();
  await flush();
  expect(tiles()).toBe(2);
  expect(fetchFrame).toHaveBeenCalledTimes(2);
});
