import { API_URL } from '@/shared/config';
import type { ApiErrorBody, QueryParams } from './types';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | undefined;

  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST';
  params?: QueryParams;
  body?: unknown;
}

export function buildUrl(path: string, params: QueryParams = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.append(key, String(value));
  }
  const query = search.toString();
  return `${API_URL}/${path.replace(/^\/+/, '')}${query ? `?${query}` : ''}`;
}

async function toApiError(response: Response): Promise<ApiError> {
  const body: ApiErrorBody | null = await response.json().catch(() => null);
  return new ApiError(
    response.status,
    body?.message ?? `Ошибка сервера: ${response.status}`,
    body?.code
  );
}

export async function request<T>(
  path: string,
  { method = 'GET', params, body }: RequestOptions = {}
): Promise<T> {
  const response = await fetch(buildUrl(path, params), {
    method,
    ...(body !== undefined && {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  });
  if (!response.ok) throw await toApiError(response);
  return response.json() as Promise<T>;
}
