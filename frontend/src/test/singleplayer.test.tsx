import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { ApiError } from '../api';
import { AuthContext } from '../auth/context';
import { gameApi, type GameRound } from '../games/singleplayer';

vi.mock('../games/singleplayer', () => ({
  gameApi: { current: vi.fn(), start: vi.fn(), guess: vi.fn() },
}));
vi.mock('../games/Reveal', () => ({ Reveal: () => <div aria-label="Server-masked picture" /> }));
const guest = {
  user: null,
  restrictions: null,
  loading: false,
  error: '',
  refresh: vi.fn(),
  signOut: vi.fn(),
};
let current: GameRound | null;
function makeRound(overrides: Partial<GameRound> = {}): GameRound {
  const now = new Date();
  return {
    id: 'round-one',
    status: 'active',
    server_now: now.toISOString(),
    started_at: now.toISOString(),
    reveal_finishes_at: new Date(+now + 30_000).toISOString(),
    expires_at: new Date(+now + 86_400_000).toISOString(),
    grid_size: 20,
    revealed_count: 0,
    total_tiles: 400,
    revealed_tiles: [],
    guess_count: 0,
    image_url: '/api/games/singleplayer/rounds/round-one/image/?v=0',
    completion: null,
    ...overrides,
  };
}
function solved(): GameRound {
  return makeRound({
    status: 'solved',
    revealed_count: 400,
    revealed_tiles: Array.from({ length: 400 }, (_, i) => i),
    guess_count: 2,
    completion: {
      answer: 'lighthouse',
      solved_in_seconds: 12.5,
      guesses: 2,
      license: 'CC0 1.0',
      attribution: 'Original illustration',
      category: 'Places',
    },
  });
}
function page(path = '/singleplayer') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthContext.Provider value={guest}>
        <App />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}
beforeEach(() => {
  current = null;
  vi.mocked(gameApi.current).mockImplementation(async () => ({ round: current }));
  vi.mocked(gameApi.start).mockImplementation(async () => {
    current = makeRound();
    return { round: current };
  });
  vi.mocked(gameApi.guess).mockImplementation(async (_id, guess) => {
    current =
      guess === 'beacon'
        ? solved()
        : {
            ...current!,
            server_now: new Date().toISOString(),
            guess_count: (current?.guess_count ?? 0) + 1,
          };
    return { round: current, result: guess === 'beacon' ? 'correct' : 'incorrect' };
  });
});

describe('Singleplayer experience', () => {
  it('starts a real guest round and accepts keyboard guesses without penalties', async () => {
    page();
    expect(screen.getByText('Guest play')).toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: /Start a round/ }));
    const input = await screen.findByLabelText('Your guess');
    expect(screen.getByLabelText('Reveal countdown')).toHaveTextContent('30s');
    expect(screen.getByText('Enter to submit. No penalties. No cooldown.')).toBeInTheDocument();
    fireEvent.change(input, { target: { value: 'castle' } });
    fireEvent.submit(input.closest('form')!);
    await screen.findByText(/castle.*isn't it yet/);
    expect(input).toHaveValue('');
    expect(screen.getByRole('button', { name: /Submit guess/ })).toBeDisabled();
    fireEvent.change(input, { target: { value: 'beacon' } });
    fireEvent.submit(input.closest('form')!);
    expect(await screen.findByRole('heading', { name: 'lighthouse' })).toBeInTheDocument();
    expect(screen.getByText('12.5s')).toBeInTheDocument();
    expect(screen.queryByLabelText('Your guess')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Play Again/ }));
    await screen.findByLabelText('Your guess');
    expect(gameApi.start).toHaveBeenCalledTimes(2);
  });
  it('resumes the saved round on refresh without creating another', async () => {
    current = makeRound({
      revealed_count: 200,
      revealed_tiles: Array.from({ length: 200 }, (_, i) => i),
      guess_count: 3,
    });
    page();
    await screen.findByLabelText('Your guess');
    expect(screen.getByText('200 / 400 tiles')).toBeInTheDocument();
    expect(gameApi.start).not.toHaveBeenCalled();
    expect(screen.queryByText('lighthouse')).not.toBeInTheDocument();
  });
  it('keeps guessing available after all tiles disappear', async () => {
    current = makeRound({
      reveal_finishes_at: new Date(Date.now() - 1000).toISOString(),
      revealed_count: 400,
      revealed_tiles: Array.from({ length: 400 }, (_, i) => i),
    });
    page();
    const input = await screen.findByLabelText('Your guess');
    expect(screen.getByLabelText('Reveal countdown')).toHaveTextContent('0s');
    expect(screen.getByText('All tiles revealed. Take your time.')).toBeInTheDocument();
    fireEvent.change(input, { target: { value: 'beacon' } });
    expect(screen.getByRole('button', { name: /Submit guess/ })).toBeEnabled();
    fireEvent.submit(input.closest('form')!);
    await screen.findByRole('heading', { name: 'lighthouse' });
  });
  it('shows a clear empty library and retries the same start safely', async () => {
    vi.mocked(gameApi.start).mockRejectedValueOnce(
      new ApiError('No approved images.', 503, 'library_empty'),
    );
    page();
    fireEvent.click(await screen.findByRole('button', { name: /Start a round/ }));
    await screen.findByRole('heading', { name: 'The library is waiting.' });
    expect(screen.getByRole('link', { name: /Contribute an image/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Check again/ }));
    await screen.findByLabelText('Your guess');
    expect(vi.mocked(gameApi.start).mock.calls[0][0]).toBe(
      vi.mocked(gameApi.start).mock.calls[1][0],
    );
  });
  it('retains a round during connection loss and recovers on reconnect', async () => {
    current = makeRound();
    page();
    await screen.findByLabelText('Your guess');
    vi.mocked(gameApi.current).mockRejectedValueOnce(new Error('Connection interrupted.'));
    fireEvent(window, new Event('online'));
    await screen.findByText(/Connection interrupted.*Your round stays saved/);
    expect(screen.getByLabelText('Your guess')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reconnect' }));
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Reconnect' })).not.toBeInTheDocument(),
    );
  });
  it('offers a fresh round after expiry', async () => {
    current = makeRound({ status: 'expired', image_url: null });
    page();
    await screen.findByRole('heading', { name: 'This round has expired.' });
    expect(screen.queryByLabelText('Your guess')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Start a round/ }));
    await screen.findByLabelText('Your guess');
  });
  it('displays a completed round when reconnecting', async () => {
    current = solved();
    page();
    await screen.findByRole('heading', { name: 'lighthouse' });
    expect(screen.getByRole('button', { name: /Play Again/ })).toBeEnabled();
    expect(screen.getByText('Original illustration')).toBeInTheDocument();
  });
  it('rejects a delayed active poll after a correct submission', async () => {
    current = makeRound();
    page();
    const input = await screen.findByLabelText('Your guess');
    let finish!: (value: { round: GameRound }) => void;
    const stale = makeRound();
    vi.mocked(gameApi.current).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    fireEvent(window, new Event('online'));
    fireEvent.change(input, { target: { value: 'beacon' } });
    fireEvent.submit(input.closest('form')!);
    await screen.findByRole('heading', { name: 'lighthouse' });
    await act(async () => {
      finish({ round: stale });
    });
    expect(screen.queryByLabelText('Your guess')).not.toBeInTheDocument();
  });
  it('redirects the legacy singleplayer rules URL into the game', async () => {
    page('/modes/singleplayer');
    await screen.findByRole('button', { name: /Start a round/ });
    expect(screen.getByRole('heading', { name: /Find the bigger picture/ })).toBeInTheDocument();
  });
});
