import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { Pagination } from '../pages/RankedPublic';
import { AuthContext } from '../auth/context';
import { rankedApi, type DuelState, type QueueState } from '../games/ranked';
import { api } from '../api';
let deliver: (state: DuelState | QueueState) => void;
let connectionChanged: (status: string) => void;
const close = vi.fn();
vi.mock('../api', async (original) => ({ ...(await original<object>()), api: vi.fn() }));
vi.mock('../games/RankedReveal', () => ({ RankedReveal: () => <div>Server-masked picture</div> }));
vi.mock('../games/ranked', async (original) => ({
  ...(await original<object>()),
  rankedApi: {
    queue: vi.fn(),
    join: vi.fn(),
    cancel: vi.fn(),
    state: vi.fn(),
    guess: vi.fn(),
    leave: vi.fn(),
    leaderboard: vi.fn(),
    history: vi.fn(),
  },
  connectRanked: vi.fn((_path, onState, onConnection) => {
    deliver = onState;
    connectionChanged = onConnection;
    onConnection('Connected');
    return close;
  }),
}));
const user = {
  id: 'u',
  username: 'player',
  email: 'private@example.com',
  display_name: 'Player',
  rating: 1000,
  ranked_tier: null,
  ranked_matches: 0,
  ranked_wins: 0,
  ranked_losses: 0,
  title: null,
  date_joined: '2026-01-01',
};
const auth = {
  user,
  restrictions: { blocked: false, probation: false, unacknowledged_warnings: [] },
  loading: false,
  error: '',
  refresh: vi.fn(),
  signOut: vi.fn(),
};
function state(): DuelState {
  return {
    id: 'duel',
    status: 'active',
    revision: 1,
    server_now: '2026-10-12T12:00:03Z',
    me_id: 'p1',
    winner_id: null,
    outcome: '',
    message: '',
    waiting: false,
    players: [
      {
        id: 'p1',
        username: 'player',
        rating_before: 1000,
        rating_after: null,
        rating_delta: null,
        tier: null,
        wins: 0,
        connected: true,
        reconnect_until: null,
      },
      {
        id: 'p2',
        username: 'opponent',
        rating_before: 1000,
        rating_after: null,
        rating_delta: null,
        tier: null,
        wins: 0,
        connected: true,
        reconnect_until: null,
      },
    ],
    round: {
      id: 'r1',
      number: 1,
      status: 'active',
      started_at: '2026-10-12T12:00:03Z',
      reveal_finishes_at: '2026-10-12T12:00:48Z',
      next_starts_at: null,
      winner_id: null,
      grid_size: 20,
      revealed_tiles: [],
      revealed_count: 0,
      total_tiles: 400,
      image_url: '/private',
      guessed_ids: [],
      completion: null,
    },
  };
}
function page(path = '/ranked/duel') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthContext.Provider value={auth}>
        <App />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(rankedApi.state).mockResolvedValue(state());
  vi.mocked(rankedApi.queue).mockResolvedValue({
    status: 'idle',
    ticket: null,
    match_id: null,
    server_now: '2026-10-12T12:00:00Z',
  });
});
describe('Ranked duel', () => {
  it('focuses the guess input and submits only once for repeated Enter', async () => {
    let finish!: (value: { state: DuelState; result: 'incorrect' }) => void;
    vi.mocked(rankedApi.guess).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    page();
    const input = await screen.findByLabelText('Your one guess');
    expect(input).toHaveFocus();
    fireEvent.change(input, { target: { value: 'cat' } });
    fireEvent.submit(input.closest('form')!);
    fireEvent.submit(input.closest('form')!);
    expect(rankedApi.guess).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(input, { key: 'Enter', repeat: true });
    expect(rankedApi.guess).toHaveBeenCalledTimes(1);
    const next = state();
    next.revision++;
    next.round!.guessed_ids = ['p1'];
    await act(async () => finish({ state: next, result: 'incorrect' }));
    expect(screen.getByText(/Your guess was incorrect/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Your one guess')).not.toBeInTheDocument();
    expect(screen.getByLabelText('opponent wins')).toHaveTextContent('0');
  });
  it('focuses results then a fresh input, ignores stale packets, and shows Wash', async () => {
    page();
    await screen.findByLabelText('Your one guess');
    const result = state();
    result.revision = 2;
    result.round!.status = 'results';
    result.round!.completion = { answer: 'cat', license: 'CC0', attribution: 'Original' };
    result.round!.next_starts_at = '2026-10-12T12:00:08Z';
    act(() => deliver(result));
    expect(screen.getByRole('heading', { name: 'Wash' })).toHaveFocus();
    act(() => deliver(state()));
    expect(screen.getByRole('heading', { name: 'Wash' })).toBeInTheDocument();
    const next = state();
    next.revision = 3;
    next.round!.id = 'r2';
    next.round!.number = 2;
    act(() => deliver(next));
    expect(screen.getByLabelText('Your one guess')).toHaveFocus();
    expect(screen.getByLabelText('Your one guess')).toHaveValue('');
  });
  it('shows synchronized versus countdown and exact pre-match ratings', async () => {
    const next = state();
    next.round!.status = 'countdown';
    next.server_now = '2026-10-12T12:00:00Z';
    vi.mocked(rankedApi.state).mockResolvedValue(next);
    page();
    await screen.findByRole('heading', { name: 'Face to face.' });
    expect(screen.getAllByText('1000 Elo')).toHaveLength(2);
    expect(screen.queryByLabelText('Your one guess')).not.toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });
  it('waits during disconnect and preserves a used guess after reconnect', async () => {
    page();
    await screen.findByLabelText('Your one guess');
    const result = state();
    result.revision = 2;
    result.waiting = true;
    result.players[1].connected = false;
    result.players[1].reconnect_until = '2026-10-12T12:00:33Z';
    result.round!.status = 'results';
    result.round!.completion = { answer: 'cat', license: 'CC0', attribution: 'Original' };
    act(() => deliver(result));
    expect(screen.getByText(/Waiting for both players/)).toBeInTheDocument();
    expect(screen.getByText(/opponent disconnected/)).toBeInTheDocument();
    act(() => connectionChanged('Reconnecting'));
    expect(screen.getByText('Reconnecting')).toBeInTheDocument();
  });
  it('requires leave confirmation and displays a persistent rated final with normal queue link', async () => {
    const final = state();
    final.status = 'complete';
    final.revision = 4;
    final.winner_id = 'p2';
    final.outcome = 'forfeit';
    final.round = null;
    final.players[0].rating_after = 980;
    final.players[0].rating_delta = -20;
    final.players[1].rating_after = 1020;
    final.players[1].rating_delta = 20;
    vi.mocked(rankedApi.leave).mockResolvedValue(final);
    page();
    await screen.findByLabelText('Your one guess');
    fireEvent.click(screen.getByRole('button', { name: 'Leave duel' }));
    expect(rankedApi.leave).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Leave match' }));
    await screen.findByRole('heading', { name: 'Defeat' });
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Defeat' })).toHaveFocus());
    expect(screen.getByText('-20 Elo')).toBeInTheDocument();
    expect(screen.getByText('+20 Elo')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Play Again' })).toHaveAttribute('href', '/ranked');
    expect(close).toHaveBeenCalled();
  });
  it('recovers final No Contest through read-only polling when an expired socket is denied', async () => {
    page();
    await screen.findByLabelText('Your one guess');
    const final = state();
    final.status = 'complete';
    final.outcome = 'no_contest';
    final.round = null;
    final.revision = 3;
    final.players.forEach((p) => {
      p.rating_after = 1000;
      p.rating_delta = 0;
    });
    vi.mocked(rankedApi.state).mockResolvedValue(final);
    act(() => connectionChanged('Disconnected'));
    await screen.findByRole('heading', { name: 'No Contest' }, { timeout: 4500 });
  });
  it('shows No Contest with unchanged ratings', async () => {
    const final = state();
    final.status = 'complete';
    final.outcome = 'no_contest';
    final.round = null;
    final.players.forEach((p) => {
      p.rating_after = 1000;
      p.rating_delta = 0;
    });
    vi.mocked(rankedApi.state).mockResolvedValue(final);
    page();
    await screen.findByRole('heading', { name: 'No Contest' });
    expect(screen.getByText(/rated-match counts are unchanged/)).toBeInTheDocument();
  });
  it('never opens a queue before Find opponent and cancels the current ticket', async () => {
    const queued: QueueState = {
      status: 'searching',
      ticket: 'ticket',
      match_id: null,
      queued_at: '2026-10-12T12:00:00Z',
      server_now: '2026-10-12T12:00:00Z',
      search_window: 100,
    };
    vi.mocked(rankedApi.join).mockResolvedValue(queued);
    vi.mocked(rankedApi.cancel).mockResolvedValue({ ...queued, status: 'idle' });
    page('/ranked');
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Find opponent' })).toBeEnabled(),
    );
    expect(rankedApi.join).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Find opponent' }));
    await screen.findByText('Finding your opponent…');
    expect(screen.getByText(/±100 Elo/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel search' }));
    await screen.findByRole('button', { name: 'Find opponent' });
    expect(rankedApi.cancel).toHaveBeenCalledWith('ticket');
  });
  it('automatically navigates to a paired match, including cancellation races', async () => {
    vi.mocked(rankedApi.join).mockResolvedValue({
      status: 'matched',
      ticket: 'ticket',
      match_id: 'duel',
      server_now: '2026-10-12T12:00:00Z',
    });
    page('/ranked');
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Find opponent' })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Find opponent' }));
    await screen.findByLabelText('Your one guess');
    expect(rankedApi.state).toHaveBeenCalledWith('duel');
  });
  it('cancels a queue response arriving after the player leaves the queue page', async () => {
    let resolve!: (state: QueueState) => void;
    vi.mocked(rankedApi.join).mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    vi.mocked(rankedApi.cancel).mockResolvedValue({
      status: 'idle',
      ticket: 'late',
      match_id: null,
      server_now: '2026-10-12T12:00:00Z',
    });
    const view = page('/ranked');
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Find opponent' })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Find opponent' }));
    view.unmount();
    await act(async () =>
      resolve({
        status: 'searching',
        ticket: 'late',
        match_id: null,
        server_now: '2026-10-12T12:00:00Z',
      }),
    );
    expect(rankedApi.cancel).toHaveBeenCalledWith('late');
  });
  it('shows empty-library errors and permits retry', async () => {
    vi.mocked(rankedApi.join).mockRejectedValue(new Error('No approved images are available.'));
    page('/ranked');
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Find opponent' })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Find opponent' }));
    await screen.findByText('No approved images are available.');
    expect(screen.getByRole('button', { name: 'Find opponent' })).toBeEnabled();
  });
  it('shows public leaderboard positions and profile links without an Unranked badge', async () => {
    vi.mocked(rankedApi.leaderboard).mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      my_position: 1,
      results: [{ username: 'player', rating: 1020, tier: null, position: 1 }],
    });
    page('/leaderboards');
    await screen.findByText('1020');
    expect(screen.getByRole('link', { name: 'player' })).toHaveAttribute('href', '/players/player');
    expect(screen.queryByText('Unranked')).not.toBeInTheDocument();
  });
  it('shows public profile stats and history without private email', async () => {
    vi.mocked(api).mockResolvedValue(user);
    vi.mocked(rankedApi.history).mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 'm',
          date: '2026-10-12T12:00:00Z',
          opponent: 'opponent',
          outcome: 'win',
          forfeit: false,
          score: 4,
          opponent_score: 2,
          rating_before: 1000,
          rating_after: 1020,
          rating_delta: 20,
        },
      ],
    });
    page('/players/player');
    await screen.findByRole('heading', { name: '1000 Elo' });
    expect(screen.getByRole('link', { name: 'opponent' })).toHaveAttribute(
      'href',
      '/players/opponent',
    );
    expect(screen.getByText('4–2')).toBeInTheDocument();
    expect(screen.queryByText('private@example.com')).not.toBeInTheDocument();
  });
});

it('pagination preserves centered slots when disabled and handles page navigation', () => {
  const change = vi.fn();
  const view = render(<Pagination page={1} next="page2" previous={null} onPage={change} />);
  expect(screen.getByRole('navigation', { name: 'Page navigation' })).toHaveClass(
    'ranked-pagination',
  );
  expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  expect(change).toHaveBeenLastCalledWith(2);
  view.rerender(<Pagination page={2} next={null} previous="page1" onPage={change} />);
  expect(screen.getByText('Page 2')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Previous' }));
  expect(change).toHaveBeenLastCalledWith(1);
});
