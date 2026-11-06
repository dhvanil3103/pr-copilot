import type { Review, ReviewDetail } from "../types";

export const review = (overrides: Partial<Review> = {}): Review => ({
  id: 1,
  repo_full_name: "acme/api",
  pr_number: 42,
  head_sha: "abcdef1234567",
  status: "done",
  error_message: null,
  input_tokens: 1200,
  output_tokens: 300,
  estimated_cost_usd: 0.0027,
  created_at: "2026-11-06T10:00:00Z",
  started_at: "2026-11-06T10:00:01Z",
  finished_at: "2026-11-06T10:00:31Z",
  comment_count: 2,
  duration_seconds: 30,
  pr_url: "https://github.com/acme/api/pull/42",
  ...overrides,
});

export const detail = (overrides: Partial<ReviewDetail> = {}): ReviewDetail => ({
  ...review(),
  summary: "## PR Copilot review\nLooks mostly fine.",
  comments: [
    { id: 3, agent: "test", file_path: "src/b.py", line: 4, severity: "info", category: "test", body: "Test empty input", posted: true, created_at: "2026-11-06T10:00:31Z" },
    { id: 2, agent: "review", file_path: "src/a.py", line: 20, severity: "warning", category: "bug", body: "Off by one", posted: true, created_at: "2026-11-06T10:00:31Z" },
    { id: 1, agent: "review", file_path: "src/a.py", line: 7, severity: "error", category: "security", body: "SQL injection", posted: true, created_at: "2026-11-06T10:00:31Z" },
  ],
  ...overrides,
});
