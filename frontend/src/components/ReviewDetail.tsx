import { formatCost, formatDuration, formatTokens } from "../format";
import type { ReviewComment, ReviewDetail as Detail } from "../types";
import { StatusBadge } from "./StatusBadge";

const AGENT_LABEL = { review: "Code review", test: "Test suggestion" } as const;

function groupByFile(comments: ReviewComment[]): [string, ReviewComment[]][] {
  const groups = new Map<string, ReviewComment[]>();
  for (const c of comments) groups.set(c.file_path, [...(groups.get(c.file_path) ?? []), c]);
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([file, items]) => [file, items.sort((a, b) => a.line - b.line)]);
}

export function ReviewDetail({ review }: { review: Detail }) {
  return (
    <article>
      <a href="#/">← All reviews</a>
      <h2>
        {review.repo_full_name}{" "}
        <a href={review.pr_url} target="_blank" rel="noreferrer">
          #{review.pr_number}
        </a>{" "}
        <StatusBadge status={review.status} />
      </h2>
      <p className="meta">
        Commit <code>{review.head_sha.slice(0, 7)}</code> · {formatDuration(review.duration_seconds)} ·{" "}
        {formatTokens(review.input_tokens + review.output_tokens)} tokens · {formatCost(review.estimated_cost_usd)}
      </p>
      {review.error_message && <p className="error">{review.error_message}</p>}
      {review.summary && <pre className="summary">{review.summary}</pre>}

      <h3>Comments ({review.comments.length})</h3>
      {review.comments.length === 0 && <p className="empty">No inline comments.</p>}
      {groupByFile(review.comments).map(([file, comments]) => (
        <section key={file} className="file">
          <h4>
            <code>{file}</code>
          </h4>
          {comments.map((c) => (
            <div key={c.id} className={`comment severity-${c.severity}`} data-testid="comment">
              <div className="comment-head">
                <span>Line {c.line}</span>
                <span className={`severity severity-${c.severity}`}>{c.severity}</span>
                <span className="category">{c.category}</span>
                <span className="agent">{AGENT_LABEL[c.agent]}</span>
              </div>
              <pre className="comment-body">{c.body}</pre>
            </div>
          ))}
        </section>
      ))}
    </article>
  );
}
