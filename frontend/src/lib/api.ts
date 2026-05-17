/**
 * API helper for both server-side and client-side fetches.
 */

export function getApiUrl(): string {
  if (typeof window === 'undefined') {
    return process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';
  }
  return process.env.NEXT_PUBLIC_API_URL || '/api/v1';
}

/**
 * Client-side fetch wrapper that includes the JWT token from localStorage.
 */
export async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const baseUrl = getApiUrl();
  let token: string | null = null;
  if (typeof window !== 'undefined') {
    try {
      token = localStorage.getItem('access_token');
    } catch {
      token = null;
    }
  }

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  return fetch(`${baseUrl}${path}`, {
    ...options,
    headers,
  });
}

/**
 * Thrown for any non-2xx ``apiCall`` response. ``detail`` is the parsed
 * JSON body's ``detail`` field — string for simple errors, object for
 * structured ones (e.g. ``{error: "fact_responses_incomplete", missing_fact_ids: [...]}``).
 */
export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

function messageFromDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail;
  if (typeof detail === 'object' && detail !== null) {
    const m = (detail as { message?: unknown }).message;
    if (typeof m === 'string') return m;
  }
  return fallback;
}

/**
 * Typed client-side API call with JSON parsing and error handling.
 */
export async function apiCall<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await apiFetch(path, options);

  if (res.status === 401) {
    // Token expired — clear auth
    if (typeof window !== 'undefined') {
      try {
        localStorage.removeItem('access_token');
        localStorage.removeItem('user');
      } catch {
        // Ignore browsers that block storage access.
      }
    }
    throw new ApiError('Unauthorized', 401, 'Unauthorized');
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: 'Request failed' }));
    const detail = body.detail;
    throw new ApiError(messageFromDetail(detail, `API error: ${res.status}`), res.status, detail);
  }

  return res.json();
}
