import { api, type Page } from '../api';

export const root = '/api/moderation/workspace/';
export const post = <T>(url: string, body: unknown = {}) =>
  api<T>(url, { method: 'POST', body: JSON.stringify(body) });
export type Kind = 'warning' | 'probation' | 'suspension' | 'closed';
export interface Player {
  id: string;
  username: string;
  display_name: string;
  rating: number;
  date_joined: string;
  is_active: boolean;
  protected: boolean;
  moderator: boolean;
}
export interface Sanction {
  state: string;
  id: string;
  kind: Kind;
  category: string;
  reason: string;
  internal_note: string;
  starts_at: string;
  expires_at: string | null;
  acknowledged_at: string | null;
  revoked_at: string | null;
  issued_by: string;
  revoked_by: string | null;
  replaces: string | null;
  active: boolean;
}
export interface Report {
  id: string;
  subject: Player;
  reporter: string;
  category: string;
  details: string;
  created_at: string;
  resolved_at: string | null;
  resolution: string;
}
export interface Appeal {
  id: string;
  player: Player;
  sanction: Sanction;
  kind: Kind;
  explanation: string;
  created_at: string;
  resolved_at: string | null;
  status: string;
}
export interface Activity {
  id: string;
  actor: string;
  action: string;
  created_at: string;
  changes: Record<string, unknown>;
}
export interface PlayerDetail {
  player: Player;
  sanctions: Sanction[];
  reports: Report[];
  appeals: Appeal[];
  activity: Activity[];
}
export interface Overview {
  pending_reports: number;
  pending_appeals: number;
  administrator: boolean;
}
export type Inbox = Page<Report> | Page<Appeal>;
export const label = (value: string) => value.replaceAll('_', ' ');
export const date = (value: string | null) =>
  value ? new Date(value).toLocaleString() : 'No expiry';
export const expiry = (sanction: Pick<Sanction, 'kind' | 'expires_at'>) =>
  sanction.expires_at
    ? date(sanction.expires_at)
    : sanction.kind === 'closed'
      ? 'Permanent'
      : 'Indefinite';
