import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert

from api.signature import verify_signature
from shared.db import Review
from shared.events import PullRequestEventV1

log = logging.getLogger(__name__)
router = APIRouter()

HANDLED_ACTIONS = {"opened", "synchronize", "reopened"}


class _Repo(BaseModel):
    full_name: str


class _Head(BaseModel):
    sha: str


class _PullRequest(BaseModel):
    number: int
    head: _Head


class _Installation(BaseModel):
    id: int


class PullRequestPayload(BaseModel):
    action: str
    pull_request: _PullRequest
    repository: _Repo
    installation: _Installation


@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
):
    settings = request.app.state.settings
    body = await request.body()
    if not verify_signature(settings.github_webhook_secret, body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="invalid signature")

    if x_github_event != "pull_request":
        return {"status": "ignored", "reason": "unsupported event"}
    try:
        raw = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON") from None
    if raw.get("action") not in HANDLED_ACTIONS:
        return {"status": "ignored", "reason": "unsupported action"}
    payload = PullRequestPayload.model_validate(raw)

    # The unique (repo, pr, sha) constraint is the dedupe mechanism: GitHub
    # redelivering the same webhook yields the same row, so no second event.
    stmt = (
        insert(Review)
        .values(
            repo_full_name=payload.repository.full_name,
            pr_number=payload.pull_request.number,
            head_sha=payload.pull_request.head.sha,
            installation_id=payload.installation.id,
        )
        .on_conflict_do_nothing(index_elements=["repo_full_name", "pr_number", "head_sha"])
        .returning(Review.id)
    )
    async with request.app.state.session_factory() as session:
        review_id = (await session.execute(stmt)).scalar_one_or_none()
        await session.commit()

        if review_id is None:
            log.info("duplicate delivery %s ignored", x_github_delivery)
            return {"status": "duplicate"}

        event = PullRequestEventV1(
            review_id=review_id,
            delivery_id=x_github_delivery or "",
            repo_full_name=payload.repository.full_name,
            pr_number=payload.pull_request.number,
            head_sha=payload.pull_request.head.sha,
            installation_id=payload.installation.id,
        )
        try:
            await request.app.state.producer.send_and_wait(
                settings.kafka_topic,
                key=event.message_key.encode(),
                value=event.model_dump_json().encode(),
            )
        except Exception:
            # Roll the row back so GitHub's retry of this delivery is not
            # mistaken for a duplicate of an event that was never published.
            log.exception("failed to publish event for review %s", review_id)
            await session.delete(await session.get(Review, review_id))
            await session.commit()
            raise HTTPException(status_code=503, detail="queue unavailable") from None

    log.info("queued review %s", review_id)
    return {"status": "queued", "review_id": review_id}
