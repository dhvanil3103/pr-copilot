import asyncio
import logging
import signal
from pathlib import Path

from aiokafka import AIOKafkaProducer, TopicPartition

from shared.config import get_settings
from shared.db import make_engine, make_session_factory
from shared.kafka import ensure_topics, make_consumer, make_producer
from shared.logging import configure_logging
from worker.agents.langchain_runner import LangChainAgentRunner
from worker.consumer import handle_message
from worker.github import GitHubAppClient
from worker.processor import WorkerDeps

log = logging.getLogger(__name__)

# The worker has no HTTP server; Docker and Kubernetes probes check this file's age.
HEARTBEAT_FILE = Path("/tmp/worker-heartbeat")
HEARTBEAT_INTERVAL_SECONDS = 10


def dead_letter_publisher(producer: AIOKafkaProducer, topic: str, key: bytes | None):
    async def publish(value: bytes, error: str, attempts: int) -> None:
        await producer.send_and_wait(
            topic,
            key=key,
            value=value,
            headers=[("error", error.encode()), ("attempts", str(attempts).encode())],
        )

    return publish


async def _heartbeat(stop: asyncio.Event) -> None:
    # Runs beside the consume loop, so it keeps beating during a long review
    # but stops if the event loop itself hangs.
    while not stop.is_set():
        await asyncio.to_thread(HEARTBEAT_FILE.touch)
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


async def run_worker(deps: WorkerDeps, stop: asyncio.Event) -> None:
    """Consume pr-events until `stop` is set. Integration tests call this with fakes."""
    settings = deps.settings
    await ensure_topics(settings)
    producer = make_producer(settings)
    consumer = make_consumer(settings)
    await producer.start()
    await consumer.start()
    heartbeat = asyncio.create_task(_heartbeat(stop))
    log.info("worker started")
    try:
        while not stop.is_set():
            batch = await consumer.getmany(timeout_ms=1000)
            for tp, messages in batch.items():
                for message in messages:
                    dlq = dead_letter_publisher(producer, settings.kafka_dlq_topic, message.key)
                    await handle_message(message.value, deps, dlq)
                    # Commit only after the message is fully handled (done or dead-lettered).
                    await consumer.commit(
                        {TopicPartition(tp.topic, tp.partition): message.offset + 1}
                    )
    finally:
        heartbeat.cancel()
        await consumer.stop()
        await producer.stop()
        log.info("worker stopped")


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = make_engine(settings.database_url)
    github = GitHubAppClient(
        settings.github_app_id, settings.github_private_key, settings.github_api_url
    )
    # The only place real implementations are chosen; everything else takes interfaces.
    deps = WorkerDeps(
        settings=settings,
        session_factory=make_session_factory(engine),
        github=github,
        runner=LangChainAgentRunner(settings),
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await run_worker(deps, stop)
    finally:
        await github.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
