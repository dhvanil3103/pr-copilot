import type { ReviewDetail, ReviewPage, ReviewStatus, Stats } from "./types";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return (await response.json()) as T;
}

export interface ReviewFilters {
  page?: number;
  repo?: string;
  status?: ReviewStatus | "";
}

export function fetchReviews({ page = 1, repo, status }: ReviewFilters = {}): Promise<ReviewPage> {
  const params = new URLSearchParams({ page: String(page), page_size: "20" });
  if (repo) params.set("repo", repo);
  if (status) params.set("status", status);
  return getJson(`/api/reviews?${params}`);
}

export const fetchReview = (id: number) => getJson<ReviewDetail>(`/api/reviews/${id}`);
export const fetchStats = () => getJson<Stats>("/api/stats");
