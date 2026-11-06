"""REST and webhook endpoints against real Postgres, with Kafka replaced by a recorder."""

import hashlib
import hmac
import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from api.main import create_app
from shared.config import Settings
from shared.db import AgentName, Comment, Review, ReviewStatus, Severity, utcnow
from tests.doubles.kafka import FakeProducer

pytestmark = pytest.mark.integration
SECRET = "test-secret"


@pytest.fixture
def producer():
    return FakeProducer()


@pytest.fixture
async def client(session_factory, producer):
    app = create_app(Settings(github_webhook_secret=SECRET))
    # httpx's ASGI transport does not run the lifespan, so wire state directly.
    app.state.session_factory = session_factory
    app.state.producer = producer
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def seed(session_factory):
    now = utcnow()
    async with session_factory() as session:
        done = Review(
            repo_full_name="acme/api", pr_number=1, head_sha="a", installation_id=1,
            status=ReviewStatus.done, started_at=now - timedelta(seconds=30), finished_at=now,
            input_tokens=1000, output_tokens=100, estimated_cost_usd=0.0015, summary="ok",
        )  # fmt: skip
        failed = Review(
            repo_full_name="acme/web", pr_number=2, head_sha="b", installation_id=1,
            status=ReviewStatus.failed, error_message="boom",
        )  # fmt: skip
        queued = Review(repo_full_name="acme/api", pr_number=3, head_sha="c", installation_id=1)
        session.add_all([done, failed, queued])
        await session.flush()
        session.add_all(
            Comment(
                review_id=done.id,
                agent=agent,
                file_path=path,
                line=line,
                severity=Severity.warning,
                category="bug",
                body="b",
                posted=True,
            )  # fmt: skip
            for agent, path, line in [
                (AgentName.review, "b.py", 5),
                (AgentName.test, "a.py", 9),
                (AgentName.review, "a.py", 2),
            ]
        )
        await session.commit()
    return done, failed, queued


async def test_list_reviews_with_filters_and_pagination(client, session_factory):
    done, _, queued = await seed(session_factory)

    body = (await client.get("/api/reviews")).json()
    assert body["total"] == 3
    by_id = {r["id"]: r for r in body["items"]}
    assert by_id[done.id]["comment_count"] == 3
    assert by_id[done.id]["duration_seconds"] == pytest.approx(30)
    assert by_id[done.id]["pr_url"] == "https://github.com/acme/api/pull/1"

    body = (await client.get("/api/reviews", params={"repo": "acme/api"})).json()
    assert {r["id"] for r in body["items"]} == {done.id, queued.id}

    body = (await client.get("/api/reviews", params={"status": "failed"})).json()
    assert [r["error_message"] for r in body["items"]] == ["boom"]

    body = (await client.get("/api/reviews", params={"page": 2, "page_size": 2})).json()
    assert len(body["items"]) == 1 and body["total"] == 3

    assert (await client.get("/api/reviews", params={"status": "bogus"})).status_code == 422


async def test_review_detail_sorts_comments_by_file_and_line(client, session_factory):
    done, *_ = await seed(session_factory)
    body = (await client.get(f"/api/reviews/{done.id}")).json()
    assert body["summary"] == "ok"
    assert [(c["file_path"], c["line"]) for c in body["comments"]] == [
        ("a.py", 2),
        ("a.py", 9),
        ("b.py", 5),
    ]
    assert (await client.get("/api/reviews/9999")).status_code == 404


async def test_stats(client, session_factory):
    await seed(session_factory)
    body = (await client.get("/api/stats")).json()
    assert body["total_reviews"] == 3
    assert body["counts_by_status"] == {
        "queued": 1, "running": 0, "done": 1, "failed": 1, "skipped": 0,
    }  # fmt: skip
    assert body["avg_duration_seconds"] == pytest.approx(30)
    assert body["total_input_tokens"] == 1000
    assert body["total_estimated_cost_usd"] == pytest.approx(0.0015)


async def test_stats_on_empty_database(client):
    body = (await client.get("/api/stats")).json()
    assert body["total_reviews"] == 0 and body["avg_duration_seconds"] is None


def signed(payload: dict, event="pull_request") -> dict:
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    headers = {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": "delivery-1",
        "X-Hub-Signature-256": sig,
        "Content-Type": "application/json",
    }
    return {"content": body, "headers": headers}


def pr_payload(action="opened", sha="abc"):
    return {
        "action": action,
        "pull_request": {"number": 4, "head": {"sha": sha}},
        "repository": {"full_name": "acme/api"},
        "installation": {"id": 77},
    }


async def count_reviews(session_factory) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count(Review.id)))


async def test_webhook_queues_review_and_publishes_keyed_event(client, producer, session_factory):
    response = await client.post("/webhooks/github", **signed(pr_payload()))
    assert response.json()["status"] == "queued"

    topic, key, value = producer.sent[0]
    assert topic == "pr-events" and key == b"acme/api#4"
    event = json.loads(value)
    assert event["installation_id"] == 77 and event["delivery_id"] == "delivery-1"
    assert await count_reviews(session_factory) == 1


async def test_duplicate_webhook_is_ignored(client, producer, session_factory):
    await client.post("/webhooks/github", **signed(pr_payload()))
    response = await client.post("/webhooks/github", **signed(pr_payload()))
    assert response.json()["status"] == "duplicate"
    assert len(producer.sent) == 1
    assert await count_reviews(session_factory) == 1


async def test_new_push_to_same_pr_is_a_new_review(client, producer):
    await client.post("/webhooks/github", **signed(pr_payload(sha="one")))
    await client.post("/webhooks/github", **signed(pr_payload(action="synchronize", sha="two")))
    assert len(producer.sent) == 2


async def test_bad_signature_is_rejected(client, producer):
    request = signed(pr_payload())
    request["headers"]["X-Hub-Signature-256"] = "sha256=" + "0" * 64
    assert (await client.post("/webhooks/github", **request)).status_code == 401
    assert producer.sent == []


async def test_unsupported_events_and_actions_return_200(client, producer):
    r1 = await client.post("/webhooks/github", **signed({"zen": "hi"}, event="ping"))
    r2 = await client.post("/webhooks/github", **signed(pr_payload(action="closed")))
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["status"] == r2.json()["status"] == "ignored"
    assert producer.sent == []


async def test_publish_failure_returns_503_and_allows_redelivery(client, producer, session_factory):
    producer.fail = True
    response = await client.post("/webhooks/github", **signed(pr_payload()))
    assert response.status_code == 503
    assert await count_reviews(session_factory) == 0

    producer.fail = False
    response = await client.post("/webhooks/github", **signed(pr_payload()))
    assert response.json()["status"] == "queued"
