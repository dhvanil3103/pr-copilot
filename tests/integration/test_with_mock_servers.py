"""The real GitHub client and LangChain runner, over HTTP, against the e2e mock servers."""

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from shared.config import Settings
from shared.db import Review, ReviewStatus
from tests.e2e.mocks.anthropic.app import app as mock_anthropic
from tests.e2e.mocks.github import app as mock_github_module
from tests.integration.test_pipeline import make_review
from tests.servers import serve
from worker.agents.langchain_runner import LangChainAgentRunner
from worker.github import GitHubAppClient
from worker.processor import WorkerDeps, process_event

pytestmark = pytest.mark.integration


def private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


async def test_real_clients_against_mock_servers(session_factory):
    mock_github_module._reviews.clear()
    with serve(mock_github_module.app) as github_url, serve(mock_anthropic) as anthropic_url:
        settings = Settings(anthropic_api_key="mock", anthropic_base_url=anthropic_url)
        github = GitHubAppClient("1", private_key_pem(), base_url=github_url)
        deps = WorkerDeps(settings, session_factory, github, LangChainAgentRunner(settings))
        event = await make_review(session_factory)
        try:
            await process_event(event, deps)
        finally:
            await github.aclose()
        async with httpx.AsyncClient() as client:
            posted = (await client.get(f"{github_url}/_mock/reviews")).json()

    async with session_factory() as session:
        review = await session.get(Review, event.review_id)
    assert review.status == ReviewStatus.done, review.error_message
    assert review.input_tokens > 0 and float(review.estimated_cost_usd) > 0

    assert len(posted) == 1
    assert posted[0]["event"] == "COMMENT" and posted[0]["commit_id"] == "abc"
    # Lockfile and binary are filtered; both agents cite the first added line of each file.
    assert {(c["path"], c["line"]) for c in posted[0]["comments"]} == {
        ("app/payments.py", 1),
        ("web/src/greet.js", 2),
    }
