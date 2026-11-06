import { render, screen, within } from "@testing-library/react";
import { detail } from "../test/fixtures";
import { ReviewDetail } from "./ReviewDetail";

test("groups comments by file, sorted by line, with severity and agent", () => {
  render(<ReviewDetail review={detail()} />);

  const files = screen.getAllByRole("heading", { level: 4 }).map((h) => h.textContent);
  expect(files).toEqual(["src/a.py", "src/b.py"]);

  const comments = screen.getAllByTestId("comment");
  expect(comments.map((c) => within(c).getByText(/^Line/).textContent)).toEqual(["Line 7", "Line 20", "Line 4"]);

  const first = within(comments[0]);
  expect(comments[0]).toHaveClass("severity-error");
  expect(first.getByText("security")).toBeInTheDocument();
  expect(first.getByText("Code review")).toBeInTheDocument();
  expect(within(comments[2]).getByText("Test suggestion")).toBeInTheDocument();
});

test("shows summary, usage and short sha", () => {
  render(<ReviewDetail review={detail()} />);
  expect(screen.getByText(/Looks mostly fine/)).toBeInTheDocument();
  expect(screen.getByText("abcdef1")).toBeInTheDocument();
  expect(screen.getByText(/1,500 tokens/)).toBeInTheDocument();
  expect(screen.getByText(/\$0\.0027/)).toBeInTheDocument();
});

test("shows the error for a failed review", () => {
  render(<ReviewDetail review={detail({ status: "failed", error_message: "GitHub returned 502", comments: [], summary: null })} />);
  expect(screen.getByText("GitHub returned 502")).toBeInTheDocument();
  expect(screen.getByText("No inline comments.")).toBeInTheDocument();
});
