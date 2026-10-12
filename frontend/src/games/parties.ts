import { api, ApiError } from '../api';

export interface PartyMember {
  id: string;
  name: string;
  connected: boolean;
}
export interface PartyScore extends PartyMember {
  total_score: number;
  round_score: number;
  solved: boolean;
  left: boolean;
  round_rank: number;
  solved_rounds: number;
}
export interface PartyRound {
  id: string;
  number: number;
  status: 'countdown' | 'active' | 'results';
  started_at: string;
  reveal_finishes_at: string;
  next_starts_at: string | null;
  grid_size: number;
  revealed_count: number;
  total_tiles: number;
  revealed_tiles: number[];
  image_url: string;
  completion: { answer: string; license: string; attribution: string; category: string } | null;
  me: {
    solved: boolean;
    round_score: number;
    guess_count: number;
    incorrect_count: number;
    cooldown_until: string | null;
  };
}
export interface PartyState {
  code: string;
  status: 'lobby' | 'playing' | 'complete' | 'closed';
  revision: number;
  server_now: string;
  expires_at: string;
  host_id: string | null;
  me_id: string;
  settings: { reveal_seconds: number; round_limit: number };
  members: PartyMember[];
  match_id: string | null;
  round: PartyRound | null;
  leaderboard: PartyScore[];
  winners: string[];
  message: string;
}
export interface PartyGuess {
  round_id: string;
  guess: string;
  request_id: string;
}
export interface PartyGuessResult {
  state: PartyState;
  result: 'correct' | 'incorrect';
}
const url = (code: string) => `/api/parties/${encodeURIComponent(code.toUpperCase())}/`;
export const partyApi = {
  create: (data: {
    reveal_seconds: number;
    round_limit: number;
    display_name: string;
    request_id: string;
  }) => api<PartyState>('/api/parties/', { method: 'POST', body: JSON.stringify(data) }),
  join: (code: string, display_name: string) =>
    api<PartyState>(url(code) + 'join/', {
      method: 'POST',
      body: JSON.stringify({ display_name }),
    }),
  current: (code: string) => api<PartyState>(url(code)),
  settings: (code: string, data: PartyState['settings']) =>
    api<PartyState>(url(code), { method: 'PATCH', body: JSON.stringify(data) }),
  action: (code: string, action: 'start' | 'lobby', request_id: string) =>
    api<PartyState>(url(code) + `${action}/`, {
      method: 'POST',
      body: JSON.stringify({ request_id }),
    }),
  leave: (code: string) => api<void>(url(code) + 'leave/', { method: 'POST' }),
  guess: (code: string, data: PartyGuess) =>
    api<PartyGuessResult>(url(code) + 'guesses/', { method: 'POST', body: JSON.stringify(data) }),
};

export interface PartyConnection {
  guess(data: PartyGuess): Promise<PartyGuessResult>;
  close(): void;
}
export function connectParty(
  code: string,
  onState: (state: PartyState) => void,
  onConnection: (online: boolean) => void,
): PartyConnection {
  let socket: WebSocket | null = null;
  let stopped = false;
  let retries = 0;
  let retry: ReturnType<typeof setTimeout> | undefined;
  const pending = new Map<
    string,
    {
      resolve: (result: PartyGuessResult) => void;
      reject: (error: Error) => void;
      timeout: ReturnType<typeof setTimeout>;
    }
  >();
  const rejectPending = () => {
    for (const item of pending.values()) {
      clearTimeout(item.timeout);
      item.reject(new Error('Connection interrupted.'));
    }
    pending.clear();
  };
  const open = () => {
    if (stopped) return;
    socket = new WebSocket(
      `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/parties/${encodeURIComponent(code)}/`,
    );
    socket.onopen = () => {
      retries = 0;
      onConnection(true);
    };
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.state) onState(message.state as PartyState);
      const item = pending.get(message.request_id);
      if (item) {
        clearTimeout(item.timeout);
        pending.delete(message.request_id);
        if (message.type === 'guess_result')
          item.resolve({ state: message.state, result: message.result });
        else
          item.reject(
            new ApiError(message.detail || 'Guess failed.', message.status || 400, message.code),
          );
      }
    };
    socket.onclose = () => {
      onConnection(false);
      rejectPending();
      if (!stopped) retry = setTimeout(open, Math.min(8000, 1000 * 2 ** retries++));
    };
    socket.onerror = () => socket?.close();
  };
  const heartbeat = setInterval(() => {
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'heartbeat' }));
  }, 5000);
  open();
  return {
    async guess(data) {
      if (socket?.readyState !== WebSocket.OPEN) return partyApi.guess(code, data);
      try {
        return await new Promise<PartyGuessResult>((resolve, reject) => {
          const timeout = setTimeout(() => {
            pending.delete(data.request_id);
            reject(new Error('No acknowledgement.'));
          }, 8000);
          pending.set(data.request_id, { resolve, reject, timeout });
          socket!.send(JSON.stringify({ type: 'guess', ...data }));
        });
      } catch (error) {
        if (error instanceof ApiError) throw error;
        // Lost acknowledgements retry the SAME request UUID through the HTTP fallback.
        return partyApi.guess(code, data);
      }
    },
    close() {
      stopped = true;
      clearTimeout(retry);
      clearInterval(heartbeat);
      rejectPending();
      socket?.close();
    },
  };
}
