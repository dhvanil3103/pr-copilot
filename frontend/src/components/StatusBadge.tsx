import type { ReviewStatus } from "../types";

export function StatusBadge({ status }: { status: ReviewStatus }) {
  return <span className={`badge badge-${status}`}>{status}</span>;
}
