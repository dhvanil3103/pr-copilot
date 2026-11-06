import { formatCost, formatDuration, formatTokens } from "../format";
import type { Stats } from "../types";

export function StatsHeader({ stats }: { stats: Stats | null }) {
  if (!stats) return <section className="stats" aria-busy="true" />;
  const { counts_by_status: counts } = stats;
  const tiles = [
    ["Reviews", String(stats.total_reviews)],
    ["Done", String(counts.done)],
    ["In progress", String(counts.queued + counts.running)],
    ["Failed", String(counts.failed)],
    ["Avg duration", formatDuration(stats.avg_duration_seconds)],
    ["Tokens", formatTokens(stats.total_input_tokens + stats.total_output_tokens)],
    ["Est. cost", formatCost(stats.total_estimated_cost_usd)],
  ];
  return (
    <section className="stats" aria-label="Stats">
      {tiles.map(([label, value]) => (
        <div className="tile" key={label}>
          <div className="tile-value">{value}</div>
          <div className="tile-label">{label}</div>
        </div>
      ))}
    </section>
  );
}
