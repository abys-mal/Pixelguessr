import type { Restrictions } from '../api';

export type SanctionFeature = 'ranked' | 'party' | 'contributions';
export function restrictedSanction(restrictions: Restrictions | null, feature: SanctionFeature) {
  if (restrictions?.blocked) return 'closed';
  if (restrictions?.suspension) return 'suspension';
  if (feature !== 'party' && restrictions?.probation) return 'probation';
  if (restrictions?.unacknowledged_warnings.length) return 'warning';
  return undefined;
}
