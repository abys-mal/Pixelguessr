import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import { ApiError } from '../api';
import { AuthContext } from '../auth/context';
import {
  connectParty,
  partyApi,
  type PartyState,
  type PartyGuess,
  type PartyGuessResult,
} from '../games/parties';

vi.mock('../games/parties', () => ({
  connectParty: vi.fn(),
  partyApi: {
    create: vi.fn(),
    join: vi.fn(),
    current: vi.fn(),
    settings: vi.fn(),
    action: vi.fn(),
    leave: vi.fn(),
    guess: vi.fn(),
    kick: vi.fn(),
  },
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
let current: PartyState;
let push: (state: PartyState) => void;
let online: (connected: boolean) => void;
let deny: (error: ApiError) => void;
let sendGuess: ReturnType<typeof vi.fn<(data: PartyGuess) => Promise<PartyGuessResult>>>;
function makeParty(): PartyState {
  return {
    code: 'K7M2Q9',
    status: 'lobby',
    revision: 1,
    server_now: new Date().toISOString(),
    expires_at: new Date(Date.now() + 86400000).toISOString(),
    host_id: 'host',
    me_id: 'host',
    settings: { reveal_seconds: 30, round_limit: 10 },
    members: [
      { id: 'host', name: 'Avery', connected: true },
      { id: 'friend', name: 'Robin', connected: true },
    ],
    match_id: null,
    round: null,
    leaderboard: [],
    winners: [],
    message: '',
    end_reason: '',
    end_message: '',
  };
}
function active(): PartyState {
  const state = makeParty();
  return {
    ...state,
    status: 'playing',
    match_id: 'match-one',
    round: {
      id: 'round-one',
      number: 1,
      status: 'active',
      started_at: state.server_now,
      reveal_finishes_at: new Date(Date.parse(state.server_now) + 30000).toISOString(),
      next_starts_at: null,
      grid_size: 20,
      revealed_count: 0,
      total_tiles: 400,
      revealed_tiles: [],
      image_url: '/opaque-frame/',
      completion: null,
      me: {
        solved: false,
        round_score: 0,
        guess_count: 0,
        incorrect_count: 0,
        cooldown_until: null,
      },
    },
    leaderboard: state.members.map((m, i) => ({
      ...m,
      total_score: 0,
      round_score: 0,
      solved: false,
      left: false,
      round_rank: i + 1,
      solved_rounds: 0,
    })),
  };
}
function page(path = '/party/K7M2Q9') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthContext.Provider value={guest}>
        <App />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}
function update(state: PartyState) {
  current = { ...state, revision: current.revision + 1 };
  act(() => push(current));
}
beforeEach(() => {
  current = makeParty();
  sendGuess = vi.fn(async () => ({ state: current, result: 'incorrect' as const }));
  vi.mocked(partyApi.current).mockImplementation(async () => current);
  vi.mocked(partyApi.create).mockImplementation(async () => current);
  vi.mocked(partyApi.join).mockImplementation(async () => current);
  vi.mocked(partyApi.settings).mockImplementation(async (_code, settings) => {
    current = { ...current, settings, revision: current.revision + 1 };
    return current;
  });
  vi.mocked(partyApi.action).mockImplementation(async (_code, action) => {
    current = action === 'start' ? active() : makeParty();
    current.revision += 10;
    return current;
  });
  vi.mocked(partyApi.leave).mockResolvedValue(undefined);
  vi.mocked(partyApi.kick).mockImplementation(async (_code, id) => {
    current = {
      ...current,
      members: current.members.filter((m) => m.id !== id),
      revision: current.revision + 1,
    };
    return current;
  });
  vi.mocked(connectParty).mockImplementation((_code, onState, onConnection, onAccessDenied) => {
    push = onState;
    deny = onAccessDenied!;
    online = onConnection;
    onConnection(true);
    return { guess: sendGuess, close: vi.fn() };
  });
});

describe('Multiplayer parties', () => {
  it('creates a guest party with the only two configurable game settings', async () => {
    const user = userEvent.setup();
    page('/party/new');
    expect(screen.queryByLabelText('Display name')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Reveal duration')).toHaveValue('30');
    expect(screen.getByLabelText('Number of rounds')).toHaveValue('10');
    await user.selectOptions(screen.getByLabelText('Reveal duration'), '15');
    await user.selectOptions(screen.getByLabelText('Number of rounds'), '5');
    await user.click(screen.getByRole('button', { name: 'Create Party' }));
    await screen.findByRole('heading', { name: 'Party lobby' });
    expect(partyApi.create).toHaveBeenCalledWith(
      expect.objectContaining({ reveal_seconds: 15, round_limit: 5 }),
    );
    expect(screen.getByRole('button', { name: 'Start Game' })).toBeEnabled();
  });
  it('joins using a lower-case invite code and display name', async () => {
    const user = userEvent.setup();
    page('/party/join');
    await user.type(screen.getByLabelText('Party code'), 'k7m2q9');
    await user.click(screen.getByRole('button', { name: 'Join Party' }));
    await screen.findByRole('heading', { name: 'Party lobby' });
    expect(partyApi.join).toHaveBeenCalledWith('K7M2Q9');
  });
  it('asks a new guest opening an invite link to join', async () => {
    const user = userEvent.setup();
    vi.mocked(partyApi.current).mockRejectedValue(new ApiError('Join first.', 404));
    page();
    await screen.findByRole('heading', { name: 'Join Party K7M2Q9' });
    await user.click(screen.getByRole('button', { name: 'Join Party' }));
    await screen.findByRole('heading', { name: 'Party lobby' });
  });
  it.each(['Party full.', 'This party has expired.', 'That name is taken.'])(
    'shows a useful join error: %s',
    async (message) => {
      const user = userEvent.setup();
      vi.mocked(partyApi.join).mockRejectedValue(new ApiError(message, 409));
      page('/party/join');
      await user.type(screen.getByLabelText('Party code'), 'K7M2Q9');
      await user.click(screen.getByRole('button', { name: 'Join Party' }));
      expect(await screen.findByRole('alert')).toHaveTextContent(message);
    },
  );
  it('hides host controls from other players and streams membership changes', async () => {
    current.me_id = 'friend';
    page();
    await screen.findByRole('heading', { name: 'Party lobby' });
    expect(screen.queryByRole('button', { name: /Remove Robin/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Start Game' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Reveal duration')).not.toBeInTheDocument();
    expect(screen.getByText('Waiting for Avery to start.')).toBeInTheDocument();
    update({
      ...current,
      members: [...current.members, { id: 'third', name: 'Sage', connected: true }],
      host_id: 'friend',
    });
    expect(screen.getByText('Sage')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start Game' })).toBeEnabled();
  });
  it('disables a one-player start and saves host settings', async () => {
    const user = userEvent.setup();
    current.members = current.members.slice(0, 1);
    page();
    await screen.findByRole('heading', { name: 'Party lobby' });
    expect(screen.getByRole('button', { name: 'Start Game' })).toBeDisabled();
    await user.selectOptions(screen.getByLabelText('Reveal duration'), '60');
    await user.click(screen.getByRole('button', { name: 'Save Settings' }));
    await waitFor(() =>
      expect(partyApi.settings).toHaveBeenCalledWith('K7M2Q9', {
        reveal_seconds: 60,
        round_limit: 10,
      }),
    );
  });
  it('sends Enter guesses, displays penalties and cooldown, then retains input focus', async () => {
    const user = userEvent.setup();
    current = active();
    sendGuess.mockImplementation(async () => {
      current = {
        ...current,
        revision: 2,
        round: {
          ...current.round!,
          me: {
            ...current.round!.me,
            round_score: -50,
            guess_count: 1,
            incorrect_count: 1,
            cooldown_until: new Date(Date.parse(current.server_now) + 2000).toISOString(),
          },
        },
      };
      return { state: current, result: 'incorrect' };
    });
    page();
    const input = await screen.findByLabelText('Your Guess');
    expect(input).toHaveFocus();
    await user.type(input, 'castle{Enter}');
    await screen.findByText('Incorrect. −50 points.');
    expect(input).toHaveFocus();
    expect(input).toHaveValue('');
    await user.type(input, 'beacon{Enter}');
    expect(sendGuess).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: /Wait/ })).toBeDisabled();
    update({
      ...current,
      server_now: new Date(Date.parse(current.server_now) + 2000).toISOString(),
    });
    expect(screen.getByRole('button', { name: 'Submit Guess' })).toBeEnabled();
  });
  it('switches correct players to spectators without revealing the answer', async () => {
    const user = userEvent.setup();
    current = active();
    sendGuess.mockImplementation(async () => {
      current = {
        ...current,
        revision: 2,
        round: { ...current.round!, me: { ...current.round!.me, solved: true, round_score: 810 } },
      };
      return { state: current, result: 'correct' };
    });
    page();
    await user.type(await screen.findByLabelText('Your Guess'), 'beacon{Enter}');
    expect(await screen.findByRole('heading', { name: 'Correct!' })).toHaveFocus();
    expect(screen.queryByLabelText('Your Guess')).not.toBeInTheDocument();
    expect(screen.queryByText('lighthouse')).not.toBeInTheDocument();
    expect(screen.getByText('Waiting for the round to end.')).toBeInTheDocument();
    expect(screen.queryByRole('table', { name: 'Overall leaderboard' })).not.toBeInTheDocument();
    expect(screen.getByText('0 of 2 players solved')).toBeInTheDocument();
  });
  it('receives round results and automatic new rounds with a cleared focused input', async () => {
    const user = userEvent.setup();
    current = active();
    page();
    await user.type(await screen.findByLabelText('Your Guess'), 'unfinished guess');
    update({
      ...current,
      round: {
        ...current.round!,
        status: 'results',
        revealed_count: 400,
        completion: {
          answer: 'lighthouse',
          license: 'CC0',
          category: 'Places',
          attribution: 'Original drawing',
        },
        next_starts_at: new Date(Date.parse(current.server_now) + 5000).toISOString(),
      },
    });
    expect(screen.getByRole('heading', { name: 'Round 1 results' })).toHaveFocus();
    expect(screen.getByText('lighthouse')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Round ranking' })).toBeInTheDocument();
    update({
      ...current,
      round: { ...active().round!, id: 'round-two', number: 2, status: 'countdown' },
    });
    expect(screen.getByRole('heading', { name: 'Get ready' })).toHaveFocus();
    expect(screen.queryByLabelText('Your Guess')).not.toBeInTheDocument();
    update({ ...current, round: { ...current.round!, status: 'active' } });
    expect(screen.getByLabelText('Your Guess')).toHaveFocus();
    expect(screen.getByLabelText('Your Guess')).toHaveValue('');
  });
  it('restores solved status and leaderboard after a refresh and reconnects without new membership', async () => {
    current = active();
    current.round!.me.solved = true;
    current.round!.me.round_score = 563;
    page();
    await screen.findByRole('heading', { name: 'Correct!' });
    act(() => online(false));
    expect(screen.getByText(/Reconnecting/)).toBeInTheDocument();
    const newState = {
      ...current,
      leaderboard: current.leaderboard.map((p) => ({ ...p, total_score: 563 })),
    };
    update(newState);
    act(() => online(true));
    expect(screen.queryByText(/Reconnecting/)).not.toBeInTheDocument();
    expect(screen.queryByRole('table', { name: 'Overall leaderboard' })).not.toBeInTheDocument();
    expect(screen.getByText('0 of 2 players solved')).toBeInTheDocument();
    expect(partyApi.join).not.toHaveBeenCalled();
    expect(partyApi.create).not.toHaveBeenCalled();
  });
  it('does not carry a delayed guess acknowledgment into the next round', async () => {
    const user = userEvent.setup();
    let acknowledge!: (reply: PartyGuessResult) => void;
    sendGuess.mockImplementation(
      () =>
        new Promise((resolve) => {
          acknowledge = resolve;
        }),
    );
    current = active();
    page();
    await user.type(await screen.findByLabelText('Your Guess'), 'wrong answer');
    await user.keyboard('{Enter}');
    await waitFor(() => expect(sendGuess).toHaveBeenCalledOnce());
    update({ ...current, round: { ...current.round!, id: 'round-two', number: 2 } });
    await act(async () => {
      acknowledge({ state: current, result: 'incorrect' });
    });
    expect(screen.getByRole('heading', { name: 'Round 2 of 10' })).toBeInTheDocument();
    expect(screen.queryByText('Incorrect. −50 points.')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Your Guess')).toHaveValue('');
    expect(screen.getByLabelText('Your Guess')).toHaveFocus();
  });
  it('ignores stale shared events that would undo a solve', async () => {
    current = active();
    page();
    await screen.findByLabelText('Your Guess');
    const stale = current;
    update({
      ...current,
      round: { ...current.round!, me: { ...current.round!.me, solved: true } },
    });
    act(() => push(stale));
    expect(screen.getByRole('heading', { name: 'Correct!' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Your Guess')).not.toBeInTheDocument();
  });
  it('highlights tied winners and returns everyone to the lobby by keyboard', async () => {
    const user = userEvent.setup();
    current = { ...active(), status: 'complete', winners: ['host', 'friend'] };
    page();
    const heading = await screen.findByRole('heading', { name: 'Final Results' });
    expect(heading).toHaveFocus();
    expect(screen.getByText('Tied winners: Avery, Robin')).toBeInTheDocument();
    await user.tab();
    const lobby = screen.getByRole('button', { name: 'Return to Lobby' });
    expect(lobby).toHaveFocus();
    expect(fireEvent.keyDown(lobby, { key: 'Enter', repeat: true })).toBe(false);
    expect(partyApi.action).not.toHaveBeenCalled();
    await user.keyboard('{Enter}');
    expect(await screen.findByRole('heading', { name: /Lobby 2/ })).toHaveFocus();
  });
  it('leaves a party without modifying a match from the client', async () => {
    const user = userEvent.setup();
    page();
    await user.click(await screen.findByRole('button', { name: 'Leave Party' }));
    await screen.findByRole('heading', { name: 'Join Party' });
    expect(partyApi.leave).toHaveBeenCalledWith('K7M2Q9');
  });
  it('opens a host-only confirmation with an unchecked ban option, keyboard containment and focus restoration', async () => {
    const user = userEvent.setup();
    page();
    const trigger = await screen.findByRole('button', { name: 'Remove Robin' });
    expect(screen.queryByRole('button', { name: 'Remove Avery' })).not.toBeInTheDocument();
    await user.click(trigger);
    const dialog = screen.getByRole('dialog', { name: 'Remove player?' });
    expect(dialog).toHaveAccessibleDescription('Remove Robin from this party?');
    const checkbox = within(dialog).getByRole('checkbox', {
      name: 'Prevent this player from re-joining',
    });
    expect(checkbox).not.toBeChecked();
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus();
    expect(partyApi.kick).not.toHaveBeenCalled();
    await user.tab();
    expect(within(dialog).getByRole('button', { name: 'Remove player' })).toHaveFocus();
    await user.tab();
    expect(checkbox).toHaveFocus();
    await user.tab({ shift: true });
    expect(within(dialog).getByRole('button', { name: 'Remove player' })).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    await user.click(trigger);
    await user.click(screen.getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(trigger).toHaveFocus();
    expect(partyApi.kick).not.toHaveBeenCalled();
  });
  it.each([false, true])('confirms removal with the selected party-ban option: %s', async (ban) => {
    const user = userEvent.setup();
    page();
    await user.click(await screen.findByRole('button', { name: 'Remove Robin' }));
    if (ban) await user.click(screen.getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: 'Remove player' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(partyApi.kick).toHaveBeenCalledWith('K7M2Q9', 'friend', ban, expect.any(String));
    expect(screen.getByRole('heading', { name: /Lobby 1/ })).toHaveFocus();
    expect(screen.getByRole('button', { name: 'Start Game' })).toBeDisabled();
  });
  it('dismisses a confirmation safely when its target leaves remotely', async () => {
    const user = userEvent.setup();
    page();
    await user.click(await screen.findByRole('button', { name: 'Remove Robin' }));
    update({ ...current, members: current.members.slice(0, 1) });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Lobby 1/ })).toHaveFocus();
    expect(partyApi.kick).not.toHaveBeenCalled();
  });
  it('shows a failed removal inside the confirmation without removing the player', async () => {
    const user = userEvent.setup();
    vi.mocked(partyApi.kick).mockRejectedValue(new ApiError('Try again later.', 503));
    page();
    await user.click(await screen.findByRole('button', { name: 'Remove Robin' }));
    await user.click(screen.getByRole('button', { name: 'Remove player' }));
    const dialog = screen.getByRole('dialog', { name: 'Remove player?' });
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Try again later.');
    expect(screen.getByRole('heading', { name: /Lobby 2/ })).toBeInTheDocument();
  });
  it.each(['The host left the party.', 'The host disconnected.', 'Not enough players remain.'])(
    'ends the match with its authoritative explanation: %s',
    async (message) => {
      current = active();
      page();
      await screen.findByLabelText('Your Guess');
      const previous = current;
      update({ ...current, status: 'aborted', end_message: message, round: null });
      expect(screen.getByRole('heading', { name: 'Match ended' })).toHaveFocus();
      expect(screen.getByText(message)).toBeInTheDocument();
      expect(screen.queryByLabelText('Your Guess')).not.toBeInTheDocument();
      expect(screen.queryByRole('table')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Return to Lobby' })).not.toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Return Home' })).toHaveAttribute('href', '/');
      act(() => push({ ...previous, revision: current.revision + 10 }));
      expect(screen.getByRole('heading', { name: 'Match ended' })).toBeInTheDocument();
    },
  );
  it('shows party closure when the lobby host leaves', async () => {
    page();
    await screen.findByRole('heading', { name: 'Party lobby' });
    update({ ...current, status: 'closed', end_message: 'The host left the party.' });
    expect(screen.getByRole('heading', { name: 'Party closed' })).toHaveFocus();
    expect(screen.queryByRole('button', { name: 'Start Game' })).not.toBeInTheDocument();
  });
  it.each(['party_removed', 'party_banned'])(
    'stops a removed player from reconnecting or automatically joining: %s',
    async (code) => {
      current = active();
      page();
      await screen.findByLabelText('Your Guess');
      act(() => deny(new ApiError('You were removed from this party.', 403, code)));
      expect(screen.getByRole('heading', { name: 'Removed from party' })).toBeInTheDocument();
      expect(screen.queryByLabelText('Your Guess')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Join Party' })).not.toBeInTheDocument();
      expect(partyApi.join).not.toHaveBeenCalled();
      expect(vi.mocked(connectParty).mock.results[0].value.close).toHaveBeenCalled();
    },
  );
  it('enforces a persisted removal notice after page refresh', async () => {
    vi.mocked(partyApi.current).mockRejectedValue(
      new ApiError('You cannot rejoin this party.', 403, 'party_banned'),
    );
    page();
    await screen.findByRole('heading', { name: 'Removed from party' });
    expect(connectParty).not.toHaveBeenCalled();
    expect(partyApi.join).not.toHaveBeenCalled();
  });
  it('shows compact solved counts during gameplay and full standings only between rounds', async () => {
    current = active();
    current.leaderboard[1].solved = true;
    page();
    await screen.findByLabelText('Your Guess');
    expect(screen.getByText('1 of 2 players solved')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    update({
      ...current,
      round: {
        ...current.round!,
        status: 'results',
        completion: {
          answer: 'lighthouse',
          license: 'CC0',
          attribution: 'Original',
          category: 'Places',
        },
      },
    });
    expect(screen.getByRole('table', { name: 'Overall leaderboard' })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Round ranking' })).toBeInTheDocument();
    expect(screen.queryByText('1 of 2 players solved')).not.toBeInTheDocument();
    update({ ...current, status: 'complete', winners: ['friend'] });
    expect(screen.getByRole('table', { name: 'Overall leaderboard' })).toBeInTheDocument();
    expect(screen.getByText('Winner: Robin')).toBeInTheDocument();
  });
  it('redirects the old party-mode route to creation', async () => {
    page('/modes/party');
    expect(await screen.findByRole('heading', { name: 'Create Party' })).toBeInTheDocument();
  });
});
