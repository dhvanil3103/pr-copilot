import asyncio
import logging
import signal

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


def dead_letter_publisher(producer: AIOKafkaProducer, topic: str, key: bytes | None):
    async def publish(value: bytes, error: str, attempts: int) -> None:
        await producer.send_and_wait(
            topic,
            key=key,
            value=value,
            headers=[("error", error.encode()), ("attempts", str(attempts).encode())],
        )

    return publish


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    await ensure_topics(settings)

    engine = make_engine(settings.database_url)
    github = GitHubAppClient(
        settings.github_app_id, settings.github_private_key, settings.github_api_url
    )
    # The only place real implementations are chosen; everything below takes interfaces.
    deps = WorkerDeps(
        settings=settings,
        session_factory=make_session_factory(engine),
        github=github,
        runner=LangChainAgentRunner(settings),
    )
    producer = make_producer(settings)
    consumer = make_consumer(settings)
    await producer.start()
    await consumer.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

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
        await consumer.stop()
        await producer.stop()
        await github.aclose()
        await engine.dispose()
        log.info("worker stopped")


if __name__ == "__main__":
    asyncio.run(run())
