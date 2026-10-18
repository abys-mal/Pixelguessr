import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
import { RankedReveal } from '../games/RankedReveal';
import type { DuelRound } from '../games/ranked';
import { Reveal } from '../games/Reveal';
import type { GameRound } from '../games/singleplayer';

const round: GameRound = {
  id: 'private-round',
  number: 1,
  score: 0,
  available_points: 990,
  can_forfeit: false,
  reveal_duration_seconds: 45,
  status: 'active',
  server_now: '2026-10-11T12:00:00Z',
  started_at: '2026-10-11T12:00:00Z',
  reveal_finishes_at: '2026-10-11T12:00:45Z',
  expires_at: '2026-10-12T12:00:00Z',
  grid_size: 20,
  total_tiles: 400,
  revealed_count: 2,
  revealed_tiles: [17, 306],
  guess_count: 0,
  image_url: '/api/games/singleplayer/rounds/private-round/image/?v=2',
  completion: null,
};
let create: Mock<(obj: Blob | MediaSource) => string>;
let revoke: Mock<(url: string) => void>;
beforeEach(() => {
  create = vi.fn<(obj: Blob | MediaSource) => string>().mockReturnValue('blob:private-frame');
  revoke = vi.fn<(url: string) => void>();
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
      decode() {
        return Promise.resolve();
      }
    },
  );
  vi.spyOn(globalThis, 'fetch').mockImplementation(
    async () => new Response(new Blob(['masked-webp']), { status: 200 }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
describe('Server-masked reveal delivery', () => {
  it('waits for full-frame decode and a paint opportunity before party results', async () => {
    let finishDecode!: () => void;
    const decode = vi
      .fn()
      .mockResolvedValueOnce(undefined)
      .mockImplementationOnce(
        () =>
          new Promise<void>((resolve) => {
            finishDecode = resolve;
          }),
      );
    vi.stubGlobal(
      'Image',
      class {
        src = '';
        decode = decode;
      },
    );
    const frames = new Map<number, FrameRequestCallback>();
    let sequence = 0;
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frames.set(++sequence, callback);
      return sequence;
    });
    vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id));
    const ready = vi.fn();
    const view = render(<Reveal round={round} onFullReveal={ready} />);
    await screen.findByRole('img');
    view.rerender(
      <Reveal
        round={{
          ...round,
          image_url: '/image/?v=400',
          revealed_tiles: Array.from({ length: 400 }, (_, i) => i),
          completion: { answer: 'lighthouse' },
        }}
        onFullReveal={ready}
      />,
    );
    await waitFor(() => expect(decode).toHaveBeenCalledTimes(2));
    expect(document.querySelectorAll('.is-revealed')).toHaveLength(2);
    expect(ready).not.toHaveBeenCalled();
    await act(async () => finishDecode());
    await waitFor(() => expect(document.querySelectorAll('.is-revealed')).toHaveLength(400));
    expect(document.querySelector('.reveal-stage')).toHaveClass('party-final-frame');
    view.rerender(
      <Reveal
        round={{
          ...round,
          image_url: '/image/?v=400',
          revealed_tiles: Array.from({ length: 400 }, (_, i) => i),
          completion: { answer: 'lighthouse' },
        }}
        onFullReveal={ready}
      />,
    );
    expect(sequence).toBe(1); // Repeated snapshots must not restart the paint handoff.
    const paint = () => {
      const next = frames.entries().next().value!;
      frames.delete(next[0]);
      next[1](16);
    };
    act(paint);
    expect(ready).not.toHaveBeenCalled();
    act(paint);
    expect(ready).toHaveBeenCalledExactlyOnceWith(round.id);
  });
  it('cancels pending party completion callbacks when its image unmounts', async () => {
    const ready = vi.fn();
    const frames = new Map<number, FrameRequestCallback>();
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frames.set(1, callback);
      return 1;
    });
    vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id));
    const view = render(
      <Reveal
        round={{
          ...round,
          revealed_tiles: Array.from({ length: 400 }, (_, i) => i),
          completion: { answer: 'lighthouse' },
        }}
        onFullReveal={ready}
      />,
    );
    await waitFor(() => expect(frames.size).toBe(1));
    view.unmount();
    expect(frames.size).toBe(0);
    expect(ready).not.toHaveBeenCalled();
  });
  it('does not report a failed final frame as ready', async () => {
    const ready = vi.fn();
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 503 }));
    render(
      <Reveal
        round={{
          ...round,
          revealed_tiles: Array.from({ length: 400 }, (_, i) => i),
          completion: { answer: 'lighthouse' },
        }}
        onFullReveal={ready}
      />,
    );
    await screen.findByRole('alert');
    expect(ready).not.toHaveBeenCalled();
    expect(document.querySelectorAll('.is-revealed')).toHaveLength(0);
    expect(screen.getByRole('button', { name: 'Reload picture' })).toBeInTheDocument();
  });
  it('does not download an image before a round starts', () => {
    render(<Reveal round={null} />);
    expect(fetch).not.toHaveBeenCalled();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(document.querySelectorAll('.game-tiles i')).toHaveLength(400);
  });
  it('fetches the authorized frame and animates only confirmed tiles', async () => {
    render(<Reveal round={round} />);
    const img = await screen.findByRole('img', { name: 'Partially revealed mystery image' });
    expect(img).toHaveAttribute('src', 'blob:private-frame');
    expect(fetch).toHaveBeenCalledWith(
      round.image_url,
      expect.objectContaining({ credentials: 'same-origin', signal: expect.any(AbortSignal) }),
    );
    expect(document.querySelectorAll('.game-tiles .is-revealed')).toHaveLength(2);
    expect(document.querySelectorAll('.game-tiles i')).toHaveLength(400);
    expect(screen.queryByText('lighthouse')).not.toBeInTheDocument();
  });
  it('preserves the old frame on failure and offers a working retry', async () => {
    const view = render(<Reveal round={round} />);
    await screen.findByRole('img');
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 503 }));
    view.rerender(
      <Reveal
        round={{ ...round, image_url: round.image_url + '3', revealed_tiles: [17, 306, 88] }}
      />,
    );
    await screen.findByRole('alert');
    expect(document.querySelectorAll('.is-revealed')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: 'Reload picture' }));
    await waitFor(() => expect(document.querySelectorAll('.is-revealed')).toHaveLength(3));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
  it('releases blob resources on unmount', async () => {
    const view = render(<Reveal round={round} />);
    await screen.findByRole('img');
    view.unmount();
    expect(revoke).toHaveBeenCalledWith('blob:private-frame');
  });
});

