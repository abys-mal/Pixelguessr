import { api } from '../api';

export interface GameRound {
  id: string;
  status: 'active' | 'solved' | 'expired';
  server_now: string;
  started_at: string;
  reveal_finishes_at: string;
  expires_at: string;
  grid_size: number;
  revealed_count: number;
  total_tiles: number;
  revealed_tiles: number[];
  guess_count: number;
  image_url: string | null;
  completion: null | {
    answer: string;
    solved_in_seconds: number;
    guesses: number;
    license: string;
    attribution: string;
    category: string;
  };
}
export const gameApi = {
  current: () => api<{ round: GameRound | null }>('/api/games/singleplayer/current/'),
  start: (request_id: string) =>
    api<{ round: GameRound }>('/api/games/singleplayer/rounds/', {
      method: 'POST',
      body: JSON.stringify({ request_id }),
    }),
  guess: (id: string, guess: string, request_id: string) =>
    api<{ round: GameRound; result: 'correct' | 'incorrect' | 'already_solved' }>(
      `/api/games/singleplayer/rounds/${id}/guesses/`,
      {
        method: 'POST',
        body: JSON.stringify({ guess, request_id }),
      },
    ),
};
