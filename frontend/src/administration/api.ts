import { api } from '../api';
export const adminRoot = '/api/moderation/workspace/administration/';
export const send = <T>(path: string, body: unknown) =>
  api<T>(adminRoot + path, { method: 'POST', body: JSON.stringify(body) });
export interface AuditEntry {
  id: string;
  actor: string;
  action: string;
  target_type: string;
  target_id: string;
  created_at: string;
  changes: Record<string, unknown>;
  reason: string;
}
export interface HealthCheck {
  name: string;
  state: string;
}
export interface AdminOverview {
  players: number;
  active_games: number;
  playable_images: number;
  pending_images: number;
  incomplete_imports: number;
  recent_activity: AuditEntry[];
  health: HealthCheck[];
  import_tracking_note: string;
}
export interface LibraryImage {
  id: string;
  canonical_answer: string;
  accepted_synonyms: string[];
  category: number;
  category_name: string;
  status: string;
  license: string;
  attribution: string;
  source_url: string;
  source: string;
  preview_url: string;
  review_reason: string;
  import_metadata: Record<string, unknown>;
}
export interface Batch {
  id: string;
  name: string;
  items: number;
  failed: number;
  pending: number;
  created_at: string;
}
export interface ImportItem {
  id: string;
  filename: string;
  status: string;
  error: string;
  image: LibraryImage | null;
}
export interface Announcement {
  title: string;
  body: string;
  published: boolean;
  expires_at: string | null;
  version: number;
  editor?: string | null;
  updated_at?: string;
}