it('Ranked keeps identical frames across clock snapshots and finishes slow decodes before loading latest', async () => {
  create.mockReturnValueOnce('blob:first').mockReturnValueOnce('blob:latest');
  let decode!: () => void;
  const decoding = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          decode = resolve;
        }),
    )
    .mockResolvedValue(undefined);
  vi.stubGlobal(
    'Image',
    class {
      src = '';
      decode = decoding;
    },
  );
  const first = { ...round } as unknown as DuelRound;
  const view = render(<RankedReveal round={first} />);
  await waitFor(() => expect(decoding).toHaveBeenCalledOnce());
  view.rerender(<RankedReveal round={{ ...first }} />);
  expect(fetch).toHaveBeenCalledTimes(1);
  const third = { ...first, image_url: '/image/?v=3', revealed_tiles: [17, 306, 88] };
  view.rerender(<RankedReveal round={third} />);
  const fourth = { ...third, image_url: '/image/?v=4', revealed_tiles: [17, 306, 88, 99] };
  view.rerender(<RankedReveal round={fourth} />);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(document.querySelectorAll('.is-revealed')).toHaveLength(0);
  decode();
  await waitFor(() => expect(document.querySelectorAll('.is-revealed')).toHaveLength(4));
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(vi.mocked(fetch).mock.calls[1][0]).toBe('/image/?v=4');
  view.rerender(<RankedReveal round={{ ...fourth }} />);
  expect(fetch).toHaveBeenCalledTimes(2);
  view.unmount();
  expect(revoke).toHaveBeenCalledWith('blob:first');
  expect(revoke).toHaveBeenCalledWith('blob:latest');
});
it('Ranked rejects a masked frame that disagrees with its authorized prefix', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(
    new Response(new Blob(['masked']), { headers: { 'X-Revealed-Tiles': '20' } }),
  );
  render(<RankedReveal round={round as unknown as DuelRound} />);
  await screen.findByRole('alert');
  expect(document.querySelectorAll('.is-revealed')).toHaveLength(0);
});
