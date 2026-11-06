import pytest

from shared.config import Settings
from shared.db import ReviewStatus
from shared.events import PullRequestEventV1
from worker import consumer
from worker.processor import WorkerDeps

EVENT = (
    PullRequestEventV1(
        review_id=5,
        delivery_id="d",
        repo_full_name="o/r",
        pr_number=1,
        head_sha="s",
        installation_id=1,
    )
    .model_dump_json()
    .encode()
)


@pytest.fixture
def deps():
    settings = Settings(worker_max_attempts=3, worker_retry_base_seconds=0)
    return WorkerDeps(settings=settings, session_factory=None, github=None, runner=None)


@pytest.fixture
def statuses(monkeypatch):
    recorded = []

    async def fake_set_status(deps, review_id, status, error=None):
        recorded.append(status)

    monkeypatch.setattr(consumer, "set_status", fake_set_status)
    return recorded


class DLQ:
    def __init__(self):
        self.messages = []

    async def __call__(self, value, error, attempts):
        self.messages.append((value, error, attempts))


async def test_success_on_retry_does_not_dead_letter(monkeypatch, deps, statuses):
    calls = []

    async def flaky(event, deps):
        calls.append(event)
        if len(calls) < 2:
            raise RuntimeError("boom")

    monkeypatch.setattr(consumer, "process_event", flaky)
    dlq = DLQ()
    await consumer.handle_message(EVENT, deps, dlq)
    assert len(calls) == 2
    assert dlq.messages == []
    # Released back to queued between attempts so the retry can claim it.
    assert statuses == [ReviewStatus.queued]


async def test_persistent_failure_marks_failed_and_dead_letters(monkeypatch, deps, statuses):
    async def broken(event, deps):
        raise RuntimeError("boom")

    monkeypatch.setattr(consumer, "process_event", broken)
    dlq = DLQ()
    await consumer.handle_message(EVENT, deps, dlq)
    assert statuses == [ReviewStatus.queued, ReviewStatus.queued, ReviewStatus.failed]
    assert len(dlq.messages) == 1
    value, error, attempts = dlq.messages[0]
    assert value == EVENT and "boom" in error and attempts == 3


async def test_malformed_message_goes_straight_to_dlq(deps, statuses):
    dlq = DLQ()
    await consumer.handle_message(b'{"not": "an event"}', deps, dlq)
    assert len(dlq.messages) == 1 and dlq.messages[0][2] == 0
    assert statuses == []
