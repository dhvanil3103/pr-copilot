import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { review } from "../test/fixtures";
import { ReviewList } from "./ReviewList";

function renderList(props: Partial<Parameters<typeof ReviewList>[0]> = {}) {
  const handlers = { onStatusChange: vi.fn(), onPageChange: vi.fn() };
  render(
    <ReviewList
      reviews={[review(), review({ id: 2, status: "failed", pr_number: 7, duration_seconds: null, comment_count: 0 })]}
      total={2}
      page={1}
      pageSize={20}
      status=""
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

test("shows a row per review with PR link, status, duration and comment count", () => {
  renderList();
  const rows = screen.getAllByRole("row").slice(1);
  expect(rows).toHaveLength(2);

  const first = within(rows[0]);
  expect(first.getByRole("link", { name: "#42" })).toHaveAttribute("href", "https://github.com/acme/api/pull/42");
  expect(first.getByRole("link", { name: "acme/api" })).toHaveAttribute("href", "#/reviews/1");
  expect(first.getByText("done")).toHaveClass("badge-done");
  expect(first.getByText("30.0s")).toBeInTheDocument();

  const second = within(rows[1]);
  expect(second.getByText("failed")).toHaveClass("badge-failed");
  expect(second.getByText("—")).toBeInTheDocument();
});

test("filters by status and pages", async () => {
  const { onStatusChange, onPageChange } = renderList({ total: 45 });
  await userEvent.selectOptions(screen.getByLabelText(/status/i), "failed");
  expect(onStatusChange).toHaveBeenCalledWith("failed");

  expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(onPageChange).toHaveBeenCalledWith(2);
});

test("shows an empty state", () => {
  renderList({ reviews: [], total: 0 });
  expect(screen.getByText(/no reviews yet/i)).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});
