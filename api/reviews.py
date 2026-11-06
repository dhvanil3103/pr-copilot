from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import extract, func, select
from sqlalchemy.orm import selectinload

from api.schemas import CommentOut, ReviewDetail, ReviewOut, ReviewPage, Stats
from shared.db import Comment, Review, ReviewStatus

router = APIRouter(prefix="/api")


@router.get("/reviews", response_model=ReviewPage)
async def list_reviews(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    repo: str | None = None,
    status: ReviewStatus | None = None,
) -> ReviewPage:
    filters = []
    if repo:
        filters.append(Review.repo_full_name == repo)
    if status:
        filters.append(Review.status == status)

    comment_count = (
        select(func.count(Comment.id)).where(Comment.review_id == Review.id).scalar_subquery()
    )
    query = (
        select(Review, comment_count.label("comment_count"))
        .where(*filters)
        .order_by(Review.created_at.desc(), Review.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    async with request.app.state.session_factory() as session:
        total = await session.scalar(select(func.count(Review.id)).where(*filters))
        rows = (await session.execute(query)).all()

    items = [
        ReviewOut.model_validate(review).model_copy(update={"comment_count": count})
        for review, count in rows
    ]
    return ReviewPage(items=items, total=total or 0, page=page, page_size=page_size)


@router.get("/reviews/{review_id}", response_model=ReviewDetail)
async def get_review(request: Request, review_id: int) -> ReviewDetail:
    async with request.app.state.session_factory() as session:
        review = await session.scalar(
            select(Review).where(Review.id == review_id).options(selectinload(Review.comments))
        )
    if review is None:
        raise HTTPException(status_code=404, detail="review not found")

    comments = sorted(review.comments, key=lambda c: (c.file_path, c.line))
    base = ReviewOut.model_validate(review).model_dump(exclude={"duration_seconds", "pr_url"})
    base["comment_count"] = len(comments)
    return ReviewDetail(
        **base,
        summary=review.summary,
        comments=[CommentOut.model_validate(c) for c in comments],
    )


@router.get("/stats", response_model=Stats)
async def stats(request: Request) -> Stats:
    duration = extract("epoch", Review.finished_at - Review.started_at)
    async with request.app.state.session_factory() as session:
        counts = dict(
            (
                await session.execute(select(Review.status, func.count()).group_by(Review.status))
            ).all()
        )
        totals = (
            await session.execute(
                select(
                    func.avg(duration).filter(Review.status == ReviewStatus.done),
                    func.coalesce(func.sum(Review.input_tokens), 0),
                    func.coalesce(func.sum(Review.output_tokens), 0),
                    func.coalesce(func.sum(Review.estimated_cost_usd), 0),
                )
            )
        ).one()

    avg_duration, input_tokens, output_tokens, cost = totals
    return Stats(
        total_reviews=sum(counts.values()),
        counts_by_status={s: counts.get(s, 0) for s in ReviewStatus},
        avg_duration_seconds=float(avg_duration) if avg_duration is not None else None,
        total_input_tokens=input_tokens,
        total_output_tokens=output_tokens,
        total_estimated_cost_usd=float(cost),
    )
