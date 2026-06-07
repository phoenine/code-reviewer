import type { DashboardSummary, FilterOptions, MembersResponse, ReviewListResponse, ReviewQuery } from '../types/dashboard';

function toQuery(params: Partial<Record<string, string | number | undefined>>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') {
      query.set(key, String(value));
    }
  });
  const result = query.toString();
  return result ? `?${result}` : '';
}

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export function fetchSummary(start?: number, end?: number): Promise<DashboardSummary> {
  const params: Record<string, string> = {};
  if (start !== undefined) params.start = String(start);
  if (end !== undefined) params.end = String(end);
  const qs = new URLSearchParams(params).toString();
  return getJson<DashboardSummary>(`/api/dashboard/summary${qs ? `?${qs}` : ''}`);
}

export function fetchReviews(query: ReviewQuery): Promise<ReviewListResponse> {
  return getJson<ReviewListResponse>(`/api/dashboard/reviews${toQuery({ ...query })}`);
}

export function fetchFilterOptions(): Promise<FilterOptions> {
  return getJson<FilterOptions>('/api/dashboard/filter-options');
}

export function fetchMembers(start?: number, end?: number): Promise<MembersResponse> {
  const params: Record<string, string> = {};
  if (start !== undefined) params.start = String(start);
  if (end !== undefined) params.end = String(end);
  const qs = new URLSearchParams(params).toString();
  return getJson<MembersResponse>(`/api/dashboard/members${qs ? `?${qs}` : ''}`);
}
