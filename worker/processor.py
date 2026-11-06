import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.config import Settings
from shared.cost import estimate_cost_usd
from shared.db import AgentName, Comment, Review, ReviewStatus, utcnow
from shared.events import PullRequestEventV1
from worker.agents.base import AgentResult, AgentRunner, PRContext
from worker.diff import select_files
from worker.github import GitHubClient, ReviewComment
from worker.grounding import AttributedFinding, ground_findings
from worker.summary import comment_body, review_body

log = logging.getLogger(__name__)


class AgentsFailedError(Exception):
    pass


@dataclass
class WorkerDeps:
    """Everything the pipeline talks to, injected so tests can substitute doubles."""

    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    github: GitHubClient
    runner: AgentRunner


async def claim_review(deps: WorkerDeps, review_id: int) -> bool:
    """Atomically move a review to running. False means another delivery already owns it."""
    stale_before = utcnow() - timedelta(seconds=deps.settings.review_stale_after_seconds)
    async with deps.session_factory() as session:
        result = await session.execute(
            update(Review)
            .where(
                Review.id == review_id,
                or_(
                    Review.status == ReviewStatus.queued,
                    # A worker that crashed mid-review leaves "running" behind;
                    # after the stale window a redelivery may take it over.
                    (Review.status == ReviewStatus.running) & (Review.started_at < stale_before),
                ),
            )
            .values(status=ReviewStatus.running, started_at=utcnow(), error_message=None)
        )
        await session.commit()
        return result.rowcount == 1


async def set_status(
    deps: WorkerDeps, review_id: int, status: ReviewStatus, error: str | None = None
) -> None:
    values: dict = {"status": status, "error_message": error}
    if status in (ReviewStatus.failed, ReviewStatus.skipped, ReviewStatus.done):
        values["finished_at"] = utcnow()
    async with deps.session_factory() as session:
        await session.execute(update(Review).where(Review.id == review_id).values(**values))
        await session.commit()


async def _run_agent(
    settings: Settings, runner: AgentRunner, agent: AgentName, pr: PRContext
) -> AgentResult:
    model = settings.model_for(agent)
    try:
        return await asyncio.wait_for(runner.run(agent, pr), timeout=settings.agent_timeout_seconds)
    except TimeoutError:
        return AgentResult(agent=agent, model=model, output=None, error="timed out")
    except Exception as exc:
        log.exception("%s agent failed", agent)
        return AgentResult(agent=agent, model=model, output=None, error=type(exc).__name__)


async def run_agents(settings: Settings, runner: AgentRunner, pr: PRContext) -> list[AgentResult]:
    """Run both agents concurrently. A failing agent yields a result with `error` set."""
    return list(
        await asyncio.gather(
            _run_agent(settings, runner, AgentName.review, pr),
            _run_agent(settings, runner, AgentName.test, pr),
        )
    )


async def process_event(event: PullRequestEventV1, deps: WorkerDeps) -> None:
    """Run one review end to end. Safe to call again for the same event."""
    if not await claim_review(deps, event.review_id):
        log.info("review %s already handled, skipping", event.review_id)
        return

    s = deps.settings
    raw_files = await deps.github.list_pr_files(
        event.installation_id, event.repo_full_name, event.pr_number
    )
    selection = select_files(raw_files, s.max_diff_chars)
    if not selection.files:
        await set_status(deps, event.review_id, ReviewStatus.skipped, "no reviewable files")
        return

    pr = PRContext(
        repo=event.repo_full_name,
        pr_number=event.pr_number,
        head_sha=event.head_sha,
        installation_id=event.installation_id,
        files=selection.files,
        github=deps.github,
    )
    results = await run_agents(s, deps.runner, pr)
    if all(r.output is None for r in results):
        # Raising lets the consumer retry and eventually dead-letter the event.
        raise AgentsFailedError("; ".join(f"{r.agent}: {r.error}" for r in results))

    attributed = [
        AttributedFinding(agent=r.agent, finding=f)
        for r in results
        if r.output
        for f in r.output.findings
    ]
    grounding = ground_findings(attributed, selection.files, s.max_inline_comments)
    log.info(
        "review %s: %s findings, %s kept, %s ungrounded, %s duplicates",
        event.review_id,
        len(attributed),
        len(grounding.kept),
        grounding.dropped_ungrounded,
        grounding.dropped_duplicates,
    )

    body = review_body(results, selection, grounding)
    comments = [
        ReviewComment(path=af.finding.file_path, line=af.finding.line, body=comment_body(af))
        for af in grounding.kept
    ]
    await deps.github.create_review(
        event.installation_id,
        event.repo_full_name,
        event.pr_number,
        event.head_sha,
        body,
        comments,
    )

    input_tokens = sum(r.input_tokens for r in results)
    output_tokens = sum(r.output_tokens for r in results)
    cost = sum(
        estimate_cost_usd(r.model, r.input_tokens, r.output_tokens, s.model_prices) for r in results
    )
    async with deps.session_factory() as session:
        session.add_all(
            Comment(
                review_id=event.review_id,
                agent=af.agent,
                file_path=af.finding.file_path,
                line=af.finding.line,
                severity=af.finding.severity,
                category=af.finding.category[:64],
                body=comment.body,
                posted=True,
            )
            for af, comment in zip(grounding.kept, comments, strict=True)
        )
        await session.execute(
            update(Review)
            .where(Review.id == event.review_id)
            .values(
                status=ReviewStatus.done,
                summary=body,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=cost,
                finished_at=utcnow(),
            )
        )
        await session.commit()
