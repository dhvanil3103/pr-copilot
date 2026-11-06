"""process_event against real Postgres, with fake GitHub and agent runner."""

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from shared.config import Settings
from shared.db import AgentName, Comment, Review, ReviewStatus, Severity, utcnow
from shared.events import PullRequestEventV1
from tests.doubles.agents import FakeAgentRunner
from tests.doubles.github import FakeGitHubClient
from worker.findings import Finding
from worker.processor import AgentsFailedError, WorkerDeps, process_event

pytestmark = pytest.mark.integration

PATCH = "@@ -1,2 +1,4 @@\n import os\n+password = 'hunter2'\n+query = f'SELECT {x}'\n x = 1"
FILES = [
    {"filename": "app.py", "status": "modified", "patch": PATCH, "additions": 2},
    {"filename": "uv.lock", "status": "modified", "patch": "@@ -1 +1 @@\n+x"},
]


def finding(line, message, severity=Severity.error, category="security"):
    return Finding(
        file_path="app.py", line=line, severity=severity, category=category, message=message
    )


async def make_review(session_factory, status=ReviewStatus.queued) -> PullRequestEventV1:
    async with session_factory() as session:
        review = Review(
            repo_full_name="acme/demo", pr_number=3, head_sha="abc", installation_id=1,
            status=status,
        )  # fmt: skip
        session.add(review)
        await session.commit()
    return PullRequestEventV1(
        review_id=review.id,
        delivery_id="d1",
        repo_full_name="acme/demo",
        pr_number=3,
        head_sha="abc",
        installation_id=1,
    )


def make_deps(session_factory, github, runner, **settings) -> WorkerDeps:
    return WorkerDeps(
        settings=Settings(**settings), session_factory=session_factory, github=github, runner=runner
    )


async def load(session_factory, review_id):
    async with session_factory() as session:
        review = await session.get(Review, review_id)
        comments = (
            (await session.execute(select(Comment).where(Comment.review_id == review_id)))
            .scalars()
            .all()
        )
    return review, comments


async def test_full_review_posts_grounded_comments_and_records_usage(session_factory):
    github = FakeGitHubClient(files=FILES)
    runner = FakeAgentRunner(
        findings={
            AgentName.review: [
                finding(2, "Hardcoded password"),
                finding(4, "Comment on an unchanged line"),  # dropped by grounding
                finding(99, "Hallucinated line"),  # dropped by grounding
            ],
            AgentName.test: [finding(3, "Test that x is escaped", Severity.info, "test")],
        }
    )
    event = await make_review(session_factory)

    await process_event(event, make_deps(session_factory, github, runner))

    assert len(github.posted) == 1
    posted = github.posted[0]
    assert posted.commit_sha == "abc"
    assert [(c.path, c.line) for c in posted.comments] == [("app.py", 2), ("app.py", 3)]
    # Lockfile never reaches the agents.
    assert [f.path for f in runner.calls[0][1].files] == ["app.py"]

    review, comments = await load(session_factory, event.review_id)
    assert review.status == ReviewStatus.done
    assert review.finished_at and review.started_at
    assert review.input_tokens == 2000 and review.output_tokens == 400
    # Two agents x (1000 in at $1/M + 200 out at $5/M) on the default Haiku model.
    assert float(review.estimated_cost_usd) == pytest.approx(0.004)
    assert "review summary" in review.summary
    assert {(c.agent, c.line, c.posted) for c in comments} == {
        (AgentName.review, 2, True),
        (AgentName.test, 3, True),
    }


async def test_redelivered_event_is_not_processed_twice(session_factory):
    github = FakeGitHubClient(files=FILES)
    deps = make_deps(session_factory, github, FakeAgentRunner())
    event = await make_review(session_factory)

    await process_event(event, deps)
    await process_event(event, deps)

    assert len(github.posted) == 1


async def test_fresh_running_review_is_not_stolen_but_stale_one_is(session_factory):
    github = FakeGitHubClient(files=FILES)
    deps = make_deps(session_factory, github, FakeAgentRunner(), review_stale_after_seconds=60)
    event = await make_review(session_factory, status=ReviewStatus.running)
    async with session_factory() as session:
        await session.execute(
            update(Review).where(Review.id == event.review_id).values(started_at=utcnow())
        )
        await session.commit()

    await process_event(event, deps)
    assert github.posted == []

    async with session_factory() as session:
        stale = utcnow() - timedelta(minutes=5)
        await session.execute(
            update(Review).where(Review.id == event.review_id).values(started_at=stale)
        )
        await session.commit()
    await process_event(event, deps)
    assert len(github.posted) == 1


async def test_one_agent_failing_still_posts_the_other(session_factory):
    github = FakeGitHubClient(files=FILES)
    runner = FakeAgentRunner(
        findings={AgentName.review: [finding(2, "Hardcoded password")]}, fail={AgentName.test}
    )
    event = await make_review(session_factory)
    await process_event(event, make_deps(session_factory, github, runner))

    assert "test suggestion agent failed" in github.posted[0].body
    review, _ = await load(session_factory, event.review_id)
    assert review.status == ReviewStatus.done


async def test_both_agents_failing_raises_for_retry(session_factory):
    runner = FakeAgentRunner(fail={AgentName.review, AgentName.test})
    event = await make_review(session_factory)
    with pytest.raises(AgentsFailedError):
        await process_event(
            event, make_deps(session_factory, FakeGitHubClient(files=FILES), runner)
        )


async def test_pr_with_only_noise_files_is_skipped(session_factory):
    github = FakeGitHubClient(files=[FILES[1]])
    runner = FakeAgentRunner()
    event = await make_review(session_factory)
    await process_event(event, make_deps(session_factory, github, runner))

    review, _ = await load(session_factory, event.review_id)
    assert review.status == ReviewStatus.skipped
    assert runner.calls == [] and github.posted == []
