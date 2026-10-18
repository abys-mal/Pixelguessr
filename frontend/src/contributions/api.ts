import type { Page } from '../api';
export const contributionRoot = '/api/library/contributions/';
export interface Contribution {
  id: string;
  status: 'pending' | 'approved' | 'rejected' | 'removed';
  created_at: string;
  canonical_answer?: string;
  accepted_synonyms?: string[];
  category?: number;
  category_name?: string;
  source?: string;
  source_url?: string;
  license?: string;
  attribution?: string;
  retired?: boolean;
  explanation?: string;
  preview_url?: string | null;
  submitter?: string;
  submitter_id?: string | null;
  rights_acknowledged_at?: string | null;
}
export interface ContributionPage extends Page<Contribution> {
  stats: { total: number; pending: number; approved: number };
}
export const contributionStatuses = ['all', 'pending', 'approved', 'rejected', 'removed'];
export const statusLabel = (status: string) => status[0].toUpperCase() + status.slice(1);

const sources: Record<string, string> = {
  manual: 'Player upload',
  licensed: 'Licensed third-party image',
  ai: 'AI-generated',
  commons: 'Wikimedia Commons',
};
export const sourceLabel = (source?: string) => sources[source ?? ''] ?? source ?? 'Not supplied';
