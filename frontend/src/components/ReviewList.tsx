import { formatDuration, formatTime } from "../format";
import type { Review, ReviewStatus } from "../types";
import { StatusBadge } from "./StatusBadge";

const STATUSES: ReviewStatus[] = ["queued", "running", "done", "failed", "skipped"];

interface Props {
  reviews: Review[];
  total: number;
  page: number;
  pageSize: number;
  status: ReviewStatus | "";
  onStatusChange: (status: ReviewStatus | "") => void;
  onPageChange: (page: number) => void;
}

export function ReviewList({ reviews, total, page, pageSize, status, onStatusChange, onPageChange }: Props) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <section>
      <div className="toolbar">
        <h2>Reviews</h2>
        <label>
          Status{" "}
          <select value={status} onChange={(e) => onStatusChange(e.target.value as ReviewStatus | "")}>
            <option value="">all</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>
      {reviews.length === 0 ? (
        <p className="empty">No reviews yet. Open a pull request in a repo where the app is installed.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Repository</th>
              <th>PR</th>
              <th>Status</th>
              <th>Duration</th>
              <th>Comments</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {reviews.map((r) => (
              <tr key={r.id}>
                <td>
                  <a href={`#/reviews/${r.id}`}>{r.repo_full_name}</a>
                </td>
                <td>
                  <a href={r.pr_url} target="_blank" rel="noreferrer">
                    #{r.pr_number}
                  </a>
                </td>
                <td>
                  <StatusBadge status={r.status} />
                </td>
                <td>{formatDuration(r.duration_seconds)}</td>
                <td>{r.comment_count}</td>
                <td>{formatTime(r.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <nav className="pager" aria-label="Pagination">
        <button disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
          Previous
        </button>
        <span>
          Page {page} of {pages}
        </span>
        <button disabled={page >= pages} onClick={() => onPageChange(page + 1)}>
          Next
        </button>
      </nav>
    </section>
  );
}
