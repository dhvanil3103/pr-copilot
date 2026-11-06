import asyncio
import logging

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import KafkaError, TopicAlreadyExistsError

from shared.config import Settings

log = logging.getLogger(__name__)


async def ensure_topics(settings: Settings) -> None:
    """Create the main and dead letter topics if missing. Safe to call repeatedly.

    Retries while the broker is unreachable, because in Kubernetes the API and
    worker usually start before Kafka is ready; crash-looping would also work
    but makes real failures harder to spot.
    """
    for attempt in range(1, settings.kafka_startup_attempts + 1):
        try:
            await _create_topics(settings)
            return
        except KafkaError as exc:
            if attempt == settings.kafka_startup_attempts:
                raise
            delay = min(2 * attempt, 10)
            log.warning("Kafka not ready (%s), retrying in %ss", exc, delay)
            await asyncio.sleep(delay)


async def _create_topics(settings: Settings) -> None:
    admin = AIOKafkaAdminClient(bootstrap_servers=settings.kafka_bootstrap_servers)
    await admin.start()
    try:
        for name in (settings.kafka_topic, settings.kafka_dlq_topic):
            topic = NewTopic(
                name=name,
                num_partitions=settings.kafka_partitions,
                replication_factor=settings.kafka_replication_factor,
            )
            try:
                await admin.create_topics([topic])
                log.info("created topic %s", name)
            except TopicAlreadyExistsError:
                # Several replicas can start at once; losing the race is fine.
                pass
    finally:
        await admin.close()


def make_producer(settings: Settings) -> AIOKafkaProducer:
    # acks="all" so a webhook is only acknowledged once the broker has the event.
    return AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers, acks="all")


def make_consumer(settings: Settings) -> AIOKafkaConsumer:
    return AIOKafkaConsumer(
        settings.kafka_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        # Offsets are committed manually, only after processing finishes.
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        # One review (two agents plus retries) can take minutes; without this the
        # broker would assume the worker died and rebalance mid-review.
        max_poll_interval_ms=settings.kafka_max_poll_interval_ms,
        max_poll_records=1,
    )


async def kafka_reachable(settings: Settings) -> bool:
    admin = AIOKafkaAdminClient(bootstrap_servers=settings.kafka_bootstrap_servers)
    try:
        await admin.start()
        await admin.list_topics()
        return True
    except Exception:
        return False
    finally:
        await admin.close()
