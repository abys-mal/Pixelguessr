import { api } from '../api';

export type RoundStatus = 'pending' | 'active' | 'solved' | 'forfeited' | 'expired';
export interface GameRound {
  id: string;
  number: number;
  status: RoundStatus;
  server_now: string;
  started_at: string | null;
  reveal_finishes_at: string | null;
  expires_at: string | null;
  reveal_duration_seconds: number;
  grid_size: number;
  revealed_count: number;
  total_tiles: number;
  revealed_tiles: number[];
  guess_count: number;
  score: number;
  available_points: number;
  can_forfeit: boolean;
  image_url: string | null;
  completion: null | {
    answer: string;
    outcome: 'solved' | 'forfeited';
    score: number;
    solved_in_seconds: number | null;
    guesses: number;
    license: string;
    attribution: string;
    category: string;
  };
}
export interface GameSession {
  id: string;
  revision: number;
  status: 'active' | 'complete' | 'expired';
  server_now: string;
  expires_at: string | null;
  total_rounds: number;
  current_round_number: number;
  total_score: number;
  max_score: number;
  solved_rounds: number;
  rounds: { number: number; outcome: RoundStatus; score: number | null; answer?: string }[];
}
export interface GameState {
  round: GameRound | null;
  session: GameSession | null;
}
export interface GameResponse extends GameState {
  result?:
    | 'correct'
    | 'incorrect'
    | 'already_completed'
    | 'forfeited'
    | 'started'
    | 'resumed'
    | 'session_complete';
}
const base = '/api/games/singleplayer/';
export const gameApi = {
  current: () => api<GameState>(base + 'current/'),
  start: (request_id: string) =>
    api<GameResponse>(base + 'rounds/', { method: 'POST', body: JSON.stringify({ request_id }) }),
  guess: (id: string, guess: string, request_id: string) =>
    api<GameResponse>(`${base}rounds/${id}/guesses/`, {
      method: 'POST',
      body: JSON.stringify({ guess, request_id }),
    }),
  next: (id: string, request_id: string) =>
    api<GameResponse>(`${base}rounds/${id}/next/`, {
      method: 'POST',
      body: JSON.stringify({ request_id }),
    }),
  forfeit: (id: string) =>
    api<GameResponse>(`${base}rounds/${id}/forfeit/`, { method: 'POST', body: JSON.stringify({}) }),
};
