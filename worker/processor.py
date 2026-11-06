import logging

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.db import Review, ReviewStatus, utcnow
from shared.events import PullRequestEventV1

log = logging.getLogger(__name__)


async def process_event(
    event: PullRequestEventV1, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Process one event. Safe to run twice for the same review (at-least-once delivery)."""
    async with session_factory() as session:
        # Atomic queued -> running claim: if Kafka redelivers a message that was
        # already processed, no row matches and the duplicate is dropped.
        claimed = await session.execute(
            update(Review)
            .where(Review.id == event.review_id, Review.status == ReviewStatus.queued)
            .values(status=ReviewStatus.running, started_at=utcnow())
        )
        await session.commit()
        if claimed.rowcount == 0:
            log.info("review %s already claimed, skipping", event.review_id)
            return

        # Agents are added in the next branch; for now a review completes immediately.
        await session.execute(
            update(Review)
            .where(Review.id == event.review_id)
            .values(status=ReviewStatus.done, finished_at=utcnow())
        )
        await session.commit()
