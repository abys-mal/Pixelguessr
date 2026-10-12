import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest';
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
