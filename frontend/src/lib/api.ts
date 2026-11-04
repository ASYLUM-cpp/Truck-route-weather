import type { AppConfig, HeatmapResponse, LngLat, PlanResponse, Place } from '../types';

const BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly fields: Record<string, string> = {},
  ) {
    super(message);
  }
}

function flattenErrors(body: unknown, prefix = ''): Record<string, string> {
  const out: Record<string, string> = {};
  if (!body || typeof body !== 'object') return out;
  for (const [key, value] of Object.entries(body as Record<string, unknown>)) {
    const name = prefix ? `${prefix}.${key}` : key;
    if (Array.isArray(value) && typeof value[0] === 'string') out[name] = value[0];
    else if (typeof value === 'string') out[name] = value;
    else Object.assign(out, flattenErrors(value, name));
  }
  return out;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    });
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err;
    throw new ApiError('The server is unreachable. Check your connection and try again.', 0);
  }
  if (resp.ok) return resp.json() as Promise<T>;

  let body: unknown = null;
  try {
    body = await resp.json();
  } catch {
    /* non-JSON error body */
  }
  const detail = (body as { detail?: string } | null)?.detail;
  const fields = detail ? {} : flattenErrors(body);
  const message =
    detail ??
    Object.values(fields)[0] ??
    (resp.status === 429
      ? 'Too many requests. Wait a minute and try again.'
      : 'Something went wrong on the server. Try again.');
  throw new ApiError(message, resp.status, fields);
}

export interface PlanRequest {
  origin: { lat: number; lon: number };
  destination: { lat: number; lon: number };
  departure: string;
  load_lb: number;
}

export const api = {
  config: () => request<AppConfig>('/api/config'),

  places: (q: string, signal: AbortSignal) =>
    request<{ results: Place[] }>(`/api/places?q=${encodeURIComponent(q)}`, { signal }).then((r) => r.results),

  reverse: (lat: number, lon: number) =>
    request<{ result: Place | null }>(`/api/reverse?lat=${lat.toFixed(6)}&lon=${lon.toFixed(6)}`).then((r) => r.result),

  plan: (body: PlanRequest) => request<PlanResponse>('/api/plan', { method: 'POST', body: JSON.stringify(body) }),

  heatmap: (body: { paths: LngLat[][]; departure: string; load_lb: number }, signal: AbortSignal) =>
    request<HeatmapResponse>('/api/heatmap', {
      method: 'POST',
      body: JSON.stringify(body),
      signal,
    }),
};
