import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { ApiError } from '../api';
import { AuthContext } from '../auth/context';
import { gameApi, type GameRound, type GameState, type GameResponse } from '../games/singleplayer';

vi.mock('../games/singleplayer', () => ({
  gameApi: { current: vi.fn(), start: vi.fn(), guess: vi.fn(), next: vi.fn(), forfeit: vi.fn() },
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
let current: GameState;
function makeRound(number = 1, overrides: Partial<GameRound> = {}): GameRound {
  const now = new Date();
  return {
    id: `round-${number}`,
    number,
    status: 'active',
    server_now: now.toISOString(),
    started_at: now.toISOString(),
    reveal_finishes_at: new Date(+now + 45_000).toISOString(),
    expires_at: new Date(+now + 86_400_000).toISOString(),
    reveal_duration_seconds: 45,
    grid_size: 20,
    revealed_count: 0,
    total_tiles: 400,
    revealed_tiles: [],
    guess_count: 0,
    score: 0,
    available_points: 1000,
    can_forfeit: false,
    image_url: `/api/games/singleplayer/rounds/round-${number}/image/?v=0`,
    completion: null,
    ...overrides,
  };
}
function makeState(): GameState {
  const round = makeRound();
  return {
    round,
    session: {
      id: 'session-one',
      revision: 1,
      status: 'active',
      server_now: round.server_now,
      expires_at: round.expires_at,
      total_rounds: 5,
      current_round_number: 1,
      total_score: 0,
      max_score: 5000,
      solved_rounds: 0,
      rounds: Array.from({ length: 5 }, (_, i) => ({
        number: i + 1,
        outcome: i ? 'pending' : 'active',
        score: null,
      })),
    },
  };
}
function complete(outcome: 'solved' | 'forfeited'): GameResponse {
  const round = current.round!;
  const session = current.session!;
  const points = outcome === 'forfeited' ? 0 : round.available_points;
  current = {
    round: {
      ...round,
      status: outcome,
      score: points,
      available_points: 0,
      can_forfeit: false,
      guess_count: round.guess_count + (outcome === 'solved' ? 1 : 0),
      revealed_count: 400,
      completion: {
        answer: 'lighthouse',
        outcome,
        score: points,
        solved_in_seconds: outcome === 'solved' ? 11.25 : null,
        guesses: 1,
        license: 'CC0',
        attribution: 'Original illustration',
        category: 'Places',
      },
    },
    session: {
      ...session,
      revision: session.revision + 1,
      total_score: session.total_score + points,
      solved_rounds: session.solved_rounds + (outcome === 'solved' ? 1 : 0),
      status: round.number === 5 ? 'complete' : 'active',
      rounds: session.rounds.map((item) =>
        item.number === round.number
          ? { ...item, outcome, score: points, answer: 'lighthouse' }
          : item,
      ),
    },
  };
  return { ...current, result: outcome === 'solved' ? 'correct' : 'forfeited' };
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
async function enter(text: string) {
  const input = await screen.findByLabelText('Your Guess');
  fireEvent.change(input, { target: { value: text } });
  fireEvent.submit(input.closest('form')!);
}
beforeEach(() => {
  current = { round: null, session: null };
  vi.mocked(gameApi.current).mockImplementation(async () => current);
  vi.mocked(gameApi.start).mockImplementation(async () => {
    current = makeState();
    current.session!.id = crypto.randomUUID();
    return current;
  });
  vi.mocked(gameApi.next).mockImplementation(async () => {
    const session = current.session!;
    const number = current.round!.number + 1;
    current = {
      round: makeRound(number),
      session: {
        ...session,
        revision: session.revision + 1,
        current_round_number: number,
        rounds: session.rounds.map((item) =>
          item.number === number ? { ...item, outcome: 'active' } : item,
        ),
      },
    };
    return { ...current, result: 'started' };
  });
  vi.mocked(gameApi.guess).mockImplementation(async (_id, text) => {
    if (text === 'beacon') return complete('solved');
    current = {
      ...current,
      round: { ...current.round!, guess_count: current.round!.guess_count + 1 },
      session: { ...current.session!, revision: current.session!.revision + 1 },
    };
    return { ...current, result: 'incorrect' };
  });
  vi.mocked(gameApi.forfeit).mockImplementation(async () => complete('forfeited'));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('Five-round singleplayer', () => {
  it('starts a guest game, shows counters, and accepts incorrect keyboard guesses', async () => {
    page();
    expect(screen.getByText('Guest')).toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: 'Start Game' }));
    await screen.findByLabelText('Your Guess');
    expect(screen.getByText('Round 1 of 5')).toBeInTheDocument();
    expect(screen.getByLabelText('Time Remaining')).toHaveTextContent('45s');
    expect(screen.queryByText('Current Score')).not.toBeInTheDocument();
    expect(screen.getByText('Total Score')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Forfeit Round' })).not.toBeInTheDocument();
    await enter('castle');
    await screen.findByText('Incorrect');
    expect(screen.getByLabelText('Your Guess')).toHaveValue('');
    expect(current.session!.total_score).toBe(0);
  });
  it('shows a readable round result, points, and guarded Next Round', async () => {
    current = makeState();
    current.round!.available_points = 563;
    page();
    await enter('beacon');
    expect(await screen.findByRole('heading', { name: 'Correct' })).toHaveFocus();
    expect(screen.getByText('lighthouse')).toBeInTheDocument();
    expect(screen.getByText('Points earned').nextElementSibling).toHaveTextContent('563');
    expect(screen.queryByLabelText('Your Guess')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next Round' }));
    await screen.findByLabelText('Your Guess');
    expect(screen.getByText('Round 2 of 5')).toBeInTheDocument();
    expect(current.session!.total_score).toBe(563);
    expect(screen.queryByText('Incorrect')).not.toBeInTheDocument();
  });
  it('completes exactly five rounds and resets score on Play Again', async () => {
    current = makeState();
    page();
    for (let number = 1; number <= 5; number++) {
      await enter('beacon');
      if (number < 5) {
        await screen.findByRole('button', { name: 'Next Round' });
        fireEvent.click(screen.getByRole('button', { name: 'Next Round' }));
        await waitFor(() =>
          expect(screen.getByText(`Round ${number + 1} of 5`)).toBeInTheDocument(),
        );
      }
    }
    expect(await screen.findByRole('heading', { name: 'Final Results' })).toHaveFocus();
    expect(screen.getByLabelText('Final score')).toHaveTextContent('5,000 / 5,000');
    expect(screen.getByText('Solved 5 of 5 rounds')).toBeInTheDocument();
    expect(screen.getAllByRole('row')).toHaveLength(6);
    expect(screen.queryByRole('button', { name: 'Next Round' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Return Home' })).toHaveAttribute('href', '/');
    fireEvent.click(screen.getByRole('button', { name: 'Play Again' }));
    await screen.findByLabelText('Your Guess');
    expect(current.session!.total_score).toBe(0);
    expect(screen.getByText('Round 1 of 5')).toBeInTheDocument();
  });
  it('uses the server full-reveal permission for Forfeit Round', async () => {
    current = makeState();
    current.round = makeRound(1, {
      revealed_count: 400,
      available_points: 0,
      can_forfeit: true,
      reveal_finishes_at: new Date(Date.now() - 1000).toISOString(),
    });
    page();
    await screen.findByRole('button', { name: 'Forfeit Round' });
    expect(screen.getByLabelText('Time Remaining')).toHaveTextContent('0s');
    await enter('wrong');
    await screen.findByText('Incorrect');
    fireEvent.click(screen.getByRole('button', { name: 'Forfeit Round' }));
    await screen.findByRole('heading', { name: 'Forfeited' });
    expect(current.round!.score).toBe(0);
    expect(screen.getByRole('button', { name: 'Next Round' })).toBeEnabled();
  });
  it('records a correct guess after full reveal as solved with zero points', async () => {
    current = makeState();
    current.round!.available_points = 0;
    current.round!.can_forfeit = true;
    page();
    await enter('beacon');
    await screen.findByRole('heading', { name: 'Correct' });
    expect(current.round!.status).toBe('solved');
    expect(current.session!.total_score).toBe(0);
  });
  it('forfeiting Round 5 opens final results with the correct outcomes', async () => {
    current = makeState();
    current.round = makeRound(5, { can_forfeit: true, available_points: 0, revealed_count: 400 });
    current.session = {
      ...current.session!,
      current_round_number: 5,
      total_score: 2000,
      solved_rounds: 3,
      rounds: current.session!.rounds.map((item) => ({
        ...item,
        outcome: item.number < 4 ? 'solved' : item.number === 4 ? 'forfeited' : 'active',
        score: item.number < 4 ? [1000, 563, 437][item.number - 1] : item.number === 4 ? 0 : null,
        answer: item.number < 5 ? 'lighthouse' : undefined,
      })),
    };
    page();
    fireEvent.click(await screen.findByRole('button', { name: 'Forfeit Round' }));
    await screen.findByRole('heading', { name: 'Final Results' });
    expect(screen.getByLabelText('Final score')).toHaveTextContent('2,000 / 5,000');
    expect(screen.getByText('Solved 3 of 5 rounds')).toBeInTheDocument();
    expect(screen.getAllByRole('cell', { name: 'Forfeited' })).toHaveLength(2);
  });
  it('resumes saved score and round without creating another game', async () => {
    current = makeState();
    current.round = makeRound(2);
    current.session!.current_round_number = 2;
    current.session!.total_score = 563;
    page();
    await screen.findByLabelText('Your Guess');
    expect(screen.getByText('Round 2 of 5')).toBeInTheDocument();
    expect(gameApi.start).not.toHaveBeenCalled();
    expect(screen.queryByText('lighthouse')).not.toBeInTheDocument();
  });
  it('shows empty-library and retry errors clearly', async () => {
    vi.mocked(gameApi.start).mockRejectedValueOnce(
      new ApiError('No approved images.', 503, 'library_empty'),
    );
    page();
    fireEvent.click(await screen.findByRole('button', { name: 'Start Game' }));
    await screen.findByRole('heading', { name: 'No images available' });
    fireEvent.click(screen.getByRole('button', { name: 'Check Again' }));
    await screen.findByLabelText('Your Guess');
    expect(vi.mocked(gameApi.start).mock.calls[0][0]).toBe(
      vi.mocked(gameApi.start).mock.calls[1][0],
    );
  });
  it('recovers after connection loss while retaining round and score', async () => {
    current = makeState();
    page();
    await screen.findByLabelText('Your Guess');
    vi.mocked(gameApi.current).mockRejectedValueOnce(new Error('Connection interrupted.'));
    fireEvent(window, new Event('online'));
    await screen.findByText(/Connection interrupted.*Progress is saved/);
    expect(screen.getByLabelText('Your Guess')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reconnect' }));
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Reconnect' })).not.toBeInTheDocument(),
    );
  });
  it('shows an expired game with a fresh-start option', async () => {
    current = makeState();
    current.session!.status = 'expired';
    current.round!.status = 'expired';
    page();
    await screen.findByRole('heading', { name: 'Game expired' });
    expect(screen.queryByLabelText('Your Guess')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Start Game' }));
    await screen.findByLabelText('Your Guess');
  });
  it('does not let a delayed poll undo awarded points', async () => {
    current = makeState();
    page();
    await screen.findByLabelText('Your Guess');
    let finish!: (state: GameState) => void;
    const stale = makeState();
    vi.mocked(gameApi.current).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    fireEvent(window, new Event('online'));
    await enter('beacon');
    await screen.findByRole('heading', { name: 'Correct' });
    await act(async () => {
      finish(stale);
    });
    expect(screen.queryByLabelText('Your Guess')).not.toBeInTheDocument();
    expect(current.session!.total_score).toBe(1000);
  });
  it('does not let a cosmetic timer unlock forfeit without the server', async () => {
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date', 'performance'],
    });
    current = makeState();
    page();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    vi.mocked(gameApi.current).mockRejectedValue(new Error('Offline'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(45_000);
    });
    expect(screen.getByLabelText('Time Remaining')).toHaveTextContent('0s');
    expect(screen.queryByRole('button', { name: 'Forfeit Round' })).not.toBeInTheDocument();
  });
  it('redirects the old rules URL into the real game', async () => {
    page('/modes/singleplayer');
    await screen.findByRole('button', { name: 'Start Game' });
    expect(screen.getByRole('heading', { name: 'Singleplayer' })).toBeInTheDocument();
  });
});
