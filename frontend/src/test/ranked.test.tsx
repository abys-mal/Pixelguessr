import { readFileSync } from 'node:fs';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
      incorrect_guess_ids: [],
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
  it('keeps a confirmed opponent mistake beneath Submit until the round ends', async () => {
    page();
    await screen.findByLabelText('Your one guess');
    expect(screen.queryByText('Your opponent guessed incorrectly!')).not.toBeInTheDocument();
    expect(screen.queryByText(/guess available|guess used/i)).not.toBeInTheDocument();
    const wrong = state();
    wrong.revision = 2;
    wrong.round!.guessed_ids = ['p2'];
    wrong.round!.incorrect_guess_ids = ['p2'];
    vi.useFakeTimers();
    try {
      act(() => deliver(wrong));
      const status = screen.getByText('Your opponent guessed incorrectly!');
      const submit = screen.getByRole('button', { name: 'Submit guess' });
      expect(status).toHaveAttribute('role', 'status');
      expect(status).toHaveClass('field-help');
      expect(submit.closest('form')!.nextElementSibling).toBe(status);
      expect(status.closest('.ranked-controls')).toBe(submit.closest('.ranked-controls'));
      act(() => vi.advanceTimersByTime(10000));
      act(() => deliver({ ...wrong, revision: 3 }));
      expect(screen.getAllByText('Your opponent guessed incorrectly!')).toHaveLength(1);
      const result = structuredClone(wrong);
      result.revision = 4;
      result.round!.status = 'results';
      result.round!.completion = { answer: 'cat', license: 'CC0', attribution: 'Original' };
      act(() => deliver(result));
      expect(screen.queryByText('Your opponent guessed incorrectly!')).not.toBeInTheDocument();
      const next = state();
      next.revision = 5;
      next.round!.id = 'r2';
      next.round!.number = 2;
      next.round!.status = 'countdown';
      act(() => deliver(next));
      expect(screen.queryByText('Your opponent guessed incorrectly!')).not.toBeInTheDocument();
      next.round!.status = 'active';
      act(() => deliver({ ...next, revision: 6 }));
      expect(screen.getByRole('button', { name: 'Submit guess' })).toBeInTheDocument();
      // Delayed snapshots of the old round cannot restore its status.
      act(() => deliver(wrong));
      expect(screen.queryByText('Your opponent guessed incorrectly!')).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
  it.each(['correct', 'timeout', 'ambiguous', 'missing', 'own incorrect'])(
    'never infers an opponent mistake from %s guess availability',
    async (kind) => {
      page();
      await screen.findByLabelText('Your one guess');
      act(() => deliver(state()));
      const next = state();
      next.revision = 2;
      if (kind !== 'timeout') next.round!.guessed_ids = ['p2'];
      if (kind === 'missing') delete next.round!.incorrect_guess_ids;
      if (kind === 'own incorrect') {
        next.round!.guessed_ids = ['p1'];
        next.round!.incorrect_guess_ids = ['p1'];
      }
      if (kind === 'correct' || kind === 'timeout') {
        next.round!.status = 'results';
        next.round!.winner_id = kind === 'correct' ? 'p2' : null;
        next.round!.completion = { answer: 'cat', license: 'CC0', attribution: 'Original' };
      }
      act(() => deliver(next));
      expect(screen.queryByText('Your opponent guessed incorrectly!')).not.toBeInTheDocument();
      expect(screen.queryByText(/guess available|guess used/i)).not.toBeInTheDocument();
    },
  );
  it('reconstructs the current-round status on refresh and the first reconnect snapshot', async () => {
    const wrong = state();
    wrong.round!.guessed_ids = ['p2'];
    wrong.round!.incorrect_guess_ids = ['p2'];
    vi.mocked(rankedApi.state).mockResolvedValue(wrong);
    const view = page();
    await screen.findByLabelText('Your one guess');
    expect(screen.getByText('Your opponent guessed incorrectly!')).toBeInTheDocument();
    act(() => deliver(wrong));
    expect(screen.getAllByText('Your opponent guessed incorrectly!')).toHaveLength(1);
    view.unmount();
    vi.mocked(rankedApi.state).mockResolvedValue(state());
    page();
    await screen.findByLabelText('Your one guess');
    act(() => deliver(state()));
    act(() => connectionChanged('Reconnecting'));
    act(() => connectionChanged('Connected'));
    act(() => deliver({ ...wrong, revision: 2 }));
    expect(screen.getAllByText('Your opponent guessed incorrectly!')).toHaveLength(1);
    act(() => deliver({ ...wrong, revision: 3 }));
    expect(screen.getAllByText('Your opponent guessed incorrectly!')).toHaveLength(1);
  });
  it('preserves confirmed round status during interruption and clears it on a recovered new round', async () => {
    page();
    await screen.findByLabelText('Your one guess');
    act(() => deliver(state()));
    const wrong = state();
    wrong.revision = 2;
    wrong.round!.guessed_ids = ['p2'];
    wrong.round!.incorrect_guess_ids = ['p2'];
    act(() => deliver(wrong));
    expect(screen.getByText('Your opponent guessed incorrectly!')).toBeInTheDocument();
    act(() => connectionChanged('Reconnecting'));
    expect(screen.getByText('Your opponent guessed incorrectly!')).toBeInTheDocument();
    act(() => connectionChanged('Connected'));
    expect(screen.getByText('Your opponent guessed incorrectly!')).toBeInTheDocument();
    act(() => deliver({ ...wrong, revision: 3 }));
    expect(screen.getAllByText('Your opponent guessed incorrectly!')).toHaveLength(1);
    const next = state();
    next.revision = 4;
    next.round!.id = 'r2';
    next.round!.number = 2;
    act(() => deliver(next));
    expect(screen.queryByText('Your opponent guessed incorrectly!')).not.toBeInTheDocument();
  });
  it('separates lobby navigation click targets without changing queue entry', async () => {
    page('/ranked');
    await screen.findByRole('button', { name: 'Find opponent' });
    const nav = screen.getByRole('navigation', { name: 'Ranked lobby navigation' });
    expect(within(nav).getByRole('link', { name: 'View Standings' })).toHaveAttribute(
      'href',
      '/leaderboards',
    );
    expect(within(nav).getByRole('link', { name: 'Back to Menu' })).toHaveAttribute('href', '/');
    expect(
      screen.getByText('45-second reveal · One guess per round · First to 4 decisive wins'),
    ).toBeInTheDocument();
    expect(document.querySelector('.rank-icon')).not.toBeInTheDocument();
    expect(rankedApi.join).not.toHaveBeenCalled();
  });
  it.each(['win', 'loss', 'no_contest'])(
    'centers and separates %s final actions while preserving destinations',
    async (outcome) => {
      const final = state();
      final.status = 'complete';
      final.outcome = outcome === 'no_contest' ? 'no_contest' : 'victory';
      final.round = null;
      final.winner_id = outcome === 'win' ? 'p1' : outcome === 'loss' ? 'p2' : null;
      vi.mocked(rankedApi.state).mockResolvedValue(final);
      page();
      const again = await screen.findByRole('link', { name: 'Play Again' });
      const actions = again.parentElement!;
      const style = document.createElement('style');
      style.textContent = readFileSync('src/pages/ranked-presentation.css', 'utf8');
      document.head.append(style);
      try {
        const layout = getComputedStyle(actions);
        expect(layout.display).toBe('flex');
        expect(layout.gap).toBe('12px');
        expect(layout.justifyContent).toBe('center');
        expect(layout.flexWrap).toBe('wrap');
      } finally {
        style.remove();
      }
      expect(again).toHaveAttribute('href', '/ranked');
      expect(again).toHaveClass('button');
      expect(screen.getByRole('link', { name: 'Back to Menu' })).toHaveAttribute('href', '/');
      expect(document.querySelector('.rank-icon')).not.toBeInTheDocument();
    },
  );
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
  it('adds matching tier icons to standings and the server-configured ranked journey', async () => {
    const tiers: [number, string][] = [
      [1200, 'Bronze'],
      [1400, 'Silver'],
      [1600, 'Gold'],
      [1800, 'Diamond'],
    ];
    vi.mocked(rankedApi.leaderboard).mockResolvedValue({
      count: 4,
      next: null,
      previous: null,
      my_position: null,
      tiers,
      results: tiers.map(([rating, tier], i) => ({
        username: `player${i}`,
        rating,
        tier,
        position: i + 1,
      })),
    });
    page('/leaderboards');
    await screen.findByText('1200');
    for (const [minimum, tier] of tiers) {
      const cell = screen.getByRole('cell', { name: tier });
      expect(cell.querySelector(`.rank-icon-${tier.toLowerCase()}`)).toBeInTheDocument();
      const step = screen.getByText(`${tier} · ${minimum}`);
      expect(step.querySelector(`.rank-icon-${tier.toLowerCase()}`)).toBeInTheDocument();
    }
    expect(screen.getAllByRole('columnheader').map((cell) => cell.textContent)).toContain('Tier');
  });
  it.each([
    [1200, 'Bronze'],
    [1400, 'Silver'],
    [1600, 'Gold'],
    [1800, 'Diamond'],
  ] as const)(
    'places the %s Elo %s icon beside the profile rating without a separate text badge',
    async (rating, tier) => {
      vi.mocked(api).mockResolvedValue({ ...user, rating, ranked_tier: tier });
      vi.mocked(rankedApi.history).mockResolvedValue({
        count: 0,
        next: null,
        previous: null,
        results: [],
      });
      page('/players/player');
      const icon = await screen.findByRole('img', { name: `${tier} rank` });
      expect(icon.previousElementSibling).toHaveTextContent(`${rating} Elo`);
      expect(icon.parentElement).toHaveClass('profile-elo');
      expect(document.querySelector('.profile-panel .badge')).not.toBeInTheDocument();
      const style = document.createElement('style');
      style.textContent = readFileSync('src/pages/ranked-presentation.css', 'utf8');
      document.head.append(style);
      try {
        expect(getComputedStyle(icon.parentElement!).gap).toBe('8px');
        expect(getComputedStyle(icon.parentElement!).alignItems).toBe('center');
      } finally {
        style.remove();
      }
    },
  );
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
