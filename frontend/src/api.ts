export interface User {
  moderation_access?: boolean;
  administrator?: boolean;
  id: string;
  username: string;
  email: string;
  display_name: string;
  ranked_tier: string | null;
  rating: number;
  ranked_matches: number;
  ranked_wins: number;
  ranked_losses: number;
  title: string | null;
  date_joined: string;
}
export interface Restrictions {
  suspension?: boolean;
  notice?: {
    kind: 'warning' | 'probation' | 'suspension';
    message: string;
    expires_at: string | null;
  } | null;
  blocked: boolean;
  probation: boolean;
  unacknowledged_warnings: string[];
}
export interface Session {
  account_closed?: boolean;
  closure_message?: string;
  user: User | null;
  restrictions: Restrictions | null;
}
export interface ClosureDetails {
  reason: string;
  issued_at: string;
}
export interface Category {
  id: number;
  name: string;
  slug: string;
}
export interface Submission {
  id: string;
  canonical_answer: string;
  status: string;
  category: number;
  created_at: string;
}
export interface Page<T> {
  count: number;
  page: number;
  page_size: number;
  total_pages: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
    public fields?: Record<string, string[]>,
    public closure?: ClosureDetails,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function errorMessage(body: unknown, status: number): string {
  if (typeof body === 'object' && body !== null) {
    return Object.entries(body)
      .filter(([key]) => !['code', 'round', 'session', 'result', 'closure'].includes(key))
      .map(([key, value]) => {
        const content = Array.isArray(value) ? value.join(' ') : String(value);
        return ['detail', 'non_field_errors'].includes(key)
          ? content
          : `${key.replaceAll('_', ' ')}: ${content}`;
      })
      .join(' ');
  }
  return `Request failed (${status}). Please try again.`;
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set('Content-Type', 'application/json');
  if (!['GET', 'HEAD', 'OPTIONS'].includes(options.method ?? 'GET')) {
    // Fetch a fresh masked token after session rotation; never store bearer tokens.
    const tokenResponse = await fetch('/api/auth/csrf/', { credentials: 'same-origin' });
    if (!tokenResponse.ok) throw new Error('Unable to secure this request. Please try again.');
    const { csrfToken } = (await tokenResponse.json()) as { csrfToken: string };
    headers.set('X-CSRFToken', csrfToken);
  }
  let response: Response;
  try {
    response = await fetch(path, { ...options, headers, credentials: 'same-origin' });
  } catch {
    throw new Error('The service is unavailable. Please try again shortly.');
  }
  if (response.status === 204) return undefined as T;
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const code =
      typeof body === 'object' && body !== null && 'code' in body ? String(body.code) : undefined;
    const fields =
      typeof body === 'object' && body !== null
        ? Object.fromEntries(
            Object.entries(body).filter(
              (entry): entry is [string, string[]] =>
                Array.isArray(entry[1]) && entry[1].every((item) => typeof item === 'string'),
            ),
          )
        : undefined;
    const closure =
      code === 'account_closed' &&
      typeof body === 'object' &&
      body !== null &&
      'closure' in body &&
      typeof body.closure === 'object' &&
      body.closure !== null &&
      'reason' in body.closure &&
      typeof body.closure.reason === 'string' &&
      'issued_at' in body.closure &&
      typeof body.closure.issued_at === 'string'
        ? { reason: body.closure.reason, issued_at: body.closure.issued_at }
        : undefined;
    throw new ApiError(errorMessage(body, response.status), response.status, code, fields, closure);
  }
  return body as T;
}
