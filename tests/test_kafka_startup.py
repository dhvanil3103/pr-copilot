import pytest
from aiokafka.errors import KafkaConnectionError

from shared import kafka
from shared.config import Settings


async def test_ensure_topics_waits_for_broker(monkeypatch):
    calls = []

    async def flaky(settings):
        calls.append(1)
        if len(calls) < 3:
            raise KafkaConnectionError("broker not up")

    async def no_sleep(_):
        pass

    monkeypatch.setattr(kafka, "_create_topics", flaky)
    monkeypatch.setattr(kafka.asyncio, "sleep", no_sleep)
    await kafka.ensure_topics(Settings())
    assert len(calls) == 3


async def test_ensure_topics_gives_up(monkeypatch):
    async def down(settings):
        raise KafkaConnectionError("broker not up")

    async def no_sleep(_):
        pass

    monkeypatch.setattr(kafka, "_create_topics", down)
    monkeypatch.setattr(kafka.asyncio, "sleep", no_sleep)
    with pytest.raises(KafkaConnectionError):
        await kafka.ensure_topics(Settings(kafka_startup_attempts=2))
