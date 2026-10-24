import { API_URL } from '@/shared/config';
import type { ApiErrorBody, BBoxTuple, QueryParams } from './types';

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST';
  params?: QueryParams;
}

export function buildUrl(path: string, params: QueryParams = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.append(key, String(value));
  }
  const query = search.toString();
  return `${API_URL}/${path.replace(/^\/+/, '')}${query ? `?${query}` : ''}`;
}

export function bboxToQuery([west, south, east, north]: BBoxTuple): QueryParams {
  return { west, south, east, north };
}

async function readErrorMessage(response: Response): Promise<string> {
  const body: ApiErrorBody | null = await response.json().catch(() => null);
  const detail = body?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail[0]) return detail[0].msg;
  return `Ошибка сервера: ${response.status}`;
}

export async function request<T>(
  path: string,
  { method = 'GET', params }: RequestOptions = {}
): Promise<T> {
  const response = await fetch(buildUrl(path, params), { method });
  if (!response.ok) throw new ApiError(response.status, await readErrorMessage(response));
  return response.json() as Promise<T>;
}
