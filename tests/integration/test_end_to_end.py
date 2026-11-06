"""Full path over real Kafka and Postgres: webhook -> Kafka -> worker -> review posted.

Only GitHub and the LLM are replaced, by the in-memory doubles in tests/doubles.
"""

import asyncio
import hashlib
import hmac
import json
import uuid

import httpx
import pytest
from aiokafka import AIOKafkaConsumer

from api.main import create_app
from shared.config import Settings
from shared.db import AgentName, Review, ReviewStatus, Severity
from tests.doubles.agents import FakeAgentRunner
from tests.doubles.github import FakeGitHubClient
from worker.findings import Finding
from worker.main import run_worker
from worker.processor import WorkerDeps

pytestmark = pytest.mark.integration
SECRET = "e2e-secret"
PATCH = "@@ -1,1 +1,3 @@\n import os\n+eval(input())\n+print('ok')"
FILES = [{"filename": "app.py", "status": "modified", "patch": PATCH, "additions": 2}]


@pytest.fixture
def settings(database_url, kafka_bootstrap):
    # Fresh topics and group per test so leftover messages cannot leak between tests.
    suffix = uuid.uuid4().hex[:8]
    return Settings(
        database_url=database_url,
        kafka_bootstrap_servers=kafka_bootstrap,
        kafka_topic=f"pr-events-{suffix}",
        kafka_dlq_topic=f"pr-events-dlq-{suffix}",
        kafka_consumer_group=f"pr-workers-{suffix}",
        github_webhook_secret=SECRET,
        worker_max_attempts=2,
        worker_retry_base_seconds=0,
    )


@pytest.fixture
async def api(settings, session_factory):
    app = create_app(settings)
    # Run the real lifespan: topic creation, Kafka producer, DB engine.
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def start_worker(settings, session_factory, github, runner):
    deps = WorkerDeps(settings, session_factory, github, runner)
    stop = asyncio.Event()
    task = asyncio.create_task(run_worker(deps, stop))
    return stop, task


async def send_webhook(api, sha="abc"):
    payload = {
        "action": "opened",
        "pull_request": {"number": 9, "head": {"sha": sha}},
        "repository": {"full_name": "acme/e2e"},
        "installation": {"id": 1},
    }
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    response = await api.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": str(uuid.uuid4()),
            "X-Hub-Signature-256": signature,
        },
    )
    return response.json()


async def wait_for_status(session_factory, review_id, statuses) -> Review:
    async with asyncio.timeout(45):
        while True:
            async with session_factory() as session:
                review = await session.get(Review, review_id)
                if review.status in statuses:
                    return review
            await asyncio.sleep(0.5)


async def test_webhook_to_posted_review_and_duplicate_ignored(api, settings, session_factory):
    github = FakeGitHubClient(files=FILES)
    finding = Finding(
        file_path="app.py", line=2, severity=Severity.error, category="security", message="eval"
    )
    runner = FakeAgentRunner(findings={AgentName.review: [finding]})
    stop, task = await start_worker(settings, session_factory, github, runner)
    try:
        queued = await send_webhook(api)
        assert queued["status"] == "queued"

        review = await wait_for_status(session_factory, queued["review_id"], {ReviewStatus.done})
        assert review.input_tokens > 0
        assert len(github.posted) == 1
        assert [(c.path, c.line) for c in github.posted[0].comments] == [("app.py", 2)]

        detail = (await api.get(f"/api/reviews/{review.id}")).json()
        assert [c["line"] for c in detail["comments"]] == [2]

        # GitHub redelivers the same webhook: no new review, nothing posted again.
        assert (await send_webhook(api))["status"] == "duplicate"
        await asyncio.sleep(2)
        assert len(github.posted) == 1
    finally:
        stop.set()
        await task


async def test_failing_review_is_marked_failed_and_dead_lettered(api, settings, session_factory):
    runner = FakeAgentRunner(fail={AgentName.review, AgentName.test})
    stop, task = await start_worker(
        settings, session_factory, FakeGitHubClient(files=FILES), runner
    )
    try:
        queued = await send_webhook(api, sha="bad")
        review = await wait_for_status(session_factory, queued["review_id"], {ReviewStatus.failed})
        assert "AgentsFailedError" in review.error_message
        # One call per agent per attempt.
        assert len(runner.calls) == 2 * settings.worker_max_attempts
    finally:
        stop.set()
        await task

    dlq = AIOKafkaConsumer(
        settings.kafka_dlq_topic,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        auto_offset_reset="earliest",
        group_id=f"dlq-reader-{uuid.uuid4().hex[:6]}",
    )
    await dlq.start()
    try:
        message = await asyncio.wait_for(dlq.getone(), timeout=20)
    finally:
        await dlq.stop()
    assert message.key == b"acme/e2e#9"
    assert json.loads(message.value)["review_id"] == queued["review_id"]
    headers = dict(message.headers)
    assert headers["attempts"] == b"2"
    assert b"AgentsFailedError" in headers["error"]
