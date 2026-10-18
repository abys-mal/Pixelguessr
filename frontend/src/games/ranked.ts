import { api, ApiError } from '../api';
import type { Page } from '../api';
export type ConnectionStatus = 'Connecting' | 'Connected' | 'Reconnecting' | 'Disconnected';
export interface QueueState {
  status: 'idle' | 'searching' | 'matched';
  ticket: string | null;
  match_id: string | null;
  server_now: string;
  queued_at?: string | null;
  search_window?: number;
  rating?: number;
  tier?: string | null;
}
export interface DuelPlayer {
  deleted?: boolean;
  title?: string | null;
  id: string;
  username: string;
  rating_before: number;
  rating_after: number | null;
  rating_delta: number | null;
  tier: string | null;
  wins: number;
  connected: boolean;
  reconnect_until: string | null;
}
export interface DuelRound {
  id: string;
  number: number;
  status: 'countdown' | 'active' | 'results';
  started_at: string;
  reveal_finishes_at: string;
  next_starts_at: string | null;
  winner_id: string | null;
  grid_size: number;
  revealed_tiles: number[];
  revealed_count: number;
  total_tiles: number;
  image_url: string;
  guessed_ids: string[];
  incorrect_guess_ids?: string[];
  completion: { answer: string; license: string; attribution: string } | null;
}
export interface DuelState {
  id: string;
  status: 'active' | 'complete';
  revision: number;
  server_now: string;
  me_id: string;
  winner_id: string | null;
  outcome: string;
  message: string;
  players: DuelPlayer[];
  round: DuelRound | null;
  waiting: boolean;
}
export interface Standing {
  title?: string | null;
  position: number;
  username: string;
  rating: number;
  tier: string | null;
}
export interface HistoryEntry {
  opponent_deleted?: boolean;
  opponent_title?: string | null;
  id: string;
  date: string;
  opponent: string;
  outcome: 'win' | 'loss' | 'no_contest';
  forfeit: boolean;
  score: number;
  opponent_score: number;
  rating_before: number;
  rating_after: number;
  rating_delta: number;
}
const matchUrl = (id: string) => `/api/ranked/matches/${encodeURIComponent(id)}/`;
export const rankedApi = {
  queue: () => api<QueueState>('/api/ranked/queue/'),
  join: (ticket: string) =>
    api<QueueState>('/api/ranked/queue/', {
      method: 'POST',
      body: JSON.stringify({ request_id: ticket }),
    }),
  cancel: (ticket: string) =>
    api<QueueState>('/api/ranked/queue/cancel/', {
      method: 'POST',
      body: JSON.stringify({ request_id: ticket }),
    }),
  state: (id: string) => api<DuelState>(matchUrl(id)),
  leave: (id: string) => api<DuelState>(matchUrl(id) + 'leave/', { method: 'POST' }),
  guess: (id: string, round_id: string, guess: string, request_id: string) =>
    api<{ state: DuelState; result: 'correct' | 'incorrect' }>(matchUrl(id) + 'guesses/', {
      method: 'POST',
      body: JSON.stringify({ round_id, guess, request_id }),
    }),
  leaderboard: (page: number) =>
    api<
      Page<Standing> & {
        my_position: number | null;
        tiers?: [number, string][];
        starting_elo?: number;
      }
    >(`/api/ranked/leaderboard/?page=${page}`),
  history: (username: string, page: number) =>
    api<Page<HistoryEntry>>(`/api/ranked/history/${encodeURIComponent(username)}/?page=${page}`),
};
export function connectRanked<T>(
  path: string,
  onState: (state: T) => void,
  onConnection: (status: ConnectionStatus) => void,
  onError: (error: Error) => void,
  onTime?: (server: string, sent: number, received: number) => void,
) {
  let socket: WebSocket | null = null;
  let stopped = false;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let sent: number | null = null;
  const sync = (active: WebSocket) => {
    sent = performance.now();
    active.send(JSON.stringify({ type: 'clock', token: String(sent) }));
  };
  const open = () => {
    if (stopped) return;
    const active = new WebSocket(
      `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${path}`,
    );
    socket = active;
    const current = () => !stopped && socket === active;
    active.onopen = () => {
      if (!current()) return;
      onConnection('Connected');
      sync(active);
    };
    active.onmessage = (event) => {
      if (!current()) return;
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      if (message?.type === 'clock' && sent !== null && message.token === String(sent)) {
        onTime?.(message.server_now, sent, performance.now());
        sent = null;
      } else if (message?.type === 'access_denied') {
        stop();
        onConnection('Disconnected');
        onError(new ApiError(message.detail, message.status || 403, message.code));
      } else if (message?.state) onState(message.state as T);
    };
    active.onclose = (event) => {
      if (!current()) return;
      socket = null;
      sent = null;
      if (event.code === 4403) {
        stop();
        onConnection('Disconnected');
        onError(new Error('This ranked connection is unavailable. Refresh to check the match.'));
        return;
      }
      onConnection('Reconnecting');
      clearTimeout(retry);
      retry = setTimeout(open, 2000);
    };
    active.onerror = () => {
      if (current()) active.close();
    };
  };
  const heartbeat = setInterval(() => {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'heartbeat' }));
      sync(socket);
    }
  }, 5000);
  function stop() {
    stopped = true;
    clearInterval(heartbeat);
    clearTimeout(retry);
    if (socket) {
      const active = socket;
      socket = null;
      // Closing CONNECTING sockets aborts the proxy handshake. Let it finish, then close.
      active.onmessage = active.onclose = active.onerror = null;
      if (active.readyState === WebSocket.OPEN) active.close();
      else if (active.readyState === WebSocket.CONNECTING) active.onopen = () => active.close();
    }
  }
  onConnection('Connecting');
  // StrictMode's setup/cleanup cycle cancels this before a handshake is created.
  retry = setTimeout(open, 0);
  return stop;
}
