import { render, screen } from "@testing-library/react";
import { StatsHeader } from "./StatsHeader";

test("renders totals from the stats endpoint", () => {
  render(
    <StatsHeader
      stats={{
        total_reviews: 12,
        counts_by_status: { queued: 1, running: 2, done: 8, failed: 1, skipped: 0 },
        avg_duration_seconds: 95,
        total_input_tokens: 10000,
        total_output_tokens: 2345,
        total_estimated_cost_usd: 0.123,
      }}
    />,
  );
  const tile = (label: string) => screen.getByText(label).previousSibling?.textContent;
  expect(tile("Reviews")).toBe("12");
  expect(tile("In progress")).toBe("3");
  expect(tile("Avg duration")).toBe("1m 35s");
  expect(tile("Tokens")).toBe("12,345");
  expect(tile("Est. cost")).toBe("$0.1230");
});
