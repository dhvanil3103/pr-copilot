export type ReviewStatus = "queued" | "running" | "done" | "failed" | "skipped";
export type Severity = "info" | "warning" | "error";

export interface Review {
  id: number;
  repo_full_name: string;
  pr_number: number;
  head_sha: string;
  status: ReviewStatus;
  error_message: string | null;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  comment_count: number;
  duration_seconds: number | null;
  pr_url: string;
}

export interface ReviewComment {
  id: number;
  agent: "review" | "test";
  file_path: string;
  line: number;
  severity: Severity;
  category: string;
  body: string;
  posted: boolean;
  created_at: string;
}

export interface ReviewDetail extends Review {
  summary: string | null;
  comments: ReviewComment[];
}

export interface ReviewPage {
  items: Review[];
  total: number;
  page: number;
  page_size: number;
}

export interface Stats {
  total_reviews: number;
  counts_by_status: Record<ReviewStatus, number>;
  avg_duration_seconds: number | null;
  total_input_tokens: number;
  total_output_tokens: number;
  total_estimated_cost_usd: number;
}
