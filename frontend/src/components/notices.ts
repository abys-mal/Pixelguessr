export interface AccountSanction {
  id: string;
  active: boolean;
  kind: string;
  reason: string;
  starts_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  acknowledged_at: string | null;
  appeal: { eligible: boolean; detail: string; available_at: string | null };
}
export interface AccountAppeal {
  id: string;
  kind: string;
  explanation: string;
  status: string;
  created_at: string;
  resolved_at: string | null;
}
export interface AccountNoticesData {
  updates?: { message: string; created_at: string }[];
  sanctions: AccountSanction[];
  appeals: AccountAppeal[];
}
export const sanctionLabel = (kind: string) =>
  ({
    warning: 'Warning',
    probation: 'Probation',
    suspension: 'Suspension',
    closed: 'Account closure',
  })[kind] ?? kind;
export const appealLabel = (status: string) =>
  ({
    pending: 'Pending',
    upheld: 'Upheld',
    reversed: 'Reversed',
    sanction_changed: 'Sanction changed',
  })[status] ?? status;
export const noticeDate = (value: string) =>
  new Date(value).toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' });
export const noticeTime = (value: string) => new Date(value).toLocaleString();
const severity: Record<string, number> = { closed: 4, suspension: 3, probation: 2, warning: 1 };
// Display ordering only: active state and appeal eligibility always come from the API.
export const orderSanctions = (sanctions: AccountSanction[]) =>
  [...sanctions].sort(
    (a, b) =>
      (severity[b.kind] ?? 0) - (severity[a.kind] ?? 0) ||
      Date.parse(b.starts_at) - Date.parse(a.starts_at),
  );
export const historicalLabel = (sanction: AccountSanction) =>
  sanction.revoked_at
    ? 'Reversed'
    : new Date(sanction.starts_at) > new Date()
      ? 'Scheduled'
      : 'Expired';
