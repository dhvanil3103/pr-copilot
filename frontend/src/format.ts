export function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

export const formatCost = (usd: number) => `$${usd.toFixed(usd < 1 ? 4 : 2)}`;

export const formatTokens = (n: number) => n.toLocaleString("en-US");

export const formatTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
