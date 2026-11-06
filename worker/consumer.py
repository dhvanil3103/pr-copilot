import asyncio
import logging
from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from shared.db import ReviewStatus
from shared.events import PullRequestEventV1
from shared.logging import review_id as review_id_ctx
from worker.processor import WorkerDeps, process_event, set_status

log = logging.getLogger(__name__)

# (original message value, error description, attempts made) -> publish to DLQ
DeadLetter = Callable[[bytes, str, int], Awaitable[None]]


async def handle_message(value: bytes, deps: WorkerDeps, dead_letter: DeadLetter) -> None:
    """Process one Kafka message with retries. Returns once the message is done or dead-lettered.

    The caller commits the offset after this returns, so a crash before then
    replays the message, and process_event's claim step makes the replay safe.
    """
    try:
        event = PullRequestEventV1.model_validate_json(value)
    except ValidationError as exc:
        # Retrying cannot fix a malformed message.
        log.error("invalid event, sending to DLQ: %s", exc)
        await dead_letter(value, f"invalid event: {exc}", 0)
        return

    token = review_id_ctx.set(event.review_id)
    try:
        max_attempts = deps.settings.worker_max_attempts
        for attempt in range(1, max_attempts + 1):
            try:
                await process_event(event, deps)
                return
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"[:2000]
                if attempt == max_attempts:
                    log.exception("review failed after %s attempts, sending to DLQ", attempt)
                    await set_status(deps, event.review_id, ReviewStatus.failed, error)
                    await dead_letter(value, error, attempt)
                    return
                delay = deps.settings.worker_retry_base_seconds * 2 ** (attempt - 1)
                log.warning("attempt %s failed (%s), retrying in %.0fs", attempt, error, delay)
                # Back to queued so the next attempt's claim succeeds.
                await set_status(deps, event.review_id, ReviewStatus.queued, error)
                await asyncio.sleep(delay)
    finally:
        review_id_ctx.reset(token)
