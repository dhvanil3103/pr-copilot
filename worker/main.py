import asyncio
import logging
import signal

from pydantic import ValidationError

from shared.config import get_settings
from shared.db import make_engine, make_session_factory
from shared.events import PullRequestEventV1
from shared.kafka import ensure_topics, make_consumer
from shared.logging import configure_logging, review_id
from worker.processor import process_event

log = logging.getLogger(__name__)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    await ensure_topics(settings)

    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    consumer = make_consumer(settings)
    await consumer.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    log.info("worker started")
    try:
        while not stop.is_set():
            batch = await consumer.getmany(timeout_ms=1000)
            for messages in batch.values():
                for message in messages:
                    try:
                        event = PullRequestEventV1.model_validate_json(message.value)
                    except ValidationError:
                        # Retrying cannot fix a malformed message; DLQ handling comes later.
                        log.exception("dropping malformed message at offset %s", message.offset)
                        await consumer.commit()
                        continue
                    review_id.set(event.review_id)
                    await process_event(event, session_factory)
                    # Commit only after processing finished, so a crash replays the message.
                    await consumer.commit()
    finally:
        await consumer.stop()
        await engine.dispose()
        log.info("worker stopped")


if __name__ == "__main__":
    asyncio.run(run())
