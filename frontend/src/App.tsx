import { useEffect, useState } from "react";
import { fetchReview, fetchReviews, fetchStats } from "./api";
import { ReviewDetail } from "./components/ReviewDetail";
import { ReviewList } from "./components/ReviewList";
import { StatsHeader } from "./components/StatsHeader";
import type { ReviewStatus } from "./types";
import { usePolling } from "./usePolling";

function useHashRoute(): number | null {
  const parse = () => {
    const match = window.location.hash.match(/^#\/reviews\/(\d+)/);
    return match ? Number(match[1]) : null;
  };
  const [reviewId, setReviewId] = useState(parse);
  useEffect(() => {
    const onChange = () => setReviewId(parse());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return reviewId;
}

function ListPage() {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<ReviewStatus | "">("");
  const { data, error } = usePolling(() => fetchReviews({ page, status }), `${page}:${status}`);
  if (error) return <p className="error">Could not load reviews: {error}</p>;
  if (!data) return <p>Loading…</p>;
  return (
    <ReviewList
      reviews={data.items}
      total={data.total}
      page={data.page}
      pageSize={data.page_size}
      status={status}
      onStatusChange={(s) => {
        setStatus(s);
        setPage(1);
      }}
      onPageChange={setPage}
    />
  );
}

function DetailPage({ id }: { id: number }) {
  const { data, error } = usePolling(() => fetchReview(id), String(id));
  if (error) return <p className="error">Could not load review {id}: {error}</p>;
  if (!data) return <p>Loading…</p>;
  return <ReviewDetail review={data} />;
}

export default function App() {
  const reviewId = useHashRoute();
  const { data: stats } = usePolling(fetchStats, "stats");
  return (
    <>
      <header>
        <h1>PR Copilot</h1>
      </header>
      <main>
        <StatsHeader stats={stats} />
        {reviewId === null ? <ListPage /> : <DetailPage id={reviewId} />}
      </main>
    </>
  );
}
