export interface User {
  id: string;
  username: string;
  email: string;
  display_name: string;
  ranked_tier: string;
  title: string | null;
  date_joined: string;
}
export interface Restrictions {
  blocked: boolean;
  probation: boolean;
  unacknowledged_warnings: string[];
}
export interface Session {
  user: User | null;
  restrictions: Restrictions | null;
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
  next: string | null;
  previous: string | null;
  results: T[];
}

function errorMessage(body: unknown, status: number): string {
  if (typeof body === 'object' && body !== null) {
    return Object.entries(body)
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
  if (!response.ok) throw new Error(errorMessage(body, response.status));
  return body as T;
}
